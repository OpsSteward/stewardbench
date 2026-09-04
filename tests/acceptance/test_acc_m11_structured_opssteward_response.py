"""M11 acceptance for source-derived structured OpsSteward chat answers."""

from __future__ import annotations

import copy
import csv
import io
import json
import threading
from collections import deque
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from catalog.models import TargetRevision
from catalog.services import create_target_revision
from evaluations.adapters import credential_environment_name
from evaluations.evaluators import JUDGE_DIMENSIONS, DeterministicFakeJudge
from evaluations.models import ComparisonItem, Execution
from evaluations.operator_answers import OPERATOR_ANSWER_METADATA_KEY
from evaluations.semantic import DeterministicFakeSemanticComparator
from evaluations.services import (
    create_baseline,
    launch_controlled_comparison,
    launch_run,
    process_next_execution,
    reevaluate_semantic_comparison,
    reevaluate_stored_answer,
)


TABLE_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "opss_v1_table_response.json").read_text()
)


@contextmanager
def _opssteward_chat_server(*responses):
    """Serve source-shaped synthetic chat responses without diagnostic logging."""

    pending = deque(copy.deepcopy(responses))
    journal = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - no fixture data in logs
            return

        def do_POST(self):  # noqa: N802 - stdlib hook
            request_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            journal.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(request_body)})
            payload = pending.popleft()
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", journal
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _revision_values(endpoint, *, credential_reference, build):
    return {
        "endpoint": endpoint,
        "adapter_key": "opss-v1-chat",
        "adapter_version": "1.0.4",
        "credential_reference": credential_reference,
        "classification": TargetRevision.Classification.LAB_TEST,
        "supports_question_api": True,
        "supports_conversation_session": False,
        "supports_runtime_metadata": False,
        "supports_health_check": True,
        "default_execution_mode": TargetRevision.ExecutionMode.SEQUENTIAL,
        "max_concurrency": 1,
        "question_timeout_seconds": 2,
        "inter_question_delay_seconds": 0,
        "declared_product_version": "synthetic-opss-v1",
        "declared_build_id": build,
        "declared_git_sha": f"synthetic-{build}",
    }


def _execute(*, actor, target, question):
    run = launch_run(actor=actor, target=target, question_ids=[question.pk])
    assert process_next_execution() is True
    execution = run.executions.get()
    execution.refresh_from_db()
    assert execution.outcome == Execution.Outcome.SUCCESS
    return run, execution


