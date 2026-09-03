"""M4 independent worker acceptance with real PostgreSQL and OS workers."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.test import override_settings
from django.utils import timezone

from catalog.models import Question, TargetRevision
from catalog.services import create_question, create_target_revision
from evaluations.models import EvaluationRun, Execution
from evaluations.services import reconcile_stale_claims
from harness.fake_target import FakeTargetServer


def _fake_revision(server, **overrides):
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
        "default_execution_mode": TargetRevision.ExecutionMode.PARALLEL,
        "max_concurrency": 4,
        "question_timeout_seconds": 2,
        "inter_question_delay_seconds": 0,
        "declared_product_version": "m4-acceptance",
        "declared_build_id": "m4-acceptance-build",
        "declared_git_sha": "m4-acceptance-sha",
    }
    values.update(overrides)
    return values


def _extra_questions(minimal_domain, count):
    questions = [minimal_domain["question"]]
    for number in range(2, count + 1):
        questions.append(
            create_question(
                actor=minimal_domain["admin"],
                stable_id=f"M4-WORKER-{number:03d}",
                kind=Question.Kind.SINGLE_TURN,
                lifecycle=Question.Lifecycle.ACTIVE,
                domain=minimal_domain["domain"],
                tags=(),
                rationale="M4 worker acceptance fixture",
                question_text=f"M4 worker question {number}",
            )
        )
    return questions


def _wait_for(predicate, *, description, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {description}")


def _worker_environment(extra=None):
    environment = os.environ.copy()
    # A subprocess is not managed by pytest-django, so point it at the real
    # disposable PostgreSQL test database that pytest already migrated.
    environment.update(
        {
            "POSTGRES_DB": connection.settings_dict["NAME"],
            "POSTGRES_USER": connection.settings_dict["USER"],
            "POSTGRES_PASSWORD": connection.settings_dict["PASSWORD"],
            "POSTGRES_HOST": connection.settings_dict["HOST"] or "db",
            "POSTGRES_PORT": str(connection.settings_dict["PORT"] or "5432"),
            "DJANGO_SECRET_KEY": environment.get("DJANGO_SECRET_KEY", "m4-test-secret"),
            "WORKER_POLL_SECONDS": "0.05",
            "WORKER_MAX_CONCURRENCY": "4",
            "WORKER_LEASE_SECONDS": "5",
            "WORKER_HEARTBEAT_SECONDS": "1",
        }
    )
    if extra:
        environment.update(extra)
    return environment


def _start_worker(*, once=False, extra_environment=None):
    arguments = [sys.executable, "manage.py", "run_worker"]
    if once:
        arguments.append("--once")
    return subprocess.Popen(
        arguments,
        cwd="/app",
        env=_worker_environment(extra_environment),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop_worker(process):
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _terminal(run_id):
    run = EvaluationRun.objects.get(pk=run_id)
    return run.is_terminal


@pytest.mark.acceptance
@pytest.mark.django_db(transaction=True)
@override_settings(WORKER_MAX_CONCURRENCY=4, WORKER_LEASE_SECONDS=5, WORKER_HEARTBEAT_SECONDS=1)
def test_acc_worker_001_two_os_workers_claim_each_execution_once_and_release_locks(minimal_domain):
    """ACC-WORKER-001: journal, DB ownership, and lock scope corroborate."""

    with FakeTargetServer() as fake:
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_fake_revision(fake, max_concurrency=4),
        )
        questions = _extra_questions(minimal_domain, 4)
        from evaluations.services import launch_run

        run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[question.pk for question in questions],
            execution_mode=EvaluationRun.ExecutionMode.PARALLEL,
        )
        fake.state.configure(block_after_acceptance=True)
        first = _start_worker()
        second = _start_worker()
        try:
            _wait_for(
                lambda: len(fake.state.journal_snapshot()["entries"]) == 4,
                description="four independently journaled target requests",
            )
            # Each call is blocked at the fake target. A NOWAIT acquisition
            # succeeds, independently proving no worker transaction spans I/O.
            blocked_execution_id = run.executions.order_by("question_order").first().pk
            with transaction.atomic():
                assert Execution.objects.select_for_update(nowait=True).get(pk=blocked_execution_id).pk == blocked_execution_id
            initial_heartbeat = Execution.objects.get(pk=blocked_execution_id).claim_heartbeat_at
            _wait_for(
                lambda: Execution.objects.get(pk=blocked_execution_id).claim_heartbeat_at > initial_heartbeat,
                description="database-backed heartbeat during a blocked target call",
            )
            assert reconcile_stale_claims() == {"safe_reclaimed": 0, "ambiguous": 0}
            fake.state.release()
            _wait_for(lambda: _terminal(run.pk), description="terminal two-worker run")
        finally:
            _stop_worker(first)
            _stop_worker(second)

        executions = list(run.executions.order_by("question_order"))
        journal = fake.state.journal_snapshot()
        assert [execution.outcome for execution in executions] == [Execution.Outcome.SUCCESS] * 4
        assert len(journal["entries"]) == 4
        assert journal["per_correlation_request_counts"] == {
            str(execution.request_correlation_id): 1 for execution in executions
        }
        assert len({execution.claim_token for execution in executions}) == 4
        assert all(execution.claim_worker_id and execution.target_call_phase == "TERMINAL" for execution in executions)
        run.refresh_from_db()
        assert run.state == EvaluationRun.State.COMPLETED


@pytest.mark.acceptance
@pytest.mark.django_db(transaction=True)
@override_settings(WORKER_MAX_CONCURRENCY=4, WORKER_LEASE_SECONDS=5, WORKER_HEARTBEAT_SECONDS=1)
def test_acc_worker_002_sequential_and_target_wide_parallel_cap(minimal_domain):
    """ACC-WORKER-002: the target journal is the independent concurrency source."""

    from evaluations.services import launch_run

    with FakeTargetServer() as fake:
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_fake_revision(fake, max_concurrency=2),
        )
        questions = _extra_questions(minimal_domain, 4)
        sequential = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[question.pk for question in questions[:3]],
            execution_mode=EvaluationRun.ExecutionMode.SEQUENTIAL,
        )
        fake.state.configure(block_after_acceptance=True)
        worker = _start_worker()
        try:
            _wait_for(
                lambda: len(fake.state.journal_snapshot()["entries"]) == 1,
                description="the one sequential in-flight request",
            )
            assert fake.state.journal_snapshot()["observed_max_concurrency"] == 1
            fake.state.release()
            _wait_for(lambda: _terminal(sequential.pk), description="terminal sequential run")
        finally:
            _stop_worker(worker)

        sequential.refresh_from_db()
        assert sequential.requested_mode == EvaluationRun.ExecutionMode.SEQUENTIAL
        assert sequential.actual_concurrency == 1
        assert fake.state.journal_snapshot()["observed_max_concurrency"] == 1

        fake.state.reset()
        first = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[question.pk for question in questions[:3]],
            execution_mode=EvaluationRun.ExecutionMode.PARALLEL,
        )
        second = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[question.pk for question in questions[1:4]],
            execution_mode=EvaluationRun.ExecutionMode.PARALLEL,
        )
        fake.state.configure(block_after_acceptance=True)
        worker_one = _start_worker()
        worker_two = _start_worker()
        try:
            _wait_for(
                lambda: len(fake.state.journal_snapshot()["entries"]) == 2,
                description="the frozen aggregate target capacity",
            )
            journal = fake.state.journal_snapshot()
            assert journal["active_requests"] == 2
            assert journal["observed_max_concurrency"] == 2
            fake.state.release()
            _wait_for(lambda: _terminal(first.pk) and _terminal(second.pk), description="both capped parallel runs")
        finally:
            _stop_worker(worker_one)
            _stop_worker(worker_two)

        journal = fake.state.journal_snapshot()
        assert journal["observed_max_concurrency"] == 2
        assert len(journal["entries"]) == 6
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.actual_concurrency == second.actual_concurrency == 2
        assert first.configured_max_concurrency == second.configured_max_concurrency == 2


@pytest.mark.acceptance
@pytest.mark.django_db(transaction=True)
@override_settings(WORKER_MAX_CONCURRENCY=4, WORKER_LEASE_SECONDS=5, WORKER_HEARTBEAT_SECONDS=1)
def test_acc_worker_003_partial_error_timeout_and_malformed_results_preserve_siblings(minimal_domain):
    """ACC-WORKER-003: progress is derived from immutable sibling outcomes."""

    from evaluations.services import launch_run, run_progress

    with FakeTargetServer() as fake:
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_fake_revision(fake, max_concurrency=1, question_timeout_seconds=1),
        )
        questions = _extra_questions(minimal_domain, 4)
        run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[question.pk for question in questions],
            execution_mode=EvaluationRun.ExecutionMode.SEQUENTIAL,
        )
        fake.state.configure(
            scripted_responses=[
                {"mode": "success", "answer": "good sibling"},
                {"mode": "http_error"},
                {"mode": "timeout", "delay_seconds": 1.2},
                {"mode": "malformed_response"},
            ]
        )
        worker = _start_worker()
        try:
            _wait_for(lambda: _terminal(run.pk), description="mixed-result run", timeout=15)
            _wait_for(
                lambda: fake.state.journal_snapshot()["active_requests"] == 0,
                description="timeout target capacity release",
            )
        finally:
            _stop_worker(worker)

        executions = list(run.executions.order_by("question_order"))
        run.refresh_from_db()
        assert [execution.outcome for execution in executions] == ["SUCCESS", "ERROR", "TIMEOUT", "ERROR"]
        assert executions[0].raw_answer == "good sibling"
        assert executions[1].error_class == "HTTP_ERROR"
        assert executions[2].error_class == "TARGET_TIMEOUT"
        assert executions[3].error_class == "MALFORMED_RESPONSE"
        assert run.state == EvaluationRun.State.COMPLETED_WITH_ERRORS
        assert run_progress(run) == {
            "total": 4,
            "pending": 0,
            "running": 0,
            "success": 1,
            "error": 2,
            "timeout": 1,
            "completed": 4,
            "elapsed_seconds": run_progress(run)["elapsed_seconds"],
        }


@pytest.mark.acceptance
@pytest.mark.django_db(transaction=True)
@override_settings(WORKER_MAX_CONCURRENCY=4, WORKER_LEASE_SECONDS=5, WORKER_HEARTBEAT_SECONDS=1)
def test_acc_worker_004_pre_submit_reclaim_ambiguity_and_terminal_restart(minimal_domain, tmp_path):
    """ACC-WORKER-004 process barriers prove both permitted recovery paths."""

    from evaluations.services import launch_run

    with FakeTargetServer() as fake:
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_fake_revision(fake, max_concurrency=1),
        )
        questions = _extra_questions(minimal_domain, 2)

        # Safe boundary: the worker is killed after a committed CLAIMED row but
        # before its durable SUBMISSION_STARTED boundary and no target journal.
        safe_run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[questions[0].pk],
            execution_mode=EvaluationRun.ExecutionMode.SEQUENTIAL,
        )
        safe_execution = safe_run.executions.get()
        hook_dir = tmp_path / "safe"
        hook_dir.mkdir()
        killed = _start_worker(
            once=True,
            extra_environment={"STEWARD_BENCH_WORKER_TEST_HOOK_DIRECTORY": str(hook_dir)},
        )
        _wait_for(
            lambda: (hook_dir / f"{safe_execution.pk}.pre_submit.ready").exists(),
            description="pre-submit process barrier",
        )
        safe_execution.refresh_from_db()
        assert safe_execution.target_call_phase == Execution.TargetCallPhase.CLAIMED
        assert fake.state.journal_snapshot()["entries"] == []
        killed.kill()
        killed.wait(timeout=3)
        Execution.objects.filter(pk=safe_execution.pk).update(
            claim_lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert reconcile_stale_claims() == {"safe_reclaimed": 1, "ambiguous": 0}
        safe_execution.refresh_from_db()
        assert safe_execution.outcome == Execution.Outcome.PENDING
        assert safe_execution.claim_token is None
        recovered = _start_worker(once=True)
        recovered.wait(timeout=6)
        assert recovered.returncode == 0
        safe_execution.refresh_from_db()
        assert safe_execution.outcome == Execution.Outcome.SUCCESS
        assert safe_execution.claim_attempt == 2
        assert fake.state.journal_snapshot()["per_correlation_request_counts"] == {
            str(safe_execution.request_correlation_id): 1
        }

        # Ambiguous boundary: the fake target has accepted and journaled the
        # request, but the worker dies before it can persist a response.
        ambiguous_run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[question.pk for question in questions],
            execution_mode=EvaluationRun.ExecutionMode.SEQUENTIAL,
        )
        ambiguous_execution = ambiguous_run.executions.order_by("question_order").first()
        fake.state.reset()
        fake.state.configure(block_after_acceptance=True)
        killed = _start_worker(once=True)
        _wait_for(
            lambda: len(fake.state.journal_snapshot()["entries"]) == 1,
            description="post-acceptance fake-target barrier",
        )
        ambiguous_execution.refresh_from_db()
        assert ambiguous_execution.target_call_phase == Execution.TargetCallPhase.SUBMISSION_STARTED
        killed.kill()
        killed.wait(timeout=3)
        Execution.objects.filter(pk=ambiguous_execution.pk).update(
            claim_lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert reconcile_stale_claims() == {"safe_reclaimed": 0, "ambiguous": 1}
        ambiguous_execution.refresh_from_db()
        assert ambiguous_execution.outcome == Execution.Outcome.ERROR
        assert ambiguous_execution.error_class == "AMBIGUOUS_INFRASTRUCTURE"
        assert ambiguous_execution.target_call_phase == Execution.TargetCallPhase.TERMINAL
        fake.state.release()
        sibling = _start_worker(once=True)
        sibling.wait(timeout=6)
        assert sibling.returncode == 0
        _wait_for(lambda: _terminal(ambiguous_run.pk), description="ambiguous run sibling completion")
        journal = fake.state.journal_snapshot()
        assert journal["per_correlation_request_counts"][str(ambiguous_execution.request_correlation_id)] == 1
        assert len(journal["entries"]) == 2

        # A response obtained before terminal persistence remains a single
        # observation after the worker exits and a new worker is started.
        terminal_run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[questions[0].pk],
            execution_mode=EvaluationRun.ExecutionMode.SEQUENTIAL,
        )
        terminal_execution = terminal_run.executions.get()
        terminal_hook_dir = tmp_path / "terminal"
        terminal_hook_dir.mkdir()
        held = _start_worker(
            once=True,
            extra_environment={
                "STEWARD_BENCH_WORKER_TEST_HOOK_DIRECTORY": str(terminal_hook_dir),
                "STEWARD_BENCH_WORKER_TEST_HOOK_PHASES": "post_response",
            },
        )
        _wait_for(
            lambda: (terminal_hook_dir / f"{terminal_execution.pk}.post_response.ready").exists(),
            description="post-response process barrier",
        )
        (terminal_hook_dir / f"{terminal_execution.pk}.post_response.release").touch()
        held.wait(timeout=6)
        terminal_execution.refresh_from_db()
        terminal_snapshot = (terminal_execution.outcome, terminal_execution.raw_response, terminal_execution.claim_token)
        restarted = _start_worker(once=True)
        restarted.wait(timeout=6)
        terminal_execution.refresh_from_db()
        assert (terminal_execution.outcome, terminal_execution.raw_response, terminal_execution.claim_token) == terminal_snapshot
        assert fake.state.journal_snapshot()["per_correlation_request_counts"][str(terminal_execution.request_correlation_id)] == 1
