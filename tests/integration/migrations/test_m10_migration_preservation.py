"""Forward populated-M9 -> M10 preservation evidence on PostgreSQL."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from catalog.models import TargetRevision
from catalog.services import create_conversation_scenario, create_target_revision
from corpus.models import ImportedSourceRow, LegacyImportBatch, LegacyObservation


M9 = ("evaluations", "0008_m9_evaluator_invocation_recovery")
M10 = ("evaluations", "0009_m10_performance_evidence")


@pytest.mark.django_db(transaction=True)
@pytest.mark.postgresql
def test_m10_migration_preserves_populated_m9_history_and_classifies_only_existing_latency(minimal_domain):
    """M10 adds telemetry without changing imported, review, worker, or M6--M9 facts."""

    revision = create_target_revision(
        actor=minimal_domain["admin"], target=minimal_domain["target"], endpoint="http://127.0.0.1:18910",
        adapter_key="fake-http", adapter_version="1", credential_reference="",
        classification=TargetRevision.Classification.LAB_TEST, supports_question_api=True,
        supports_conversation_session=True, supports_runtime_metadata=False, supports_health_check=True,
        default_execution_mode=TargetRevision.ExecutionMode.SEQUENTIAL, max_concurrency=1,
        question_timeout_seconds=30, inter_question_delay_seconds=0,
        declared_product_version="m9-preserved", declared_build_id="m9-build", declared_git_sha="m9-sha",
    )
    scenario = create_conversation_scenario(
        actor=minimal_domain["admin"], stable_id="M10-MIG-CONV", name="M10 migration conversation",
        lifecycle="ACTIVE", domain=minimal_domain["domain"],
        turns=[{"stable_turn_id": "M10-MIG-CONV.1", "prompt_template": "Olá, sessão?"}],
    )
    turn = scenario.current_version.turns.get()
    executor = MigrationExecutor(connection)
    executor.migrate([M9])
    apps = executor.loader.project_state([M9]).apps
    Run = apps.get_model("evaluations", "EvaluationRun")
    TargetSnapshot = apps.get_model("evaluations", "TargetSnapshot")
    BuildSnapshot = apps.get_model("evaluations", "BuildSnapshot")
    Execution = apps.get_model("evaluations", "Execution")
    Binding = apps.get_model("evaluations", "ResolvedBinding")
    Comment = apps.get_model("evaluations", "Comment")
    Review = apps.get_model("evaluations", "HumanReview")
    ReviewTracking = apps.get_model("evaluations", "ReviewTracking")
    Validity = apps.get_model("evaluations", "ExecutionValidityDecision")
    Baseline = apps.get_model("evaluations", "Baseline")
    Membership = apps.get_model("evaluations", "BaselineMembership")
    Comparison = apps.get_model("evaluations", "Comparison")
    Item = apps.get_model("evaluations", "ComparisonItem")
    Semantic = apps.get_model("evaluations", "SemanticComparisonResult")
    Attempt = apps.get_model("evaluations", "ConversationAttempt")
    Automated = apps.get_model("evaluations", "AutomatedEvaluationResult")
    Judge = apps.get_model("evaluations", "LLMJudgeResult")
    Invocation = apps.get_model("evaluations", "EvaluationInvocation")
    now = timezone.now()
    question, version, admin, target = (
        minimal_domain["question"], minimal_domain["question"].current_version,
        minimal_domain["admin"], minimal_domain["target"],
    )
    imported_batch = LegacyImportBatch.objects.create(
        mapping_identifier="m10-migration", mapping_name="M10 migration fixture", mapping_version=1,
        importer_version="fixture", source_filename="m9.xlsx", source_sha256="e" * 64,
        source_size_bytes=12, source_metadata={"unicode": "São Paulo"}, workbook_inventory={}, mapping_snapshot={},
        reconciliation_counts={"rows": 1}, imported_at=now, imported_by=admin,
    )
    imported_row = ImportedSourceRow.objects.create(
        batch=imported_batch, sheet_name="Questions", source_row_number=1,
        source_role="TARGET_QUESTIONS", classification="QUESTION_AND_OBSERVATION",
        interpretation_source="SOURCE_DATA", source_fingerprint="f" * 64,
        mapping_context={"m2": "preserved"}, domain=minimal_domain["domain"], question=question, question_version=version,
    )
    legacy = LegacyObservation.objects.create(
        source_row=imported_row, question=question, question_version=version, source_question_text="Pergunta legado",
        observed_answer_text="Resposta legado", answer_fidelity="SOURCE_TEXT_UNKNOWN_EXACTNESS",
        legacy_expectation="Expectativa", expected_answer_role="LEGACY_EXPECTATION", acceptable_source_value="Aceitável",
        legacy_judgment="GOOD", judgment_source="IMPORTED_LEGACY", comments="Comentário", experiment_metadata={"m2": True},
        imported_at=now,
    )

    def observed(label, *, conversation=False):
        run = Run.objects.create(
            target_id=target.pk, target_revision_id=revision.pk, launched_by_id=admin.pk,
            state="COMPLETED", requested_mode="SEQUENTIAL", configured_max_concurrency=1,
            actual_concurrency=1, question_timeout_seconds=30, inter_question_delay_seconds=0,
            total_planned=1, selection_filter={"m9": label}, started_at=now, completed_at=now,
        )
        snapshot = TargetSnapshot.objects.create(
            run_id=run.pk, target_id=target.pk, target_revision_id=revision.pk, target_display_name="M9 target",
            product_display_name="M9 product", environment_display_name="M9 environment",
            endpoint="http://127.0.0.1:18910", adapter_key="fake-http", adapter_version="1",
            credential_reference="", classification="LAB_TEST", supports_runtime_metadata=False,
        )
        build = BuildSnapshot.objects.create(
            run_id=run.pk, declared_product_version="m9-preserved", declared_build_id=label,
            declared_git_sha="m9-sha", runtime_state="UNAVAILABLE", runtime_diagnostic="M9 fixture",
            runtime_observed_at=now,
        )
        attempt = Attempt.objects.create(
            run_id=run.pk, scenario_version_id=scenario.current_version.pk, target_session_id="m9-session-✓",
            session_metadata={"unicode": "São Paulo"}, session_state="CLOSED", started_at=now, completed_at=now,
        ) if conversation else None
        execution = Execution.objects.create(
            run_id=run.pk, question_id=question.pk, question_version_id=version.pk,
            conversation_attempt_id=attempt.pk if attempt else None, conversation_turn_id=turn.pk if attempt else None,
            target_revision_id=revision.pk, target_snapshot_id=snapshot.pk, build_snapshot_id=build.pk,
            question_order=1, question_stable_id=question.stable_id, question_version_number=version.version_number,
            question_template=version.question_text, submitted_question=f"M9 {label} — Português ✓",
            outcome="SUCCESS", adapter_key="fake-http", adapter_version="1", raw_request={"label": label},
            raw_response=f"raw {label}", raw_answer=f"answer {label}", display_answer=f"answer {label}",
            evidence={"label": label, "unicode": "✓"}, claim_worker_id="m4-worker", claim_attempt=2,
            target_call_phase="TERMINAL", review_state="REVIEWED", validity="VALID",
            started_at=now, completed_at=now, latency_ms=19,
        )
        Binding.objects.create(execution_id=execution.pk, name="fixture", resolution_mode="FIXED_ADMIN", value={"label": label}, display_value=label)
        return run, execution

    baseline_run, baseline_execution = observed("baseline")
    comment = Comment.objects.create(execution_id=baseline_execution.pk, author_id=admin.pk, text="M5 append-only comment")
    review = Review.objects.create(execution_id=baseline_execution.pk, judgment="GOOD", reviewed_by_id=admin.pk, comment_id=comment.pk)
    Execution.objects.filter(pk=baseline_execution.pk).update(current_human_review_id=review.pk)
    ReviewTracking.objects.create(execution_id=baseline_execution.pk, state="REVIEWED", actor_id=admin.pk, cause="M5")
    Validity.objects.create(execution_id=baseline_execution.pk, validity="INVALID", decided_by_id=admin.pk, comment_id=comment.pk)
    baseline = Baseline.objects.create(name="M9 baseline", source_run_id=baseline_run.pk, source_target_id=target.pk, created_by_id=admin.pk)
    Membership.objects.create(baseline_id=baseline.pk, execution_id=baseline_execution.pk)
    current_run, current_execution = observed("current")
    comparison = Comparison.objects.create(baseline_id=baseline.pk, current_run_id=current_run.pk, algorithm_key="exact", algorithm_version="exact-v1")
    item = Item.objects.create(
        comparison_id=comparison.pk, baseline_execution_id=baseline_execution.pk, current_execution_id=current_execution.pk,
        baseline_human_review_id=review.pk, current_human_review_id=None, change_state="CHANGED", exact_equal=False,
        baseline_normalized_hash="a" * 64, current_normalized_hash="b" * 64,
    )
    Semantic.objects.create(comparison_item_id=item.pk, outcome="UNCERTAIN", provider_key="m7-fixture", model_identifier="m7-model", comparator_version="m7-v1", input_fingerprint="c" * 64, input_manifest={"m7": True}, rationale="M7 evidence", raw_result={"outcome": "UNCERTAIN"})
    invocation = Invocation.objects.create(execution_id=baseline_execution.pk, kind="JUDGE", state="COMPLETED", requested_by_id=admin.pk, evaluator_key="m9-judge", evaluator_version="1", provider="m9-provider", model_identifier="m9-model", judge_version="1", rubric_id="m9-rubric", rubric_version="1", prompt_version="1", configuration={"m9": True}, input_fingerprint="d" * 64)
    Automated.objects.create(execution_id=baseline_execution.pk, evaluator_key="m9-evaluator", evaluator_version="1", mechanism="DETERMINISTIC", configuration_version="1", status="COMPLETE", outcome="CANNOT_CONCLUDE", details={"m9": "automated"}, input_manifest={"m9": True}, raw_result={"status": "complete"})
    Judge.objects.create(execution_id=baseline_execution.pk, provider="m9-provider", model_identifier="m9-model", judge_version="1", rubric_id="m9-rubric", rubric_version="1", prompt_version="1", status="COMPLETE", dimensions={"grounding": "uncertain"}, rationale="M9 judge", input_manifest={"m9": True}, raw_result={"status": "complete"}, invocation_id=invocation.pk)
    _, conversation_execution = observed("conversation", conversation=True)
    before = {
        "execution": Execution.objects.values_list("submitted_question", "raw_response", "raw_answer", "display_answer", "evidence", "latency_ms", "claim_worker_id", "claim_attempt", "target_call_phase", "review_state", "validity").get(pk=baseline_execution.pk),
        "comment": Comment.objects.values_list("text", "author_id").get(pk=comment.pk),
        "review": Review.objects.values_list("judgment", "comment_id").get(pk=review.pk),
        "comparison": Item.objects.values_list("change_state", "exact_equal").get(pk=item.pk),
        "semantic": Semantic.objects.values_list("outcome", "input_manifest", "rationale").get(),
        "conversation": Execution.objects.values_list("conversation_attempt_id", "conversation_turn_id", "submitted_question").get(pk=conversation_execution.pk),
        "automated": Automated.objects.values_list("details", "input_manifest").get(),
        "judge": Judge.objects.values_list("dimensions", "rationale", "invocation_id").get(),
        "invocation": Invocation.objects.values_list("kind", "state", "configuration", "input_fingerprint").get(pk=invocation.pk),
        "import": LegacyObservation.objects.values_list("source_question_text", "observed_answer_text", "experiment_metadata").get(pk=legacy.pk),
    }

    executor = MigrationExecutor(connection)
    executor.migrate([M10])
    from evaluations.models import (AutomatedEvaluationResult, Comment as M10Comment, EvaluationInvocation, Execution as M10Execution, HumanReview, LLMJudgeResult, SemanticComparisonResult)

    assert M10Execution.objects.values_list("submitted_question", "raw_response", "raw_answer", "display_answer", "evidence", "latency_ms", "claim_worker_id", "claim_attempt", "target_call_phase", "review_state", "validity").get(pk=baseline_execution.pk) == before["execution"]
    assert M10Comment.objects.values_list("text", "author_id").get(pk=comment.pk) == before["comment"]
    assert HumanReview.objects.values_list("judgment", "comment_id").get(pk=review.pk) == before["review"]
    assert Item.objects.values_list("change_state", "exact_equal").get(pk=item.pk) == before["comparison"]
    assert SemanticComparisonResult.objects.values_list("outcome", "input_manifest", "rationale").get() == before["semantic"]
    assert M10Execution.objects.values_list("conversation_attempt_id", "conversation_turn_id", "submitted_question").get(pk=conversation_execution.pk) == before["conversation"]
    assert AutomatedEvaluationResult.objects.values_list("details", "input_manifest").get() == before["automated"]
    assert LLMJudgeResult.objects.values_list("dimensions", "rationale", "invocation_id").get() == before["judge"]
    assert EvaluationInvocation.objects.values_list("kind", "state", "configuration", "input_fingerprint").get(pk=invocation.pk) == before["invocation"]
    assert LegacyObservation.objects.values_list("source_question_text", "observed_answer_text", "experiment_metadata").get(pk=legacy.pk) == before["import"]
    preserved = M10Execution.objects.get(pk=baseline_execution.pk)
    assert (preserved.latency_ms, preserved.performance_classification, preserved.input_tokens, preserved.total_tokens) == (19, "TARGET", None, None)
