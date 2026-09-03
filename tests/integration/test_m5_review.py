"""M5 service, history, metrics, retry, and request-boundary regression tests."""

from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from catalog.models import Question, QuestionVersion, TargetRevision
from catalog.services import create_question, create_question_version, create_target_revision
from evaluations.models import (
    AutomatedEvaluationResult,
    Comment,
    EvaluationRun,
    Execution,
    HumanReview,
    LLMJudgeResult,
)
from evaluations.services import (
    append_execution_comment,
    append_run_comment,
    launch_run,
    mark_review_required,
    mark_reviewed_without_judgment,
    process_next_execution,
    record_human_review,
    rerun_source_run,
    retry_execution,
    run_review_metrics,
    set_execution_validity,
)
from harness.fake_target import FakeTargetServer


def _revision_values(server, **overrides):
    values = {
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
        "max_concurrency": 2,
        "question_timeout_seconds": 2,
        "inter_question_delay_seconds": 0,
        "declared_product_version": "m5-fixture",
        "declared_build_id": "m5-build",
        "declared_git_sha": "m5-sha",
    }
    values.update(overrides)
    return values


def _configure_target(minimal_domain, fake, **overrides):
    return create_target_revision(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        **_revision_values(fake, **overrides),
    )


def _terminal_run(minimal_domain, fake, question_ids=None, mode="success"):
    _configure_target(minimal_domain, fake)
    fake.state.configure(mode=mode)
    run = launch_run(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        question_ids=question_ids or [minimal_domain["question"].pk],
    )
    while process_next_execution():
        pass
    run.refresh_from_db()
    return run


def _observation_fingerprint(execution):
    execution.refresh_from_db()
    return {
        "outcome": execution.outcome,
        "submitted_question": execution.submitted_question,
        "question_version_id": execution.question_version_id,
        "raw_request": execution.raw_request,
        "raw_response": execution.raw_response,
        "raw_answer": execution.raw_answer,
        "display_answer": execution.display_answer,
        "evidence": execution.evidence,
        "response_metadata": execution.response_metadata,
        "target_snapshot_id": execution.target_snapshot_id,
        "build_snapshot_id": execution.build_snapshot_id,
        "target_revision_id": execution.target_revision_id,
        "adapter_key": execution.adapter_key,
        "adapter_version": execution.adapter_version,
        "completed_at": execution.completed_at,
        "latency_ms": execution.latency_ms,
    }


@pytest.mark.django_db
def test_human_review_is_attributed_append_only_and_orthogonal_to_observation(minimal_domain):
    with FakeTargetServer() as fake:
        run = _terminal_run(minimal_domain, fake)
        execution = run.executions.get()
        before = _observation_fingerprint(execution)
        automated = AutomatedEvaluationResult.objects.create(
            execution=execution,
            evaluator_key="fixture-policy",
            evaluator_version="1",
            status=AutomatedEvaluationResult.Status.COMPLETE,
            outcome=AutomatedEvaluationResult.Outcome.FAIL,
            details={"independent": True},
        )
        judge = LLMJudgeResult.objects.create(
            execution=execution,
            provider="fixture",
            model_identifier="fixture-judge",
            judge_version="1",
            prompt_version="1",
            status=LLMJudgeResult.Status.COMPLETE,
            dimensions={"grounding": "uncertain"},
        )

        first = record_human_review(
            actor=minimal_domain["admin"],
            execution=execution,
            judgment=HumanReview.Judgment.GOOD,
            comment_text="Revisão Unicode — São Paulo ✓",
        )
        execution.refresh_from_db()
        assert execution.outcome == Execution.Outcome.SUCCESS
        assert execution.review_state == Execution.ReviewState.REVIEWED
        assert execution.current_human_review_id == first.pk
        assert execution.current_human_review.judgment == HumanReview.Judgment.GOOD
        assert first.reviewed_by_id == minimal_domain["admin"].pk
        assert execution.comments.get().text == "Revisão Unicode — São Paulo ✓"
        assert _observation_fingerprint(execution) == before
        assert AutomatedEvaluationResult.objects.get(pk=automated.pk).details == {"independent": True}
        assert LLMJudgeResult.objects.get(pk=judge.pk).dimensions == {"grounding": "uncertain"}

        correction = record_human_review(
            actor=minimal_domain["admin"],
            execution=execution,
            judgment=HumanReview.Judgment.BAD,
        )
        execution.refresh_from_db()
        assert execution.current_human_review_id == correction.pk
        assert correction.supersedes_id == first.pk
        assert list(execution.review_history.values_list("judgment", flat=True)) == ["GOOD", "BAD"]
        assert _observation_fingerprint(execution) == before
        first.judgment = HumanReview.Judgment.BAD
        with pytest.raises(ValidationError):
            first.save()


