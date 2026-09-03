"""Independent M6 acceptance evidence for baseline and exact comparison contracts."""

from __future__ import annotations

import pytest
from django.urls import reverse

from catalog.models import BindingDefinition, Question, TargetRevision
from catalog.services import create_question, create_question_version, create_target_revision
from evaluations.models import (
    BaselineAttentionEvent,
    BaselineMembership,
    ComparisonItem,
    EvaluationRun,
    Execution,
)
from evaluations.services import (
    baseline_completeness,
    comparison_human_transition,
    create_baseline,
    launch_controlled_comparison,
    launch_run,
    process_next_execution,
    record_human_review,
    normalize_exact_answer,
    set_baseline_active,
    set_execution_validity,
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
        "supports_conversation_session": False,
        "supports_runtime_metadata": False,
        "supports_health_check": True,
        "default_execution_mode": TargetRevision.ExecutionMode.SEQUENTIAL,
        "max_concurrency": 1,
        "question_timeout_seconds": 2,
        "inter_question_delay_seconds": 0,
        "declared_product_version": version,
        "declared_build_id": build,
        "declared_git_sha": f"sha-{build}",
    }
    values.update(overrides)
    return values


def _set_revision(minimal_domain, fake, *, version, build, **overrides):
    return create_target_revision(
        actor=minimal_domain["admin"],
        target=minimal_domain["target"],
        **_revision_values(fake.endpoint, version=version, build=build, **overrides),
    )


def _complete_one(*, actor, target, question):
    run = launch_run(actor=actor, target=target, question_ids=[question.pk])
    assert process_next_execution() is True
    execution = run.executions.get()
    execution.refresh_from_db()
    run.refresh_from_db()
    assert execution.is_terminal
    assert run.is_terminal
    return run, execution


