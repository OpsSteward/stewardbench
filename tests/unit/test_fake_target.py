import json
import sys
from urllib import request

import pytest

from harness.fake_target import FakeTargetServer, FakeTargetState
from harness.fake_target import server as fake_server


def _call(url, *, method="GET", payload=None, headers=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(url, data=body, headers=headers or {}, method=method)
    with request.urlopen(req, timeout=2) as response:  # noqa: S310 - loopback fixture
        return response.status, response.read().decode("utf-8")


def test_fake_target_journal_controls_and_unsafe_mode_are_independent():
    with FakeTargetServer() as server:
        control_headers = {"X-Fake-Control-Token": server.state.control_token}
        status, _ = _call(
            server.endpoint + "/__control",
            method="POST",
            payload={"mode": "unsafe_html", "answer": "ignored"},
            headers=control_headers,
        )
        assert status == 200
        status, response = _call(
            server.endpoint + "/question",
            method="POST",
            payload={"request_id": "test-request", "question": "question"},
            headers={"X-StewardBench-Request-ID": "test-request", "Content-Type": "application/json"},
        )
        assert status == 200
        assert "<script>" in response
        status, journal_response = _call(server.endpoint + "/__journal", headers=control_headers)
        journal = json.loads(journal_response)
        assert status == 200
        assert journal["observed_max_concurrency"] == 1
        assert journal["entries"][0]["request_id"] == "test-request"
        assert journal["entries"][0]["concrete_question"] == "question"
        assert journal["entries"][0]["response_completed_at"]


def test_fake_target_cli_requires_explicit_non_loopback_bind_for_isolated_docker(monkeypatch):
    observed = {}

    class ControlledServer:
        def __init__(self, address, handler):
            observed["address"] = address
            self.state = None

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            observed["closed"] = True

    monkeypatch.setattr(fake_server, "ThreadingHTTPServer", ControlledServer)
    monkeypatch.setattr(
        sys,
        "argv",
        ["fake-target", "--host", "0.0.0.0", "--port", "18081", "--control-token", "synthetic"],
    )

    with pytest.raises(KeyboardInterrupt):
        fake_server.main()

    assert observed == {"address": ("0.0.0.0", 18081), "closed": True}


def test_fake_target_journal_can_survive_disposable_container_restart(tmp_path):
    journal_path = tmp_path / "journal.json"
    state = FakeTargetState(journal_path=str(journal_path))
    entry = state.accepted(
        method="POST", path="/question", request_id="durable-request", concrete_question="safe", body=b"{}"
    )
    state.response_started(entry)
    state.completed(entry)

    restarted = FakeTargetState(journal_path=str(journal_path))
    snapshot = restarted.journal_snapshot()
    assert len(snapshot["entries"]) == 1
    assert snapshot["entries"][0]["request_id"] == "durable-request"
    assert snapshot["entries"][0]["response_completed_at"]