@pytest.mark.django_db
def test_error_and_timeout_do_not_synthesize_bad_and_can_be_triaged_without_judgment(minimal_domain):
    with FakeTargetServer() as fake:
        run = _terminal_run(minimal_domain, fake, mode="http_error")
        execution = run.executions.get()
        assert execution.outcome == Execution.Outcome.ERROR
        assert execution.current_human_review is None
        mark_review_required(actor=minimal_domain["admin"], execution=execution)
        mark_reviewed_without_judgment(
            actor=minimal_domain["admin"],
            execution=execution,
            comment_text="Infrastructure triage only",
        )
        execution.refresh_from_db()
        assert execution.review_state == Execution.ReviewState.REVIEWED
        assert execution.current_human_review is None
        assert execution.review_history.count() == 0
        assert list(execution.review_tracking_events.values_list("state", flat=True)) == ["REQUIRED", "REVIEWED"]


@pytest.mark.django_db
def test_review_is_terminal_only_but_comments_are_allowed_on_pending_execution(minimal_domain):
    with FakeTargetServer() as fake:
        _configure_target(minimal_domain, fake)
        run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[minimal_domain["question"].pk],
        )
        execution = run.executions.get()
        append_execution_comment(actor=minimal_domain["admin"], execution=execution, text="Waiting for target")
        with pytest.raises(ValidationError):
            record_human_review(
                actor=minimal_domain["admin"],
                execution=execution,
                judgment=HumanReview.Judgment.GOOD,
            )
        assert execution.comments.count() == 1
        assert execution.current_human_review is None


@pytest.mark.django_db
def test_comments_are_unicode_append_only_and_reject_configured_runtime_secret(minimal_domain, monkeypatch):
    with FakeTargetServer() as fake:
        run = _terminal_run(minimal_domain, fake)
        execution = run.executions.get()
        run_comment = append_run_comment(actor=minimal_domain["admin"], run=run, text="Maintenance — amanhã")
        comment = append_execution_comment(actor=minimal_domain["admin"], execution=execution, text="first note")
        append_execution_comment(actor=minimal_domain["admin"], execution=execution, text="correction note")
        assert list(execution.comments.values_list("text", flat=True)) == ["first note", "correction note"]
        assert run_comment.text == "Maintenance — amanhã"
        comment.text = "rewritten"
        with pytest.raises(ValidationError):
            comment.save()
        with pytest.raises(ValidationError):
            comment.delete()
        monkeypatch.setenv("STEWARD_BENCH_TARGET_CREDENTIAL_M5_COMMENT", "m5-comment-secret")
        with pytest.raises(ValidationError):
            append_execution_comment(
                actor=minimal_domain["admin"],
                execution=execution,
                text="Do not persist m5-comment-secret.",
            )


@pytest.mark.django_db
def test_validity_history_preserves_evidence_and_quality_metrics_exclude_invalid(minimal_domain):
    with FakeTargetServer() as fake:
        _configure_target(minimal_domain, fake)
        questions = [minimal_domain["question"]]
        for number in range(2, 6):
            questions.append(
                create_question(
                    actor=minimal_domain["admin"],
                    stable_id=f"M5-METRIC-{number}",
                    kind=Question.Kind.SINGLE_TURN,
                    lifecycle=Question.Lifecycle.ACTIVE,
                    domain=minimal_domain["domain"],
                    tags=(),
                    rationale="",
                    question_text=f"Metric question {number}",
                )
            )
        run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[question.pk for question in questions],
        )
        while process_next_execution():
            pass
        executions = list(run.executions.order_by("question_order"))
        for execution, judgment in zip(executions[:4], ["GOOD", "BAD", "GOOD", "BAD"], strict=True):
            record_human_review(actor=minimal_domain["admin"], execution=execution, judgment=judgment)
        third_before = _observation_fingerprint(executions[2])
        invalid = set_execution_validity(
            actor=minimal_domain["admin"],
            execution=executions[2],
            validity=Execution.Validity.INVALID,
            comment_text="Broken benchmark fixture",
        )
        set_execution_validity(
            actor=minimal_domain["admin"],
            execution=executions[3],
            validity=Execution.Validity.INVALID,
        )
        executions[2].refresh_from_db()
        assert executions[2].validity == Execution.Validity.INVALID
        assert executions[2].invalidated_by_id == minimal_domain["admin"].pk
        assert executions[2].invalidated_at == invalid.decided_at
        assert _observation_fingerprint(executions[2]) == third_before
        assert run_review_metrics(run) == {
            "total": 5,
            "valid": 3,
            "invalid": 2,
            "human_reviewed": 2,
            "unreviewed": 1,
            "good": 1,
            "bad": 1,
            "review_required": 0,
        }
        correction = set_execution_validity(
            actor=minimal_domain["admin"],
            execution=executions[2],
            validity=Execution.Validity.VALID,
            comment_text="Corrected benchmark fixture",
        )
        assert correction.supersedes_id == invalid.pk
        executions[2].refresh_from_db()
        assert executions[2].validity == Execution.Validity.VALID
        assert executions[2].validity_history.count() == 2


