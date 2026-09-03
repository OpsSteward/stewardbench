"""Forward M5 -> M6 preservation evidence using a populated PostgreSQL history."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from catalog.models import TargetRevision
from catalog.services import create_target_revision


M5 = ("evaluations", "0003_llmjudgeresult_reviewtracking_and_more")
M6 = ("evaluations", "0004_m6_baselines_exact_comparison")


@pytest.mark.django_db(transaction=True)
@pytest.mark.postgresql
def test_m6_migration_preserves_populated_m5_history_and_creates_empty_m6_tables(minimal_domain):
    """M6 adds empty relations without fabricating or changing M5 evidence."""

    revision = create_target_revision(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        endpoint="http://127.0.0.1:18081",
        adapter_key="fake-http",
        adapter_version="1",
        credential_reference="",
        classification=TargetRevision.Classification.LAB_TEST,
        supports_question_api=True,
        supports_conversation_session=False,
        supports_runtime_metadata=False,
        supports_health_check=True,
        default_execution_mode=TargetRevision.ExecutionMode.SEQUENTIAL,
        max_concurrency=1,
        question_timeout_seconds=30,
        inter_question_delay_seconds=0,
        declared_product_version="m5-version",
        declared_build_id="m5-build",
        declared_git_sha="m5-sha",
    )
    executor = MigrationExecutor(connection)
    executor.migrate([M5])
    old_apps = executor.loader.project_state([M5]).apps
    OldRun = old_apps.get_model("evaluations", "EvaluationRun")
    OldTargetSnapshot = old_apps.get_model("evaluations", "TargetSnapshot")
    OldBuildSnapshot = old_apps.get_model("evaluations", "BuildSnapshot")
    OldExecution = old_apps.get_model("evaluations", "Execution")
    OldComment = old_apps.get_model("evaluations", "Comment")
    OldHumanReview = old_apps.get_model("evaluations", "HumanReview")
    OldValidityDecision = old_apps.get_model("evaluations", "ExecutionValidityDecision")
    OldReviewTracking = old_apps.get_model("evaluations", "ReviewTracking")
    now = timezone.now()
    question = minimal_domain["question"]
    version = question.current_version

    run = OldRun.objects.create(
        target_id=minimal_domain["target"].pk,
        target_revision_id=revision.pk,
        launched_by_id=minimal_domain["admin"].pk,
        state="COMPLETED_WITH_ERRORS",
        requested_mode="SEQUENTIAL",
        configured_max_concurrency=1,
        actual_concurrency=1,
        question_timeout_seconds=30,
        inter_question_delay_seconds=0,
        total_planned=3,
        selection_filter={"m5": "populated-history"},
        started_at=now,
        completed_at=now,
    )
    target = OldTargetSnapshot.objects.create(
        run_id=run.pk,
        target_id=minimal_domain["target"].pk,
        target_revision_id=revision.pk,
        target_display_name="M5 frozen target",
        product_display_name="M5 product",
        environment_display_name="M5 environment",
        endpoint="http://127.0.0.1:18081",
        adapter_key="fake-http",
        adapter_version="1",
        credential_reference="",
        classification="LAB_TEST",
        supports_runtime_metadata=False,
    )
    build = OldBuildSnapshot.objects.create(
        run_id=run.pk,
        declared_product_version="m5-version",
        declared_build_id="m5-build",
        declared_git_sha="m5-sha",
        runtime_state="UNAVAILABLE",
        runtime_diagnostic="M5 fixture",
        runtime_observed_at=now,
    )

    executions = []
    for order, (outcome, raw_answer, error) in enumerate(
        (("SUCCESS", "M5 raw answer ✓", ""), ("ERROR", "", "HTTP_ERROR"), ("TIMEOUT", "", "TARGET_TIMEOUT")),
        start=1,
    ):
        executions.append(
            OldExecution.objects.create(
                run_id=run.pk,
                question_id=question.pk,
                question_version_id=version.pk,
                target_revision_id=revision.pk,
                target_snapshot_id=target.pk,
                build_snapshot_id=build.pk,
                question_order=order,
                question_stable_id=question.stable_id,
                question_version_number=version.version_number,
                question_template=version.question_text,
                submitted_question=f"M5 exact submitted {order} — São Paulo",
                outcome=outcome,
                adapter_key="fake-http",
                adapter_version="1",
                raw_request={"m5": order},
                raw_response=f"M5 raw response {order}",
                raw_answer=raw_answer,
                display_answer=raw_answer,
                evidence={"m5": order, "unicode": "✓"},
                response_metadata={"m5": "metadata"},
                error_class=error,
                error_detail="M5 error evidence" if error else "",
                claim_worker_id="m5-worker",
                claim_attempt=2,
                target_call_phase="TERMINAL",
                started_at=now,
                completed_at=now,
                latency_ms=42,
            )
        )
    success = executions[0]
    comment = OldComment.objects.create(
        execution_id=success.pk,
        author_id=minimal_domain["admin"].pk,
        text="M5 append-only comment — contexto ✓",
    )
    good = OldHumanReview.objects.create(
        execution_id=success.pk,
        judgment="GOOD",
        reviewed_by_id=minimal_domain["admin"].pk,
        comment_id=comment.pk,
    )
    bad = OldHumanReview.objects.create(
        execution_id=success.pk,
        judgment="BAD",
        reviewed_by_id=minimal_domain["admin"].pk,
        supersedes_id=good.pk,
    )
    invalid = OldValidityDecision.objects.create(
        execution_id=success.pk,
        validity="INVALID",
        decided_by_id=minimal_domain["admin"].pk,
    )
    valid = OldValidityDecision.objects.create(
        execution_id=success.pk,
        validity="VALID",
        decided_by_id=minimal_domain["admin"].pk,
        supersedes_id=invalid.pk,
    )
    OldReviewTracking.objects.create(
        execution_id=success.pk,
        state="REVIEWED",
        actor_id=minimal_domain["admin"].pk,
        cause="M5 human correction fixture",
    )
    OldExecution.objects.filter(pk=success.pk).update(
        current_human_review_id=bad.pk,
        review_state="REVIEWED",
        validity="VALID",
        invalidated_by_id=None,
        invalidated_at=None,
    )
    retry_run = OldRun.objects.create(
        target_id=minimal_domain["target"].pk,
        target_revision_id=revision.pk,
        launched_by_id=minimal_domain["admin"].pk,
        state="COMPLETED",
        requested_mode="SEQUENTIAL",
        configured_max_concurrency=1,
        actual_concurrency=1,
        question_timeout_seconds=30,
        inter_question_delay_seconds=0,
        total_planned=1,
        selection_filter={"retry": success.pk},
        source_run_id=run.pk,
        source_execution_id=success.pk,
        started_at=now,
        completed_at=now,
    )
    retry_target = OldTargetSnapshot.objects.create(
        run_id=retry_run.pk,
        target_id=minimal_domain["target"].pk,
        target_revision_id=revision.pk,
        target_display_name="M5 frozen target",
        product_display_name="M5 product",
        environment_display_name="M5 environment",
        endpoint="http://127.0.0.1:18081",
        adapter_key="fake-http",
        adapter_version="1",
        credential_reference="",
        classification="LAB_TEST",
        supports_runtime_metadata=False,
    )
    retry_build = OldBuildSnapshot.objects.create(run_id=retry_run.pk, runtime_state="NOT_ATTEMPTED")
    OldExecution.objects.create(
        run_id=retry_run.pk,
        question_id=question.pk,
        question_version_id=version.pk,
        target_revision_id=revision.pk,
        target_snapshot_id=retry_target.pk,
        build_snapshot_id=retry_build.pk,
        question_order=1,
        question_stable_id=question.stable_id,
        question_version_number=version.version_number,
        question_template=version.question_text,
        submitted_question="M5 retry exact submitted",
        outcome="SUCCESS",
        adapter_key="fake-http",
        adapter_version="1",
        raw_response="M5 retry raw response",
        raw_answer="M5 retry answer",
        display_answer="M5 retry answer",
        evidence={"retry": True},
        claim_worker_id="m5-worker",
        claim_attempt=1,
        target_call_phase="TERMINAL",
        source_execution_id=success.pk,
        started_at=now,
        completed_at=now,
        latency_ms=11,
    )

    execution_fields = (
        "run_id", "outcome", "question_version_id", "submitted_question", "raw_request", "raw_response",
        "raw_answer", "display_answer", "evidence", "response_metadata", "error_class", "error_detail",
        "target_snapshot_id", "build_snapshot_id", "target_revision_id", "claim_worker_id", "claim_attempt",
        "target_call_phase", "review_state", "current_human_review_id", "validity", "source_execution_id",
    )
    before_executions = list(OldExecution.objects.order_by("run_id", "question_order").values_list(*execution_fields))
    before_reviews = list(OldHumanReview.objects.order_by("id").values_list("judgment", "supersedes_id", "comment_id"))
    before_validity = list(OldValidityDecision.objects.order_by("id").values_list("validity", "supersedes_id"))
    before_comments = list(OldComment.objects.values_list("text", flat=True))

    executor = MigrationExecutor(connection)
    executor.migrate([M6])

    from evaluations.models import (
        Baseline,
        BaselineMembership,
        Comparison,
        ComparisonItem,
        Execution,
        ExecutionValidityDecision,
        HumanReview,
        Comment,
    )

    assert list(Execution.objects.order_by("run_id", "question_order").values_list(*execution_fields)) == before_executions
    assert list(HumanReview.objects.order_by("id").values_list("judgment", "supersedes_id", "comment_id")) == before_reviews
    assert list(ExecutionValidityDecision.objects.order_by("id").values_list("validity", "supersedes_id")) == before_validity
    assert list(Comment.objects.values_list("text", flat=True)) == before_comments
    assert Baseline.objects.count() == BaselineMembership.objects.count() == 0
    assert Comparison.objects.count() == ComparisonItem.objects.count() == 0
