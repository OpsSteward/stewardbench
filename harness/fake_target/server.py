"""Reusable deterministic M3 fake evaluated-target HTTP service.

It is intentionally standard-library only so adapter tests can run it in a
thread today and later start the same module in a child process or Docker.
Control and journal endpoints are loopback/test-harness facilities, never an
application adapter contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import socket
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FakeTargetState:
    mode: str = "success"
    answer: str = "Deterministic fake answer"
    evidence: object = field(default_factory=lambda: {"source": "fake-target"})
    delay_seconds: float = 0
    block_before_acceptance: bool = False
    block_after_acceptance: bool = False
    block_before_response: bool = False
    scripted_responses: list[dict] = field(default_factory=list)
    expected_credential: str | None = None
    metadata: dict = field(
        default_factory=lambda: {
            "schema_version": "1",
            "product": "FakeTarget",
            "product_version": "m3-test",
            "build_id": "fake-build-1",
        }
    )
    control_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    journal: list[dict] = field(default_factory=list)
    active_requests: int = 0
    observed_max_concurrency: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _before_acceptance_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _after_acceptance_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _before_response_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def __post_init__(self):
        self._before_acceptance_event.set()
        self._after_acceptance_event.set()
        self._before_response_event.set()

    def configure(self, **values):
        with self._lock:
            for key, value in values.items():
                if key in {
                    "journal",
                    "active_requests",
                    "observed_max_concurrency",
                    "_lock",
                    "_before_acceptance_event",
                    "_after_acceptance_event",
                    "_before_response_event",
                }:
                    continue
                if hasattr(self, key):
                    setattr(self, key, value)
            self._set_barrier(self._before_acceptance_event, self.block_before_acceptance)
            self._set_barrier(self._after_acceptance_event, self.block_after_acceptance)
            self._set_barrier(self._before_response_event, self.block_before_response)

    @staticmethod
    def _set_barrier(event, blocked):
        if blocked:
            event.clear()
        else:
            event.set()

    def release(self):
        self._before_acceptance_event.set()
        self._after_acceptance_event.set()
        self._before_response_event.set()

    def wait_before_acceptance(self):
        self._before_acceptance_event.wait()

    def wait_after_acceptance(self):
        self._after_acceptance_event.wait()

    def wait_before_response(self):
        self._before_response_event.wait()

    def reset(self):
        with self._lock:
            if self.active_requests:
                raise RuntimeError("Cannot reset a fake target with active requests.")
            self.journal.clear()
            self.observed_max_concurrency = 0

    def journal_snapshot(self):
        with self._lock:
            counts = {}
            for entry in self.journal:
                request_id = entry["request_id"]
                counts[request_id] = counts.get(request_id, 0) + 1
            return {
                "entries": list(self.journal),
                "active_requests": self.active_requests,
                "observed_max_concurrency": self.observed_max_concurrency,
                "per_correlation_request_counts": counts,
            }

    def accepted(self, *, method, path, request_id, concrete_question, body):
        with self._lock:
            scripted = self.scripted_responses.pop(0) if self.scripted_responses else {}
            mode = scripted.get("mode", self.mode)
            self.active_requests += 1
            self.observed_max_concurrency = max(self.observed_max_concurrency, self.active_requests)
            entry = {
                "sequence": len(self.journal) + 1,
                "request_id": request_id,
                "method": method,
                "path": path,
                "concrete_question": concrete_question,
                "request_fingerprint": hashlib.sha256(body).hexdigest(),
                "accepted_at": _timestamp(),
                "response_started_at": None,
                "response_completed_at": None,
                "disconnected_at": None,
                "active_request_count": self.active_requests,
                "mode": mode,
                "response_delay_seconds": scripted.get("delay_seconds", self.delay_seconds),
                "answer": scripted.get("answer"),
            }
            self.journal.append(entry)
            return entry

    def response_started(self, entry):
        with self._lock:
            entry["response_started_at"] = _timestamp()

    def completed(self, entry):
        with self._lock:
            entry["response_completed_at"] = _timestamp()
            self.active_requests -= 1

    def disconnected(self, entry):
        with self._lock:
            entry["disconnected_at"] = _timestamp()


class _Handler(BaseHTTPRequestHandler):
    server_version = "StewardBenchFakeTarget/1"

    @property
    def state(self):
        return self.server.state

    def log_message(self, format, *args):  # pragma: no cover - keeps test output secret-safe
        return

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            return body, json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return body, None

    def _send(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # A timeout test intentionally disconnects before a delayed response.
            return

    def _control_allowed(self):
        return secrets.compare_digest(
            self.headers.get("X-Fake-Control-Token", ""), self.state.control_token
        )

    def do_GET(self):  # noqa: N802 - stdlib hook
        if self.path == "/health":
            return self._health()
        if self.path == "/metadata":
            return self._metadata()
        if self.path == "/__journal":
            if not self._control_allowed():
                return self._send(403, b'{"error":"forbidden"}')
            return self._send(200, json.dumps(self.state.journal_snapshot()).encode("utf-8"))
        self._send(404, b'{"error":"not found"}')

    def _health(self):
        if self.state.mode == "health_unavailable":
            return self._send(503, b'{"error":"unavailable"}')
        if self.state.mode == "health_unauthorized":
            return self._send(401, b'{"error":"unauthorized"}')
        return self._send(200, b'{"status":"ok"}')

    def do_POST(self):  # noqa: N802 - stdlib hook
        if self.path == "/question":
            return self._question()
        if self.path in {"/__control", "/__reset", "/__release"}:
            if not self._control_allowed():
                return self._send(403, b'{"error":"forbidden"}')
            if self.path == "/__reset":
                try:
                    self.state.reset()
                except RuntimeError as exc:
                    return self._send(409, json.dumps({"error": str(exc)}).encode("utf-8"))
                return self._send(200, b'{"status":"reset"}')
            if self.path == "/__release":
                self.state.release()
                return self._send(200, b'{"status":"released"}')
            _, values = self._read_json()
            if not isinstance(values, dict):
                return self._send(400, b'{"error":"invalid control payload"}')
            self.state.configure(**values)
            return self._send(200, b'{"status":"configured"}')
        self._send(404, b'{"error":"not found"}')

    def _metadata(self):
        mode = self.state.mode
        if mode == "metadata_unavailable":
            return self._send(404, b'{"error":"metadata unavailable"}')
        if mode == "metadata_malformed":
            return self._send(200, b"not-json", "application/json")
        if mode == "metadata_delayed":
            time.sleep(self.state.delay_seconds or 1)
        if mode == "metadata_unauthorized":
            return self._send(401, b'{"error":"unauthorized"}')
        return self._send(200, json.dumps(self.state.metadata, ensure_ascii=False).encode("utf-8"))

    def _question(self):
        body, payload = self._read_json()
        if self.state.mode == "disconnect_before_acceptance":
            self.connection.close()
            return
        request_id = self.headers.get("X-StewardBench-Request-ID", "")
        concrete_question = None
        if isinstance(payload, dict):
            request_id = str(payload.get("request_id") or request_id)
            submitted = payload.get("question")
            concrete_question = submitted if isinstance(submitted, str) else None
        self.state.wait_before_acceptance()
        entry = self.state.accepted(
            method="POST",
            path="/question",
            request_id=request_id,
            concrete_question=concrete_question,
            body=body,
        )
        try:
            self.state.wait_after_acceptance()
            mode = entry["mode"]
            if mode == "disconnect_after_acceptance":
                self.state.disconnected(entry)
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if self.state.expected_credential is not None:
                supplied = self.headers.get("Authorization", "")
                if supplied != f"Bearer {self.state.expected_credential}":
                    self.state.response_started(entry)
                    return self._send(401, b'{"error":"unauthorized"}')
            if mode == "auth_rejected":
                self.state.response_started(entry)
                return self._send(401, b'{"error":"unauthorized"}')
            if entry["response_delay_seconds"]:
                time.sleep(entry["response_delay_seconds"])
            elif mode == "timeout":
                time.sleep(1)
            self.state.wait_before_response()
            self.state.response_started(entry)
            if mode == "http_error":
                return self._send(503, b'{"error":"scripted target error"}')
            if mode == "malformed_response":
                return self._send(200, b"{not-json", "application/json")
            if mode == "wrong_content_type":
                return self._send(200, b"complete but not JSON", "text/plain")
            if mode == "incomplete_response":
                return self._send(200, b'{"complete":false,"answer":"partial"}')
            answer = entry["answer"] if entry["answer"] is not None else self.state.answer
            if mode == "unsafe_html":
                answer = "<script>window.__fake_target_executed = true</script><b>unsafe</b>"
            envelope = {
                "complete": True,
                "answer": answer,
                "evidence": self.state.evidence,
                "correlation_id": request_id,
                "metadata": {"fake_mode": mode},
            }
            return self._send(200, json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
        finally:
            self.state.completed(entry)


class FakeTargetServer:
    def __init__(self, state: FakeTargetState | None = None):
        self.state = state or FakeTargetState()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.state = self.state
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def endpoint(self):
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, traceback):
        self.stop()


def main():
    parser = argparse.ArgumentParser(description="Run the StewardBench deterministic fake target.")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address; use 0.0.0.0 only on an isolated Docker test network.",
    )
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--control-token", default=None)
    options = parser.parse_args()
    state = FakeTargetState()
    if options.control_token:
        state.control_token = options.control_token
    server = ThreadingHTTPServer((options.host, options.port), _Handler)
    server.state = state
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