@pytest.mark.django_db
def test_retry_creates_exact_new_history_and_distinct_fake_target_request(minimal_domain):
    with FakeTargetServer() as fake:
        run = _terminal_run(minimal_domain, fake)
        source = run.executions.get()
        before = _observation_fingerprint(source)
        append_execution_comment(actor=minimal_domain["admin"], execution=source, text="Source context")
        record_human_review(actor=minimal_domain["admin"], execution=source, judgment="GOOD")
        key = uuid.uuid4()
        retry_run = retry_execution(actor=minimal_domain["admin"], execution=source, retry_request_key=key)
        assert retry_execution(actor=minimal_domain["admin"], execution=source, retry_request_key=key).pk == retry_run.pk
        retry = retry_run.executions.get()
        assert retry_run.pk != run.pk
        assert retry_run.source_run_id == run.pk
        assert retry_run.source_execution_id == source.pk
        assert retry.source_execution_id == source.pk
        assert retry.question_version_id == source.question_version_id
        assert retry.submitted_question == source.submitted_question
        assert list(retry.resolved_bindings.values_list("name", "value")) == list(
            source.resolved_bindings.values_list("name", "value")
        )
        assert retry.request_correlation_id != source.request_correlation_id
        assert retry.comments.count() == retry.review_history.count() == 0
        assert process_next_execution() is True
        source.refresh_from_db()
        retry.refresh_from_db()
        journal = fake.state.journal_snapshot()
        assert len(journal["entries"]) == 2
        assert set(journal["per_correlation_request_counts"]) == {
            str(source.request_correlation_id),
            str(retry.request_correlation_id),
        }
        assert all(count == 1 for count in journal["per_correlation_request_counts"].values())
        assert _observation_fingerprint(source) == before


@pytest.mark.django_db
def test_rerun_selected_and_all_use_new_normal_manifest_without_copying_review_or_comments(minimal_domain):
    with FakeTargetServer() as fake:
        _configure_target(minimal_domain, fake)
        second = create_question(
            actor=minimal_domain["admin"],
            stable_id="M5-RERUN-SECOND",
            kind=Question.Kind.SINGLE_TURN,
            lifecycle=Question.Lifecycle.ACTIVE,
            domain=minimal_domain["domain"],
            tags=(),
            rationale="",
            question_text="Original second question",
        )
        source_run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[minimal_domain["question"].pk, second.pk],
        )
        while process_next_execution():
            pass
        source = list(source_run.executions.order_by("question_order"))
        append_run_comment(actor=minimal_domain["admin"], run=source_run, text="Source run context")
        record_human_review(actor=minimal_domain["admin"], execution=source[0], judgment="GOOD")
        original_fingerprint = _observation_fingerprint(source[0])
        create_question_version(
            actor=minimal_domain["admin"],
            question=source[0].question,
            question_text="New normal rerun question version",
            change_type=QuestionVersion.ChangeType.TEST_BUG_FIX,
            change_reason="M5 rerun distinction",
        )
        selected = rerun_source_run(
            actor=minimal_domain["admin"],
            source_run=source_run,
            source_execution_ids=[source[0].pk],
        )
        selected_execution = selected.executions.get()
        assert selected.source_run_id == source_run.pk
        assert selected_execution.question_version_id != source[0].question_version_id
        assert selected_execution.review_history.count() == selected_execution.comments.count() == 0
        all_rerun = rerun_source_run(actor=minimal_domain["admin"], source_run=source_run)
        assert all_rerun.source_run_id == source_run.pk
        assert all_rerun.total_planned == 2
        source[0].refresh_from_db()
        assert _observation_fingerprint(source[0]) == original_fingerprint


