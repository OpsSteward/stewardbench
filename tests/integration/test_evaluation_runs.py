from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from catalog.models import BindingDefinition, Question, QuestionVersion, TargetRevision
from catalog.services import create_question, create_question_version, create_target_revision
from evaluations.adapters import credential_environment_name
from evaluations.models import EvaluationRun, Execution
from evaluations.services import (
    launch_run,
    process_next_execution,
    recover_interrupted_executions,
    run_progress,
)
from harness.fake_target import FakeTargetServer


@pytest.fixture
def fake_target():
    with FakeTargetServer() as server:
        yield server


def fake_revision_values(server, **overrides):
    values = {
        "endpoint": server.endpoint,
        "adapter_key": "fake-http",
        "adapter_version": "1",
        "credential_reference": "",
        "classification": TargetRevision.Classification.LAB_TEST,
        "supports_question_api": True,
        "supports_conversation_session": False,
        "supports_runtime_metadata": True,
        "supports_health_check": True,
        "default_execution_mode": TargetRevision.ExecutionMode.SEQUENTIAL,
        "max_concurrency": 4,
        "question_timeout_seconds": 2,
        "inter_question_delay_seconds": 0,
        "declared_product_version": "declared-m3",
        "declared_build_id": "declared-build",
        "declared_git_sha": "declared-sha",
    }
    values.update(overrides)
    return values


def configure_fake_target(minimal_domain, fake_target, **overrides):
    return create_target_revision(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        **fake_revision_values(fake_target, **overrides),
    )


@pytest.mark.django_db
def test_launch_freezes_active_single_turn_manifest_and_fixed_binding(minimal_domain, fake_target):
    configure_fake_target(minimal_domain, fake_target)
    bound = create_question(
        actor=minimal_domain["admin"],
        stable_id="FIXTURE-BOUND",
        kind=Question.Kind.SINGLE_TURN,
        lifecycle=Question.Lifecycle.ACTIVE,
        domain=minimal_domain["domain"],
        tags=(),
        rationale="",
        question_text="What is the state of {{site_id}}?",
        bindings=[
            {
                "name": "site_id",
                "value_type": BindingDefinition.ValueType.IDENTIFIER,
                "is_required": True,
                "description": "Configured test site",
                "fixed_value": "São Paulo",
            }
        ],
    )

    run = launch_run(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        question_ids=[minimal_domain["question"].id, bound.id],
    )

    executions = list(run.executions.order_by("question_order").prefetch_related("resolved_bindings"))
    assert run.state == EvaluationRun.State.PENDING
    assert run.requested_mode == EvaluationRun.ExecutionMode.SEQUENTIAL
    assert run.actual_concurrency == 1
    assert [execution.question_stable_id for execution in executions] == ["FIXTURE-001", "FIXTURE-BOUND"]
    bound_execution = executions[1]
    assert bound_execution.question_template == "What is the state of {{site_id}}?"
    assert bound_execution.submitted_question == "What is the state of São Paulo?"
    assert bound_execution.resolved_bindings.get().value == "São Paulo"
    assert run.target_snapshot.endpoint == fake_target.endpoint
    assert run.build_snapshot.declared_product_version == "declared-m3"


@pytest.mark.django_db
def test_missing_required_binding_becomes_explicit_error_without_target_submission(minimal_domain, fake_target):
    configure_fake_target(minimal_domain, fake_target)
    question = create_question(
        actor=minimal_domain["admin"],
        stable_id="FIXTURE-MISSING-BINDING",
        kind=Question.Kind.SINGLE_TURN,
        lifecycle=Question.Lifecycle.ACTIVE,
        domain=minimal_domain["domain"],
        tags=(),
        rationale="",
        question_text="What is the state of {{site_id}}?",
        bindings=[
            {
                "name": "site_id",
                "value_type": BindingDefinition.ValueType.IDENTIFIER,
                "is_required": True,
                "description": "Must be configured",
                "fixed_value": None,
            }
        ],
    )
    run = launch_run(actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[question.id])

    assert process_next_execution() is True
    execution = run.executions.get()
    execution.refresh_from_db()
    assert execution.outcome == Execution.Outcome.ERROR
    assert execution.error_class == "BINDING_CONFIGURATION_ERROR"
    assert fake_target.state.journal_snapshot()["entries"] == []


