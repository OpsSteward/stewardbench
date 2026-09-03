"""Independent M5 acceptance: ACC-REVIEW-001 and ACC-RETRY-001."""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from django.urls import reverse

from catalog.models import Question, TargetRevision
from catalog.services import create_question, create_target_revision
from evaluations.models import AutomatedEvaluationResult, Execution, HumanReview, LLMJudgeResult
from evaluations.services import (
    launch_run,
    process_next_execution,
    record_human_review,
    retry_execution,
    run_review_metrics,
    set_execution_validity,
)
from harness.fake_target import FakeTargetServer


def _revision_values(server):
    return {
        "endpoint": server.endpoint,
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
        "declared_product_version": "m5-acceptance",
        "declared_build_id": "m5-acceptance-build",
        "declared_git_sha": "m5-acceptance-sha",
    }


def _terminal_snapshot(execution):
    execution.refresh_from_db()
    values = {
        "id": execution.pk,
        "run": str(execution.run_id),
        "outcome": execution.outcome,
        "question_version": execution.question_version_id,
        "submitted_question": execution.submitted_question,
        "bindings": list(execution.resolved_bindings.values("name", "value", "display_value")),
        "raw_request": execution.raw_request,
        "raw_response": execution.raw_response,
        "raw_answer": execution.raw_answer,
        "display_answer": execution.display_answer,
        "evidence": execution.evidence,
        "target_snapshot": execution.target_snapshot_id,
        "build_snapshot": execution.build_snapshot_id,
        "target_revision": execution.target_revision_id,
        "adapter": [execution.adapter_key, execution.adapter_version],
        "timing": [execution.started_at.isoformat(), execution.completed_at.isoformat(), execution.latency_ms],
    }
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest(), values


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_review_001_review_judgment_automation_outcome_and_validity_stay_orthogonal(client, minimal_domain):
    """Service, HTTP, and PostgreSQL evidence for ACC-REVIEW-001."""

    with FakeTargetServer() as fake:
        create_target_revision(actor=minimal_domain["admin"], target=minimal_domain["target"], **_revision_values(fake))
        second = create_question(
            actor=minimal_domain["admin"],
            stable_id="ACC-M5-ERROR",
            kind=Question.Kind.SINGLE_TURN,
            lifecycle=Question.Lifecycle.ACTIVE,
            domain=minimal_domain["domain"],
            tags=(),
            rationale="",
            question_text="Acceptance error observation",
        )
        run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[minimal_domain["question"].pk, second.pk],
        )
        assert process_next_execution() is True
        fake.state.configure(mode="http_error")
        assert process_next_execution() is True
        success, error = list(run.executions.order_by("question_order"))
        before_hash, before_values = _terminal_snapshot(success)
        automated = AutomatedEvaluationResult.objects.create(
            execution=success,
            evaluator_key="acceptance-fixture",
            evaluator_version="1",
            status="COMPLETE",
            outcome="FAIL",
            details={"fixture": "automated"},
        )
        judge = LLMJudgeResult.objects.create(
            execution=success,
            provider="fixture",
            model_identifier="m5-judge",
            judge_version="1",
            prompt_version="1",
            status="COMPLETE",
            dimensions={"completeness": "low"},
        )

        client.force_login(minimal_domain["admin"])
        review_response = client.post(
            reverse("execution-review", args=[success.pk]),
            {"judgment": "GOOD", "comment": "Admin review ✓"},
        )
        assert review_response.status_code == 302
        success.refresh_from_db()
        assert success.outcome == Execution.Outcome.SUCCESS
        assert success.review_state == Execution.ReviewState.REVIEWED
        assert success.current_human_review.judgment == HumanReview.Judgment.GOOD
        assert success.current_human_review.reviewed_by_id == minimal_domain["admin"].pk
        assert success.review_history.count() == 1
        assert AutomatedEvaluationResult.objects.get(pk=automated.pk).details == {"fixture": "automated"}
        assert LLMJudgeResult.objects.get(pk=judge.pk).dimensions == {"completeness": "low"}
        assert _terminal_snapshot(success) == (before_hash, before_values)

        # A SUCCESS can validly be BAD; correction is appended rather than edited.
        record_human_review(actor=minimal_domain["admin"], execution=success, judgment="BAD")
        success.refresh_from_db()
        assert list(success.review_history.values_list("judgment", flat=True)) == ["GOOD", "BAD"]
        assert success.current_human_review.judgment == "BAD"
        assert _terminal_snapshot(success) == (before_hash, before_values)

        # ERROR remains a transport outcome and has no fabricated human BAD.
        error.refresh_from_db()
        assert error.outcome == Execution.Outcome.ERROR
        assert error.current_human_review is None
        assert error.review_state == Execution.ReviewState.NONE
        error_page = client.get(reverse("execution-detail", args=[error.pk]))
        assert error_page.status_code == 200
        assert b"No complete answer was captured" in error_page.content

        set_execution_validity(actor=minimal_domain["admin"], execution=success, validity="INVALID")
        success.refresh_from_db()
        assert success.validity == "INVALID"
        assert success.invalidated_by_id == minimal_domain["admin"].pk
        assert _terminal_snapshot(success) == (before_hash, before_values)
        metrics = run_review_metrics(run)
        assert metrics["invalid"] == 1
        assert metrics["good"] == metrics["bad"] == 0


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_retry_001_retry_and_rerun_append_new_history_and_fake_target_requests(client, minimal_domain):
    """ACC-RETRY-001: source snapshot, IDs, DB links, and target journal agree."""

    with FakeTargetServer() as fake:
        create_target_revision(actor=minimal_domain["admin"], target=minimal_domain["target"], **_revision_values(fake))
        second = create_question(
            actor=minimal_domain["admin"],
            stable_id="ACC-M5-RERUN",
            kind=Question.Kind.SINGLE_TURN,
            lifecycle=Question.Lifecycle.ACTIVE,
            domain=minimal_domain["domain"],
            tags=(),
            rationale="",
            question_text="Rerun selection source",
        )
        source_run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[minimal_domain["question"].pk, second.pk],
        )
        while process_next_execution():
            pass
        source = source_run.executions.order_by("question_order").first()
        before_hash, before_values = _terminal_snapshot(source)
        journal_before = fake.state.journal_snapshot()
        assert len(journal_before["entries"]) == 2

        client.force_login(minimal_domain["admin"])
        retry_key = uuid.uuid4()
        response = client.post(
            reverse("execution-retry", args=[source.pk]),
            {"retry_request_key": str(retry_key)},
        )
        assert response.status_code == 302
        retry_run_id = response["Location"].rstrip("/").split("/")[-1]
        retry_run = source_run.__class__.objects.get(pk=retry_run_id)
        retry = retry_run.executions.get()
        assert retry_run.pk != source_run.pk
        assert retry_run.source_run_id == source_run.pk
        assert retry_run.source_execution_id == source.pk
        assert retry.source_execution_id == source.pk
        assert retry.request_correlation_id != source.request_correlation_id
        assert retry.question_version_id == source.question_version_id
        assert retry.submitted_question == source.submitted_question
        assert _terminal_snapshot(source) == (before_hash, before_values)
        assert process_next_execution() is True
        retry.refresh_from_db()
        assert retry.outcome == Execution.Outcome.SUCCESS
        journal_after = fake.state.journal_snapshot()
        assert len(journal_after["entries"]) == 3
        assert journal_after["per_correlation_request_counts"][str(source.request_correlation_id)] == 1
        assert journal_after["per_correlation_request_counts"][str(retry.request_correlation_id)] == 1
        assert _terminal_snapshot(source) == (before_hash, before_values)

        rerun_response = client.post(
            reverse("run-rerun", args=[source_run.pk]),
            {"rerun_scope": "selected", "execution_ids": [source.pk]},
        )
        assert rerun_response.status_code == 302
        selected_rerun_id = rerun_response["Location"].rstrip("/").split("/")[-1]
        selected_rerun = source_run.__class__.objects.get(pk=selected_rerun_id)
        assert selected_rerun.source_run_id == source_run.pk
        assert selected_rerun.total_planned == 1
        assert selected_rerun.executions.get().pk != source.pk
        assert selected_rerun.executions.get().review_history.count() == 0
        assert _terminal_snapshot(source) == (before_hash, before_values)
