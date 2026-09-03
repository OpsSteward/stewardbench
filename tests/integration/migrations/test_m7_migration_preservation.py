"""Forward M6 -> M7 preservation evidence using populated PostgreSQL history."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from catalog.models import TargetRevision
from catalog.services import create_target_revision


M6 = ("evaluations", "0004_m6_baselines_exact_comparison")
M7 = ("evaluations", "0005_semanticcomparisonresult")


@pytest.mark.django_db(transaction=True)
@pytest.mark.postgresql
def test_m7_migration_preserves_populated_m6_history_and_adds_empty_semantic_results(minimal_domain):
    """M7 adds semantic history only; it must not rewrite M6 observations."""

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
        declared_product_version="m6-version",
        declared_build_id="m6-build",
        declared_git_sha="m6-sha",
    )
    executor = MigrationExecutor(connection)
    executor.migrate([M6])
    old_apps = executor.loader.project_state([M6]).apps
    OldRun = old_apps.get_model("evaluations", "EvaluationRun")
    OldTargetSnapshot = old_apps.get_model("evaluations", "TargetSnapshot")
    OldBuildSnapshot = old_apps.get_model("evaluations", "BuildSnapshot")
    OldExecution = old_apps.get_model("evaluations", "Execution")
    OldBaseline = old_apps.get_model("evaluations", "Baseline")
    OldMembership = old_apps.get_model("evaluations", "BaselineMembership")
    OldComparison = old_apps.get_model("evaluations", "Comparison")
    OldComparisonItem = old_apps.get_model("evaluations", "ComparisonItem")
    OldHumanReview = old_apps.get_model("evaluations", "HumanReview")
    OldValidity = old_apps.get_model("evaluations", "ExecutionValidityDecision")
    OldTracking = old_apps.get_model("evaluations", "ReviewTracking")
    OldAttention = old_apps.get_model("evaluations", "BaselineAttentionEvent")
    question = minimal_domain["question"]
    version = question.current_version
    now = timezone.now()

    def run_with_snapshots(label, *, state="COMPLETED", comparison_baseline_id=None):
        run = OldRun.objects.create(
            target_id=minimal_domain["target"].pk,
            target_revision_id=revision.pk,
            launched_by_id=minimal_domain["admin"].pk,
            state=state,
            requested_mode="SEQUENTIAL",
            configured_max_concurrency=1,
            actual_concurrency=1,
            question_timeout_seconds=30,
            inter_question_delay_seconds=0,
            total_planned=2 if state == "COMPLETED_WITH_ERRORS" else 1,
            selection_filter={"m6": label},
            comparison_baseline_id=comparison_baseline_id,
            started_at=now,
            completed_at=now,
        )
        target = OldTargetSnapshot.objects.create(
            run_id=run.pk,
            target_id=minimal_domain["target"].pk,
            target_revision_id=revision.pk,
            target_display_name=f"M6 target {label}",
            product_display_name="M6 product",
            environment_display_name="M6 environment",
            endpoint="http://127.0.0.1:18081",
            adapter_key="fake-http",
            adapter_version="1",
            credential_reference="",
            classification="LAB_TEST",
            supports_runtime_metadata=False,
        )
        build = OldBuildSnapshot.objects.create(
            run_id=run.pk,
            declared_product_version="m6-version",
            declared_build_id=f"m6-{label}",
            declared_git_sha="m6-sha",
            runtime_state="UNAVAILABLE",
            runtime_diagnostic="M6 migration fixture",
            runtime_observed_at=now,
        )
        return run, target, build

    def terminal_execution(run, target, build, *, order, answer, validity="VALID", outcome="SUCCESS"):
        return OldExecution.objects.create(
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
            submitted_question="M6 frozen question — São Paulo",
            outcome=outcome,
            adapter_key="fake-http",
            adapter_version="1",
            raw_request={"m6": order},
            raw_response=f"M6 raw response {order}",
            raw_answer=answer,
            display_answer=answer,
            evidence={"m6": order, "unicode": "✓"},
            error_class="HTTP_ERROR" if outcome == "ERROR" else "",
            error_detail="M6 retained error" if outcome == "ERROR" else "",
            claim_worker_id="m6-worker",
            claim_attempt=1,
            target_call_phase="TERMINAL",
            review_state="REQUIRED" if order == 1 and outcome == "SUCCESS" else "NONE",
            validity=validity,
            started_at=now,
            completed_at=now,
            latency_ms=21,
        )

    source_run, source_target, source_build = run_with_snapshots("source", state="COMPLETED_WITH_ERRORS")
    baseline_execution = terminal_execution(
        source_run, source_target, source_build, order=1, answer="M6 baseline answer"
    )
    invalid_member = terminal_execution(
        source_run, source_target, source_build, order=2, answer="", validity="INVALID", outcome="ERROR"
    )
    first_review = OldHumanReview.objects.create(
        execution_id=baseline_execution.pk,
        judgment="GOOD",
        reviewed_by_id=minimal_domain["admin"].pk,
    )
    baseline_review = OldHumanReview.objects.create(
        execution_id=baseline_execution.pk,
        judgment="BAD",
        reviewed_by_id=minimal_domain["admin"].pk,
        supersedes_id=first_review.pk,
    )
    OldExecution.objects.filter(pk=baseline_execution.pk).update(
        current_human_review_id=baseline_review.pk, review_state="REVIEWED"
    )
    invalidity = OldValidity.objects.create(
        execution_id=invalid_member.pk,
        validity="INVALID",
        decided_by_id=minimal_domain["admin"].pk,
    )
    baseline = OldBaseline.objects.create(
        name="M6 preserved baseline",
        description="M6 observed history",
        source_run_id=source_run.pk,
        source_target_id=minimal_domain["target"].pk,
        created_by_id=minimal_domain["admin"].pk,
        is_active=True,
        requires_attention=True,
        attention_opened_at=now,
        attention_detail="M6 invalid member requires attention",
    )
    OldMembership.objects.create(baseline_id=baseline.pk, execution_id=baseline_execution.pk)
    OldMembership.objects.create(baseline_id=baseline.pk, execution_id=invalid_member.pk)
    OldAttention.objects.create(
        baseline_id=baseline.pk,
        execution_id=invalid_member.pk,
        validity_decision_id=invalidity.pk,
        actor_id=minimal_domain["admin"].pk,
        detail="M6 retained invalid baseline member",
    )

    current_run, current_target, current_build = run_with_snapshots(
        "current", comparison_baseline_id=baseline.pk
    )
    current_execution = terminal_execution(
        current_run, current_target, current_build, order=1, answer="M6 current changed answer"
    )
    comparison = OldComparison.objects.create(
        baseline_id=baseline.pk,
        current_run_id=current_run.pk,
        algorithm_key="exact",
        algorithm_version="exact-v1",
    )
    comparison_item = OldComparisonItem.objects.create(
        comparison_id=comparison.pk,
        baseline_execution_id=baseline_execution.pk,
        current_execution_id=current_execution.pk,
        baseline_human_review_id=baseline_review.pk,
        change_state="CHANGED",
        exact_equal=False,
        baseline_normalized_hash="a" * 64,
        current_normalized_hash="b" * 64,
        detail="M6 exact evidence must remain CHANGED",
    )
    OldTracking.objects.create(
        execution_id=current_execution.pk,
        state="REQUIRED",
        actor_id=None,
        cause=f"Exact comparison exact-v1 CHANGED (comparison item {comparison_item.pk}) requires review",
    )

    execution_fields = (
        "run_id", "outcome", "question_version_id", "submitted_question", "raw_answer", "display_answer",
        "evidence", "review_state", "current_human_review_id", "validity", "baseline_execution_id",
    )
    before_executions = list(OldExecution.objects.order_by("run_id", "question_order").values_list(*execution_fields))
    before_baseline = OldBaseline.objects.values_list(
        "id", "source_run_id", "source_target_id", "name", "requires_attention", "attention_detail"
    ).get(pk=baseline.pk)
    before_memberships = list(OldMembership.objects.order_by("id").values_list("baseline_id", "execution_id"))
    before_item = OldComparisonItem.objects.values_list(
        "baseline_execution_id", "current_execution_id", "change_state", "exact_equal",
        "baseline_normalized_hash", "current_normalized_hash", "detail",
    ).get(pk=comparison_item.pk)
    before_reviews = list(OldHumanReview.objects.order_by("id").values_list("judgment", "supersedes_id"))
    before_tracking = list(OldTracking.objects.order_by("id").values_list("state", "actor_id", "cause"))

    executor = MigrationExecutor(connection)
    executor.migrate([M7])

    from evaluations.models import (
        Baseline,
        BaselineAttentionEvent,
        BaselineMembership,
        ComparisonItem,
        Execution,
        HumanReview,
        ReviewTracking,
        SemanticComparisonResult,
    )

    assert list(Execution.objects.order_by("run_id", "question_order").values_list(*execution_fields)) == before_executions
    assert Baseline.objects.values_list(
        "id", "source_run_id", "source_target_id", "name", "requires_attention", "attention_detail"
    ).get(pk=baseline.pk) == before_baseline
    assert list(BaselineMembership.objects.order_by("id").values_list("baseline_id", "execution_id")) == before_memberships
    assert BaselineAttentionEvent.objects.filter(baseline_id=baseline.pk).count() == 1
    assert ComparisonItem.objects.values_list(
        "baseline_execution_id", "current_execution_id", "change_state", "exact_equal",
        "baseline_normalized_hash", "current_normalized_hash", "detail",
    ).get(pk=comparison_item.pk) == before_item
    assert list(HumanReview.objects.order_by("id").values_list("judgment", "supersedes_id")) == before_reviews
    assert list(ReviewTracking.objects.order_by("id").values_list("state", "actor_id", "cause")) == before_tracking
    assert SemanticComparisonResult.objects.count() == 0