@pytest.mark.django_db
def test_review_workstation_navigation_and_operator_direct_posts_are_read_only(client, minimal_domain):
    with FakeTargetServer() as fake:
        _configure_target(minimal_domain, fake)
        second = create_question(
            actor=minimal_domain["admin"],
            stable_id="M5-NAV-SECOND",
            kind=Question.Kind.SINGLE_TURN,
            lifecycle=Question.Lifecycle.ACTIVE,
            domain=minimal_domain["domain"],
            tags=(),
            rationale="",
            question_text="Navigation second question",
        )
        run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[minimal_domain["question"].pk, second.pk],
        )
        while process_next_execution():
            pass
        first, second_execution = list(run.executions.order_by("question_order"))
        client.force_login(minimal_domain["admin"])
        stable_queue = f"queue=unreviewed&queue_ids={first.pk},{second_execution.pk}"
        page = client.get(reverse("execution-detail", args=[first.pk]) + f"?{stable_queue}")
        assert page.status_code == 200
        assert b"1 of 2" in page.content
        assert f"/executions/{second_execution.pk}/".encode() in page.content
        review_response = client.post(
            reverse("execution-review", args=[first.pk]),
            {"judgment": "GOOD", "return_queue": stable_queue},
        )
        assert review_response.status_code == 302
        # The action keeps the original, explicit item list even though this
        # execution no longer matches the live unreviewed filter.
        assert "queue=unreviewed" in review_response["Location"]
        preserved_queue_page = client.get(review_response["Location"])
        assert b"1 of 2" in preserved_queue_page.content
        assert f"/executions/{second_execution.pk}/".encode() in preserved_queue_page.content
        append_run_comment(actor=minimal_domain["admin"], run=run, text="Visible operational context")
        client.force_login(minimal_domain["operator"])
        assert client.get(reverse("execution-detail", args=[first.pk])).status_code == 200
        run_page = client.get(reverse("run-detail", args=[run.pk]))
        assert run_page.status_code == 200
        assert b"Visible operational context" in run_page.content
        assert b"Admin review controls" not in run_page.content
        before = _observation_fingerprint(first)
        # Services enforce the same product role policy as the request layer;
        # hidden controls cannot become a mutation bypass.
        with pytest.raises(PermissionDenied):
            record_human_review(actor=minimal_domain["operator"], execution=first, judgment="BAD")
        with pytest.raises(PermissionDenied):
            mark_review_required(actor=minimal_domain["operator"], execution=first)
        with pytest.raises(PermissionDenied):
            append_execution_comment(actor=minimal_domain["operator"], execution=first, text="service bypass")
        with pytest.raises(PermissionDenied):
            append_run_comment(actor=minimal_domain["operator"], run=run, text="service bypass")
        with pytest.raises(PermissionDenied):
            set_execution_validity(actor=minimal_domain["operator"], execution=first, validity="INVALID")
        with pytest.raises(PermissionDenied):
            retry_execution(actor=minimal_domain["operator"], execution=first)
        with pytest.raises(PermissionDenied):
            rerun_source_run(actor=minimal_domain["operator"], source_run=run)
        post_paths = [
            ("execution-review", {"judgment": "GOOD"}),
            ("execution-review-state", {"state": "REQUIRED"}),
            ("execution-comment", {"text": "operator mutation"}),
            ("execution-validity", {"validity": "INVALID"}),
            ("execution-retry", {"retry_request_key": str(uuid.uuid4())}),
            ("run-comment", {"text": "operator mutation"}),
            ("run-rerun", {"rerun_scope": "all"}),
        ]
        for name, data in post_paths:
            args = [run.pk] if name.startswith("run-") else [first.pk]
            response = client.post(reverse(name, args=args), data)
            assert response.status_code == 403
        assert _observation_fingerprint(first) == before
        assert first.review_history.count() == 1
        assert first.comments.count() == first.validity_history.count() == 0