def test_m6_exact_v1_normalization_is_deliberately_shallow():
    assert normalize_exact_answer("EVC-A  \r\nEVC-B\t") == "EVC-A\nEVC-B"
    assert normalize_exact_answer("EVC-A, EVC-B") != normalize_exact_answer("EVC-A and EVC-B")


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_base_001_warning_membership_and_active_history_are_immutable(minimal_domain):
    """ACC-BASE-001: fixed observed membership accepts BAD/unreviewed history."""

    with FakeTargetServer() as fake:
        _set_revision(minimal_domain, fake, version="baseline-v1", build="build-a")
        second = create_question(
            actor=minimal_domain["admin"],
            stable_id="M6-UNREVIEWED",
            kind=Question.Kind.SINGLE_TURN,
            lifecycle=Question.Lifecycle.ACTIVE,
            domain=minimal_domain["domain"],
            tags=(),
            rationale="",
            question_text="Second observed question",
        )
        source_run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[minimal_domain["question"].pk, second.pk],
        )
        assert process_next_execution() is True
        assert process_next_execution() is True
        source = list(source_run.executions.order_by("question_order"))
        record_human_review(
            actor=minimal_domain["admin"], execution=source[0], judgment="BAD", comment_text="Historical BAD is allowed."
        )

        baseline = create_baseline(
            actor=minimal_domain["admin"],
            source_run=source_run,
            name="M6 warning baseline",
            description="Observed history only",
            is_active=True,
        )
        frozen_ids = list(baseline.memberships.order_by("execution__question_order").values_list("execution_id", flat=True))
        assert frozen_ids == [source[0].pk, source[1].pk]
        assert baseline_completeness(baseline) == {
            "total": 2,
            "valid": 2,
            "invalid": 0,
            "human_reviewed": 1,
            "unreviewed": 1,
            "good": 0,
            "bad": 1,
            "success": 2,
            "error": 0,
            "timeout": 0,
        }
        assert baseline.state_history.count() == 1
        event = set_baseline_active(actor=minimal_domain["admin"], baseline=baseline, is_active=False)
        assert event and event.is_active is False
        assert set_baseline_active(actor=minimal_domain["admin"], baseline=baseline, is_active=True)
        baseline.refresh_from_db()
        assert baseline.is_active is True
        assert baseline.state_history.count() == 3
        assert list(baseline.memberships.order_by("execution__question_order").values_list("execution_id", flat=True)) == frozen_ids
        assert BaselineMembership.objects.filter(baseline=baseline).count() == 2


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_comp_001_replay_reuses_v1_bindings_and_current_target_identity(minimal_domain):
    """ACC-COMP-001: current build changes, exact baseline QV/bindings do not."""

    with FakeTargetServer() as fake:
        baseline_revision = _set_revision(minimal_domain, fake, version="2.0.0", build="commit-a")
        controlled = create_question(
            actor=minimal_domain["admin"],
            stable_id="M6-CONTROLLED",
            kind=Question.Kind.SINGLE_TURN,
            lifecycle=Question.Lifecycle.ACTIVE,
            domain=minimal_domain["domain"],
            tags=(),
            rationale="",
            question_text="Show {{evc}} status",
            bindings=[
                {
                    "name": "evc",
                    "value_type": BindingDefinition.ValueType.IDENTIFIER,
                    "is_required": True,
                    "description": "Controlled EVC",
                    "fixed_value": "CONTROL-EVC-001",
                }
            ],
        )
        fake.state.configure(answer="EVC-A, EVC-B")
        source_run, source = _complete_one(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question=controlled
        )
        record_human_review(actor=minimal_domain["admin"], execution=source, judgment="BAD")
        baseline = create_baseline(
            actor=minimal_domain["admin"], source_run=source_run, name="M6 exact v1 baseline"
        )
        v1 = source.question_version
        create_question_version(
            actor=minimal_domain["admin"],
            question=controlled,
            question_text="NEW v2 wording for {{evc}} status",
            change_type="TEST_BUG_FIX",
            change_reason="M6 temporal control proof",
            bindings=[
                {
                    "name": "evc",
                    "value_type": BindingDefinition.ValueType.IDENTIFIER,
                    "is_required": True,
                    "description": "Different normal-run control",
                    "fixed_value": "CONTROL-EVC-002",
                }
            ],
        )
        current_revision = _set_revision(minimal_domain, fake, version="2.0.1", build="commit-b")
        fake.state.configure(answer="EVC-A, EVC-C")

        current_run = launch_controlled_comparison(
            actor=minimal_domain["admin"], baseline=baseline, target=minimal_domain["target"]
        )
        current = current_run.executions.get()
        assert current_run.comparison_baseline_id == baseline.pk
        assert current_run.target_revision_id == current_revision.pk
        assert current_run.target_revision_id != baseline_revision.pk
        assert current.question_version_id == v1.pk
        assert current.submitted_question == "Show CONTROL-EVC-001 status"
        assert current.question_template == "Show {{evc}} status"
        assert current.resolved_bindings.get().value == "CONTROL-EVC-001"
        assert current.resolved_bindings.get().resolution_mode == "BASELINE_FROZEN"

        assert process_next_execution() is True
        current.refresh_from_db()
        item = current.current_comparison_items.select_related("comparison", "baseline_execution").get()
        assert item.comparison.baseline_id == baseline.pk
        assert item.baseline_execution_id == source.pk
        assert item.change_state == ComparisonItem.ChangeState.CHANGED
        assert item.exact_equal is False
        assert item.comparison.algorithm_version == "exact-v1"
        assert current.review_state == Execution.ReviewState.REQUIRED
        assert current.current_human_review_id is None
        assert len(fake.state.journal_snapshot()["entries"]) == 2

        record_human_review(actor=minimal_domain["admin"], execution=current, judgment="GOOD")
        current.refresh_from_db()
        item.refresh_from_db()
        assert current.review_state == Execution.ReviewState.REVIEWED
        assert current.current_human_review.judgment == "GOOD"
        assert item.change_state == ComparisonItem.ChangeState.CHANGED
        assert comparison_human_transition(item) == "BAD → GOOD"


