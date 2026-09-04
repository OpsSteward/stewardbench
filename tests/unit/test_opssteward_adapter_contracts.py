"""Source-derived fixtures for the supported OpsSteward chat generations.

These fixtures deliberately exercise the real adapter wire shape rather than
the product-neutral fake-target contract.  They are contract implementation
evidence only; no test here claims a configured OpsSteward deployment is live
certified.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from evaluations.adapters import AdapterFailure, ConversationFailure, adapter_for


V1_CHAT_RESPONSE = {
    "conversation_id": "v1-conversation",
    "interaction_id": "v1-interaction",
    "text": "v1 answer",
    "evidence": [{"source": "synthetic-v1"}],
    "metadata": {
        "performance": {
            "ollama": {
                "prompt_tokens": 101,
                "completion_tokens": 202,
                "total_tokens": 303,
                "provider": "Ollama",
                "model": "v1-model",
                "total_ms": 801,
            },
            "routing_ms": 4,
        }
    },
}

V2_CHAT_RESPONSE = {
    "conversation_id": "v2-conversation",
    "interaction_id": "v2-interaction",
    "text": "v2 answer",
    "evidence": [{"source": "synthetic-v2"}],
    "metadata": {
        "performance": {
            "model_serving": {
                "prompt_tokens": 401,
                "completion_tokens": 502,
                "total_tokens": 903,
                "providers": ["vLLM"],
                "models": ["v2-model"],
                "total_ms": 701,
            },
            "document_search_ms": 13,
        }
    },
}


@contextmanager
def _contract_server(*, chat_status=200, chat_response=None, version_response=None):
    journal = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - silence test server
            return

        def _send(self, status, payload):
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self):  # noqa: N802 - stdlib hook
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            journal.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "body": json.loads(raw)})
            self._send(chat_status, chat_response or {"detail": "synthetic error"})

        def do_GET(self):  # noqa: N802 - stdlib hook
            journal.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
            self._send(200, version_response or {"product": "OpsSteward", "version": "synthetic", "source_sha": "abc123", "build_time": "2026-09-04T00:00:00Z"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", journal
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


@pytest.mark.parametrize(
    ("adapter_key", "chat_response", "expected"),
    [
        ("opss-v1-chat", V1_CHAT_RESPONSE, ("v1.0.4", 101, 202, 303, "Ollama", "v1-model")),
        ("opss-v2-chat", V2_CHAT_RESPONSE, ("development", 401, 502, 903, "vLLM", "v2-model")),
    ],
)
def test_source_derived_chat_contract_fixtures(adapter_key, chat_response, expected):
    """POST /chat, typed response, cookie auth, and telemetry map explicitly."""

    with _contract_server(chat_response=chat_response) as (endpoint, journal):
        adapter = adapter_for(adapter_key)
        submission = adapter.submit_question(
            endpoint=endpoint,
            credential="fixture-session",
            request_id="steward-correlation",
            question="Qual é o estado?",
            timeout_seconds=2,
        )

    version, input_tokens, output_tokens, total_tokens, runtime, model = expected
    assert submission.adapter_version == version
    assert submission.raw_answer == chat_response["text"]
    assert submission.input_tokens == input_tokens
    assert submission.output_tokens == output_tokens
    assert submission.total_tokens == total_tokens
    assert submission.runtime_telemetry["provider_or_runtime"] == runtime
    assert submission.runtime_telemetry["model"] == model
    assert journal[0]["path"] == "/chat"
    assert journal[0]["body"] == {
        "conversation_id": None,
        "message": "Qual é o estado?",
        "mode": "auto",
        "source": "auto",
    }
    assert journal[0]["headers"]["Cookie"] == "opssteward_session=fixture-session"
    assert submission.raw_request["headers"] == {
        "Content-Type": "application/json",
        "X-StewardBench-Request-ID": "steward-correlation",
    }


@pytest.mark.parametrize("adapter_key", ["opss-v1-chat", "opss-v2-chat"])
def test_source_derived_version_contract_and_missing_optional_telemetry(adapter_key):
    """GET /version maps build identity; absent optional telemetry preserves success."""

    response = {"conversation_id": "c", "interaction_id": "i", "text": "answer", "evidence": [], "metadata": {}}
    with _contract_server(chat_response=response) as (endpoint, journal):
        adapter = adapter_for(adapter_key)
        submission = adapter.submit_question(endpoint=endpoint, credential="session", request_id="r", question="q", timeout_seconds=2)
        metadata = adapter.runtime_metadata(endpoint=endpoint, credential="session", timeout_seconds=2)
        health = adapter.health_check(endpoint=endpoint, credential="session", timeout_seconds=2)

    assert submission.raw_answer == "answer"
    assert submission.total_tokens is None
    assert submission.runtime_telemetry == {}
    assert metadata.state == "AVAILABLE"
    assert metadata.metadata == {
        "product": "OpsSteward",
        "product_version": "synthetic",
        "git_sha": "abc123",
        "build_time": "2026-09-04T00:00:00Z",
    }
    assert journal[1]["path"] == "/version"
    assert journal[1]["headers"]["Cookie"] == "opssteward_session=session"
    assert health.status == "REACHABLE"
    assert journal[2]["path"] == "/health"
    assert journal[2]["headers"]["Cookie"] == "opssteward_session=session"


@pytest.mark.parametrize("adapter_key", ["opss-v1-chat", "opss-v2-chat"])
def test_source_derived_error_and_malformed_optional_telemetry_are_isolated(adapter_key):
    """401 is auth failure; malformed advisory fields cannot discard a valid answer."""

    malformed = {
        "conversation_id": "c",
        "interaction_id": "i",
        "text": "still a valid answer",
        "evidence": [],
        "metadata": {
            "telemetry": {
                "usage": {"input_tokens": "bad", "output_tokens": -4, "total_tokens": True},
                "runtime": {"provider_or_runtime": "<script>runtime</script>", "model": 42},
                "internal_timings": {"routing_ms": "bad", "safe_ms": 4},
            }
        },
    }
    with _contract_server(chat_response=malformed) as (endpoint, _):
        submission = adapter_for(adapter_key).submit_question(endpoint=endpoint, credential="session", request_id="r", question="q", timeout_seconds=2)
    assert submission.raw_answer == "still a valid answer"
    assert (submission.input_tokens, submission.output_tokens, submission.total_tokens) == (None, None, None)
    assert submission.runtime_telemetry == {"provider_or_runtime": "<script>runtime</script>"}
    assert submission.internal_timing_metadata == {"safe_ms": 4}
    assert set(submission.token_usage_metadata["diagnostics"]) >= {
        "malformed_input_tokens",
        "malformed_output_tokens",
        "malformed_total_tokens",
        "malformed_runtime_model",
        "malformed_timing_routing_ms",
    }

    with _contract_server(chat_status=401) as (endpoint, _):
        with pytest.raises(AdapterFailure, match="HTTP 401") as exc:
            adapter_for(adapter_key).submit_question(endpoint=endpoint, credential="session", request_id="r", question="q", timeout_seconds=2)
    assert exc.value.error_class == "AUTHENTICATION_FAILED"


@pytest.mark.parametrize("adapter_key", ["opss-v1-chat", "opss-v2-chat"])
def test_source_derived_chat_contract_does_not_claim_m8_session_support(adapter_key):
    """A chat conversation_id is not silently promoted into an M8 session API."""

    adapter = adapter_for(adapter_key)
    with pytest.raises(ConversationFailure, match="not an M8-compatible") as exc:
        adapter.open_conversation(endpoint="https://example.invalid", credential=None, request_id="r", timeout_seconds=1)
    assert (exc.value.error_class, exc.value.continuity) == ("UNSUPPORTED_BEHAVIOR", "UNUSABLE")
