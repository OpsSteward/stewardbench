"""Forward M3 -> M4 migration preservation evidence against PostgreSQL."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from catalog.models import TargetRevision
from catalog.services import create_target_revision
M3 = ("evaluations", "0001_m3_durable_execution")
M4 = ("evaluations", "0002_remove_evaluationrun_evaluations_m3_sequential_only_and_more")


@pytest.mark.django_db(transaction=True)
def test_m4_migration_preserves_populated_m3_terminal_observations(minimal_domain):
    """No M4 claim metadata invents historical owners or rewrites evidence."""

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
        declared_product_version="m3-version",
        declared_build_id="m3-build",
        declared_git_sha="m3-sha",
    )

    executor = MigrationExecutor(connection)
    executor.migrate([M3])
    old_apps = executor.loader.project_state([M3]).apps
    OldRun = old_apps.get_model("evaluations", "EvaluationRun")
    OldTargetSnapshot = old_apps.get_model("evaluations", "TargetSnapshot")
    OldBuildSnapshot = old_apps.get_model("evaluations", "BuildSnapshot")
    OldExecution = old_apps.get_model("evaluations", "Execution")
    now = timezone.now()
    old_run = OldRun.objects.create(
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
        selection_filter={"m3": "preservation"},
        started_at=now,
        completed_at=now,
    )
    old_target_snapshot = OldTargetSnapshot.objects.create(
        run_id=old_run.pk,
        target_id=minimal_domain["target"].pk,
        target_revision_id=revision.pk,
        target_display_name="M3 target snapshot",
        product_display_name="M3 product snapshot",
        environment_display_name="M3 environment snapshot",
        endpoint="http://127.0.0.1:18081",
        adapter_key="fake-http",
        adapter_version="1",
        credential_reference="",
        classification="LAB_TEST",
        supports_runtime_metadata=False,
    )
    old_build_snapshot = OldBuildSnapshot.objects.create(
        run_id=old_run.pk,
        declared_product_version="m3-version",
        declared_build_id="m3-build",
        declared_git_sha="m3-sha",
        runtime_state="UNAVAILABLE",
        runtime_diagnostic="M3 test metadata unavailable",
        runtime_observed_at=now,
    )
    question = minimal_domain["question"]
    version = question.current_version
    outcomes = [
        ("SUCCESS", "M3 raw response success", "M3 answer success", "", ""),
        ("ERROR", "M3 raw response error", "", "HTTP_ERROR", "M3 preserved HTTP error"),
        ("TIMEOUT", "M3 raw response timeout", "", "TARGET_TIMEOUT", "M3 preserved timeout"),
    ]
    for order, (outcome, raw_response, raw_answer, error_class, error_detail) in enumerate(outcomes, start=1):
        OldExecution.objects.create(
            run_id=old_run.pk,
            question_id=question.pk,
            question_version_id=version.pk,
            target_revision_id=revision.pk,
            target_snapshot_id=old_target_snapshot.pk,
            build_snapshot_id=old_build_snapshot.pk,
            question_order=order,
            question_stable_id=question.stable_id,
            question_version_number=version.version_number,
            question_template=version.question_text,
            submitted_question=f"M3 concrete question {order}",
            outcome=outcome,
            adapter_key="fake-http",
            adapter_version="1",
            raw_request={"m3": order},
            raw_response=raw_response,
            raw_answer=raw_answer,
            display_answer=raw_answer,
            evidence={"m3": order},
            error_class=error_class,
            error_detail=error_detail,
            started_at=now,
            completed_at=now,
            latency_ms=0,
        )

    before = list(
        OldExecution.objects.order_by("question_order").values_list(
            "outcome",
            "submitted_question",
            "raw_response",
            "raw_answer",
            "error_class",
            "error_detail",
            "target_revision_id",
            "build_snapshot_id",
        )
    )
    # Rebuild the executor after the backwards migration so its recorder and
    # graph state reflect the supported M3 upgrade starting point.
    executor = MigrationExecutor(connection)
    executor.migrate([M4])
    m4_apps = executor.loader.project_state([M4]).apps
    M4Execution = m4_apps.get_model("evaluations", "Execution")
    M4Run = m4_apps.get_model("evaluations", "EvaluationRun")

    preserved = list(
        M4Execution.objects.filter(run_id=old_run.pk)
        .order_by("question_order")
        .values_list(
            "outcome",
            "submitted_question",
            "raw_response",
            "raw_answer",
            "error_class",
            "error_detail",
            "target_revision_id",
            "build_snapshot_id",
        )
    )
    assert preserved == before
    upgraded = list(M4Execution.objects.filter(run_id=old_run.pk).order_by("question_order"))
    assert all(item.target_call_phase == "NONE" for item in upgraded)
    assert all(item.claim_worker_id == "" and item.claim_token is None for item in upgraded)
    upgraded_run = M4Run.objects.get(pk=old_run.pk)
    assert upgraded_run.state == "COMPLETED_WITH_ERRORS"
    assert upgraded_run.next_dispatch_at is None
