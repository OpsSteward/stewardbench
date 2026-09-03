"""Forward M7 -> M8 evidence: historical M0-M7 rows stay byte-for-byte meaningful."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from catalog.models import TargetRevision
from catalog.services import create_target_revision


M7 = ("evaluations", "0005_semanticcomparisonresult")
M8 = ("evaluations", "0006_m8_conversation_scenarios")


@pytest.mark.django_db(transaction=True)
@pytest.mark.postgresql
def test_m8_migration_preserves_populated_m7_evidence_and_starts_conversation_tables_empty(minimal_domain):
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
        declared_product_version="m7-version",
        declared_build_id="m7-build",
        declared_git_sha="m7-sha",
    )
    executor = MigrationExecutor(connection)
    executor.migrate([M7])
    apps = executor.loader.project_state([M7]).apps
    Run = apps.get_model("evaluations", "EvaluationRun")
    Snapshot = apps.get_model("evaluations", "TargetSnapshot")
    Build = apps.get_model("evaluations", "BuildSnapshot")
    Execution = apps.get_model("evaluations", "Execution")
    Review = apps.get_model("evaluations", "HumanReview")
    Validity = apps.get_model("evaluations", "ExecutionValidityDecision")
    Baseline = apps.get_model("evaluations", "Baseline")
    Membership = apps.get_model("evaluations", "BaselineMembership")
    Comparison = apps.get_model("evaluations", "Comparison")
    Item = apps.get_model("evaluations", "ComparisonItem")
    Semantic = apps.get_model("evaluations", "SemanticComparisonResult")
    now = timezone.now()
    question = minimal_domain["question"]
    version = question.current_version

    def run_with_evidence(label, *, baseline_id=None):
        run = Run.objects.create(
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
            selection_filter={"m7": label},
            comparison_baseline_id=baseline_id,
            started_at=now,
            completed_at=now,
        )
        target = Snapshot.objects.create(
            run_id=run.pk,
            target_id=minimal_domain["target"].pk,
            target_revision_id=revision.pk,
            target_display_name="M7 preserved target",
            product_display_name="M7 preserved product",
            environment_display_name="M7 preserved environment",
            endpoint="http://127.0.0.1:18081",
            adapter_key="fake-http",
            adapter_version="1",
            credential_reference="",
            classification="LAB_TEST",
            supports_runtime_metadata=False,
        )
        build = Build.objects.create(
            run_id=run.pk,
            declared_product_version="m7-version",
            declared_build_id=f"m7-{label}",
            declared_git_sha="m7-sha",
            runtime_state="UNAVAILABLE",
            runtime_diagnostic="M7 preservation fixture",
            runtime_observed_at=now,
        )
        execution = Execution.objects.create(
            run_id=run.pk,
            question_id=question.pk,
            question_version_id=version.pk,
            target_revision_id=revision.pk,
            target_snapshot_id=target.pk,
            build_snapshot_id=build.pk,
            question_order=1,
            question_stable_id=question.stable_id,
            question_version_number=version.version_number,
            question_template=version.question_text,
            submitted_question="M7 frozen Unicode — São Paulo ✓",
            outcome="SUCCESS",
            adapter_key="fake-http",
            adapter_version="1",
            raw_request={"request": label},
            raw_response=f"M7 raw response {label}",
            raw_answer=f"M7 answer {label}",
            display_answer=f"M7 answer {label}",
            evidence={"label": label, "unicode": "✓"},
            claim_worker_id="m7-worker",
            claim_attempt=1,
            target_call_phase="TERMINAL",
            review_state="REVIEWED",
            validity="VALID",
            started_at=now,
            completed_at=now,
            latency_ms=17,
        )
        return run, execution

    baseline_run, baseline_execution = run_with_evidence("baseline")
    first = Review.objects.create(execution_id=baseline_execution.pk, judgment="GOOD", reviewed_by_id=minimal_domain["admin"].pk)
    review = Review.objects.create(execution_id=baseline_execution.pk, judgment="BAD", reviewed_by_id=minimal_domain["admin"].pk, supersedes_id=first.pk)
    Execution.objects.filter(pk=baseline_execution.pk).update(current_human_review_id=review.pk)
    validity = Validity.objects.create(execution_id=baseline_execution.pk, validity="INVALID", decided_by_id=minimal_domain["admin"].pk)
    baseline = Baseline.objects.create(
        name="M7 populated baseline",
        source_run_id=baseline_run.pk,
        source_target_id=minimal_domain["target"].pk,
        created_by_id=minimal_domain["admin"].pk,
        is_active=True,
    )
    Membership.objects.create(baseline_id=baseline.pk, execution_id=baseline_execution.pk)
    current_run, current_execution = run_with_evidence("current", baseline_id=baseline.pk)
    item = Item.objects.create(
        comparison_id=Comparison.objects.create(
            baseline_id=baseline.pk, current_run_id=current_run.pk, algorithm_key="exact", algorithm_version="exact-v1"
        ).pk,
        baseline_execution_id=baseline_execution.pk,
        current_execution_id=current_execution.pk,
        baseline_human_review_id=review.pk,
        change_state="CHANGED",
        exact_equal=False,
        baseline_normalized_hash="a" * 64,
        current_normalized_hash="b" * 64,
    )
    semantic = Semantic.objects.create(
        comparison_item_id=item.pk,
        outcome="UNCERTAIN",
        provider_key="deterministic",
        model_identifier="m7-double",
        comparator_version="m7-v1",
        input_fingerprint="c" * 64,
        input_manifest={"item": item.pk},
        rationale="M7 result remains historical",
        raw_result={"outcome": "UNCERTAIN"},
        latency_ms=3,
    )
    before = {
        "execution": Execution.objects.values_list(
            "submitted_question", "raw_response", "raw_answer", "display_answer", "evidence", "claim_worker_id", "claim_attempt", "review_state", "validity", "current_human_review_id"
        ).get(pk=baseline_execution.pk),
        "membership": list(Membership.objects.values_list("baseline_id", "execution_id")),
        "comparison": Item.objects.values_list("baseline_execution_id", "current_execution_id", "change_state", "exact_equal").get(pk=item.pk),
        "semantic": Semantic.objects.values_list("outcome", "provider_key", "input_manifest", "rationale", "raw_result").get(pk=semantic.pk),
    }

    executor = MigrationExecutor(connection)
    executor.migrate([M8])

    from catalog.models import ConversationScenario, ConversationScenarioVersion, ConversationTurn
    from evaluations.models import ConversationAttempt, Execution as M8Execution, SemanticComparisonResult

    assert M8Execution.objects.values_list(
        "submitted_question", "raw_response", "raw_answer", "display_answer", "evidence", "claim_worker_id", "claim_attempt", "review_state", "validity", "current_human_review_id"
    ).get(pk=baseline_execution.pk) == before["execution"]
    assert list(Membership.objects.values_list("baseline_id", "execution_id")) == before["membership"]
    assert Item.objects.values_list("baseline_execution_id", "current_execution_id", "change_state", "exact_equal").get(pk=item.pk) == before["comparison"]
    assert SemanticComparisonResult.objects.values_list("outcome", "provider_key", "input_manifest", "rationale", "raw_result").get(pk=semantic.pk) == before["semantic"]
    assert ConversationScenario.objects.count() == ConversationScenarioVersion.objects.count() == ConversationTurn.objects.count() == ConversationAttempt.objects.count() == 0
