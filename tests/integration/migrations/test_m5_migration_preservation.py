"""Forward M4 -> M5 historical-preservation evidence against PostgreSQL."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from catalog.models import TargetRevision
from catalog.services import create_target_revision
from evaluations.models import EvaluationRun, Execution


M4 = ("evaluations", "0002_remove_evaluationrun_evaluations_m3_sequential_only_and_more")
M5 = ("evaluations", "0003_llmjudgeresult_reviewtracking_and_more")


@pytest.mark.django_db(transaction=True)
@pytest.mark.postgresql
def test_m5_migration_preserves_populated_m4_observations_and_only_initializes_m5_state(minimal_domain):
    """M5 defaults do not fabricate review/validity history or rewrite M4 evidence."""

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
        declared_product_version="m4-version",
        declared_build_id="m4-build",
        declared_git_sha="m4-sha",
    )
    executor = MigrationExecutor(connection)
    executor.migrate([M4])
    old_apps = executor.loader.project_state([M4]).apps
    OldRun = old_apps.get_model("evaluations", "EvaluationRun")
    OldTargetSnapshot = old_apps.get_model("evaluations", "TargetSnapshot")
    OldBuildSnapshot = old_apps.get_model("evaluations", "BuildSnapshot")
    OldExecution = old_apps.get_model("evaluations", "Execution")
    now = timezone.now()
    question = minimal_domain["question"]
    version = question.current_version

    def old_run_with_snapshot(index, state, planned):
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
            total_planned=planned,
            selection_filter={"m4": index},
            started_at=now,
            completed_at=now,
        )
        target = OldTargetSnapshot.objects.create(
            run_id=run.pk,
            target_id=minimal_domain["target"].pk,
            target_revision_id=revision.pk,
            target_display_name=f"M4 target {index}",
            product_display_name="M4 product",
            environment_display_name="M4 environment",
            endpoint="http://127.0.0.1:18081",
            adapter_key="fake-http",
            adapter_version="1",
            credential_reference="",
            classification="LAB_TEST",
            supports_runtime_metadata=False,
        )
        build = OldBuildSnapshot.objects.create(
            run_id=run.pk,
            declared_product_version="m4-version",
            declared_build_id=f"m4-build-{index}",
            declared_git_sha="m4-sha",
            runtime_state="UNAVAILABLE",
            runtime_diagnostic="M4 metadata unavailable",
            runtime_observed_at=now,
        )
        return run, target, build

    first_run, first_target, first_build = old_run_with_snapshot(1, "COMPLETED_WITH_ERRORS", 4)
    second_run, second_target, second_build = old_run_with_snapshot(2, "COMPLETED", 1)
    observations = [
        (first_run, first_target, first_build, "SUCCESS", "success raw response", "success normalized answer", "", ""),
        (first_run, first_target, first_build, "ERROR", "error raw response", "", "HTTP_ERROR", "target HTTP failure"),
        (first_run, first_target, first_build, "TIMEOUT", "timeout raw response", "", "TARGET_TIMEOUT", "target deadline elapsed"),
        (first_run, first_target, first_build, "ERROR", "ambiguous raw response", "", "AMBIGUOUS_INFRASTRUCTURE", "remote completion unknown"),
        (second_run, second_target, second_build, "SUCCESS", "second run raw response", "second run answer", "", ""),
    ]
    for order, (run, target, build, outcome, raw_response, raw_answer, error_class, error_detail) in enumerate(
        observations,
        start=1,
    ):
        OldExecution.objects.create(
            run_id=run.pk,
            question_id=question.pk,
            question_version_id=version.pk,
            target_revision_id=revision.pk,
            target_snapshot_id=target.pk,
            build_snapshot_id=build.pk,
            question_order=order if run.pk == first_run.pk else 1,
            question_stable_id=question.stable_id,
            question_version_number=version.version_number,
            question_template=version.question_text,
            submitted_question=f"M4 submitted question {order} — São Paulo ✓",
            outcome=outcome,
            adapter_key="fake-http",
            adapter_version="1",
            raw_request={"m4": order},
            raw_response=raw_response,
            raw_answer=raw_answer,
            display_answer=raw_answer,
            evidence={"m4": order, "unicode": "✓"},
            response_metadata={"m4": "metadata"},
            error_class=error_class,
            error_detail=error_detail,
            claim_worker_id="m4-worker",
            claim_attempt=1,
            target_call_phase="TERMINAL",
            started_at=now,
            completed_at=now,
            latency_ms=42,
        )

    fields = (
        "run_id",
        "outcome",
        "question_version_id",
        "submitted_question",
        "raw_request",
        "raw_response",
        "raw_answer",
        "display_answer",
        "evidence",
        "response_metadata",
        "error_class",
        "error_detail",
        "target_snapshot_id",
        "build_snapshot_id",
        "target_revision_id",
        "claim_worker_id",
        "claim_attempt",
        "target_call_phase",
        "started_at",
        "completed_at",
        "latency_ms",
    )
    before = list(OldExecution.objects.order_by("run_id", "question_order").values_list(*fields))

    executor = MigrationExecutor(connection)
    executor.migrate([M5])
    after = list(Execution.objects.order_by("run_id", "question_order").values_list(*fields))
    assert after == before
    upgraded = list(Execution.objects.order_by("run_id", "question_order"))
    assert all(item.review_state == Execution.ReviewState.NONE for item in upgraded)
    assert all(item.validity == Execution.Validity.VALID for item in upgraded)
    assert all(item.current_human_review_id is None for item in upgraded)
    assert all(item.invalidated_by_id is None and item.invalidated_at is None for item in upgraded)
    assert all(item.review_history.count() == item.validity_history.count() == item.comments.count() == 0 for item in upgraded)
    assert EvaluationRun.objects.get(pk=first_run.pk).state == EvaluationRun.State.COMPLETED_WITH_ERRORS
    assert EvaluationRun.objects.get(pk=second_run.pk).state == EvaluationRun.State.COMPLETED