@pytest.mark.acceptance
@pytest.mark.django_db
def test_bad_baseline_exact_equality_is_unchanged_not_current_good(minimal_domain):
    """BAD history is context: equality never copies a correctness judgment."""

    with FakeTargetServer() as fake:
        _set_revision(minimal_domain, fake, version="baseline", build="bad-a")
        fake.state.configure(answer="A")
        source_run, source = _complete_one(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question=minimal_domain["question"]
        )
        record_human_review(actor=minimal_domain["admin"], execution=source, judgment="BAD")
        baseline = create_baseline(actor=minimal_domain["admin"], source_run=source_run, name="M6 BAD equality")
        _set_revision(minimal_domain, fake, version="current", build="bad-b")
        fake.state.configure(answer="A")
        current_run = launch_controlled_comparison(
            actor=minimal_domain["admin"], baseline=baseline, target=minimal_domain["target"]
        )
        assert process_next_execution() is True
        current = current_run.executions.get()
        item = current.current_comparison_items.get()
        current.refresh_from_db()
        assert item.change_state == ComparisonItem.ChangeState.UNCHANGED
        assert current.current_human_review_id is None
        assert current.review_state == Execution.ReviewState.NONE
        assert comparison_human_transition(item) == "BAD → unreviewed"


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_comp_002_unavailable_frozen_binding_makes_non_comparable_without_call(minimal_domain):
    """ACC-COMP-002: no dynamic replacement is sent when a frozen input is unsafe."""

    with FakeTargetServer() as fake:
        _set_revision(minimal_domain, fake, version="baseline", build="binding-a")
        broken = create_question(
            actor=minimal_domain["admin"],
            stable_id="M6-BROKEN-BINDING",
            kind=Question.Kind.SINGLE_TURN,
            lifecycle=Question.Lifecycle.ACTIVE,
            domain=minimal_domain["domain"],
            tags=(),
            rationale="",
            question_text="Which {{evc}} is affected?",
            bindings=[
                {
                    "name": "evc",
                    "value_type": BindingDefinition.ValueType.IDENTIFIER,
                    "is_required": True,
                    "description": "Deliberately unavailable frozen value",
                    "fixed_value": None,
                }
            ],
        )
        source_run = launch_run(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            question_ids=[minimal_domain["question"].pk, broken.pk],
        )
        assert process_next_execution() is True
        assert process_next_execution() is True
        source = list(source_run.executions.order_by("question_order"))
        assert source[1].outcome == Execution.Outcome.ERROR
        assert source[1].preflight_error_class == "BINDING_CONFIGURATION_ERROR"
        baseline = create_baseline(actor=minimal_domain["admin"], source_run=source_run, name="M6 no substitution")
        _set_revision(minimal_domain, fake, version="current", build="binding-b")
        calls_before = len(fake.state.journal_snapshot()["entries"])
        current_run = launch_controlled_comparison(
            actor=minimal_domain["admin"], baseline=baseline, target=minimal_domain["target"]
        )
        assert process_next_execution() is True
        assert process_next_execution() is True
        replay = list(current_run.executions.order_by("question_order"))
        replay[1].refresh_from_db()
        item = replay[1].current_comparison_items.get()
        assert replay[1].outcome == Execution.Outcome.ERROR
        assert replay[1].error_class == "COMPARISON_NON_COMPARABLE"
        assert item.change_state == ComparisonItem.ChangeState.NON_COMPARABLE
        assert item.non_comparable_reason == "FROZEN_BINDING_UNAVAILABLE"
        assert len(fake.state.journal_snapshot()["entries"]) == calls_before + 1
        assert (
            fake.state.journal_snapshot()["entries"][-1]["concrete_question"]
            == minimal_domain["question"].current_version.question_text
        )


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_valid_001_later_baseline_invalidation_preserves_membership_and_comparison(minimal_domain):
    """ACC-VALID-001 M6 portion: attention appears; evidence is never rewritten."""

    with FakeTargetServer() as fake:
        _set_revision(minimal_domain, fake, version="baseline", build="valid-a")
        fake.state.configure(answer="before")
        source_run, source = _complete_one(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question=minimal_domain["question"]
        )
        baseline = create_baseline(actor=minimal_domain["admin"], source_run=source_run, name="M6 validity attention")
        _set_revision(minimal_domain, fake, version="current", build="valid-b")
        fake.state.configure(answer="after")
        current_run = launch_controlled_comparison(
            actor=minimal_domain["admin"], baseline=baseline, target=minimal_domain["target"]
        )
        assert process_next_execution() is True
        item = current_run.comparison.items.get()
        original = (item.change_state, item.exact_equal, item.baseline_normalized_hash, item.current_normalized_hash)

        decision = set_execution_validity(
            actor=minimal_domain["admin"], execution=source, validity=Execution.Validity.INVALID, comment_text="Fixture invalidation"
        )
        baseline.refresh_from_db()
        item.refresh_from_db()
        assert decision and baseline.requires_attention is True
        assert BaselineAttentionEvent.objects.filter(baseline=baseline, execution=source).count() == 1
        assert BaselineMembership.objects.filter(baseline=baseline, execution=source).exists()
        assert (item.change_state, item.exact_equal, item.baseline_normalized_hash, item.current_normalized_hash) == original
        assert baseline_completeness(baseline)["invalid"] == 1
        calls_before = len(fake.state.journal_snapshot()["entries"])
        non_comparable_run = launch_controlled_comparison(
            actor=minimal_domain["admin"], baseline=baseline, target=minimal_domain["target"]
        )
        assert process_next_execution() is True
        invalid_current = non_comparable_run.executions.get()
        invalid_item = invalid_current.current_comparison_items.get()
        assert invalid_item.change_state == ComparisonItem.ChangeState.NON_COMPARABLE
        assert invalid_item.non_comparable_reason == "BASELINE_EXECUTION_INVALID"
        assert len(fake.state.journal_snapshot()["entries"]) == calls_before


