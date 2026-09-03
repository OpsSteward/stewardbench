"""Forward M8 -> M9 preservation evidence over populated PostgreSQL history."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from catalog.models import TargetRevision
from catalog.services import create_conversation_scenario, create_target_revision


M8 = ("evaluations", "0006_m8_conversation_scenarios")
M9 = ("evaluations", "0008_m9_evaluator_invocation_recovery")


@pytest.mark.django_db(transaction=True)
@pytest.mark.postgresql
def test_m9_migration_preserves_populated_m8_history_and_adds_empty_evaluator_work(minimal_domain):
    """M9 appends evaluator schema without fabricating or rewriting M0--M8 facts."""

    revision = create_target_revision(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        endpoint="http://127.0.0.1:18091",
        adapter_key="fake-http",
        adapter_version="1",
        credential_reference="",
        classification=TargetRevision.Classification.LAB_TEST,
        supports_question_api=True,
        supports_conversation_session=True,
        supports_runtime_metadata=False,
        supports_health_check=True,
        default_execution_mode=TargetRevision.ExecutionMode.SEQUENTIAL,
        max_concurrency=1,
        question_timeout_seconds=30,
        inter_question_delay_seconds=0,
        declared_product_version="m8-preserved",
        declared_build_id="m8-build",
        declared_git_sha="m8-sha",
    )
    scenario = create_conversation_scenario(
        actor=minimal_domain["admin"],
        stable_id="M9-MIG-CONV",
        name="M9 migration conversation",
        lifecycle="ACTIVE",
        domain=minimal_domain["domain"],
        turns=[{"stable_turn_id": "M9-MIG-CONV.1", "prompt_template": "Olá, estado da sessão?"}],
    )
    turn = scenario.current_version.turns.get()
    executor = MigrationExecutor(connection)
    executor.migrate([M8])
    apps = executor.loader.project_state([M8]).apps
    Run = apps.get_model("evaluations", "EvaluationRun")
    TargetSnapshot = apps.get_model("evaluations", "TargetSnapshot")
    BuildSnapshot = apps.get_model("evaluations", "BuildSnapshot")
    Execution = apps.get_model("evaluations", "Execution")
    Binding = apps.get_model("evaluations", "ResolvedBinding")
    Automated = apps.get_model("evaluations", "AutomatedEvaluationResult")
    Judge = apps.get_model("evaluations", "LLMJudgeResult")
    HumanReview = apps.get_model("evaluations", "HumanReview")
    ReviewTracking = apps.get_model("evaluations", "ReviewTracking")
    Validity = apps.get_model("evaluations", "ExecutionValidityDecision")
    Baseline = apps.get_model("evaluations", "Baseline")
    Membership = apps.get_model("evaluations", "BaselineMembership")
    Comparison = apps.get_model("evaluations", "Comparison")
    Item = apps.get_model("evaluations", "ComparisonItem")
    Semantic = apps.get_model("evaluations", "SemanticComparisonResult")
    Attempt = apps.get_model("evaluations", "ConversationAttempt")
    now = timezone.now()
    question = minimal_domain["question"]
    version = question.current_version

    def observed_run(label, *, conversation=False):
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
            selection_filter={"m8": label},
            started_at=now,
            completed_at=now,
        )
        target = TargetSnapshot.objects.create(
            run_id=run.pk,
            target_id=minimal_domain["target"].pk,
            target_revision_id=revision.pk,
            target_display_name="M8 target",
            product_display_name="M8 product",
            environment_display_name="M8 environment",
            endpoint="http://127.0.0.1:18091",
            adapter_key="fake-http",
            adapter_version="1",
            credential_reference="",
            classification="LAB_TEST",
            supports_runtime_metadata=False,
        )
        build = BuildSnapshot.objects.create(
            run_id=run.pk,
            declared_product_version="m8-preserved",
            declared_build_id=label,
            declared_git_sha="m8-sha",
            runtime_state="UNAVAILABLE",
            runtime_diagnostic="M8 preservation",
            runtime_observed_at=now,
        )
        attempt = None
        if conversation:
            attempt = Attempt.objects.create(
                run_id=run.pk,
                scenario_version_id=scenario.current_version.pk,
                target_session_id="m8-session-✓",
                session_metadata={"unicode": "São Paulo"},
                session_state="CLOSED",
                started_at=now,
                completed_at=now,
            )
        execution = Execution.objects.create(
            run_id=run.pk,
            question_id=question.pk,
            question_version_id=version.pk,
            conversation_attempt_id=attempt.pk if attempt else None,
            conversation_turn_id=turn.pk if attempt else None,
            target_revision_id=revision.pk,
            target_snapshot_id=target.pk,
            build_snapshot_id=build.pk,
            question_order=1,
            question_stable_id=question.stable_id,
            question_version_number=version.version_number,
            question_template=version.question_text,
            submitted_question=f"M8 frozen {label} — Português ✓",
            outcome="SUCCESS",
            adapter_key="fake-http",
            adapter_version="1",
            raw_request={"label": label},
            raw_response=f"raw {label}",
            raw_answer=f"answer {label}",
            display_answer=f"answer {label}",
            evidence={"label": label, "unicode": "✓"},
            claim_worker_id="m8-worker",
            claim_attempt=1,
            target_call_phase="TERMINAL",
            review_state="REVIEWED",
            validity="VALID",
            started_at=now,
            completed_at=now,
            latency_ms=19,
        )
        Binding.objects.create(
            execution_id=execution.pk,
            name="fixture",
            resolution_mode="FIXED_ADMIN",
            value={"label": label},
            display_value=label,
        )
        return run, execution

    baseline_run, baseline_execution = observed_run("baseline")
    first = HumanReview.objects.create(
        execution_id=baseline_execution.pk, judgment="GOOD", reviewed_by_id=minimal_domain["admin"].pk
    )
    review = HumanReview.objects.create(
        execution_id=baseline_execution.pk,
        judgment="BAD",
        reviewed_by_id=minimal_domain["admin"].pk,
        supersedes_id=first.pk,
    )
    Execution.objects.filter(pk=baseline_execution.pk).update(current_human_review_id=review.pk)
    ReviewTracking.objects.create(execution_id=baseline_execution.pk, state="REVIEWED", actor_id=minimal_domain["admin"].pk)
    Validity.objects.create(execution_id=baseline_execution.pk, validity="INVALID", decided_by_id=minimal_domain["admin"].pk)
    automated = Automated.objects.create(
        execution_id=baseline_execution.pk,
        evaluator_key="m5-envelope",
        evaluator_version="1",
        status="COMPLETE",
        outcome="CANNOT_CONCLUDE",
        details={"m5": "automated"},
    )
    judge = Judge.objects.create(
        execution_id=baseline_execution.pk,
        provider="m5-fixture",
        model_identifier="m5-model",
        judge_version="1",
        prompt_version="1",
        status="COMPLETE",
        dimensions={"grounding": "uncertain"},
    )
    baseline = Baseline.objects.create(
        name="M8 populated baseline",
        source_run_id=baseline_run.pk,
        source_target_id=minimal_domain["target"].pk,
        created_by_id=minimal_domain["admin"].pk,
    )
    Membership.objects.create(baseline_id=baseline.pk, execution_id=baseline_execution.pk)
    current_run, current_execution = observed_run("current")
    comparison = Comparison.objects.create(
        baseline_id=baseline.pk, current_run_id=current_run.pk, algorithm_key="exact", algorithm_version="exact-v1"
    )
    item = Item.objects.create(
        comparison_id=comparison.pk,
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
        provider_key="m8-fake",
        model_identifier="m8-model",
        comparator_version="m8-v1",
        input_fingerprint="c" * 64,
        input_manifest={"m8": True},
        rationale="M8 semantic history",
        raw_result={"outcome": "UNCERTAIN"},
    )
    _, conversation_execution = observed_run("conversation", conversation=True)
    before = {
        "execution": Execution.objects.values_list(
            "submitted_question", "raw_response", "raw_answer", "display_answer", "evidence", "review_state", "validity"
        ).get(pk=baseline_execution.pk),
        "review": list(HumanReview.objects.values_list("judgment", "supersedes_id")),
        "automated": Automated.objects.values_list("evaluator_key", "outcome", "details").get(pk=automated.pk),
        "judge": Judge.objects.values_list("provider", "dimensions").get(pk=judge.pk),
        "comparison": Item.objects.values_list("change_state", "exact_equal").get(pk=item.pk),
        "semantic": Semantic.objects.values_list("outcome", "input_manifest", "rationale").get(pk=semantic.pk),
        "conversation": Execution.objects.values_list("conversation_attempt_id", "conversation_turn_id", "submitted_question").get(
            pk=conversation_execution.pk
        ),
    }

    executor = MigrationExecutor(connection)
    executor.migrate([M9])

    from evaluations.models import (
        AutomatedEvaluationResult,
        EvaluationInvocation,
        Execution as M9Execution,
        HumanReview as M9Review,
        LLMJudgeResult,
        SemanticComparisonResult,
    )

    assert M9Execution.objects.values_list(
        "submitted_question", "raw_response", "raw_answer", "display_answer", "evidence", "review_state", "validity"
    ).get(pk=baseline_execution.pk) == before["execution"]
    assert list(M9Review.objects.values_list("judgment", "supersedes_id")) == before["review"]
    assert AutomatedEvaluationResult.objects.values_list("evaluator_key", "outcome", "details").get(pk=automated.pk) == before["automated"]
    assert LLMJudgeResult.objects.values_list("provider", "dimensions").get(pk=judge.pk) == before["judge"]
    assert Item.objects.values_list("change_state", "exact_equal").get(pk=item.pk) == before["comparison"]
    assert SemanticComparisonResult.objects.values_list("outcome", "input_manifest", "rationale").get(pk=semantic.pk) == before["semantic"]
    assert M9Execution.objects.values_list("conversation_attempt_id", "conversation_turn_id", "submitted_question").get(
        pk=conversation_execution.pk
    ) == before["conversation"]
    assert EvaluationInvocation.objects.count() == 0