def _dimensions():
    return {
        name: {"result": "strong", "rationale": f"{name} source-fixture rationale"}
        for name in JUDGE_DIMENSIONS
    }


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_m11_structured_table_is_immutable_safe_and_exported(client, minimal_domain, monkeypatch):
    """ACC-M11-STRUCT-001: source-shaped table survives every operator path."""

    credential_reference = "fixtures/m11-structured-table"
    synthetic_credential = "m11-synthetic-credential-canary"
    monkeypatch.setenv(credential_environment_name(credential_reference), synthetic_credential)
    response = copy.deepcopy(TABLE_FIXTURE)
    response["response_payload"]["rows"][0][0] = "<script>window.m11=1</script>"
    response["response_payload"]["rows"][0][1] = "=1+1"
    expected_operator_answer = {
        "schema_version": "opss-structured-answer-v1",
        "answer_type": "text",
        "text": response["text"],
        "response_kind": "table",
        "response_payload": response["response_payload"],
    }

    with _opssteward_chat_server(response) as (endpoint, journal):
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_revision_values(endpoint, credential_reference=credential_reference, build="structured-a"),
        )
        run, execution = _execute(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question=minimal_domain["question"]
        )

    assert execution.raw_response == json.dumps(response, ensure_ascii=False)
    assert execution.raw_answer == response["text"]
    assert execution.display_answer == response["text"]
    assert execution.response_metadata[OPERATOR_ANSWER_METADATA_KEY] == expected_operator_answer
    assert (execution.normalizer_key, execution.normalizer_version) == ("opss-structured-answer", "1")
    assert journal[0]["path"] == "/chat"
    assert journal[0]["headers"]["Cookie"] == f"opssteward_session={synthetic_credential}"
    assert synthetic_credential not in json.dumps(execution.raw_request)
    assert synthetic_credential not in execution.raw_response
    assert synthetic_credential not in json.dumps(execution.response_metadata)

    # Terminal Execution evidence cannot be altered after the structured result.
    execution.response_metadata = {}
    with pytest.raises(ValidationError):
        execution.save()
    execution.refresh_from_db()

    client.force_login(minimal_domain["operator"])
    page = client.get(reverse("execution-detail", args=[execution.pk]))
    assert page.status_code == 200
    rendered = page.content.decode("utf-8")
    assert "Complete operator-facing answer" in rendered
    assert "Device" in rendered and "lab-west" in rendered
    assert "&lt;script&gt;window.m11=1&lt;/script&gt;" in rendered
    assert "<script>window.m11=1</script>" not in rendered
    assert "=1+1" in rendered

    json_export = json.loads(client.get(reverse("run-json-export", args=[run.pk])).content)
    observation = json_export["executions"][0]["observation"]
    assert observation["raw_response"] == json.dumps(response, ensure_ascii=False)
    assert observation["operator_answer"] == expected_operator_answer
    assert observation["response_metadata"][OPERATOR_ANSWER_METADATA_KEY] == expected_operator_answer
    assert synthetic_credential not in json.dumps(json_export, ensure_ascii=False)

    csv_export = client.get(reverse("run-csv-export", args=[run.pk]))
    rows = list(csv.DictReader(io.StringIO(csv_export.content.decode("utf-8"))))
    assert rows[0]["raw_answer"] == response["text"]
    assert "operator_answer" not in rows[0]
    assert "synthetic-border-01" not in csv_export.content.decode("utf-8")
    assert synthetic_credential not in csv_export.content.decode("utf-8")


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_m11_table_cell_change_is_exact_changed_and_reaches_semantic_and_judge(minimal_domain, monkeypatch):
    """ACC-M11-STRUCT-002: unchanged heading cannot hide a changed table cell."""

    credential_reference = "fixtures/m11-comparison"
    monkeypatch.setenv(credential_environment_name(credential_reference), "m11-comparison-canary")
    baseline_response = copy.deepcopy(TABLE_FIXTURE)
    current_response = copy.deepcopy(TABLE_FIXTURE)
    current_response["response_payload"]["rows"][1][2] = "lab-north"
    assert baseline_response["text"] == current_response["text"]

    with _opssteward_chat_server(baseline_response, current_response) as (endpoint, _journal):
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_revision_values(endpoint, credential_reference=credential_reference, build="baseline"),
        )
        source_run, source = _execute(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question=minimal_domain["question"]
        )
        baseline = create_baseline(actor=minimal_domain["admin"], source_run=source_run, name="M11 structured baseline")
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_revision_values(endpoint, credential_reference=credential_reference, build="current"),
        )
        current_run = launch_controlled_comparison(
            actor=minimal_domain["admin"], baseline=baseline, target=minimal_domain["target"]
        )
        assert process_next_execution() is True
        current = current_run.executions.get()
        item = current.current_comparison_items.get()

    assert item.change_state == ComparisonItem.ChangeState.CHANGED
    assert item.exact_equal is False
    assert source.display_answer == current.display_answer == baseline_response["text"]

    comparator = DeterministicFakeSemanticComparator([{"outcome": "MATERIAL_CHANGE"}])
    semantic = reevaluate_semantic_comparison(
        actor=minimal_domain["admin"], comparison_item=item, comparator=comparator
    )
    assert semantic.outcome == "MATERIAL_CHANGE"
    assert "response_payload" in comparator.calls[0].baseline_answer
    assert "lab-west" in comparator.calls[0].baseline_answer
    assert "lab-north" in comparator.calls[0].current_answer

    judge = DeterministicFakeJudge([{"dimensions": _dimensions(), "advisory_disposition": "STRONG"}])
    result = reevaluate_stored_answer(actor=minimal_domain["admin"], execution=current, judge=judge)
    assert result.status == "COMPLETE"
    assert "response_payload" in judge.calls[0].product_answer
    assert "lab-north" in judge.calls[0].product_answer


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_m11_unknown_response_kind_is_preserved_and_safely_degraded(client, minimal_domain, monkeypatch):
    """ACC-M11-STRUCT-003: a future kind stays visible as escaped JSON evidence."""

    credential_reference = "fixtures/m11-unknown-kind"
    monkeypatch.setenv(credential_environment_name(credential_reference), "m11-unknown-kind-canary")
    response = copy.deepcopy(TABLE_FIXTURE)
    response["response_kind"] = "matrix-vnext"
    response["response_payload"] = {"cells": [["<script>unknown-kind</script>", "=2+2"]]}
    with _opssteward_chat_server(response) as (endpoint, _journal):
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_revision_values(endpoint, credential_reference=credential_reference, build="unknown-kind"),
        )
        _run, execution = _execute(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question=minimal_domain["question"]
        )

    client.force_login(minimal_domain["operator"])
    rendered = client.get(reverse("execution-detail", args=[execution.pk])).content.decode("utf-8")
    assert "Unsupported structured response kind" in rendered
    assert "matrix-vnext" in rendered
    assert "&lt;script&gt;unknown-kind&lt;/script&gt;" in rendered
    assert "<script>unknown-kind</script>" not in rendered
    assert "=2+2" in rendered
    assert execution.response_metadata[OPERATOR_ANSWER_METADATA_KEY]["response_payload"] == response["response_payload"]