@pytest.mark.django_db
def test_m6_ui_and_operator_post_denial(client, minimal_domain):
    """M6 UI is readable to OPERATOR; all baseline mutations remain ADMIN-only."""

    with FakeTargetServer() as fake:
        _set_revision(minimal_domain, fake, version="baseline", build="ui-a")
        source_run, _source = _complete_one(
            actor=minimal_domain["admin"], target=minimal_domain["target"], question=minimal_domain["question"]
        )
        baseline = create_baseline(actor=minimal_domain["admin"], source_run=source_run, name="M6 UI baseline")
        client.force_login(minimal_domain["admin"])
        assert b"Create Baseline" in client.get(reverse("run-detail", args=[source_run.pk])).content
        baseline_page = client.get(reverse("baseline-detail", args=[baseline.pk]))
        assert baseline_page.status_code == 200
        assert b"Run controlled comparison" in baseline_page.content
        assert b"Review completeness warning" in baseline_page.content
        launch = client.post(
            reverse("baseline-controlled-replay", args=[baseline.pk]), {"target": minimal_domain["target"].pk}
        )
        assert launch.status_code == 302
        current_run = baseline.controlled_runs.get()
        assert process_next_execution() is True
        current = current_run.executions.get()
        comparison = current_run.comparison
        comparison_page = client.get(reverse("comparison-detail", args=[comparison.pk]))
        assert comparison_page.status_code == 200
        assert b"Summary and triage links" in comparison_page.content
        assert client.get(f"{reverse('comparison-detail', args=[comparison.pk])}?state=UNCHANGED").status_code == 200
        execution_page = client.get(reverse("execution-detail", args=[current.pk]))
        assert execution_page.status_code == 200
        assert b"Baseline / current exact comparison" in execution_page.content
        client.force_login(minimal_domain["operator"])
        assert client.get(reverse("baseline-list")).status_code == 200
        detail = client.get(reverse("baseline-detail", args=[baseline.pk]))
        assert detail.status_code == 200
        assert b"not ground truth" in detail.content
        assert client.get(reverse("comparison-list")).status_code == 200
        assert client.post(reverse("baseline-state", args=[baseline.pk]), {"is_active": "false"}).status_code == 403
        assert client.post(
            reverse("baseline-controlled-replay", args=[baseline.pk]), {"target": minimal_domain["target"].pk}
        ).status_code == 403
        assert client.post(
            reverse("baseline-create", args=[source_run.pk]), {"name": "operator cannot create"}
        ).status_code == 403
