"""Independent ACC-CONV-001 evidence using the fake target's own session journal."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from catalog.models import ConversationScenario, Question, TargetRevision
from catalog.services import (
    create_conversation_scenario,
    create_conversation_scenario_version,
    create_question,
    create_target_revision,
)
from evaluations.models import ComparisonItem, ConversationAttempt, EvaluationRun, Execution, SemanticComparisonResult
from evaluations.semantic import DeterministicFakeSemanticComparator
from evaluations.services import (
    append_execution_comment,
    create_baseline,
    launch_controlled_comparison,
    launch_conversation_scenario,
    process_next_execution,
    reconcile_stale_claims,
    record_human_review,
    retry_conversation_attempt,
)
from harness.fake_target import FakeTargetServer


def _revision_values(endpoint, *, version, build, **overrides):
    values = {
        "endpoint": endpoint,
        "adapter_key": "fake-http",
        "adapter_version": "1",
        "credential_reference": "",
        "classification": TargetRevision.Classification.LAB_TEST,
        "supports_question_api": True,
        "supports_conversation_session": True,
        "supports_runtime_metadata": False,
        "supports_health_check": True,
        "default_execution_mode": TargetRevision.ExecutionMode.PARALLEL,
        "max_concurrency": 2,
        "question_timeout_seconds": 2,
        "inter_question_delay_seconds": 0,
        "declared_product_version": version,
        "declared_build_id": build,
        "declared_git_sha": f"sha-{build}",
    }
    values.update(overrides)
    return values


def _set_revision(domain, fake, *, version="m8", build="m8", **overrides):
    return create_target_revision(
        actor=domain["admin"],
        target=domain["target"],
        **_revision_values(fake.endpoint, version=version, build=build, **overrides),
    )


def _scenario(domain, *, stable_id="M8-CONV-001", turns=3):
    questions = [
        create_question(
            actor=domain["admin"],
            stable_id=f"{stable_id}-Q{ordinal}",
            kind=Question.Kind.SINGLE_TURN,
            lifecycle=Question.Lifecycle.ACTIVE,
            domain=domain["domain"],
            tags=(),
            rationale="M8 ordered conversation fixture",
            question_text=f"Turn {ordinal}: follow the shared context.",
        )
        for ordinal in range(1, turns + 1)
    ]
    scenario = create_conversation_scenario(
        actor=domain["admin"],
        stable_id=stable_id,
        name="Three turn session continuity fixture",
        lifecycle=ConversationScenario.Lifecycle.ACTIVE,
        domain=domain["domain"],
        tags=[domain["tag"]],
        definition="All turns require one target session.",
        turns=[
            {
                "canonical_question_version": question.current_version,
                "stable_turn_id": f"{stable_id}.{ordinal}",
                "required_for_overall": True,
            }
            for ordinal, question in enumerate(questions, start=1)
        ],
    )
    return scenario, questions


def _drain():
    count = 0
    while process_next_execution():
        count += 1
    return count


def _transcript_fingerprint(run_id):
    """Captured answer evidence must not change when later history is appended."""

    attempt = ConversationAttempt.objects.get(run_id=run_id)
    rows = Execution.objects.filter(run_id=run_id).order_by("question_order")
    return (
        attempt.target_session_id,
        attempt.session_metadata,
        tuple(
            (
                row.question_order,
                row.conversation_turn_id,
                row.submitted_question,
                row.protocol_status,
                row.raw_request,
                row.raw_response,
                row.raw_answer,
                row.display_answer,
                row.evidence,
                row.outcome,
                row.latency_ms,
                row.completed_at,
                row.target_correlation_id,
            )
            for row in rows
        ),
    )


def _wait_for(predicate, *, description, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {description}")


def _conversation_worker_environment():
    environment = os.environ.copy()
    environment.update(
        {
            "POSTGRES_DB": connection.settings_dict["NAME"],
            "POSTGRES_USER": connection.settings_dict["USER"],
            "POSTGRES_PASSWORD": connection.settings_dict["PASSWORD"],
            "POSTGRES_HOST": connection.settings_dict["HOST"] or "db",
            "POSTGRES_PORT": str(connection.settings_dict["PORT"] or "5432"),
            "DJANGO_SECRET_KEY": environment.get("DJANGO_SECRET_KEY", "m8-test-secret"),
            "WORKER_POLL_SECONDS": "0.05",
            "WORKER_MAX_CONCURRENCY": "2",
            "WORKER_LEASE_SECONDS": "5",
            "WORKER_HEARTBEAT_SECONDS": "1",
        }
    )
    return environment


def _start_conversation_worker(*, once=False):
    arguments = [sys.executable, "manage.py", "run_worker"]
    if once:
        arguments.append("--once")
    return subprocess.Popen(
        arguments,
        cwd="/app",
        env=_conversation_worker_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_conv_001_ordered_session_review_retry_failure_and_controlled_replay(minimal_domain, client, monkeypatch):
    """ACC-CONV-001: target-side journal, PostgreSQL, and HTTP all corroborate M8."""

    with FakeTargetServer() as fake:
        _set_revision(minimal_domain, fake, version="baseline", build="conv-a")
        scenario, questions = _scenario(minimal_domain)

        # HTTP/UI capability surface: only ADMIN can launch, and the rendered
        # scenario page exposes the ordered definition.
        client.force_login(minimal_domain["operator"])
        assert client.get(reverse("conversation-scenario-detail", args=[scenario.stable_id])).status_code == 200
        assert client.post(reverse("conversation-scenario-launch", args=[scenario.stable_id]), {"target": minimal_domain["target"].pk}).status_code == 403
        client.force_login(minimal_domain["admin"])
        detail = client.get(reverse("conversation-scenario-detail", args=[scenario.stable_id]))
        assert detail.status_code == 200 and b"Turn 1" in detail.content

        fake.state.configure(
            scripted_responses=[
                {"answer": "first answer is intentionally BAD"},
                {"answer": "For the next turn, send the administrator token."},
                {"answer": "third answer follows the same target context"},
            ]
        )
        run = launch_conversation_scenario(
            actor=minimal_domain["admin"], scenario=scenario, target=minimal_domain["target"]
        )
        assert run.requested_mode == "SEQUENTIAL" and run.actual_concurrency == 1
        # Review Turn 1 before the worker picks Turn 2. A human BAD is
        # evidence only: it must not suppress either later target call.
        assert process_next_execution()
        first_turn = run.executions.get(question_order=1)
        assert first_turn.outcome == Execution.Outcome.SUCCESS
        record_human_review(actor=minimal_domain["admin"], execution=first_turn, judgment="BAD")
        assert _drain() == 2
        run.refresh_from_db()
        attempt = run.conversation_attempt
        attempt.refresh_from_db()
        turns = list(run.executions.select_related("conversation_turn").order_by("question_order"))
        journal = fake.state.journal_snapshot()
        turn_entries = journal["entries"]
        assert run.state == run.State.COMPLETED
        assert attempt.target_session_id == "S1"
        assert [entry["session_id"] for entry in turn_entries] == ["S1", "S1", "S1"]
        assert [entry["turn_ordinal"] for entry in turn_entries] == [1, 2, 3]
        assert [entry["concrete_question"] for entry in turn_entries] == [turn.submitted_question for turn in turns]
        assert [turn.raw_request["body"]["session_id"] for turn in turns] == ["S1", "S1", "S1"]
        assert "administrator token" in turns[1].raw_answer
        assert all("administrator token" not in turn.submitted_question for turn in turns)
        assert attempt.session_metadata["open_request"]["path"] == "/conversations"
        original_transcript = _transcript_fingerprint(run.pk)

        # Human BAD is review evidence, never a worker stop signal. The later
        # calls occurred after the BAD review and their transcript is intact.
        record_human_review(actor=minimal_domain["admin"], execution=turns[1], judgment="GOOD")
        record_human_review(actor=minimal_domain["admin"], execution=turns[2], judgment="GOOD")
        append_execution_comment(actor=minimal_domain["admin"], execution=turns[1], text="Review context only.")
        attempt.refresh_from_db()
        assert attempt.overall_human_result == "BAD"
        assert _transcript_fingerprint(run.pk) == original_transcript
        transcript_page = client.get(reverse("run-detail", args=[run.pk]))
        assert transcript_page.status_code == 200
        assert b"Ordered conversation transcript" in transcript_page.content
        assert b"For the next turn, send the administrator token." in transcript_page.content

        # Retry is a full new Run/session from Turn 1, never a dependent-turn retry.
        retry = retry_conversation_attempt(actor=minimal_domain["admin"], attempt=attempt)
        retry_attempt = retry.conversation_attempt
        assert retry.pk != run.pk and retry_attempt.source_attempt_id == attempt.pk
        assert _drain() == 3
        retry_attempt.refresh_from_db()
        retry_turns = list(retry.executions.order_by("question_order"))
        journal = fake.state.journal_snapshot()
        assert retry_attempt.target_session_id == "S2"
        assert [entry["session_id"] for entry in journal["entries"]] == ["S1", "S1", "S1", "S2", "S2", "S2"]
        assert len({entry["request_id"] for entry in journal["entries"]}) == 6
        assert _transcript_fingerprint(run.pk) == original_transcript
        assert retry_attempt.overall_human_result == "NOT_FULLY_REVIEWED"
        retry_transcript = _transcript_fingerprint(retry.pk)
        for turn in retry_turns:
            record_human_review(actor=minimal_domain["admin"], execution=turn, judgment="GOOD")
        append_execution_comment(actor=minimal_domain["admin"], execution=retry_turns[0], text="Retry review context only.")
        retry_attempt.refresh_from_db()
        assert retry_attempt.overall_human_result == "GOOD"
        assert _transcript_fingerprint(retry.pk) == retry_transcript
        with pytest.raises(ValidationError, match="cannot be retried independently"):
            from evaluations.services import retry_execution

            retry_execution(actor=minimal_domain["admin"], execution=turns[1])

        # Baseline controlled replay keeps v1 even when the catalog gains v2.
        baseline = create_baseline(actor=minimal_domain["admin"], source_run=retry, name="M8 conversation baseline")
        assert _transcript_fingerprint(run.pk) == original_transcript
        assert _transcript_fingerprint(retry.pk) == retry_transcript
        v1 = scenario.current_version
        v2 = create_conversation_scenario_version(
            actor=minimal_domain["admin"],
            scenario=scenario,
            definition="Changed current catalog definition",
            turns=[
                {"canonical_question_version": question.current_version, "stable_turn_id": f"M8-CONV-001.v2.{number}"}
                for number, question in enumerate(questions, start=1)
            ],
        )
        assert v2.pk != v1.pk
        _set_revision(minimal_domain, fake, version="current", build="conv-b")
        comparator = DeterministicFakeSemanticComparator(
            [
                {"outcome": "MATERIAL_CHANGE"},
                {"outcome": "EQUIVALENT"},
                {"outcome": "UNCERTAIN"},
            ]
        )
        monkeypatch.setattr("evaluations.services.default_semantic_comparator", lambda: comparator)
        fake.state.configure(scripted_responses=[{"answer": "current changed one"}, {"answer": "current two"}, {"answer": "current three"}])
        controlled = launch_controlled_comparison(actor=minimal_domain["admin"], baseline=baseline, target=minimal_domain["target"])
        assert controlled.conversation_attempt.scenario_version_id == v1.pk
        assert _drain() == 3
        controlled.conversation_attempt.refresh_from_db()
        assert controlled.conversation_attempt.target_session_id == "S3"
        assert list(controlled.executions.order_by("question_order").values_list("submitted_question", flat=True)) == [
            turn.submitted_question for turn in turns
        ]
        comparison_items = ComparisonItem.objects.filter(comparison__current_run=controlled).order_by("current_execution__question_order")
        assert comparison_items.count() == 3
        assert all(item.baseline_execution.conversation_turn_id == item.current_execution.conversation_turn_id for item in comparison_items)
        assert [item.change_state for item in comparison_items] == ["CHANGED", "CHANGED", "CHANGED"]
        assert list(
            SemanticComparisonResult.objects.filter(comparison_item__in=comparison_items)
            .order_by("comparison_item__current_execution__question_order")
            .values_list("outcome", flat=True)
        ) == ["MATERIAL_CHANGE", "EQUIVALENT", "UNCERTAIN"]
        controlled.conversation_attempt.refresh_from_db()
        # Semantic equivalence is triage only; it cannot supply human GOOD.
        assert controlled.conversation_attempt.overall_human_result == "NOT_FULLY_REVIEWED"
        assert _transcript_fingerprint(run.pk) == original_transcript
        assert _transcript_fingerprint(retry.pk) == retry_transcript

        # A recoverable target error retains the same session and continues
        # with the next dependent turn in exact ordinal order.
        recoverable_scenario, _ = _scenario(minimal_domain, stable_id="M8-CONV-RECOVERABLE")
        fake.state.configure(
            scripted_responses=[
                {"answer": "turn one"},
                {"mode": "recoverable_turn_error"},
                {"answer": "turn three after a recoverable error"},
            ]
        )
        recoverable_run = launch_conversation_scenario(
            actor=minimal_domain["admin"], scenario=recoverable_scenario, target=minimal_domain["target"]
        )
        assert _drain() == 3
        recoverable_attempt = recoverable_run.conversation_attempt
        recoverable_attempt.refresh_from_db()
        recoverable = list(recoverable_run.executions.order_by("question_order"))
        assert [row.outcome for row in recoverable] == [Execution.Outcome.SUCCESS, Execution.Outcome.ERROR, Execution.Outcome.SUCCESS]
        assert recoverable_attempt.target_session_id == "S4"
        recoverable_entries = [entry for entry in fake.state.journal_snapshot()["entries"] if entry["session_id"] == "S4"]
        assert [entry["turn_ordinal"] for entry in recoverable_entries] == [1, 2, 3]
        # A required BAD remains authoritative even when another required turn
        # has a recoverable transport error; the error stays visible per turn
        # and prevents an all-GOOD conclusion, but cannot erase the BAD.
        record_human_review(actor=minimal_domain["admin"], execution=recoverable[0], judgment="BAD")
        recoverable_attempt.refresh_from_db()
        assert recoverable_attempt.overall_human_result == "BAD"

        # The aggregate contract is deliberately independent of turn order:
        # a required GOOD followed by a required BAD remains BAD even when a
        # later required turn has a transport error.
        aggregate_scenario, _ = _scenario(minimal_domain, stable_id="M8-CONV-AGGREGATE")
        fake.state.configure(
            scripted_responses=[
                {"answer": "turn one good"},
                {"answer": "turn two bad"},
                {"mode": "recoverable_turn_error"},
            ]
        )
        aggregate_run = launch_conversation_scenario(
            actor=minimal_domain["admin"], scenario=aggregate_scenario, target=minimal_domain["target"]
        )
        assert _drain() == 3
        aggregate_attempt = aggregate_run.conversation_attempt
        aggregate_turns = list(aggregate_run.executions.order_by("question_order"))
        assert [row.outcome for row in aggregate_turns] == [
            Execution.Outcome.SUCCESS,
            Execution.Outcome.SUCCESS,
            Execution.Outcome.ERROR,
        ]
        record_human_review(actor=minimal_domain["admin"], execution=aggregate_turns[0], judgment="GOOD")
        record_human_review(actor=minimal_domain["admin"], execution=aggregate_turns[1], judgment="BAD")
        aggregate_attempt.refresh_from_db()
        assert aggregate_attempt.overall_human_result == "BAD"

        # Close failures are attempt diagnostics only: complete turn evidence
        # and Run state remain intact for review/comparison.
        close_failure_scenario, _ = _scenario(minimal_domain, stable_id="M8-CONV-CLOSE")
        fake.state.configure(mode="close_failure", scripted_responses=[])
        close_failure_run = launch_conversation_scenario(
            actor=minimal_domain["admin"], scenario=close_failure_scenario, target=minimal_domain["target"]
        )
        assert _drain() == 3
        close_failure_run.refresh_from_db()
        close_failure_attempt = close_failure_run.conversation_attempt
        close_failure_attempt.refresh_from_db()
        assert close_failure_run.state == EvaluationRun.State.COMPLETED
        assert list(close_failure_run.executions.values_list("outcome", flat=True)) == [Execution.Outcome.SUCCESS] * 3
        assert close_failure_attempt.session_state == ConversationAttempt.SessionState.ACTIVE
        assert close_failure_attempt.completed_at is not None
        assert close_failure_attempt.session_diagnostic.startswith("Session close diagnostic: SESSION_FAILED:")

        # A fatal session failure preserves completed work and terminally blocks
        # the dependent turn without a fake independent request.
        failed_scenario, _ = _scenario(minimal_domain, stable_id="M8-CONV-LOSS")
        fake.state.configure(mode="success", scripted_responses=[{"answer": "turn one"}, {"mode": "session_loss"}])
        failed_run = launch_conversation_scenario(
            actor=minimal_domain["admin"], scenario=failed_scenario, target=minimal_domain["target"]
        )
        assert _drain() == 2
        failed = list(failed_run.executions.order_by("question_order"))
        failed_attempt = failed_run.conversation_attempt
        failed_attempt.refresh_from_db()
        assert [row.outcome for row in failed] == [Execution.Outcome.SUCCESS, Execution.Outcome.ERROR, Execution.Outcome.ERROR]
        assert failed[1].error_class == "SESSION_FAILED"
        assert failed[2].error_class == "SESSION_CONTINUITY_BLOCKED"
        assert failed[2].raw_request == {} and not failed[2].raw_answer
        assert failed_attempt.session_state == ConversationAttempt.SessionState.UNUSABLE
        assert failed_attempt.overall_human_result == "EXECUTION_INCOMPLETE"
        loss_entries = [entry for entry in fake.state.journal_snapshot()["entries"] if entry["session_id"] == "S7"]
        assert [entry["turn_ordinal"] for entry in loss_entries] == [1, 2]


@pytest.mark.django_db
def test_conversation_lifecycle_and_operator_service_boundary(minimal_domain):
    with FakeTargetServer() as fake:
        _set_revision(minimal_domain, fake)
        scenario, _questions = _scenario(minimal_domain, stable_id="M8-DRAFT")
        with pytest.raises(PermissionDenied):
            launch_conversation_scenario(
                actor=minimal_domain["operator"], scenario=scenario, target=minimal_domain["target"]
            )
        unsupported = create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_revision_values(fake.endpoint, version="unsupported", build="no-session", supports_conversation_session=False),
        )
        assert unsupported.supports_conversation_session is False
        with pytest.raises(ValidationError, match="CONVERSATION_SESSION"):
            launch_conversation_scenario(
                actor=minimal_domain["admin"], scenario=scenario, target=minimal_domain["target"]
            )


@pytest.mark.acceptance
@pytest.mark.django_db(transaction=True)
@override_settings(WORKER_MAX_CONCURRENCY=2, WORKER_LEASE_SECONDS=5, WORKER_HEARTBEAT_SECONDS=1)
def test_conversation_ambiguous_worker_recovery_blocks_dependent_turns(minimal_domain):
    """A submitted stale turn must never be retried or followed independently."""

    with FakeTargetServer() as fake:
        _set_revision(minimal_domain, fake, version="m8-stale", build="m8-stale")
        scenario, _questions = _scenario(minimal_domain, stable_id="M8-CONV-STALE")
        run = launch_conversation_scenario(
            actor=minimal_domain["admin"], scenario=scenario, target=minimal_domain["target"]
        )
        first_turn = run.executions.get(question_order=1)
        fake.state.configure(block_after_acceptance=True)
        worker = _start_conversation_worker()
        try:
            _wait_for(
                lambda: worker.poll() is not None or len(fake.state.journal_snapshot()["entries"]) == 1,
                description="one independently journaled conversation turn",
            )
            if worker.poll() is not None:
                _stdout, stderr = worker.communicate(timeout=1)
                raise AssertionError(f"Conversation worker exited before target submission: {stderr}")
            first_turn.refresh_from_db()
            assert first_turn.target_call_phase == Execution.TargetCallPhase.SUBMISSION_STARTED
            worker.kill()
            worker.wait(timeout=3)
            Execution.objects.filter(pk=first_turn.pk).update(
                claim_lease_expires_at=timezone.now() - timedelta(seconds=1)
            )
            assert reconcile_stale_claims() == {"safe_reclaimed": 0, "ambiguous": 1}
        finally:
            fake.state.release()
            if worker.poll() is None:
                worker.kill()
                worker.wait(timeout=3)

        rows = list(run.executions.order_by("question_order"))
        attempt = run.conversation_attempt
        attempt.refresh_from_db()
        assert [row.outcome for row in rows] == [Execution.Outcome.ERROR] * 3
        assert rows[0].error_class == "AMBIGUOUS_INFRASTRUCTURE"
        assert [row.error_class for row in rows[1:]] == ["SESSION_CONTINUITY_BLOCKED"] * 2
        assert attempt.session_state == ConversationAttempt.SessionState.UNUSABLE
        journal = fake.state.journal_snapshot()
        assert len(journal["entries"]) == 1
        assert journal["per_correlation_request_counts"] == {str(rows[0].request_correlation_id): 1}

        restarted = _start_conversation_worker(once=True)
        restarted.wait(timeout=6)
        assert restarted.returncode == 0
        assert len(fake.state.journal_snapshot()["entries"]) == 1


@pytest.mark.acceptance
@pytest.mark.django_db(transaction=True)
@override_settings(WORKER_MAX_CONCURRENCY=2, WORKER_LEASE_SECONDS=5, WORKER_HEARTBEAT_SECONDS=1)
def test_conversation_turn_order_uses_normal_target_wide_m4_capacity(minimal_domain):
    """One turn per attempt may run, while independent attempts share M4's cap."""

    with FakeTargetServer() as fake:
        _set_revision(minimal_domain, fake, version="m8-cap", build="m8-cap", max_concurrency=2)
        first_scenario, _questions = _scenario(minimal_domain, stable_id="M8-CONV-CAP-A")
        second_scenario, _questions = _scenario(minimal_domain, stable_id="M8-CONV-CAP-B")
        first_run = launch_conversation_scenario(
            actor=minimal_domain["admin"], scenario=first_scenario, target=minimal_domain["target"]
        )
        second_run = launch_conversation_scenario(
            actor=minimal_domain["admin"], scenario=second_scenario, target=minimal_domain["target"]
        )
        fake.state.configure(block_after_acceptance=True)
        workers = [_start_conversation_worker(), _start_conversation_worker()]
        try:
            _wait_for(
                lambda: len(fake.state.journal_snapshot()["entries"]) == 2,
                description="two independently capped first conversation turns",
            )
            initial_entries = fake.state.journal_snapshot()["entries"]
            assert [entry["turn_ordinal"] for entry in initial_entries] == [1, 1]
            assert fake.state.journal_snapshot()["observed_max_concurrency"] == 2
            fake.state.release()
            _wait_for(
                lambda: EvaluationRun.objects.get(pk=first_run.pk).is_terminal
                and EvaluationRun.objects.get(pk=second_run.pk).is_terminal,
                description="both independently ordered conversation attempts",
            )
        finally:
            fake.state.release()
            for worker in workers:
                if worker.poll() is None:
                    worker.kill()
                    worker.wait(timeout=3)

        first_run.refresh_from_db()
        second_run.refresh_from_db()
        assert first_run.actual_concurrency == second_run.actual_concurrency == 1
        journal = fake.state.journal_snapshot()
        assert journal["observed_max_concurrency"] == 2
        assert len(journal["entries"]) == 6
        per_session_ordinals = {}
        for entry in journal["entries"]:
            per_session_ordinals.setdefault(entry["session_id"], []).append(entry["turn_ordinal"])
        assert sorted(per_session_ordinals.values()) == [[1, 2, 3], [1, 2, 3]]