@pytest.mark.django_db
def test_worker_captures_exact_unicode_raw_response_metadata_and_progress(minimal_domain, fake_target):
    configure_fake_target(minimal_domain, fake_target)
    fake_target.state.configure(
        answer="São Paulo has 2 transceivers — confirmação ✓",
        evidence={"source": "fake", "circuit": "SP-01"},
    )
    run = launch_run(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        question_ids=[minimal_domain["question"].id],
    )

    assert process_next_execution() is True
    execution = run.executions.get()
    execution.refresh_from_db()
    run.refresh_from_db()
    journal = fake_target.state.journal_snapshot()["entries"]
    assert execution.outcome == Execution.Outcome.SUCCESS
    assert execution.raw_answer == "São Paulo has 2 transceivers — confirmação ✓"
    assert execution.display_answer == execution.raw_answer
    assert execution.evidence == {"source": "fake", "circuit": "SP-01"}
    assert execution.raw_response
    assert execution.request_correlation_id.hex == journal[0]["request_id"].replace("-", "")
    assert journal[0]["sequence"] == 1
    assert journal[0]["mode"] == "success"
    assert run.state == EvaluationRun.State.COMPLETED
    progress = run_progress(run)
    assert {key: progress[key] for key in ("total", "pending", "running", "success", "error", "timeout", "completed")} == {
        "total": 1,
        "pending": 0,
        "running": 0,
        "success": 1,
        "error": 0,
        "timeout": 0,
        "completed": 1,
    }
    assert run.build_snapshot.runtime_state == "AVAILABLE"
    assert run.build_snapshot.runtime_metadata["product"] == "FakeTarget"
    assert process_next_execution() is False
    assert len(fake_target.state.journal_snapshot()["entries"]) == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("metadata_mode", "expected_state"),
    [
        ("metadata_unavailable", "UNAVAILABLE"),
        ("metadata_malformed", "MALFORMED"),
    ],
)
def test_metadata_absence_or_malformed_response_does_not_prevent_question_execution(
    minimal_domain, fake_target, metadata_mode, expected_state
):
    configure_fake_target(minimal_domain, fake_target)
    fake_target.state.configure(mode=metadata_mode)
    run = launch_run(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        question_ids=[minimal_domain["question"].id],
    )

    process_next_execution()
    execution = run.executions.get()
    execution.refresh_from_db()
    run.refresh_from_db()
    run.build_snapshot.refresh_from_db()
    assert execution.outcome == Execution.Outcome.SUCCESS
    assert run.build_snapshot.runtime_state == expected_state
    assert len(fake_target.state.journal_snapshot()["entries"]) == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("mode", "expected_outcome", "expected_error"),
    [
        ("http_error", Execution.Outcome.ERROR, "HTTP_ERROR"),
        ("malformed_response", Execution.Outcome.ERROR, "MALFORMED_RESPONSE"),
        ("incomplete_response", Execution.Outcome.ERROR, "MALFORMED_RESPONSE"),
        ("wrong_content_type", Execution.Outcome.ERROR, "MALFORMED_RESPONSE"),
    ],
)
def test_worker_normalizes_target_failures_without_quality_judgment(
    minimal_domain, fake_target, mode, expected_outcome, expected_error
):
    configure_fake_target(minimal_domain, fake_target)
    fake_target.state.configure(mode=mode)
    run = launch_run(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        question_ids=[minimal_domain["question"].id],
    )

    process_next_execution()
    execution = run.executions.get()
    execution.refresh_from_db()
    assert execution.outcome == expected_outcome
    assert execution.error_class == expected_error
    assert execution.raw_answer == ""
    assert not hasattr(execution, "human_review")
    assert len(fake_target.state.journal_snapshot()["entries"]) == 1


@pytest.mark.django_db
def test_timeout_and_terminal_observation_survive_worker_restart(minimal_domain, fake_target):
    configure_fake_target(minimal_domain, fake_target, question_timeout_seconds=1)
    fake_target.state.configure(delay_seconds=1.2)
    run = launch_run(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        question_ids=[minimal_domain["question"].id],
    )

    process_next_execution()
    execution = run.executions.get()
    execution.refresh_from_db()
    assert execution.outcome == Execution.Outcome.TIMEOUT
    original_response = execution.raw_response
    assert recover_interrupted_executions() == 0
    execution.refresh_from_db()
    assert execution.outcome == Execution.Outcome.TIMEOUT
    assert execution.raw_response == original_response
    assert len(fake_target.state.journal_snapshot()["entries"]) == 1


