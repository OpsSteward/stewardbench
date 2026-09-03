import pytest
from django.urls import reverse

from catalog.models import TargetRevision
from catalog.services import create_target_revision
from evaluations.models import EvaluationRun, Execution
from evaluations.services import launch_run, process_next_execution
from harness.fake_target import FakeTargetServer


def _revision_values(endpoint):
    return {
        "endpoint": endpoint,
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
        "declared_product_version": "",
        "declared_build_id": "",
        "declared_git_sha": "",
    }


@pytest.mark.django_db
def test_admin_launches_and_operator_can_only_view_runs(client, minimal_domain):
    with FakeTargetServer() as fake:
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_revision_values(fake.endpoint),
        )
        client.force_login(minimal_domain["admin"])
        response = client.post(
            reverse("run-launch"),
            {"target": minimal_domain["target"].pk, "question_ids": [minimal_domain["question"].pk]},
        )
        assert response.status_code == 302
        run_url = response["Location"]
        assert client.get(run_url).status_code == 200

        client.force_login(minimal_domain["operator"])
        assert client.get(reverse("run-list")).status_code == 200
        assert client.get(run_url).status_code == 200
        denied = client.post(
            reverse("run-launch"),
            {"target": minimal_domain["target"].pk, "question_ids": [minimal_domain["question"].pk]},
        )
        assert denied.status_code == 403


@pytest.mark.django_db
def test_admin_can_freeze_parallel_mode_and_target_policy_in_the_run_manifest(client, minimal_domain):
    with FakeTargetServer() as fake:
        # Revision policy is immutable, so the parallel test policy is a new
        # concrete revision rather than an edit to the fixture's old policy.
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **{
                **_revision_values(fake.endpoint),
                "default_execution_mode": TargetRevision.ExecutionMode.PARALLEL,
                "max_concurrency": 2,
            },
        )
        client.force_login(minimal_domain["admin"])
        launch_page = client.get(reverse("run-launch"))
        assert launch_page.status_code == 200
        assert b"Parallel" in launch_page.content
        response = client.post(
            reverse("run-launch"),
            {
                "target": minimal_domain["target"].pk,
                "question_ids": [minimal_domain["question"].pk],
                "execution_mode": EvaluationRun.ExecutionMode.PARALLEL,
            },
        )
        assert response.status_code == 302
        run = EvaluationRun.objects.get(pk=response["Location"].rstrip("/").split("/")[-1])
        assert run.requested_mode == EvaluationRun.ExecutionMode.PARALLEL
        assert run.configured_max_concurrency == 2
        assert run.actual_concurrency == 2


@pytest.mark.django_db
def test_execution_detail_escapes_unsafe_target_output(client, minimal_domain):
    with FakeTargetServer() as fake:
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **_revision_values(fake.endpoint),
        )
        fake.state.configure(mode="unsafe_html")
        run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[minimal_domain["question"].pk],
        )
        process_next_execution()
        execution = run.executions.get()
        execution.refresh_from_db()
        assert execution.outcome == Execution.Outcome.SUCCESS

        client.force_login(minimal_domain["operator"])
        page = client.get(reverse("execution-detail", args=[execution.pk]))
        assert page.status_code == 200
        assert b"&lt;script&gt;window.__fake_target_executed" in page.content
        assert b"<script>window.__fake_target_executed" not in page.content
