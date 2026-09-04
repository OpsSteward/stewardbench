"""M10 acceptance evidence for reporting, exports, safe rendering, and status.

These checks deliberately enumerate persisted records before exercising the
dashboard/list/export projections.  They do not accept a rendered count merely
because it appears in HTML.
"""

from __future__ import annotations

import csv
import io
import json

import pytest
from django.urls import reverse

from catalog.models import TargetRevision
from catalog.services import create_target_revision
from evaluations.adapters import credential_environment_name
from evaluations.models import Execution
from evaluations.services import (
    append_execution_comment,
    launch_run,
    mark_review_required,
    process_next_execution,
    record_human_review,
    set_execution_validity,
)
from harness.fake_target import FakeTargetServer


def _revision_values(endpoint):
    return {
        "endpoint": endpoint,
        "adapter_key": "fake-http",
        "adapter_version": "1",
        "credential_reference": "",
        "classification": TargetRevision.Classification.LAB_TEST,
        "supports_question_api": True,
        "supports_conversation_session": False,
        "supports_runtime_metadata": False,
        "supports_health_check": True,
        "default_execution_mode": TargetRevision.ExecutionMode.SEQUENTIAL,
        "max_concurrency": 1,
        "question_timeout_seconds": 2,
        "inter_question_delay_seconds": 0,
        "declared_product_version": "m10-fixture",
        "declared_build_id": "build-m10",
        "declared_git_sha": "m10-sha",
    }


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_metric_001_dashboard_counts_and_drill_down_match_persisted_set(client, minimal_domain):
    """ACC-METRIC-001: counter, URL filter, and PostgreSQL IDs agree exactly."""

    with FakeTargetServer() as fake:
        create_target_revision(
            actor=minimal_domain["admin"], target=minimal_domain["target"], **_revision_values(fake.endpoint)
        )
        run = launch_run(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[minimal_domain["question"].pk]
        )
        fake.state.configure(answer="A complete answer")
        assert process_next_execution()
        execution = run.executions.get()
        record_human_review(actor=minimal_domain["admin"], execution=execution, judgment="BAD")
        mark_review_required(actor=minimal_domain["admin"], execution=execution, cause="M10 exact set proof")
        set_execution_validity(actor=minimal_domain["admin"], execution=execution, validity=Execution.Validity.INVALID)

        expected_required = list(Execution.objects.filter(review_state=Execution.ReviewState.REQUIRED).values_list("pk", flat=True))
        expected_invalid = list(Execution.objects.filter(validity=Execution.Validity.INVALID).values_list("pk", flat=True))
        client.force_login(minimal_domain["admin"])
        dashboard = client.get(reverse("dashboard"))
        assert dashboard.status_code == 200
        assert f'?review=REQUIRED">{len(expected_required)}'.encode() in dashboard.content
        assert f'?validity=INVALID">{len(expected_invalid)}'.encode() in dashboard.content

        required_page = client.get(reverse("execution-list"), {"review": "REQUIRED"})
        invalid_page = client.get(reverse("execution-list"), {"validity": "INVALID"})
        assert required_page.status_code == 200
        assert invalid_page.status_code == 200
        assert [item.pk for item in required_page.context["page"].object_list] == expected_required
        assert [item.pk for item in invalid_page.context["page"].object_list] == expected_invalid


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_export_001_json_preserves_history_and_csv_neutralizes_formula(client, minimal_domain, monkeypatch):
    """ACC-EXPORT-001: Unicode/raw history survives JSON; CSV avoids formula execution."""

    with FakeTargetServer() as fake:
        secret = "m10-export-credential-canary"
        credential_reference = "fixtures/m10-export"
        monkeypatch.setenv(credential_environment_name(credential_reference), secret)
        revision = _revision_values(fake.endpoint)
        revision["credential_reference"] = credential_reference
        create_target_revision(
            actor=minimal_domain["admin"], target=minimal_domain["target"], **revision
        )
        raw_answer = '=SUM(1,1) — resposta "em Português" \\ caminho\nlinha <script>alert(\'x\')</script>'
        fake.state.configure(answer=raw_answer, expected_credential=secret)
        run = launch_run(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[minimal_domain["question"].pk]
        )
        assert process_next_execution()
        execution = run.executions.get()
        record_human_review(actor=minimal_domain["admin"], execution=execution, judgment="GOOD", comment_text="Revisão ✅")
        append_execution_comment(actor=minimal_domain["admin"], execution=execution, text="Comentário multilinha\nsem segredo")

        client.force_login(minimal_domain["operator"])
        exported = client.get(reverse("run-json-export", args=[run.pk]))
        assert exported.status_code == 200
        payload = json.loads(exported.content)
        assert payload["schema_version"] == "stewardbench-run-export-v1"
        assert payload["run"]["id"] == str(run.pk)
        assert payload["executions"][0]["observation"]["raw_answer"] == raw_answer
        assert payload["executions"][0]["review"]["human_history"][0]["judgment"] == "GOOD"
        assert "Comentário multilinha\nsem segredo" in [comment["text"] for comment in payload["executions"][0]["comments"]]
        assert "credential_reference" not in json.dumps(payload, ensure_ascii=False)
        assert secret not in json.dumps(payload, ensure_ascii=False)

        csv_export = client.get(reverse("run-csv-export", args=[run.pk]))
        assert csv_export.status_code == 200
        rows = list(csv.DictReader(io.StringIO(csv_export.content.decode("utf-8"))))
        assert len(rows) == 1
        assert rows[0]["raw_answer"] == "'" + raw_answer
        assert secret not in csv_export.content.decode("utf-8")


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_unsafe_001_and_operational_status_are_honest_and_role_protected(client, minimal_domain):
    """ACC-UNSAFE-001 plus status readiness: no target markup execution or fake provider claim."""

    with FakeTargetServer() as fake:
        create_target_revision(
            actor=minimal_domain["admin"], target=minimal_domain["target"], **_revision_values(fake.endpoint)
        )
        fake.state.configure(mode="unsafe_html")
        run = launch_run(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[minimal_domain["question"].pk]
        )
        assert process_next_execution()
        execution = run.executions.get()

        client.force_login(minimal_domain["operator"])
        detail = client.get(reverse("execution-detail", args=[execution.pk]))
        exported = client.get(reverse("run-json-export", args=[run.pk]))
        assert b"&lt;script&gt;window.__fake_target_executed" in detail.content
        assert b"<script>window.__fake_target_executed" not in detail.content
        assert b"<script>window.__fake_target_executed" in exported.content
        assert client.get(reverse("operational-status")).status_code == 403

        client.force_login(minimal_domain["admin"])
        status = client.get(reverse("operational-status"))
        assert status.status_code == 200
        assert b"TEST_PATH_VERIFIED" in status.content
        assert b"Not configured" in status.content
        assert b"automated semantic comparison unavailable" in status.content