@pytest.mark.django_db
def test_partial_run_preserves_success_when_later_execution_errors(minimal_domain, fake_target):
    configure_fake_target(minimal_domain, fake_target)
    second = create_question(
        actor=minimal_domain["admin"],
        stable_id="FIXTURE-PARTIAL-SECOND",
        kind=Question.Kind.SINGLE_TURN,
        lifecycle=Question.Lifecycle.ACTIVE,
        domain=minimal_domain["domain"],
        tags=(),
        rationale="",
        question_text="Second execution",
    )
    run = launch_run(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        question_ids=[minimal_domain["question"].id, second.id],
    )
    # Stable ID ordering makes FIXTURE-001 the first submitted question.
    assert process_next_execution() is True
    fake_target.state.configure(mode="http_error")
    assert process_next_execution() is True

    outcomes = list(run.executions.order_by("question_order").values_list("outcome", flat=True))
    run.refresh_from_db()
    assert outcomes == [Execution.Outcome.SUCCESS, Execution.Outcome.ERROR]
    assert run.state == EvaluationRun.State.COMPLETED_WITH_ERRORS
    assert len(fake_target.state.journal_snapshot()["entries"]) == 2


@pytest.mark.django_db
def test_interrupted_running_execution_is_not_resubmitted(minimal_domain, fake_target):
    configure_fake_target(minimal_domain, fake_target)
    run = launch_run(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        question_ids=[minimal_domain["question"].id],
    )
    execution = run.executions.get()
    execution.outcome = Execution.Outcome.RUNNING
    execution.save()

    assert recover_interrupted_executions() == 1
    execution.refresh_from_db()
    assert execution.outcome == Execution.Outcome.ERROR
    assert execution.error_class == "AMBIGUOUS_INFRASTRUCTURE"
    assert process_next_execution() is False
    assert fake_target.state.journal_snapshot()["entries"] == []


@pytest.mark.django_db
def test_question_and_target_revisions_after_launch_do_not_change_execution(minimal_domain, fake_target):
    frozen_revision = configure_fake_target(minimal_domain, fake_target)
    question = minimal_domain["question"]
    version_one = question.current_version
    run = launch_run(actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[question.id])
    create_question_version(
        actor=minimal_domain["admin"],
        question=question,
        question_text="Question version two must not alter the historical run.",
        change_type=QuestionVersion.ChangeType.TEST_BUG_FIX,
        change_reason="M3 temporal acceptance",
    )
    create_target_revision(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        **fake_revision_values(fake_target, endpoint="http://127.0.0.1:9", declared_product_version="new"),
    )

    process_next_execution()
    execution = run.executions.get()
    execution.refresh_from_db()
    assert execution.outcome == Execution.Outcome.SUCCESS
    assert execution.question_version_id == version_one.id
    assert execution.question_template == "Quantos transceivers estão em uso?"
    assert execution.target_revision_id == frozen_revision.id
    assert execution.target_snapshot.endpoint == fake_target.endpoint
    assert len(fake_target.state.journal_snapshot()["entries"]) == 1


@pytest.mark.django_db
def test_credential_is_runtime_only_and_redacted_before_capture(minimal_domain, fake_target, monkeypatch):
    secret = "m3-canary-token-do-not-persist"
    reference = "secrets/m3-fake"
    configure_fake_target(minimal_domain, fake_target, credential_reference=reference)
    monkeypatch.setenv(credential_environment_name(reference), secret)
    fake_target.state.configure(expected_credential=secret, answer=f"Echo {secret}")
    run = launch_run(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        question_ids=[minimal_domain["question"].id],
    )

    process_next_execution()
    execution = run.executions.get()
    execution.refresh_from_db()
    assert execution.outcome == Execution.Outcome.SUCCESS
    assert secret not in execution.raw_response
    assert secret not in execution.raw_answer
    assert "Authorization" not in str(execution.raw_request)
    assert fake_target.state.journal_snapshot()["entries"][0]["request_id"]


@pytest.mark.django_db
def test_missing_runtime_credential_is_explicit_error_without_target_call(minimal_domain, fake_target):
    reference = "secrets/missing-m3"
    configure_fake_target(minimal_domain, fake_target, credential_reference=reference)
    run = launch_run(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        question_ids=[minimal_domain["question"].id],
    )

    process_next_execution()
    execution = run.executions.get()
    execution.refresh_from_db()
    assert execution.outcome == Execution.Outcome.ERROR
    assert execution.error_class == "AUTHENTICATION_FAILED"
    assert reference in execution.error_detail
    assert fake_target.state.journal_snapshot()["entries"] == []
