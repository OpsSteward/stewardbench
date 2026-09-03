"""Independent M3 acceptance evidence: service/DB state plus fake-target journal."""

import pytest
from django.urls import reverse

from catalog.models import Question, QuestionVersion, TargetRevision
from catalog.services import create_question, create_question_version, create_target_revision
from evaluations.models import EvaluationRun, Execution
from evaluations.services import launch_run, process_next_execution
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
        "supports_runtime_metadata": True,
        "supports_health_check": True,
        "default_execution_mode": TargetRevision.ExecutionMode.SEQUENTIAL,
        "max_concurrency": 1,
        "question_timeout_seconds": 2,
        "inter_question_delay_seconds": 0,
        "declared_product_version": "declared-acceptance",
        "declared_build_id": "acceptance-build",
        "declared_git_sha": "acceptance-sha",
    }
    values.update(overrides)
    return values


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_qver_001_exact_temporal_question_version_is_retained(minimal_domain):
    with FakeTargetServer() as fake:
        create_target_revision(
            actor=minimal_domain["admin"], target=minimal_domain["target"], **_fake_revision(fake)
        )
        question = minimal_domain["question"]
        first = question.current_version
        run = launch_run(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[question.pk]
        )
        second = create_question_version(
            actor=minimal_domain["admin"],
            question=question,
            question_text="Version two exists only after the frozen run.",
            change_type=QuestionVersion.ChangeType.TEST_BUG_FIX,
            change_reason="ACC-QVER-001",
        )

        assert process_next_execution() is True
        execution = run.executions.get()
        execution.refresh_from_db()
        journal = fake.state.journal_snapshot()["entries"]
        assert execution.question_version_id == first.id
        assert execution.question_template == "Quantos transceivers estão em uso?"
        assert second.id != first.id
        assert question.current_version.id == second.id
        assert len(journal) == 1
        assert journal[0]["request_id"].replace("-", "") == execution.request_correlation_id.hex
        current_run = launch_run(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[question.pk]
        )
        assert process_next_execution() is True
        current_execution = current_run.executions.get()
        assert current_execution.question_version_id == second.id
        assert current_execution.question_template == "Version two exists only after the frozen run."


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_run_001_prompt_frozen_manifest_uses_exact_active_filtered_selection(client, minimal_domain):
    with FakeTargetServer() as fake:
        first_revision = create_target_revision(
            actor=minimal_domain["admin"], target=minimal_domain["target"], **_fake_revision(fake)
        )
        active = create_question(
            actor=minimal_domain["admin"],
            stable_id="FILTER-M3-ACTIVE",
            kind=Question.Kind.SINGLE_TURN,
            lifecycle=Question.Lifecycle.ACTIVE,
            domain=minimal_domain["domain"],
            tags=(),
            rationale="",
            question_text="Filtered active question",
        )
        create_question(
            actor=minimal_domain["admin"],
            stable_id="FILTER-M3-DRAFT",
            kind=Question.Kind.SINGLE_TURN,
            lifecycle=Question.Lifecycle.DRAFT,
            domain=minimal_domain["domain"],
            tags=(),
            rationale="",
            question_text="Filtered draft question",
        )
        client.force_login(minimal_domain["admin"])
        response = client.post(
            reverse("run-launch"),
            {
                "target": minimal_domain["target"].pk,
                "select_all_matching": "on",
                "q": "FILTER-M3",
            },
        )
        assert response.status_code == 302
        run = EvaluationRun.objects.get(pk=response["Location"].rstrip("/").split("/")[-1])
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_fake_revision(fake, endpoint="http://127.0.0.1:9", declared_product_version="changed-after-launch"),
        )

        manifest = list(run.executions.order_by("question_order"))
        assert run.state == EvaluationRun.State.PENDING
        assert run.total_planned == 1
        assert [item.question_stable_id for item in manifest] == [active.stable_id]
        assert run.target_revision_id == first_revision.id
        assert run.target_snapshot.endpoint == fake.endpoint
        assert run.selection_filter == {"select_all_matching": True, "q": "FILTER-M3"}


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_adapt_001_complete_unicode_raw_capture_and_metadata_are_independently_journaled(minimal_domain):
    with FakeTargetServer() as fake:
        create_target_revision(
            actor=minimal_domain["admin"], target=minimal_domain["target"], **_fake_revision(fake)
        )
        fake.state.configure(
            answer="Resposta Unicode: São Paulo — ✓",
            evidence={"provenance": ["fake-target", "evidence"]},
        )
        run = launch_run(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[minimal_domain["question"].pk]
        )
        assert process_next_execution() is True

        execution = run.executions.get()
        execution.refresh_from_db()
        run.refresh_from_db()
        journal = fake.state.journal_snapshot()
        assert execution.outcome == Execution.Outcome.SUCCESS
        assert execution.raw_answer == "Resposta Unicode: São Paulo — ✓"
        assert execution.display_answer == execution.raw_answer
        assert "Resposta Unicode" in execution.raw_response
        assert execution.evidence == {"provenance": ["fake-target", "evidence"]}
        assert execution.target_correlation_id == str(execution.request_correlation_id)
        assert execution.adapter_key == "fake-http"
        assert execution.normalizer_key == "identity-display"
        assert run.build_snapshot.runtime_state == "AVAILABLE"
        assert run.build_snapshot.runtime_metadata["product"] == "FakeTarget"
        assert len(journal["entries"]) == 1
        assert journal["entries"][0]["request_id"].replace("-", "") == execution.request_correlation_id.hex
        assert journal["entries"][0]["concrete_question"] == execution.submitted_question


@pytest.mark.acceptance
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("mode", "timeout", "outcome", "error_class"),
    [
        ("auth_rejected", 2, Execution.Outcome.ERROR, "AUTHENTICATION_FAILED"),
        ("http_error", 2, Execution.Outcome.ERROR, "HTTP_ERROR"),
        ("malformed_response", 2, Execution.Outcome.ERROR, "MALFORMED_RESPONSE"),
        ("incomplete_response", 2, Execution.Outcome.ERROR, "MALFORMED_RESPONSE"),
        ("wrong_content_type", 2, Execution.Outcome.ERROR, "MALFORMED_RESPONSE"),
        ("timeout", 1, Execution.Outcome.TIMEOUT, "TARGET_TIMEOUT"),
    ],
)
def test_acc_adapt_002_failures_do_not_become_quality_judgments(
    minimal_domain, mode, timeout, outcome, error_class
):
    with FakeTargetServer() as fake:
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_fake_revision(fake, question_timeout_seconds=timeout),
        )
        # A delay equal to urllib's deadline is scheduling-sensitive. Keep the
        # fake response strictly beyond the configured M3 timeout so this
        # acceptance scenario proves a transport timeout deterministically.
        fake.state.configure(
            mode=mode,
            delay_seconds=timeout + 1 if mode == "timeout" else 0,
        )
        run = launch_run(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[minimal_domain["question"].pk]
        )
        assert process_next_execution() is True

        execution = run.executions.get()
        execution.refresh_from_db()
        run.refresh_from_db()
        journal = fake.state.journal_snapshot()["entries"]
        assert execution.outcome == outcome
        assert execution.error_class == error_class
        assert execution.raw_answer == ""
        assert execution.display_answer == ""
        assert run.state == EvaluationRun.State.COMPLETED_WITH_ERRORS
        assert len(journal) == 1
