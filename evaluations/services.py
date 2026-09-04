"""Frozen-run services and the M4 PostgreSQL-backed durable worker.

The worker deliberately uses the Execution rows as its queue. Claims are short
PostgreSQL transactions; adapter calls are deliberately outside them.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import threading
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Q, Subquery
from django.utils import timezone

from accounts.policy import require_admin
from catalog.models import ConversationScenario, ConversationScenarioVersion, EvaluationTarget, Question, TargetRevision

from .adapters import AdapterFailure, ConversationFailure, TargetTimeout, adapter_for, resolve_credential
from .models import (
    Baseline,
    BaselineAttentionEvent,
    BaselineMembership,
    BaselineStateEvent,
    BuildSnapshot,
    Comment,
    Comparison,
    ComparisonItem,
    ConversationAttempt,
    AutomatedEvaluationResult,
    EvaluationInvocation,
    EvaluationRun,
    Execution,
    ExecutionValidityDecision,
    HumanReview,
    LLMJudgeResult,
    ResolvedBinding,
    ReviewTracking,
    SemanticComparisonResult,
    TargetSnapshot,
)
from .operator_answers import exact_operator_answer, semantic_operator_answer
from .performance import PERFORMANCE_POLICY_VERSION, classify_latency, performance_comparison, token_delta
from .semantic import (
    SemanticComparator,
    SemanticComparatorFailure,
    SemanticComparatorInput,
    SemanticComparatorProtocolError,
    SemanticComparatorResponse,
    default_semantic_comparator,
)
from .evaluators import (
    JUDGE_DIMENSIONS,
    Evaluator,
    EvaluatorFailure,
    EvaluatorInput,
    EvaluatorProtocolError,
    EvaluatorResponse,
    LLMJudge,
    JudgeInput,
    JudgeResponse,
    default_evaluator,
    default_llm_judge,
)


logger = logging.getLogger("stewardbench.worker")
_IN_PROCESS_WORKER_ID = f"in-process-{uuid.uuid4()}"


@dataclass(frozen=True)
class ExecutionClaim:
    execution_id: int
    worker_id: str
    token: uuid.UUID


@dataclass(frozen=True)
class EvaluationInvocationClaim:
    invocation_id: int
    worker_id: str
    token: uuid.UUID


def _database_now():
    """Read the PostgreSQL clock used for all lease decisions in this module."""

    with connection.cursor() as cursor:
        cursor.execute("SELECT CURRENT_TIMESTAMP")
        return cursor.fetchone()[0]


def _lease_expiry(now):
    return now + timedelta(seconds=settings.WORKER_LEASE_SECONDS)


def _eligible_questions(filters: dict | None = None):
    filters = filters or {}
    questions = Question.objects.filter(
        lifecycle=Question.Lifecycle.ACTIVE,
        kind=Question.Kind.SINGLE_TURN,
        versions__valid_to__isnull=True,
    ).select_related("domain").prefetch_related("versions__binding_definitions")
    text = str(filters.get("q", "")).strip()
    domain = str(filters.get("domain", "")).strip()
    tag = str(filters.get("tag", "")).strip()
    if text:
        questions = questions.filter(
            Q(stable_id__icontains=text)
            | Q(versions__valid_to__isnull=True, versions__question_text__icontains=text)
        )
    if domain:
        questions = questions.filter(domain__slug=domain)
    if tag:
        questions = questions.filter(tags__name=tag)
    return questions.distinct().order_by("stable_id")


def eligible_question_count(filters: dict | None = None) -> int:
    return _eligible_questions(filters).count()


def _display_binding_value(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _freeze_bindings(question_version):
    concrete_question = question_version.question_text
    frozen_bindings = []
    errors = []
    for definition in question_version.binding_definitions.all().order_by("name"):
        if definition.fixed_value is None:
            if definition.is_required:
                errors.append(f"Required binding {definition.name!r} has no fixed/admin value.")
            continue
        marker = "{{" + definition.name + "}}"
        if marker not in concrete_question:
            errors.append(
                f"Fixed binding {definition.name!r} requires the exact {marker} placeholder in the template."
            )
            continue
        rendered = _display_binding_value(definition.fixed_value)
        concrete_question = concrete_question.replace(marker, rendered)
        frozen_bindings.append(
            {"name": definition.name, "value": definition.fixed_value, "display_value": rendered}
        )
    return concrete_question, frozen_bindings, errors


def _freeze_conversation_turn(turn):
    """Freeze a scenario turn's exact prompt and static non-secret bindings."""

    concrete_question = turn.prompt_template
    frozen_bindings = []
    errors = []
    for name, value in sorted((turn.static_bindings or {}).items()):
        marker = "{{" + name + "}}"
        if marker not in concrete_question:
            errors.append(f"Static binding {name!r} requires the exact {marker} placeholder in the turn prompt.")
            continue
        rendered = _display_binding_value(value)
        concrete_question = concrete_question.replace(marker, rendered)
        frozen_bindings.append({"name": name, "value": value, "display_value": rendered})
    return concrete_question, frozen_bindings, errors


def _target_snapshot_values(target: EvaluationTarget, revision: TargetRevision):
    return {
        "target": target,
        "target_revision": revision,
        "target_display_name": target.display_name,
        "product_display_name": target.product.display_name,
        "environment_display_name": target.environment.display_name,
        "endpoint": revision.endpoint,
        "adapter_key": revision.adapter_key,
        "adapter_version": revision.adapter_version,
        "credential_reference": revision.credential_reference,
        "classification": revision.classification,
        "supports_runtime_metadata": revision.supports_runtime_metadata,
    }


def _conversation_execution_values(*, run, target_revision, target_snapshot, build_snapshot, attempt, turn, order, baseline_execution=None):
    """Build one immutable turn manifest.

    A controlled replay copies the original submitted prompt and resolved
    binding evidence.  Matching a ScenarioVersion is necessary but not
    sufficient: this retains the precise frozen input actually submitted to
    the baseline target even if future data repairs expose an inconsistency.
    """
    if baseline_execution is not None:
        return (
            Execution(
                run=run,
                question=baseline_execution.question,
                question_version=baseline_execution.question_version,
                conversation_attempt=attempt,
                conversation_turn=turn,
                target_revision=target_revision,
                target_snapshot=target_snapshot,
                build_snapshot=build_snapshot,
                baseline_execution=baseline_execution,
                question_order=order,
                question_stable_id=baseline_execution.question_stable_id,
                question_version_number=baseline_execution.question_version_number,
                question_template=baseline_execution.question_template,
                submitted_question=baseline_execution.submitted_question,
                adapter_key=target_revision.adapter_key,
                adapter_version=target_revision.adapter_version,
                normalizer_key=baseline_execution.normalizer_key,
                normalizer_version=baseline_execution.normalizer_version,
                preflight_error_class=baseline_execution.preflight_error_class,
                preflight_error_detail=baseline_execution.preflight_error_detail,
                comparison_non_comparable_reason=baseline_execution.comparison_non_comparable_reason,
            ),
            [
                {
                    "name": binding.name,
                    "value": binding.value,
                    "display_value": binding.display_value,
                }
                for binding in baseline_execution.resolved_bindings.all().order_by("name")
            ],
        )
    concrete_question, bindings, binding_errors = _freeze_conversation_turn(turn)
    canonical_version = turn.canonical_question_version
    return (
        Execution(
            run=run,
            question=turn.canonical_question,
            question_version=canonical_version,
            conversation_attempt=attempt,
            conversation_turn=turn,
            target_revision=target_revision,
            target_snapshot=target_snapshot,
            build_snapshot=build_snapshot,
            baseline_execution=baseline_execution,
            question_order=order,
            question_stable_id=(turn.canonical_question.stable_id if turn.canonical_question_id else turn.stable_turn_id),
            question_version_number=(canonical_version.version_number if canonical_version else 0),
            question_template=turn.prompt_template,
            submitted_question=concrete_question,
            adapter_key=target_revision.adapter_key,
            adapter_version=target_revision.adapter_version,
            preflight_error_class="BINDING_CONFIGURATION_ERROR" if binding_errors else "",
            preflight_error_detail=" ".join(binding_errors),
        ),
        bindings,
    )


def _create_conversation_run(
    *, actor, target, revision, scenario_version, source_run=None, source_attempt=None,
    baseline=None, baseline_attempt=None, baseline_executions=None, retry_request_key=None
):
    """Persist a complete sequential scenario manifest and one empty session attempt."""

    turns = list(scenario_version.turns.select_related("canonical_question", "canonical_question_version").order_by("ordinal"))
    if not turns:
        raise ValidationError("The selected ScenarioVersion has no ordered turns.")
    run = EvaluationRun.objects.create(
        target=target,
        target_revision=revision,
        launched_by=actor,
        requested_mode=EvaluationRun.ExecutionMode.SEQUENTIAL,
        configured_max_concurrency=revision.max_concurrency,
        actual_concurrency=1,
        question_timeout_seconds=revision.question_timeout_seconds,
        inter_question_delay_seconds=revision.inter_question_delay_seconds,
        total_planned=len(turns),
        selection_filter={
            "conversation_scenario_id": scenario_version.scenario.stable_id,
            "conversation_scenario_version": scenario_version.version_number,
            "shared_session_required": True,
            **({"controlled_baseline_id": str(baseline.pk), "frozen_baseline_inputs": True} if baseline else {}),
        },
        source_run=source_run,
        comparison_baseline=baseline,
        retry_request_key=retry_request_key,
    )
    target_snapshot = TargetSnapshot.objects.create(run=run, **_target_snapshot_values(target, revision))
    build_snapshot = BuildSnapshot.objects.create(
        run=run,
        declared_product_version=revision.declared_product_version,
        declared_build_id=revision.declared_build_id,
        declared_git_sha=revision.declared_git_sha,
    )
    attempt = ConversationAttempt.objects.create(
        run=run,
        scenario_version=scenario_version,
        source_attempt=source_attempt,
        baseline_attempt=baseline_attempt,
    )
    baseline_executions = baseline_executions or {}
    executions = []
    all_bindings = []
    for order, turn in enumerate(turns, start=1):
        execution, bindings = _conversation_execution_values(
            run=run,
            target_revision=revision,
            target_snapshot=target_snapshot,
            build_snapshot=build_snapshot,
            attempt=attempt,
            turn=turn,
            order=order,
            baseline_execution=baseline_executions.get(turn.pk),
        )
        executions.append(execution)
        all_bindings.append(bindings)
    created = Execution.objects.bulk_create(executions)
    binding_rows = []
    for execution, bindings in zip(created, all_bindings, strict=True):
        binding_rows.extend(
            ResolvedBinding(
                execution=execution,
                name=binding["name"],
                resolution_mode=(
                    ResolvedBinding.ResolutionMode.BASELINE_FROZEN if baseline else ResolvedBinding.ResolutionMode.FIXED_ADMIN
                ),
                value=binding["value"],
                display_value=binding["display_value"],
            )
            for binding in bindings
        )
    ResolvedBinding.objects.bulk_create(binding_rows)
    if baseline:
        Comparison.objects.create(
            baseline=baseline,
            current_run=run,
            algorithm_key="exact",
            algorithm_version="exact-v1",
        )
    return run


@transaction.atomic
def launch_conversation_scenario(*, actor, scenario: ConversationScenario, target: EvaluationTarget):
    """Launch one current ACTIVE scenario against a conversation-capable target."""

    require_admin(actor)
    locked_scenario = ConversationScenario.objects.select_for_update().get(pk=scenario.pk)
    if locked_scenario.lifecycle != ConversationScenario.Lifecycle.ACTIVE:
        raise ValidationError("Only ACTIVE conversation scenarios can be launched.")
    scenario_version = locked_scenario.versions.filter(valid_to__isnull=True).first()
    if not scenario_version:
        raise ValidationError("The selected conversation scenario has no current version.")
    locked_target = EvaluationTarget.objects.select_for_update().select_related("product", "environment").get(pk=target.pk)
    revision = locked_target.revisions.filter(valid_to__isnull=True).first()
    if not locked_target.is_active or not revision:
        raise ValidationError("The selected target has no active current revision.")
    if not revision.supports_question_api or not revision.supports_conversation_session:
        raise ValidationError(
            "The selected target revision lacks CONVERSATION_SESSION capability; no independent one-shot substitute was launched."
        )
    return _create_conversation_run(
        actor=actor,
        target=locked_target,
        revision=revision,
        scenario_version=scenario_version,
    )


@transaction.atomic
def launch_run(
    *,
    actor,
    target: EvaluationTarget,
    question_ids: Iterable[int] = (),
    select_all=False,
    filters=None,
    execution_mode: str | None = None,
    source_run: EvaluationRun | None = None,
):
    """Persist the entire immutable manifest before a worker sees any work."""

    require_admin(actor)
    if source_run is not None and not source_run.is_terminal:
        raise ValidationError("Only a completed source run can be rerun.")
    locked_target = EvaluationTarget.objects.select_for_update().select_related(
        "product", "environment"
    ).get(pk=target.pk)
    if not locked_target.is_active:
        raise ValidationError("The selected target is inactive.")
    revision = locked_target.revisions.filter(valid_to__isnull=True).first()
    if not revision:
        raise ValidationError("The selected target has no current revision.")
    if not revision.supports_question_api:
        raise ValidationError("The selected target revision does not declare QUESTION_API capability.")

    requested_mode = execution_mode or revision.default_execution_mode
    if requested_mode not in EvaluationRun.ExecutionMode.values:
        raise ValidationError("The selected execution mode is not supported.")
    actual_concurrency = (
        1
        if requested_mode == EvaluationRun.ExecutionMode.SEQUENTIAL
        else min(revision.max_concurrency, settings.WORKER_MAX_CONCURRENCY)
    )

    filters = {key: value for key, value in (filters or {}).items() if value}
    eligible = _eligible_questions(filters)
    if select_all:
        selected = list(eligible)
    else:
        try:
            requested_ids = {int(value) for value in question_ids}
        except (TypeError, ValueError) as exc:
            raise ValidationError("Selected question identifiers are invalid.") from exc
        if not requested_ids:
            raise ValidationError("Select at least one eligible active single-turn question.")
        selected = list(eligible.filter(pk__in=requested_ids))
        if len(selected) != len(requested_ids):
            raise ValidationError(
                "Only currently ACTIVE single-turn questions with a current version can be launched."
            )
    if not selected:
        raise ValidationError("No eligible active single-turn questions match this launch.")

    run = EvaluationRun.objects.create(
        target=locked_target,
        target_revision=revision,
        launched_by=actor,
        requested_mode=requested_mode,
        configured_max_concurrency=revision.max_concurrency,
        actual_concurrency=actual_concurrency,
        question_timeout_seconds=revision.question_timeout_seconds,
        inter_question_delay_seconds=revision.inter_question_delay_seconds,
        total_planned=len(selected),
        selection_filter={"select_all_matching": bool(select_all), **filters},
        source_run=source_run,
    )
    target_snapshot = TargetSnapshot.objects.create(run=run, **_target_snapshot_values(locked_target, revision))
    build_snapshot = BuildSnapshot.objects.create(
        run=run,
        declared_product_version=revision.declared_product_version,
        declared_build_id=revision.declared_build_id,
        declared_git_sha=revision.declared_git_sha,
    )
    for order, question in enumerate(selected, start=1):
        version = question.current_version
        concrete_question, bindings, binding_errors = _freeze_bindings(version)
        execution = Execution.objects.create(
            run=run,
            question=question,
            question_version=version,
            target_revision=revision,
            target_snapshot=target_snapshot,
            build_snapshot=build_snapshot,
            question_order=order,
            question_stable_id=question.stable_id,
            question_version_number=version.version_number,
            question_template=version.question_text,
            submitted_question=concrete_question,
            adapter_key=revision.adapter_key,
            adapter_version=revision.adapter_version,
            preflight_error_class="BINDING_CONFIGURATION_ERROR" if binding_errors else "",
            preflight_error_detail=" ".join(binding_errors),
        )
        ResolvedBinding.objects.bulk_create(
            [
                ResolvedBinding(
                    execution=execution,
                    name=binding["name"],
                    resolution_mode=ResolvedBinding.ResolutionMode.FIXED_ADMIN,
                    value=binding["value"],
                    display_value=binding["display_value"],
                )
                for binding in bindings
            ]
        )
    return run


def run_progress(run: EvaluationRun) -> dict[str, int]:
    """Derive the UI projection from durable Execution truth, never counters."""

    counts = {
        row["outcome"]: row["count"]
        for row in run.executions.values("outcome").annotate(count=Count("id"))
    }
    pending = counts.get(Execution.Outcome.PENDING, 0)
    running = counts.get(Execution.Outcome.RUNNING, 0)
    success = counts.get(Execution.Outcome.SUCCESS, 0)
    errors = counts.get(Execution.Outcome.ERROR, 0)
    timeout = counts.get(Execution.Outcome.TIMEOUT, 0)
    ended_at = run.completed_at or timezone.now()
    elapsed_seconds = int((ended_at - run.started_at).total_seconds()) if run.started_at else 0
    return {
        "total": run.total_planned,
        "pending": pending,
        "running": running,
        "success": success,
        "error": errors,
        "timeout": timeout,
        "completed": success + errors + timeout,
        "elapsed_seconds": max(0, elapsed_seconds),
    }


def run_review_metrics(run: EvaluationRun) -> dict[str, int]:
    """Return transparent M5 review metrics from the valid quality population.

    INVALID observations remain in the Run and review history, but are excluded
    from the human GOOD/BAD/reviewed/unreviewed quality counters.
    """

    executions = run.executions.all()
    valid = executions.filter(validity=Execution.Validity.VALID)
    return {
        "total": executions.count(),
        "valid": valid.count(),
        "invalid": executions.filter(validity=Execution.Validity.INVALID).count(),
        "human_reviewed": valid.filter(current_human_review__isnull=False).count(),
        "unreviewed": valid.filter(current_human_review__isnull=True).count(),
        "good": valid.filter(current_human_review__judgment=HumanReview.Judgment.GOOD).count(),
        "bad": valid.filter(current_human_review__judgment=HumanReview.Judgment.BAD).count(),
        "review_required": executions.filter(review_state=Execution.ReviewState.REQUIRED).count(),
    }


def baseline_completeness(baseline: Baseline) -> dict[str, int]:
    """Current review/validity projection across a fixed baseline membership.

    The population is fixed at promotion.  Later review or validity events may
    change the displayed current projection, but can never add, remove, or
    replace a member.
    """

    executions = Execution.objects.filter(baseline_memberships__baseline=baseline)
    total = executions.count()
    reviewed = executions.filter(current_human_review__isnull=False).count()
    return {
        "total": total,
        "valid": executions.filter(validity=Execution.Validity.VALID).count(),
        "invalid": executions.filter(validity=Execution.Validity.INVALID).count(),
        "human_reviewed": reviewed,
        "unreviewed": total - reviewed,
        "good": executions.filter(current_human_review__judgment=HumanReview.Judgment.GOOD).count(),
        "bad": executions.filter(current_human_review__judgment=HumanReview.Judgment.BAD).count(),
        "success": executions.filter(outcome=Execution.Outcome.SUCCESS).count(),
        "error": executions.filter(outcome=Execution.Outcome.ERROR).count(),
        "timeout": executions.filter(outcome=Execution.Outcome.TIMEOUT).count(),
    }


@transaction.atomic
def create_baseline(*, actor, source_run: EvaluationRun, name: str, description: str = "", is_active=True):
    """Promote a terminal Run without treating its answers as ground truth."""

    require_admin(actor)
    clean_name = str(name).strip()
    if not clean_name:
        raise ValidationError("A baseline name is required.")
    locked_run = (
        EvaluationRun.objects.select_for_update()
        .select_related("target", "target__product", "target__environment")
        .get(pk=source_run.pk)
    )
    if not locked_run.is_terminal:
        raise ValidationError("Only a completed EvaluationRun can be promoted to a Baseline.")
    source_executions = list(locked_run.executions.order_by("question_order"))
    if not source_executions:
        raise ValidationError("A Baseline requires at least one captured Execution.")
    if not any(
        execution.outcome == Execution.Outcome.SUCCESS
        and execution.validity == Execution.Validity.VALID
        for execution in source_executions
    ):
        raise ValidationError("A Baseline requires at least one usable VALID SUCCESS Execution.")
    baseline = Baseline.objects.create(
        name=clean_name,
        description=description,
        source_run=locked_run,
        source_target=locked_run.target,
        created_by=actor,
        is_active=bool(is_active),
    )
    BaselineMembership.objects.bulk_create(
        [BaselineMembership(baseline=baseline, execution=execution) for execution in source_executions]
    )
    BaselineStateEvent.objects.create(baseline=baseline, is_active=baseline.is_active, actor=actor)
    return baseline


@transaction.atomic
def set_baseline_active(*, actor, baseline: Baseline, is_active: bool):
    """Append active/inactive attribution without touching immutable membership."""

    require_admin(actor)
    locked = Baseline.objects.select_for_update().get(pk=baseline.pk)
    is_active = bool(is_active)
    if locked.is_active == is_active:
        return None
    event = BaselineStateEvent.objects.create(baseline=locked, is_active=is_active, actor=actor)
    Baseline.objects.filter(pk=locked.pk).update(is_active=is_active)
    return event


def _canonical_binding_signature(execution: Execution):
    return tuple(
        (binding.name, json.dumps(binding.value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        for binding in execution.resolved_bindings.order_by("name")
    )


def _controlled_preflight_reason(source: Execution) -> tuple[str, str] | None:
    """Return a conservative reason when fixed historical input cannot replay."""

    if source.validity == Execution.Validity.INVALID:
        return (
            "BASELINE_EXECUTION_INVALID",
            "The fixed baseline Execution is currently INVALID and has no trustworthy comparison answer.",
        )
    if source.preflight_error_class:
        return (
            "FROZEN_BINDING_UNAVAILABLE",
            "The baseline's frozen bindings were not safely executable in its recorded observation; no replacement will be selected.",
        )
    if not source.submitted_question:
        return ("CONCRETE_QUESTION_MISSING", "The baseline observation has no concrete submitted question.")
    if source.outcome != Execution.Outcome.SUCCESS or not source.raw_answer:
        return (
            "BASELINE_NO_USABLE_ANSWER",
            "The baseline observation has no usable SUCCESS answer for answer-change comparison.",
        )
    return None


@transaction.atomic
def launch_controlled_comparison(*, actor, baseline: Baseline, target: EvaluationTarget):
    """Create a new run with current target identity and exact baseline inputs.

    This deliberately bypasses normal current-catalog eligibility: a baseline
    can replay an old or retired QuestionVersion, but it cannot substitute a
    newer QuestionVersion, dynamic object, or rewritten concrete question.
    """

    require_admin(actor)
    locked_baseline = (
        Baseline.objects.select_for_update()
        .select_related("source_run", "source_target", "source_target__product", "source_target__environment")
        .get(pk=baseline.pk)
    )
    if not locked_baseline.is_active:
        raise ValidationError("Only an ACTIVE Baseline may launch a controlled comparison.")
    if ConversationAttempt.objects.filter(run=locked_baseline.source_run).exists():
        return launch_controlled_conversation_comparison(
            actor=actor,
            baseline=locked_baseline,
            target=target,
        )
    locked_target = EvaluationTarget.objects.select_for_update().select_related(
        "product", "environment"
    ).get(pk=target.pk)
    if not locked_target.is_active:
        raise ValidationError("The selected current target is inactive.")
    if (
        locked_target.product_id != locked_baseline.source_target.product_id
        or locked_target.environment_id != locked_baseline.source_target.environment_id
    ):
        raise ValidationError(
            "A controlled comparison target must use the baseline Product and Environment context."
        )
    revision = locked_target.revisions.filter(valid_to__isnull=True).first()
    if not revision or not revision.supports_question_api:
        raise ValidationError("The selected current target has no compatible current question API revision.")
    members = list(
        locked_baseline.memberships.select_related(
            "execution",
            "execution__question",
            "execution__question_version",
        )
        .prefetch_related("execution__resolved_bindings")
        .order_by("execution__question_order")
    )
    if not members:
        raise ValidationError("The Baseline has no captured membership to replay.")
    requested_mode = revision.default_execution_mode
    actual_concurrency = (
        1
        if requested_mode == EvaluationRun.ExecutionMode.SEQUENTIAL
        else min(revision.max_concurrency, settings.WORKER_MAX_CONCURRENCY)
    )
    run = EvaluationRun.objects.create(
        target=locked_target,
        target_revision=revision,
        launched_by=actor,
        requested_mode=requested_mode,
        configured_max_concurrency=revision.max_concurrency,
        actual_concurrency=actual_concurrency,
        question_timeout_seconds=revision.question_timeout_seconds,
        inter_question_delay_seconds=revision.inter_question_delay_seconds,
        total_planned=len(members),
        selection_filter={
            "controlled_baseline_id": str(locked_baseline.pk),
            "frozen_baseline_inputs": True,
        },
        comparison_baseline=locked_baseline,
    )
    target_snapshot = TargetSnapshot.objects.create(run=run, **_target_snapshot_values(locked_target, revision))
    build_snapshot = BuildSnapshot.objects.create(
        run=run,
        declared_product_version=revision.declared_product_version,
        declared_build_id=revision.declared_build_id,
        declared_git_sha=revision.declared_git_sha,
    )
    for order, membership in enumerate(members, start=1):
        source = membership.execution
        preflight = _controlled_preflight_reason(source)
        replay = Execution.objects.create(
            run=run,
            question=source.question,
            question_version=source.question_version,
            target_revision=revision,
            target_snapshot=target_snapshot,
            build_snapshot=build_snapshot,
            baseline_execution=source,
            question_order=order,
            question_stable_id=source.question_stable_id,
            question_version_number=source.question_version_number,
            question_template=source.question_template,
            submitted_question=source.submitted_question,
            adapter_key=revision.adapter_key,
            adapter_version=revision.adapter_version,
            normalizer_key=source.normalizer_key,
            normalizer_version=source.normalizer_version,
            preflight_error_class="COMPARISON_NON_COMPARABLE" if preflight else "",
            preflight_error_detail=preflight[1] if preflight else "",
            comparison_non_comparable_reason=preflight[0] if preflight else "",
        )
        ResolvedBinding.objects.bulk_create(
            [
                ResolvedBinding(
                    execution=replay,
                    name=binding.name,
                    resolution_mode=ResolvedBinding.ResolutionMode.BASELINE_FROZEN,
                    value=binding.value,
                    display_value=binding.display_value,
                )
                for binding in source.resolved_bindings.all()
            ]
        )
    Comparison.objects.create(
        baseline=locked_baseline,
        current_run=run,
        algorithm_key="exact",
        algorithm_version="exact-v1",
    )
    return run


def normalize_exact_answer(value: str) -> str:
    """M6's deliberately shallow, versioned normalization.

    It normalizes line endings and trailing horizontal whitespace only.  It
    never reorders, rewrites, lowercases, strips punctuation, or interprets
    answer facts.
    """

    return exact_operator_answer(display_answer=value, raw_answer="", response_metadata={})


def _exact_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _comparison_non_comparable_reason(baseline_execution: Execution, current_execution: Execution):
    if current_execution.comparison_non_comparable_reason:
        return (
            current_execution.comparison_non_comparable_reason,
            current_execution.preflight_error_detail
            or "The controlled comparison input could not be reproduced safely.",
        )
    preflight = _controlled_preflight_reason(baseline_execution)
    if preflight:
        return preflight
    if current_execution.validity == Execution.Validity.INVALID:
        return (
            "CURRENT_EXECUTION_INVALID",
            "The current observation is INVALID and is excluded from answer-change comparison.",
        )
    if current_execution.outcome != Execution.Outcome.SUCCESS or not current_execution.raw_answer:
        return (
            "CURRENT_NO_USABLE_ANSWER",
            "The current observation has no usable SUCCESS answer for answer-change comparison.",
        )
    if baseline_execution.conversation_turn_id or current_execution.conversation_turn_id:
        if not baseline_execution.conversation_turn_id or not current_execution.conversation_turn_id:
            return ("CONVERSATION_TURN_MISMATCH", "Only one observation belongs to a conversation turn.")
        if baseline_execution.conversation_turn_id != current_execution.conversation_turn_id:
            return ("CONVERSATION_TURN_MISMATCH", "The exact version-bound conversation turn differs.")
        if (
            not baseline_execution.conversation_attempt_id
            or not current_execution.conversation_attempt_id
            or baseline_execution.conversation_attempt.scenario_version_id
            != current_execution.conversation_attempt.scenario_version_id
        ):
            return ("SCENARIO_VERSION_MISMATCH", "The observations do not use the exact same ScenarioVersion.")
        if current_execution.conversation_attempt.baseline_attempt_id != baseline_execution.conversation_attempt_id:
            return (
                "BASELINE_CONVERSATION_ATTEMPT_MISMATCH",
                "The current turn was not launched from the immutable baseline ConversationAttempt.",
            )
        if baseline_execution.submitted_question != current_execution.submitted_question:
            return ("CONCRETE_QUESTION_MISMATCH", "The exact concrete submitted question differs.")
        if _canonical_binding_signature(baseline_execution) != _canonical_binding_signature(current_execution):
            return ("FROZEN_BINDING_MISMATCH", "The exact frozen binding values differ.")
        return None
    if baseline_execution.question_id != current_execution.question_id:
        return ("QUESTION_IDENTITY_MISMATCH", "The stable Question identity differs.")
    if baseline_execution.question_version_id != current_execution.question_version_id:
        return ("QUESTION_VERSION_MISMATCH", "The exact QuestionVersion differs.")
    if baseline_execution.submitted_question != current_execution.submitted_question:
        return ("CONCRETE_QUESTION_MISMATCH", "The exact concrete submitted question differs.")
    if _canonical_binding_signature(baseline_execution) != _canonical_binding_signature(current_execution):
        return ("FROZEN_BINDING_MISMATCH", "The exact frozen binding values differ.")
    return None


@transaction.atomic
def record_exact_comparison(*, current_execution: Execution):
    """Persist one immutable M6 comparison item after a terminal observation."""

    # ``baseline_execution`` and ``current_human_review`` are nullable.  Do
    # not join either while locking: PostgreSQL correctly rejects FOR UPDATE on
    # the nullable side of an outer join.
    current = Execution.objects.select_for_update().select_related("run").get(pk=current_execution.pk)
    if not current.is_terminal or not current.baseline_execution_id:
        return None
    try:
        comparison = Comparison.objects.select_for_update().get(current_run_id=current.run_id)
    except Comparison.DoesNotExist:
        return None
    if ComparisonItem.objects.filter(comparison=comparison, current_execution=current).exists():
        return None
    current_review = HumanReview.objects.filter(pk=current.current_human_review_id).first()
    baseline_execution = (
        Execution.objects.select_related("current_human_review", "question_version", "conversation_attempt")
        .prefetch_related("resolved_bindings")
        .get(pk=current.baseline_execution_id)
    )
    completed_pair = (
        baseline_execution.outcome == Execution.Outcome.SUCCESS
        and current.outcome == Execution.Outcome.SUCCESS
    )
    performance = performance_comparison(
        baseline_execution.latency_ms if completed_pair else None,
        current.latency_ms if completed_pair else None,
    )
    input_delta, input_percent = token_delta(
        baseline_execution.input_tokens if completed_pair else None,
        current.input_tokens if completed_pair else None,
    )
    output_delta, output_percent = token_delta(
        baseline_execution.output_tokens if completed_pair else None,
        current.output_tokens if completed_pair else None,
    )
    total_delta, total_percent = token_delta(
        baseline_execution.total_tokens if completed_pair else None,
        current.total_tokens if completed_pair else None,
    )
    performance_values = {
        "performance_policy_version": PERFORMANCE_POLICY_VERSION,
        "baseline_latency_ms": performance["baseline_latency_ms"],
        "current_latency_ms": performance["current_latency_ms"],
        "latency_delta_ms": performance["latency_delta_ms"],
        "latency_delta_percent": performance["latency_delta_percent"],
        "baseline_performance_classification": performance["baseline_band"] or "",
        "current_performance_classification": performance["current_band"] or "",
        "performance_change": performance["state"],
        "performance_band_degraded": performance["band_degraded"],
        "input_token_delta": input_delta,
        "output_token_delta": output_delta,
        "total_token_delta": total_delta,
        "input_token_delta_percent": input_percent,
        "output_token_delta_percent": output_percent,
        "total_token_delta_percent": total_percent,
    }
    if (
        current.run.comparison_baseline_id != comparison.baseline_id
        or not BaselineMembership.objects.filter(
            baseline_id=comparison.baseline_id,
            execution_id=baseline_execution.pk,
        ).exists()
    ):
        return ComparisonItem.objects.create(
            comparison=comparison,
            baseline_execution=baseline_execution,
            current_execution=current,
            change_state=ComparisonItem.ChangeState.NON_COMPARABLE,
            non_comparable_reason="BASELINE_MEMBERSHIP_MISMATCH",
            detail="The current replay does not reference immutable membership of its selected Baseline.",
            baseline_human_review=baseline_execution.current_human_review,
            current_human_review=current_review,
            **performance_values,
        )
    non_comparable = _comparison_non_comparable_reason(baseline_execution, current)
    if non_comparable:
        reason, detail = non_comparable
        return ComparisonItem.objects.create(
            comparison=comparison,
            baseline_execution=baseline_execution,
            current_execution=current,
            change_state=ComparisonItem.ChangeState.NON_COMPARABLE,
            non_comparable_reason=reason,
            detail=detail,
            baseline_human_review=baseline_execution.current_human_review,
            current_human_review=current_review,
            **performance_values,
        )
    baseline_normalized = exact_operator_answer(
        display_answer=baseline_execution.display_answer,
        raw_answer=baseline_execution.raw_answer,
        response_metadata=baseline_execution.response_metadata,
    )
    current_normalized = exact_operator_answer(
        display_answer=current.display_answer,
        raw_answer=current.raw_answer,
        response_metadata=current.response_metadata,
    )
    exact_equal = baseline_normalized == current_normalized
    item = ComparisonItem.objects.create(
        comparison=comparison,
        baseline_execution=baseline_execution,
        current_execution=current,
        change_state=(
            ComparisonItem.ChangeState.UNCHANGED if exact_equal else ComparisonItem.ChangeState.CHANGED
        ),
        exact_equal=exact_equal,
        baseline_normalized_hash=_exact_hash(baseline_normalized),
        current_normalized_hash=_exact_hash(current_normalized),
        baseline_human_review=baseline_execution.current_human_review,
        current_human_review=current_review,
        **performance_values,
    )
    if not exact_equal and current.review_state != Execution.ReviewState.REVIEWED:
        ReviewTracking.objects.create(
            execution=current,
            state=Execution.ReviewState.REQUIRED,
            actor=None,
            cause=f"Exact comparison {comparison.algorithm_version} CHANGED (comparison item {item.pk})",
        )
        Execution.objects.filter(pk=current.pk).update(review_state=Execution.ReviewState.REQUIRED)
    return item


def _semantic_applicability_reason(item: ComparisonItem) -> str | None:
    """Return why M7 must not interpret this item as a semantic answer pair."""

    baseline = item.baseline_execution
    current = item.current_execution
    if item.change_state != ComparisonItem.ChangeState.CHANGED or item.exact_equal is not False:
        return "Semantic triage applies only to an M6 exact CHANGED pair."
    if baseline.validity != Execution.Validity.VALID or current.validity != Execution.Validity.VALID:
        return "INVALID evidence is excluded from semantic triage."
    if baseline.outcome != Execution.Outcome.SUCCESS or current.outcome != Execution.Outcome.SUCCESS:
        return "Semantic triage requires two successful answer observations."
    if not baseline.raw_answer or not current.raw_answer:
        return "Semantic triage requires two usable captured answers."
    return None


def _semantic_answer(execution: Execution) -> str:
    return semantic_operator_answer(
        display_answer=execution.display_answer,
        raw_answer=execution.raw_answer,
        response_metadata=execution.response_metadata,
    )


def _semantic_input_for_item(item: ComparisonItem) -> SemanticComparatorInput:
    baseline = item.baseline_execution
    current = item.current_execution
    return SemanticComparatorInput(
        question_version_id=baseline.question_version_id,
        question_template=baseline.question_template,
        concrete_question=baseline.submitted_question,
        baseline_bindings=tuple(
            (binding.name, binding.display_value)
            for binding in baseline.resolved_bindings.order_by("name")
        ),
        current_bindings=tuple(
            (binding.name, binding.display_value)
            for binding in current.resolved_bindings.order_by("name")
        ),
        baseline_answer=_semantic_answer(baseline),
        current_answer=_semantic_answer(current),
    )


def _semantic_input_manifest(item: ComparisonItem, comparison_input: SemanticComparatorInput) -> tuple[dict, str]:
    """Persist non-secret references/hashes, not another copy of answer text."""

    manifest = {
        "baseline_execution_id": item.baseline_execution_id,
        "current_execution_id": item.current_execution_id,
        "question_version_id": comparison_input.question_version_id,
        "question_template_hash": _exact_hash(comparison_input.question_template),
        "concrete_question_hash": _exact_hash(comparison_input.concrete_question),
        "baseline_bindings_hash": _exact_hash(
            json.dumps(comparison_input.baseline_bindings, ensure_ascii=False, separators=(",", ":"))
        ),
        "current_bindings_hash": _exact_hash(
            json.dumps(comparison_input.current_bindings, ensure_ascii=False, separators=(",", ":"))
        ),
        "baseline_answer_hash": _exact_hash(comparison_input.baseline_answer),
        "current_answer_hash": _exact_hash(comparison_input.current_answer),
        "exact_algorithm_version": item.comparison.algorithm_version,
    }
    fingerprint = _exact_hash(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    return manifest, fingerprint


def _safe_semantic_text(value, *, limit=2000, redact_values: tuple[str, ...] = ()) -> str:
    """Keep comparator diagnostics bounded and remove secrets/duplicated inputs."""

    text = str(value or "")
    for secret in _runtime_secret_values():
        text = text.replace(secret, "[redacted]")
    # Comparison answers already live immutably on their Executions.  A
    # provider response that echoes either complete input must not become a
    # second answer store in semantic diagnostics or raw structured output.
    for supplied_value in redact_values:
        if supplied_value:
            text = text.replace(supplied_value, "[answer referenced]")
    return text[:limit]


def _safe_semantic_json(value, *, redact_values: tuple[str, ...] = ()):
    """Retain a bounded structured comparator response without answer/secret copies."""

    if isinstance(value, dict):
        return {
            _safe_semantic_text(key, limit=120, redact_values=redact_values): _safe_semantic_json(
                item, redact_values=redact_values
            )
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple)):
        return [_safe_semantic_json(item, redact_values=redact_values) for item in list(value)[:40]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return (
            _safe_semantic_text(value, limit=1000, redact_values=redact_values)
            if isinstance(value, str)
            else value
        )
    return _safe_semantic_text(value, limit=1000, redact_values=redact_values)


# M9 intentionally reuses the same safe-output posture as semantic triage.
# Stored answers/evidence are an observation, not a provider prompt instruction,
# and must not be duplicated verbatim in evaluator diagnostics.
def _safe_evaluation_text(value, *, limit=2000, redact_values: tuple[str, ...] = ()) -> str:
    return _safe_semantic_text(value, limit=limit, redact_values=redact_values)


def _safe_evaluation_json(value, *, redact_values: tuple[str, ...] = ()):
    return _safe_semantic_json(value, redact_values=redact_values)


def _bounded_evaluation_context(value, *, limit=4000):
    """Provide only stored, non-secret evidence needed by an evaluator rubric."""

    if isinstance(value, dict):
        return {
            _safe_evaluation_text(key, limit=120): _bounded_evaluation_context(item, limit=limit)
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_evaluation_context(item, limit=limit) for item in list(value)[:40]]
    if isinstance(value, str):
        return _safe_evaluation_text(value, limit=limit)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _safe_evaluation_text(value, limit=limit)


def _untrusted_context_text_values(value) -> tuple[str, ...]:
    """Collect bounded textual inputs so provider echoes do not become copies."""

    values: list[str] = []

    def visit(item):
        if len(values) >= 80:
            return
        if isinstance(item, dict):
            for key, nested in item.items():
                visit(key)
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)
        elif isinstance(item, str) and item:
            values.append(item)

    visit(value)
    return tuple(values)


def _evaluation_bindings(execution: Execution) -> tuple[tuple[str, str], ...]:
    return tuple(
        (binding.name, binding.display_value)
        for binding in execution.resolved_bindings.order_by("name")
    )


def _stored_answer(execution: Execution) -> str:
    return semantic_operator_answer(
        display_answer=execution.display_answer,
        raw_answer=execution.raw_answer,
        response_metadata=execution.response_metadata,
    )


def _evaluator_input(execution: Execution, configuration: dict | None = None) -> EvaluatorInput:
    version = execution.question_version
    return EvaluatorInput(
        execution_id=execution.pk,
        question_version_id=execution.question_version_id,
        question=execution.submitted_question,
        frozen_bindings=_evaluation_bindings(execution),
        product_answer=_stored_answer(execution),
        evidence=_bounded_evaluation_context(execution.evidence),
        evaluation_guidance=version.evaluation_guidance if version else "",
        configuration=dict(configuration or {}),
    )


def _judge_input(execution: Execution, implementation: LLMJudge, configuration: dict | None = None) -> JudgeInput:
    version = execution.question_version
    return JudgeInput(
        execution_id=execution.pk,
        question_version_id=execution.question_version_id,
        question=execution.submitted_question,
        frozen_bindings=_evaluation_bindings(execution),
        product_answer=_stored_answer(execution),
        evidence=_bounded_evaluation_context(execution.evidence),
        evaluation_guidance=version.evaluation_guidance if version else "",
        rubric_id=implementation.rubric_id,
        rubric_version=implementation.rubric_version,
        configuration=dict(configuration or {}),
    )


def _evaluation_input_manifest(execution: Execution, *, configuration: dict, kind: str) -> tuple[dict, str]:
    """Persist references/hashes only, never a second copy of answer/evidence."""

    evidence_text = json.dumps(_bounded_evaluation_context(execution.evidence), ensure_ascii=False, sort_keys=True)
    bindings = _evaluation_bindings(execution)
    manifest = {
        "execution_id": execution.pk,
        "question_version_id": execution.question_version_id,
        "question_hash": _exact_hash(execution.submitted_question),
        "bindings_hash": _exact_hash(json.dumps(bindings, ensure_ascii=False, separators=(",", ":"))),
        "answer_hash": _exact_hash(_stored_answer(execution)),
        "evidence_hash": _exact_hash(evidence_text),
        "guidance_hash": _exact_hash(execution.question_version.evaluation_guidance if execution.question_version else ""),
        "configuration_hash": _exact_hash(json.dumps(configuration, ensure_ascii=False, sort_keys=True)),
        "kind": kind,
    }
    return manifest, _exact_hash(json.dumps(manifest, sort_keys=True, separators=(",", ":")))


def _result_invocation_id(result) -> int:
    # M5 evidence predates invocation rows.  It remains visible as history but
    # never outranks an M9 result with a durable request sequence.
    return result.invocation_id or 0


def current_judge_result(execution: Execution) -> LLMJudgeResult | None:
    """Current judge projection: highest completed durable request sequence.

    Completion order cannot make a stale Judge v1 current after a requested
    Judge v2 result has completed.  Old M5 envelope rows have no invocation
    and sort behind M9 results while still remaining inspectable.
    """

    history = list(execution.llm_judge_results.all())
    return max(history, key=lambda result: (_result_invocation_id(result), result.created_at, result.pk), default=None)


def current_automated_results(execution: Execution) -> list[AutomatedEvaluationResult]:
    """One current independent projection per evaluator key, plus history elsewhere."""

    selected: dict[str, AutomatedEvaluationResult] = {}
    for result in execution.automated_results.all():
        existing = selected.get(result.evaluator_key)
        if existing is None or (_result_invocation_id(result), result.created_at, result.pk) > (
            _result_invocation_id(existing), existing.created_at, existing.pk
        ):
            selected[result.evaluator_key] = result
    return sorted(selected.values(), key=lambda result: result.evaluator_key)


def judge_disagrees_with_human(execution: Execution, result: LLMJudgeResult | None = None) -> bool:
    """A transparent calibration indicator, not an automatic quality judgment."""

    result = result or current_judge_result(execution)
    review = execution.current_human_review
    if not result or result.status != LLMJudgeResult.Status.COMPLETE or not review:
        return False
    disposition = result.advisory_disposition.strip().upper()
    positive = {"STRONG", "POSITIVE", "GOOD"}
    negative = {"WEAK", "NEGATIVE", "POOR", "BAD"}
    return (review.judgment == HumanReview.Judgment.BAD and disposition in positive) or (
        review.judgment == HumanReview.Judgment.GOOD and disposition in negative
    )


def _validate_judge_dimensions(dimensions: object) -> dict:
    if not isinstance(dimensions, dict) or set(dimensions) != set(JUDGE_DIMENSIONS):
        raise EvaluatorProtocolError("Judge output must contain every approved dimension exactly once.")
    normalized = {}
    for name in JUDGE_DIMENSIONS:
        dimension = dimensions[name]
        if not isinstance(dimension, dict) or not str(dimension.get("result", "")).strip():
            raise EvaluatorProtocolError(f"Judge dimension {name!r} must include a qualitative result.")
        normalized[name] = {
            "result": _safe_evaluation_text(dimension["result"], limit=80),
            "rationale": _safe_evaluation_text(dimension.get("rationale", ""), limit=500),
        }
    return normalized


def _ensure_terminal_evaluation_execution(execution: Execution):
    if not execution.is_terminal:
        raise ValidationError("Stored-answer evaluation is available only after an Execution reaches a terminal outcome.")


@transaction.atomic
def enqueue_evaluator_invocation(
    *,
    actor,
    execution: Execution,
    kind: str,
    implementation: Evaluator | LLMJudge | None = None,
    configuration: dict | None = None,
) -> EvaluationInvocation:
    """Persist M9 evaluation work and return promptly; never create target work."""

    require_admin(actor)
    if kind not in EvaluationInvocation.Kind.values:
        raise ValidationError("The requested evaluation mechanism is not supported.")
    locked = (
        # ``question_version`` is nullable for some historical/conversation
        # observations. PostgreSQL cannot lock the nullable side of that outer
        # join, and M9 only needs to serialize changes to the stored Execution
        # itself before appending analysis work.
        Execution.objects.select_for_update(of=("self",))
        .select_related("question_version")
        .prefetch_related("resolved_bindings")
        .get(pk=execution.pk)
    )
    _ensure_terminal_evaluation_execution(locked)
    configuration = dict(configuration or {})
    manifest, fingerprint = _evaluation_input_manifest(locked, configuration=configuration, kind=kind)
    if kind == EvaluationInvocation.Kind.JUDGE:
        judge = implementation or default_llm_judge()
        invocation = EvaluationInvocation.objects.create(
            execution=locked,
            kind=kind,
            requested_by=actor,
            evaluator_key="llm-judge",
            evaluator_version=judge.judge_version,
            provider=judge.provider,
            model_identifier=judge.model_identifier,
            judge_version=judge.judge_version,
            rubric_id=judge.rubric_id,
            rubric_version=judge.rubric_version,
            prompt_version=judge.rubric_version,
            configuration=configuration,
            input_fingerprint=fingerprint,
        )
    else:
        evaluator = implementation or default_evaluator()
        invocation = EvaluationInvocation.objects.create(
            execution=locked,
            kind=kind,
            requested_by=actor,
            evaluator_key=evaluator.evaluator_key,
            evaluator_version=evaluator.evaluator_version,
            mechanism=evaluator.mechanism,
            configuration=configuration,
            input_fingerprint=fingerprint,
        )
    # The result keeps the complete manifest; the queue only needs its stable
    # fingerprint to prove it refers to this stored observation.
    _ = manifest
    return invocation


@transaction.atomic
def claim_next_evaluation_invocation(worker_id: str | None = None) -> EvaluationInvocationClaim | None:
    """Claim evaluator work without touching product-target concurrency state."""

    worker_id = worker_id or _IN_PROCESS_WORKER_ID
    invocation = (
        EvaluationInvocation.objects.select_for_update(skip_locked=True)
        .filter(state=EvaluationInvocation.State.PENDING)
        .order_by("id")
        .first()
    )
    if invocation is None:
        return None
    token = uuid.uuid4()
    now = _database_now()
    invocation.state = EvaluationInvocation.State.RUNNING
    invocation.worker_id = worker_id
    invocation.claim_token = token
    invocation.claim_attempt += 1
    invocation.started_at = now
    invocation.claim_heartbeat_at = now
    invocation.claim_lease_expires_at = _lease_expiry(now)
    invocation.save(
        update_fields=(
            "state",
            "worker_id",
            "claim_token",
            "claim_attempt",
            "started_at",
            "claim_heartbeat_at",
            "claim_lease_expires_at",
        )
    )
    return EvaluationInvocationClaim(invocation.pk, worker_id, token)


def refresh_evaluation_invocation_lease(claim: EvaluationInvocationClaim) -> bool:
    """Heartbeat slow provider work without interacting with target work state."""

    with transaction.atomic():
        now = _database_now()
        return (
            EvaluationInvocation.objects.filter(
                pk=claim.invocation_id,
                state=EvaluationInvocation.State.RUNNING,
                worker_id=claim.worker_id,
                claim_token=claim.token,
            ).update(claim_heartbeat_at=now, claim_lease_expires_at=_lease_expiry(now))
            == 1
        )


class _EvaluationInvocationHeartbeat:
    def __init__(self, claim: EvaluationInvocationClaim):
        self.claim = claim
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._stopped.set()
        self._thread.join(timeout=settings.WORKER_HEARTBEAT_SECONDS + 1)

    def _run(self):
        while not self._stopped.wait(settings.WORKER_HEARTBEAT_SECONDS):
            if not refresh_evaluation_invocation_lease(self.claim):
                logger.warning("worker evaluator invocation ownership lost invocation_id=%s", self.claim.invocation_id)
                return


@transaction.atomic
def reconcile_stale_evaluation_invocations() -> int:
    """Requeue expired M9 analysis work; no product request can be duplicated."""

    now = _database_now()
    stale = list(
        EvaluationInvocation.objects.select_for_update(skip_locked=True).filter(
            state=EvaluationInvocation.State.RUNNING,
            claim_lease_expires_at__lte=now,
        )
    )
    for invocation in stale:
        invocation.state = EvaluationInvocation.State.PENDING
        invocation.worker_id = ""
        invocation.claim_token = None
        invocation.claim_heartbeat_at = None
        invocation.claim_lease_expires_at = None
        invocation.started_at = None
        invocation.save(
            update_fields=(
                "state",
                "worker_id",
                "claim_token",
                "claim_heartbeat_at",
                "claim_lease_expires_at",
                "started_at",
            )
        )
    return len(stale)


def _prior_current_judge(execution: Execution) -> LLMJudgeResult | None:
    return current_judge_result(execution)


def _prior_current_evaluator(execution: Execution, evaluator_key: str) -> AutomatedEvaluationResult | None:
    return next((result for result in current_automated_results(execution) if result.evaluator_key == evaluator_key), None)


def _append_evaluator_result(
    *, invocation: EvaluationInvocation, claim: EvaluationInvocationClaim, implementation: Evaluator
) -> AutomatedEvaluationResult | None:
    """Run one evaluator outside a transaction, then append protected result evidence."""

    execution = (
        Execution.objects.select_related("question_version")
        .prefetch_related("resolved_bindings")
        .get(pk=invocation.execution_id)
    )
    evaluator_input = _evaluator_input(execution, invocation.configuration)
    manifest, fingerprint = _evaluation_input_manifest(
        execution, configuration=invocation.configuration, kind=EvaluationInvocation.Kind.EVALUATOR
    )
    started = time.monotonic()
    input_values = (
        evaluator_input.question,
        evaluator_input.product_answer,
        evaluator_input.evaluation_guidance,
        *_untrusted_context_text_values(evaluator_input.evidence),
    )
    try:
        response = implementation.evaluate(evaluator_input)
        if not isinstance(response, EvaluatorResponse):
            raise EvaluatorProtocolError()
        if not response.applicable:
            status, outcome = AutomatedEvaluationResult.Status.NOT_APPLICABLE, ""
        elif response.outcome not in AutomatedEvaluationResult.Outcome.values:
            raise EvaluatorProtocolError(f"Unsupported evaluator outcome {response.outcome!r}.")
        else:
            status, outcome = AutomatedEvaluationResult.Status.COMPLETE, response.outcome
        details = _safe_evaluation_json(response.details, redact_values=input_values)
        raw_result = _safe_evaluation_json(response.raw_result, redact_values=input_values)
        error_class = error_detail = ""
    except EvaluatorFailure as error:
        status, outcome = AutomatedEvaluationResult.Status.ERROR, ""
        details, raw_result = {}, {}
        error_class = _safe_evaluation_text(error.error_class, limit=100)
        error_detail = _safe_evaluation_text(error.detail, redact_values=input_values)
    except Exception:
        logger.warning("Evaluator failed unexpectedly for invocation %s", invocation.pk)
        status, outcome = AutomatedEvaluationResult.Status.ERROR, ""
        details, raw_result = {}, {}
        error_class = "EVALUATOR_INTERNAL_ERROR"
        error_detail = "Evaluator failed unexpectedly; the product observation remains unchanged."
    elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
    with transaction.atomic():
        locked_invocation = EvaluationInvocation.objects.select_for_update().get(pk=invocation.pk)
        if (
            locked_invocation.state != EvaluationInvocation.State.RUNNING
            or locked_invocation.worker_id != claim.worker_id
            or locked_invocation.claim_token != claim.token
        ):
            # A lease recovery assigned this stored-only analysis to a new
            # worker.  This stale completion may not append duplicate evidence
            # or displace the newer current projection.
            return None
        locked_execution = Execution.objects.select_for_update().get(pk=invocation.execution_id)
        prior = _prior_current_evaluator(locked_execution, implementation.evaluator_key)
        supersedes = prior if prior and locked_invocation.pk > _result_invocation_id(prior) else None
        result = AutomatedEvaluationResult.objects.create(
            execution=locked_execution,
            evaluator_key=_safe_evaluation_text(implementation.evaluator_key, limit=100),
            evaluator_version=_safe_evaluation_text(implementation.evaluator_version, limit=80),
            mechanism=_safe_evaluation_text(implementation.mechanism, limit=32),
            configuration_version=_safe_evaluation_text(
                str(locked_invocation.configuration.get("configuration_version", "m9-v1")), limit=80
            ),
            status=status,
            outcome=outcome,
            details=details,
            input_fingerprint=fingerprint,
            input_manifest=manifest,
            raw_result=raw_result,
            error_class=error_class,
            error_detail=error_detail,
            latency_ms=elapsed_ms,
            invocation=locked_invocation,
            supersedes=supersedes,
        )
        locked_invocation.state = EvaluationInvocation.State.COMPLETED
        locked_invocation.completed_at = _database_now()
        locked_invocation.claim_heartbeat_at = None
        locked_invocation.claim_lease_expires_at = None
        locked_invocation.result_error_class = error_class
        locked_invocation.result_error_detail = error_detail
        locked_invocation.save(
            update_fields=(
                "state",
                "completed_at",
                "claim_heartbeat_at",
                "claim_lease_expires_at",
                "result_error_class",
                "result_error_detail",
            )
        )
    return result


def _append_judge_result(
    *, invocation: EvaluationInvocation, claim: EvaluationInvocationClaim, implementation: LLMJudge
) -> LLMJudgeResult | None:
    """Run an advisory judge against stored content and append independent evidence."""

    execution = (
        Execution.objects.select_related("question_version")
        .prefetch_related("resolved_bindings")
        .get(pk=invocation.execution_id)
    )
    judge_input = _judge_input(execution, implementation, invocation.configuration)
    manifest, fingerprint = _evaluation_input_manifest(
        execution, configuration=invocation.configuration, kind=EvaluationInvocation.Kind.JUDGE
    )
    started = time.monotonic()
    input_values = (
        judge_input.question,
        judge_input.product_answer,
        judge_input.evaluation_guidance,
        *_untrusted_context_text_values(judge_input.evidence),
    )
    try:
        response = implementation.judge(judge_input)
        if not isinstance(response, JudgeResponse):
            raise EvaluatorProtocolError("The judge returned an unsupported structured result.")
        dimensions = _validate_judge_dimensions(response.dimensions)
        status = LLMJudgeResult.Status.COMPLETE
        rationale = _safe_evaluation_text(response.rationale, redact_values=input_values)
        advisory_disposition = _safe_evaluation_text(response.advisory_disposition, limit=80)
        details = {"schema": "judge-dimensions-v1"}
        raw_result = _safe_evaluation_json(response.raw_result, redact_values=input_values)
        provider_metadata = _safe_evaluation_json(response.provider_metadata, redact_values=input_values)
        error_class = error_detail = ""
    except EvaluatorFailure as error:
        status, dimensions, rationale, advisory_disposition = LLMJudgeResult.Status.ERROR, {}, "", ""
        details, raw_result, provider_metadata = {}, {}, {}
        error_class = _safe_evaluation_text(error.error_class, limit=100)
        error_detail = _safe_evaluation_text(error.detail, redact_values=input_values)
    except Exception:
        logger.warning("LLM judge failed unexpectedly for invocation %s", invocation.pk)
        status, dimensions, rationale, advisory_disposition = LLMJudgeResult.Status.ERROR, {}, "", ""
        details, raw_result, provider_metadata = {}, {}, {}
        error_class = "JUDGE_INTERNAL_ERROR"
        error_detail = "LLM judge failed unexpectedly; the product observation remains unchanged."
    elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
    with transaction.atomic():
        locked_invocation = EvaluationInvocation.objects.select_for_update().get(pk=invocation.pk)
        if (
            locked_invocation.state != EvaluationInvocation.State.RUNNING
            or locked_invocation.worker_id != claim.worker_id
            or locked_invocation.claim_token != claim.token
        ):
            return None
        locked_execution = Execution.objects.select_for_update().get(pk=invocation.execution_id)
        prior = _prior_current_judge(locked_execution)
        supersedes = prior if prior and locked_invocation.pk > _result_invocation_id(prior) else None
        result = LLMJudgeResult.objects.create(
            execution=locked_execution,
            provider=_safe_evaluation_text(implementation.provider, limit=100),
            model_identifier=_safe_evaluation_text(implementation.model_identifier, limit=160),
            judge_version=_safe_evaluation_text(implementation.judge_version, limit=80),
            rubric_id=_safe_evaluation_text(implementation.rubric_id, limit=100),
            rubric_version=_safe_evaluation_text(implementation.rubric_version, limit=80),
            prompt_version=_safe_evaluation_text(implementation.rubric_version, limit=80),
            status=status,
            dimensions=dimensions,
            rationale=rationale,
            advisory_disposition=advisory_disposition,
            details=details,
            input_fingerprint=fingerprint,
            input_manifest=manifest,
            raw_result=raw_result,
            provider_metadata=provider_metadata,
            error_class=error_class,
            error_detail=error_detail,
            latency_ms=elapsed_ms,
            invocation=locked_invocation,
            supersedes=supersedes,
        )
        locked_invocation.state = EvaluationInvocation.State.COMPLETED
        locked_invocation.completed_at = _database_now()
        locked_invocation.claim_heartbeat_at = None
        locked_invocation.claim_lease_expires_at = None
        locked_invocation.result_error_class = error_class
        locked_invocation.result_error_detail = error_detail
        locked_invocation.save(
            update_fields=(
                "state",
                "completed_at",
                "claim_heartbeat_at",
                "claim_lease_expires_at",
                "result_error_class",
                "result_error_detail",
            )
        )
    return result


def process_evaluation_invocation(
    claim: EvaluationInvocationClaim,
    *,
    evaluator: Evaluator | None = None,
    judge: LLMJudge | None = None,
):
    """Process one claimed M9 job; it has no target adapter interaction."""

    invocation = EvaluationInvocation.objects.get(pk=claim.invocation_id)
    if (
        invocation.state != EvaluationInvocation.State.RUNNING
        or invocation.worker_id != claim.worker_id
        or invocation.claim_token != claim.token
    ):
        return None
    if invocation.kind == EvaluationInvocation.Kind.JUDGE:
        with _EvaluationInvocationHeartbeat(claim):
            return _append_judge_result(
                invocation=invocation,
                claim=claim,
                implementation=judge or default_llm_judge(),
            )
    with _EvaluationInvocationHeartbeat(claim):
        return _append_evaluator_result(
            invocation=invocation,
            claim=claim,
            implementation=evaluator or default_evaluator(),
        )


def process_next_evaluation_invocation(
    worker_id: str | None = None,
    *,
    evaluator: Evaluator | None = None,
    judge: LLMJudge | None = None,
):
    claim = claim_next_evaluation_invocation(worker_id)
    if claim is None:
        return False
    process_evaluation_invocation(claim, evaluator=evaluator, judge=judge)
    return True


def reevaluate_stored_answer(
    *,
    actor,
    execution: Execution,
    evaluator: Evaluator | None = None,
    judge: LLMJudge | None = None,
    configuration: dict | None = None,
):
    """ADMIN-only immediate service path used by deterministic acceptance.

    It still creates and claims the durable M9 invocation row first.  Tests can
    inject a deterministic provider while production browser POSTs only enqueue
    work for the worker, so neither path creates a new Run, Execution, or
    target request.
    """

    if (evaluator is None) == (judge is None):
        raise ValidationError("Select exactly one evaluator or LLM judge implementation.")
    kind = EvaluationInvocation.Kind.JUDGE if judge is not None else EvaluationInvocation.Kind.EVALUATOR
    invocation = enqueue_evaluator_invocation(
        actor=actor,
        execution=execution,
        kind=kind,
        implementation=judge or evaluator,
        configuration=configuration,
    )
    claim = claim_next_evaluation_invocation(_IN_PROCESS_WORKER_ID)
    if claim is None or claim.invocation_id != invocation.pk:  # pragma: no cover - queue integrity guard
        raise RuntimeError("The newly created evaluation invocation could not be claimed.")
    return process_evaluation_invocation(claim, evaluator=evaluator, judge=judge)


def _current_semantic_result(item: ComparisonItem) -> SemanticComparisonResult | None:
    """Return the append-only chain leaf selected as current semantic triage."""

    superseded_ids = SemanticComparisonResult.objects.filter(
        comparison_item=item,
        supersedes__isnull=False,
    ).values("supersedes_id")
    return (
        SemanticComparisonResult.objects.filter(comparison_item=item)
        .exclude(pk__in=Subquery(superseded_ids))
        .order_by("-created_at", "-id")
        .first()
    )


def _system_set_review_state(execution: Execution, state: str, cause: str):
    """Append a system review transition without fabricating a human judgment."""

    ReviewTracking.objects.create(execution=execution, state=state, actor=None, cause=cause)
    Execution.objects.filter(pk=execution.pk).update(review_state=state)
    execution.review_state = state


def _is_exact_change_only_requirement(execution: Execution) -> bool:
    latest = execution.review_tracking_events.order_by("-created_at", "-id").first()
    return bool(
        execution.review_state == Execution.ReviewState.REQUIRED
        and latest
        and latest.actor_id is None
        and latest.cause.startswith("Exact comparison ")
        and " CHANGED (comparison item " in latest.cause
    )


def _apply_semantic_triage(result: SemanticComparisonResult, current_execution: Execution):
    """Project M7 attention conservatively while preserving human precedence."""

    if result.outcome == SemanticComparisonResult.Outcome.EQUIVALENT:
        if _is_exact_change_only_requirement(current_execution):
            _system_set_review_state(
                current_execution,
                Execution.ReviewState.NONE,
                f"Semantic comparison {result.comparator_version} EQUIVALENT "
                f"(semantic result {result.pk}) resolved exact-change-only review",
            )
        return
    if current_execution.review_state == Execution.ReviewState.NONE:
        _system_set_review_state(
            current_execution,
            Execution.ReviewState.REQUIRED,
            f"Semantic comparison {result.comparator_version} {result.outcome} "
            f"(semantic result {result.pk}) requires review",
        )


@transaction.atomic
def record_semantic_comparison(
    *,
    comparison_item: ComparisonItem,
    comparator: SemanticComparator | None = None,
) -> SemanticComparisonResult | None:
    """Append semantic triage after M6 exact CHANGED without changing M6 evidence.

    The item lock serializes re-evaluation.  A new result points to the prior
    unsuperseded result, so an older comparator result can never become current
    again after a later re-evaluation.
    """

    item = (
        ComparisonItem.objects.select_for_update()
        .select_related("comparison", "baseline_execution", "current_execution")
        .prefetch_related(
            "baseline_execution__resolved_bindings",
            "current_execution__resolved_bindings",
            "current_execution__review_tracking_events",
        )
        .get(pk=comparison_item.pk)
    )
    if _semantic_applicability_reason(item):
        return None
    comparison_input = _semantic_input_for_item(item)
    manifest, fingerprint = _semantic_input_manifest(item, comparison_input)
    implementation = comparator or default_semantic_comparator()
    prior = _current_semantic_result(item)
    started = time.monotonic()
    input_answers = (comparison_input.baseline_answer, comparison_input.current_answer)
    try:
        response = implementation.compare(comparison_input)
        if not isinstance(response, SemanticComparatorResponse):
            raise SemanticComparatorProtocolError()
        if response.outcome not in SemanticComparisonResult.Outcome.values:
            raise SemanticComparatorProtocolError(
                f"Unsupported semantic comparator outcome {response.outcome!r}."
            )
        outcome = response.outcome
        rationale = _safe_semantic_text(response.rationale, redact_values=input_answers)
        error_class = _safe_semantic_text(response.error_class, limit=100)
        error_detail = _safe_semantic_text(response.error_detail, redact_values=input_answers)
        raw_result = _safe_semantic_json(response.raw_result, redact_values=input_answers)
    except SemanticComparatorFailure as error:
        outcome = SemanticComparisonResult.Outcome.ERROR
        rationale = ""
        error_class = _safe_semantic_text(error.error_class, limit=100)
        error_detail = _safe_semantic_text(error.detail, redact_values=input_answers)
        raw_result = {}
    except Exception:
        # A comparator/provider exception may quote untrusted answer text or
        # transport context.  Do not echo it into ordinary worker logs.
        logger.warning("Semantic comparator failed unexpectedly for comparison item %s", item.pk)
        outcome = SemanticComparisonResult.Outcome.ERROR
        rationale = ""
        error_class = "COMPARATOR_INTERNAL_ERROR"
        error_detail = "Semantic comparator failed unexpectedly; review remains required."
        raw_result = {}
    elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
    result = SemanticComparisonResult.objects.create(
        comparison_item=item,
        supersedes=prior,
        outcome=outcome,
        provider_key=_safe_semantic_text(implementation.provider_key, limit=100),
        model_identifier=_safe_semantic_text(implementation.model_identifier, limit=160),
        comparator_version=_safe_semantic_text(implementation.comparator_version, limit=80),
        prompt_version=_safe_semantic_text(implementation.prompt_version, limit=80),
        input_fingerprint=fingerprint,
        input_manifest=manifest,
        rationale=rationale,
        error_class=error_class,
        error_detail=error_detail,
        raw_result=raw_result,
        latency_ms=elapsed_ms,
    )
    _apply_semantic_triage(result, item.current_execution)
    return result


def reevaluate_semantic_comparison(*, actor, comparison_item: ComparisonItem, comparator: SemanticComparator | None = None):
    """ADMIN-only semantic re-evaluation of stored M6 evidence; no target rerun."""

    require_admin(actor)
    result = record_semantic_comparison(comparison_item=comparison_item, comparator=comparator)
    if result is None:
        # ``comparison_item`` may carry a stale related Execution projection
        # from a caller that has just recorded a validity decision.  Explain
        # the actual persisted inapplicability rather than returning a vague
        # error based on that stale in-memory object.
        current_item = ComparisonItem.objects.select_related(
            "comparison", "baseline_execution", "current_execution"
        ).get(pk=comparison_item.pk)
        raise ValidationError(
            _semantic_applicability_reason(current_item) or "Semantic triage is not applicable."
        )
    return result


def comparison_human_transition(item: ComparisonItem) -> str:
    """Display live human context without turning comparison into correctness."""

    baseline_review = item.baseline_execution.current_human_review
    current_review = item.current_execution.current_human_review
    baseline = baseline_review.judgment if baseline_review else "unreviewed"
    current = current_review.judgment if current_review else "unreviewed"
    return f"{baseline} → {current}"


def comparison_summary(comparison: Comparison) -> dict[str, int]:
    """Transparent M6 exact and M7 semantic triage counts."""

    items = comparison.items.select_related("current_execution", "baseline_execution")
    current_semantic = SemanticComparisonResult.objects.filter(
        comparison_item__comparison=comparison,
        superseded_by__isnull=True,
    )
    return {
        "total": items.count(),
        # Keep legacy keys as exact M6 counts; M7 never rewrites them.
        "unchanged": items.filter(change_state=ComparisonItem.ChangeState.UNCHANGED).count(),
        "changed": items.filter(change_state=ComparisonItem.ChangeState.CHANGED).count(),
        "non_comparable": items.filter(change_state=ComparisonItem.ChangeState.NON_COMPARABLE).count(),
        "semantic_equivalent": current_semantic.filter(
            outcome=SemanticComparisonResult.Outcome.EQUIVALENT
        ).count(),
        "semantic_changed": current_semantic.filter(
            outcome=SemanticComparisonResult.Outcome.MATERIAL_CHANGE
        ).count(),
        "semantic_uncertain": current_semantic.filter(
            outcome=SemanticComparisonResult.Outcome.UNCERTAIN
        ).count(),
        "semantic_error": current_semantic.filter(
            outcome=SemanticComparisonResult.Outcome.ERROR
        ).count(),
        "semantic_not_run": items.filter(change_state=ComparisonItem.ChangeState.CHANGED)
        .exclude(pk__in=current_semantic.values("comparison_item_id"))
        .count(),
        "error": items.filter(current_execution__outcome=Execution.Outcome.ERROR).count(),
        "timeout": items.filter(current_execution__outcome=Execution.Outcome.TIMEOUT).count(),
        "pending_review": items.filter(current_execution__review_state=Execution.ReviewState.REQUIRED).count(),
        "good_to_bad": items.filter(
            baseline_execution__current_human_review__judgment=HumanReview.Judgment.GOOD,
            current_execution__current_human_review__judgment=HumanReview.Judgment.BAD,
        ).count(),
        "bad_to_good": items.filter(
            baseline_execution__current_human_review__judgment=HumanReview.Judgment.BAD,
            current_execution__current_human_review__judgment=HumanReview.Judgment.GOOD,
        ).count(),
    }


def _runtime_secret_values() -> tuple[str, ...]:
    """Known runtime credentials must never be persisted in reviewer text."""

    return tuple(
        value
        for name, value in os.environ.items()
        if name.startswith("STEWARD_BENCH_TARGET_CREDENTIAL_") and value
    )


def _validate_comment_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValidationError("A non-empty comment is required.")
    if any(secret in text for secret in _runtime_secret_values()):
        raise ValidationError("Comments must not contain a configured runtime credential.")
    return text


def append_run_comment(*, actor, run: EvaluationRun, text: str) -> Comment:
    require_admin(actor)
    _validate_comment_text(text)
    return Comment.objects.create(run=run, author=actor, text=text)


def append_execution_comment(*, actor, execution: Execution, text: str) -> Comment:
    require_admin(actor)
    _validate_comment_text(text)
    return Comment.objects.create(execution=execution, author=actor, text=text)


def _require_terminal_for_review(execution: Execution):
    if not execution.is_terminal:
        raise ValidationError("Human review is available only after an Execution reaches a terminal outcome.")


@transaction.atomic
def set_review_state(*, actor, execution: Execution, state: str, cause: str = "") -> ReviewTracking | None:
    """Append an attributed review-state event and update only its projection."""

    require_admin(actor)
    if state not in Execution.ReviewState.values:
        raise ValidationError("The requested review state is not supported.")
    locked = Execution.objects.select_for_update().get(pk=execution.pk)
    _require_terminal_for_review(locked)
    if locked.review_state == state:
        return None
    event = ReviewTracking.objects.create(
        execution=locked,
        state=state,
        actor=actor,
        cause=cause,
    )
    # ``review_state`` is an M5 projection, not captured target evidence.  The
    # terminal Execution model deliberately rejects ``save()`` to protect the
    # observation, so projections are updated only in this service transaction.
    Execution.objects.filter(pk=locked.pk).update(review_state=state)
    locked.review_state = state
    return event


def mark_review_required(*, actor, execution: Execution, cause: str = "Manual review required"):
    return set_review_state(
        actor=actor,
        execution=execution,
        state=Execution.ReviewState.REQUIRED,
        cause=cause,
    )


def mark_reviewed_without_judgment(*, actor, execution: Execution, comment_text: str = ""):
    """Triage a terminal infrastructure outcome without fabricating GOOD/BAD."""

    require_admin(actor)
    if execution.outcome not in {Execution.Outcome.ERROR, Execution.Outcome.TIMEOUT}:
        raise ValidationError(
            "Judgmentless REVIEWED triage is only available for terminal ERROR or TIMEOUT observations."
        )
    comment = append_execution_comment(actor=actor, execution=execution, text=comment_text) if comment_text else None
    event = set_review_state(
        actor=actor,
        execution=execution,
        state=Execution.ReviewState.REVIEWED,
        cause="Infrastructure triage without human judgment",
    )
    return event, comment


@transaction.atomic
def record_human_review(*, actor, execution: Execution, judgment: str, comment_text: str = "") -> HumanReview:
    """Append a GOOD/BAD event and set the current review/judgment projections."""

    require_admin(actor)
    if judgment not in HumanReview.Judgment.values:
        raise ValidationError("Human judgment must be GOOD or BAD.")
    # PostgreSQL cannot lock the nullable outer side created by
    # ``select_related(current_human_review)``.  Locking the Execution itself
    # serializes the current-review projection transition; read the optional
    # prior review separately while that row lock is held.
    locked = Execution.objects.select_for_update().get(pk=execution.pk)
    _require_terminal_for_review(locked)
    comment = None
    if comment_text:
        _validate_comment_text(comment_text)
        comment = Comment.objects.create(execution=locked, author=actor, text=comment_text)
    review = HumanReview.objects.create(
        execution=locked,
        judgment=judgment,
        reviewed_by=actor,
        supersedes=locked.current_human_review,
        comment=comment,
    )
    if locked.review_state != Execution.ReviewState.REVIEWED:
        ReviewTracking.objects.create(
            execution=locked,
            state=Execution.ReviewState.REVIEWED,
            actor=actor,
            cause="Human GOOD/BAD review",
        )
    Execution.objects.filter(pk=locked.pk).update(
        current_human_review=review,
        review_state=Execution.ReviewState.REVIEWED,
    )
    return review


@transaction.atomic
def set_execution_validity(*, actor, execution: Execution, validity: str, comment_text: str = ""):
    """Append an attributed VALID/INVALID decision; never erase the source observation."""

    require_admin(actor)
    if validity not in Execution.Validity.values:
        raise ValidationError("The requested validity state is not supported.")
    locked = Execution.objects.select_for_update().get(pk=execution.pk)
    _require_terminal_for_review(locked)
    if locked.validity == validity:
        return None
    comment = None
    if comment_text:
        _validate_comment_text(comment_text)
        comment = Comment.objects.create(execution=locked, author=actor, text=comment_text)
    previous = locked.validity_history.order_by("-decided_at", "-id").first()
    decision = ExecutionValidityDecision.objects.create(
        execution=locked,
        validity=validity,
        decided_by=actor,
        supersedes=previous,
        comment=comment,
    )
    values = {"validity": validity}
    if validity == Execution.Validity.INVALID:
        values.update({"invalidated_by": actor, "invalidated_at": decision.decided_at})
    else:
        values.update({"invalidated_by": None, "invalidated_at": None})
    Execution.objects.filter(pk=locked.pk).update(**values)
    if validity == Execution.Validity.INVALID:
        memberships = list(
            BaselineMembership.objects.select_related("baseline")
            .filter(execution=locked)
            .order_by("baseline__created_at")
        )
        for membership in memberships:
            baseline = membership.baseline
            detail = (
                f"Baseline member Execution {locked.pk} was marked INVALID; "
                "membership and historical comparisons remain preserved."
            )
            BaselineAttentionEvent.objects.get_or_create(
                baseline=baseline,
                execution=locked,
                defaults={
                    "validity_decision": decision,
                    "actor": actor,
                    "detail": detail,
                },
            )
            if not baseline.requires_attention:
                Baseline.objects.filter(pk=baseline.pk).update(
                    requires_attention=True,
                    attention_opened_at=decision.decided_at,
                    attention_detail=detail,
                )
    return decision


def _create_retry_run(*, actor, source: Execution, retry_request_key: uuid.UUID | None = None) -> EvaluationRun:
    """Create a one-item exact replay of a terminal source Execution.

    Retry intentionally reuses the source QuestionVersion, concrete submitted
    question, resolved bindings, TargetRevision, and frozen launch policy.  It
    creates fresh snapshots, a fresh request correlation ID, and a new Run so a
    later target call is a distinct historical observation.
    """

    source_run = source.run
    source_target = source.target_snapshot
    run = EvaluationRun.objects.create(
        target=source_run.target,
        target_revision=source.target_revision,
        launched_by=actor,
        requested_mode=source_run.requested_mode,
        configured_max_concurrency=source_run.configured_max_concurrency,
        actual_concurrency=1,
        question_timeout_seconds=source_run.question_timeout_seconds,
        inter_question_delay_seconds=source_run.inter_question_delay_seconds,
        total_planned=1,
        selection_filter={"retry_of_execution": source.pk, "frozen_execution_inputs": True},
        source_run=source_run,
        source_execution=source,
        retry_request_key=retry_request_key,
    )
    target_snapshot = TargetSnapshot.objects.create(
        run=run,
        target=source_target.target,
        target_revision=source_target.target_revision,
        target_display_name=source_target.target_display_name,
        product_display_name=source_target.product_display_name,
        environment_display_name=source_target.environment_display_name,
        endpoint=source_target.endpoint,
        adapter_key=source_target.adapter_key,
        adapter_version=source_target.adapter_version,
        credential_reference=source_target.credential_reference,
        classification=source_target.classification,
        supports_runtime_metadata=source_target.supports_runtime_metadata,
    )
    source_build = source.build_snapshot
    build_snapshot = BuildSnapshot.objects.create(
        run=run,
        declared_product_version=source_build.declared_product_version,
        declared_build_id=source_build.declared_build_id,
        declared_git_sha=source_build.declared_git_sha,
    )
    retry = Execution.objects.create(
        run=run,
        question=source.question,
        question_version=source.question_version,
        target_revision=source.target_revision,
        target_snapshot=target_snapshot,
        build_snapshot=build_snapshot,
        source_execution=source,
        question_order=1,
        question_stable_id=source.question_stable_id,
        question_version_number=source.question_version_number,
        question_template=source.question_template,
        submitted_question=source.submitted_question,
        adapter_key=source.adapter_key,
        adapter_version=source.adapter_version,
        normalizer_key=source.normalizer_key,
        normalizer_version=source.normalizer_version,
        preflight_error_class=source.preflight_error_class,
        preflight_error_detail=source.preflight_error_detail,
    )
    ResolvedBinding.objects.bulk_create(
        [
            ResolvedBinding(
                execution=retry,
                name=binding.name,
                resolution_mode=binding.resolution_mode,
                value=binding.value,
                display_value=binding.display_value,
            )
            for binding in source.resolved_bindings.all()
        ]
    )
    return run


def retry_execution(*, actor, execution: Execution, retry_request_key: uuid.UUID | str | None = None) -> EvaluationRun:
    """Create, but never append to, a deliberate new one-execution retry Run."""

    require_admin(actor)
    if execution.conversation_attempt_id:
        raise ValidationError(
            "A dependent conversation turn cannot be retried independently; retry the complete conversation from turn 1."
        )
    key = None
    if retry_request_key:
        try:
            key = uuid.UUID(str(retry_request_key))
        except (TypeError, ValueError) as exc:
            raise ValidationError("Retry request token is invalid.") from exc
        existing = EvaluationRun.objects.filter(retry_request_key=key).first()
        if existing:
            return existing
    try:
        with transaction.atomic():
            source = (
                # Question and QuestionVersion are nullable for contextual
                # conversation turns.  Lock the immutable source Execution,
                # not nullable joined evidence relations.
                Execution.objects.select_for_update(of=("self",))
                .select_related("run", "target_snapshot", "build_snapshot", "question", "question_version")
                .prefetch_related("resolved_bindings")
                .get(pk=execution.pk)
            )
            _require_terminal_for_review(source)
            return _create_retry_run(actor=actor, source=source, retry_request_key=key)
    except IntegrityError:
        if key:
            return EvaluationRun.objects.get(retry_request_key=key)
        raise


@transaction.atomic
def retry_conversation_attempt(*, actor, attempt: ConversationAttempt, retry_request_key: uuid.UUID | str | None = None):
    """Retry a whole historical conversation in a new Run and fresh target session."""

    require_admin(actor)
    key = None
    if retry_request_key:
        try:
            key = uuid.UUID(str(retry_request_key))
        except (TypeError, ValueError) as exc:
            raise ValidationError("The conversation retry request key is invalid.") from exc
        existing = EvaluationRun.objects.filter(retry_request_key=key).first()
        if existing:
            return existing
    locked = (
        ConversationAttempt.objects.select_for_update()
        .select_related("run", "scenario_version", "run__target", "run__target_revision")
        .get(pk=attempt.pk)
    )
    if not locked.run.is_terminal:
        raise ValidationError("Only a completed conversation Run can be retried.")
    revision = locked.run.target.revisions.filter(valid_to__isnull=True).first()
    if not revision or not revision.supports_question_api or not revision.supports_conversation_session:
        raise ValidationError("The current target does not support the conversation session API required for retry.")
    try:
        # Keep the uniqueness race in a savepoint.  Otherwise an IntegrityError
        # would poison this outer transaction before the idempotent lookup.
        with transaction.atomic():
            return _create_conversation_run(
                actor=actor,
                target=locked.run.target,
                revision=revision,
                scenario_version=locked.scenario_version,
                source_run=locked.run,
                source_attempt=locked,
                retry_request_key=key,
            )
    except IntegrityError:
        if key:
            return EvaluationRun.objects.get(retry_request_key=key)
        raise


@transaction.atomic
def launch_controlled_conversation_comparison(*, actor, baseline: Baseline, target: EvaluationTarget):
    """Replay one baseline scenario version from turn 1 in a fresh session."""

    require_admin(actor)
    locked_baseline = Baseline.objects.select_for_update().select_related("source_run", "source_target").get(pk=baseline.pk)
    if not locked_baseline.is_active:
        raise ValidationError("Only an ACTIVE Baseline may launch a controlled comparison.")
    source_attempt = ConversationAttempt.objects.select_related("scenario_version").filter(run=locked_baseline.source_run).first()
    members = list(
        locked_baseline.memberships.select_related("execution", "execution__conversation_turn").order_by("execution__question_order")
    )
    if not source_attempt or not members or any(member.execution.conversation_attempt_id != source_attempt.pk for member in members):
        raise ValidationError("A controlled conversation comparison requires one complete historical ConversationAttempt.")
    turns = list(source_attempt.scenario_version.turns.order_by("ordinal"))
    if len(turns) != len(members):
        raise ValidationError("The baseline conversation membership is incomplete and cannot be replayed safely.")
    baseline_executions = {member.execution.conversation_turn_id: member.execution for member in members}
    if set(baseline_executions) != {turn.pk for turn in turns}:
        raise ValidationError("The baseline conversation turns do not exactly match its ScenarioVersion.")
    locked_target = EvaluationTarget.objects.select_for_update().select_related("product", "environment").get(pk=target.pk)
    if not locked_target.is_active:
        raise ValidationError("The selected current target is inactive.")
    if (
        locked_target.product_id != locked_baseline.source_target.product_id
        or locked_target.environment_id != locked_baseline.source_target.environment_id
    ):
        raise ValidationError("A controlled comparison target must use the baseline Product and Environment context.")
    revision = locked_target.revisions.filter(valid_to__isnull=True).first()
    if not revision or not revision.supports_question_api or not revision.supports_conversation_session:
        raise ValidationError("The selected target has no compatible current conversation session API revision.")
    return _create_conversation_run(
        actor=actor,
        target=locked_target,
        revision=revision,
        scenario_version=source_attempt.scenario_version,
        baseline=locked_baseline,
        baseline_attempt=source_attempt,
        baseline_executions=baseline_executions,
    )


@transaction.atomic
def rerun_source_run(
    *,
    actor,
    source_run: EvaluationRun,
    source_execution_ids: Iterable[int] | None = None,
) -> EvaluationRun:
    """Create a normal independently-frozen run from selected/all source items.

    Unlike retry, rerun follows normal current launch semantics for the source
    selection: only source Questions still eligible for a normal run are used,
    and ``launch_run`` freezes the current QuestionVersion/bindings/target
    revision afresh.  Existing comments and reviews are deliberately not copied.
    """

    require_admin(actor)
    locked_run = EvaluationRun.objects.select_for_update().get(pk=source_run.pk)
    if not locked_run.is_terminal:
        raise ValidationError("Only a completed Run can be rerun.")
    if hasattr(locked_run, "conversation_attempt"):
        raise ValidationError("Conversation scenarios are retried as a complete conversation from turn 1.")
    source_executions = locked_run.executions.order_by("question_order")
    if source_execution_ids is not None:
        requested = {int(value) for value in source_execution_ids}
        selected_source = list(source_executions.filter(pk__in=requested))
        if not requested or len(selected_source) != len(requested):
            raise ValidationError("Select one or more Executions from the completed source Run.")
    else:
        selected_source = list(source_executions)
    source_question_ids = {item.question_id for item in selected_source}
    eligible_ids = list(_eligible_questions().filter(pk__in=source_question_ids).values_list("pk", flat=True))
    if not eligible_ids:
        raise ValidationError("No selected source Questions are currently eligible for a normal rerun.")
    if source_execution_ids is not None and len(eligible_ids) != len(source_question_ids):
        raise ValidationError("Every selected source Question must still be eligible for a normal rerun.")
    return launch_run(
        actor=actor,
        target=locked_run.target,
        question_ids=eligible_ids,
        source_run=locked_run,
    )


def _set_run_started(run: EvaluationRun, now):
    if run.state == EvaluationRun.State.PENDING:
        run.state = EvaluationRun.State.RUNNING
        run.started_at = now
        run.save(update_fields=("state", "started_at"))


def _finalize_run_if_complete(run: EvaluationRun, now):
    counts = run_progress(run)
    if counts["pending"] or counts["running"]:
        return run
    run.state = (
        EvaluationRun.State.COMPLETED_WITH_ERRORS
        if counts["error"] or counts["timeout"]
        else EvaluationRun.State.COMPLETED
    )
    run.completed_at = now
    run.next_dispatch_at = None
    run.save(update_fields=("state", "completed_at", "next_dispatch_at"))
    return run


def _active_claims(queryset, now):
    return queryset.filter(
        outcome=Execution.Outcome.RUNNING,
        target_call_phase__in=(
            Execution.TargetCallPhase.CLAIMED,
            Execution.TargetCallPhase.SUBMISSION_STARTED,
        ),
        claim_lease_expires_at__gt=now,
    )


def _clear_safe_claim(execution: Execution):
    execution.outcome = Execution.Outcome.PENDING
    execution.claim_worker_id = ""
    execution.claim_token = None
    execution.claimed_at = None
    execution.claim_lease_expires_at = None
    execution.claim_heartbeat_at = None
    execution.target_call_phase = Execution.TargetCallPhase.NONE
    execution.started_at = None
    execution.save(
        update_fields=(
            "outcome",
            "claim_worker_id",
            "claim_token",
            "claimed_at",
            "claim_lease_expires_at",
            "claim_heartbeat_at",
            "target_call_phase",
            "started_at",
        )
    )


def _finalize_locked_execution(execution: Execution, *, outcome, values, now):
    """Persist a terminal observation while the caller owns its row lock."""

    for field, value in values.items():
        setattr(execution, field, value)
    execution.outcome = outcome
    execution.target_call_phase = Execution.TargetCallPhase.TERMINAL
    execution.completed_at = now
    if execution.started_at:
        execution.latency_ms = max(0, int((now - execution.started_at).total_seconds() * 1000))
    execution.performance_policy_version = PERFORMANCE_POLICY_VERSION
    execution.performance_classification = (
        classify_latency(execution.latency_ms) if outcome == Execution.Outcome.SUCCESS else ""
    ) or ""
    execution.save()


@transaction.atomic
def reconcile_stale_claims():
    """Recover only unstarted claims; finalize potentially submitted ones safely."""

    now = _database_now()
    stale = list(
        Execution.objects.select_for_update(skip_locked=True)
        .select_related("run")
        .filter(outcome=Execution.Outcome.RUNNING)
        .filter(
            Q(target_call_phase__in=(Execution.TargetCallPhase.NONE, Execution.TargetCallPhase.LEGACY_UNKNOWN))
            | Q(claim_lease_expires_at__lte=now)
        )
        .order_by("run__created_at", "question_order")
    )
    safe_reclaimed = 0
    ambiguous = 0
    finalized_runs = set()
    for execution in stale:
        if execution.target_call_phase == Execution.TargetCallPhase.CLAIMED:
            _clear_safe_claim(execution)
            safe_reclaimed += 1
            continue
        _finalize_locked_execution(
            execution,
            outcome=Execution.Outcome.ERROR,
            now=now,
            values={
                "error_class": "AMBIGUOUS_INFRASTRUCTURE",
                "error_detail": (
                    "Worker ownership became stale after target submission may have started; "
                    "remote completion is unknown and StewardBench will not resubmit it."
                ),
            },
        )
        if execution.conversation_attempt_id:
            # A worker that died after the durable submission boundary cannot
            # establish whether the target session remains a trustworthy
            # continuation point.  Do not submit later dependent turns or
            # silently create a replacement session.
            _mark_conversation_session_unusable(
                execution_id=execution.pk,
                error_class="AMBIGUOUS_INFRASTRUCTURE",
                detail=(
                    "Worker ownership became stale after target submission may have started; "
                    "shared-session continuity is unknown."
                ),
            )
        else:
            finalized_runs.add(execution.run_id)
        ambiguous += 1
    for run_id in finalized_runs:
        run = EvaluationRun.objects.select_for_update().get(pk=run_id)
        _finalize_run_if_complete(run, now)
    return {"safe_reclaimed": safe_reclaimed, "ambiguous": ambiguous}


def recover_interrupted_executions():
    """M3-compatible entry point now backed by M4 phase-aware reconciliation."""

    result = reconcile_stale_claims()
    return result["safe_reclaimed"] + result["ambiguous"]


@transaction.atomic
def claim_next_execution(worker_id: str | None = None):
    """Claim one eligible row. No database lock survives this function."""

    worker_id = worker_id or _IN_PROCESS_WORKER_ID
    if not worker_id:
        raise ValueError("A worker identity is required to claim execution work.")
    now = _database_now()
    candidates = list(
        # Conversation relationships are intentionally nullable so M3--M7
        # one-question executions retain their historical shape. PostgreSQL
        # cannot lock the nullable side of the LEFT JOIN introduced by
        # select_related below, so lock only the durable Execution work row.
        # The Run, ConversationAttempt, and TargetRevision are each locked
        # explicitly before their mutable dispatch state is inspected.
        Execution.objects.select_for_update(of=("self",), skip_locked=True)
        .select_related("run", "conversation_attempt", "conversation_turn")
        .filter(
            outcome=Execution.Outcome.PENDING,
            run__state__in=(EvaluationRun.State.PENDING, EvaluationRun.State.RUNNING),
        )
        .filter(Q(run__next_dispatch_at__isnull=True) | Q(run__next_dispatch_at__lte=now))
        .order_by("run__created_at", "question_order")
    )
    for execution in candidates:
        run = EvaluationRun.objects.select_for_update().get(pk=execution.run_id)
        if run.is_terminal or (run.next_dispatch_at and run.next_dispatch_at > now):
            continue
        if execution.conversation_attempt_id:
            attempt = ConversationAttempt.objects.select_for_update().get(pk=execution.conversation_attempt_id)
            if attempt.session_state == ConversationAttempt.SessionState.UNUSABLE:
                # A terminal blocker is created when continuity becomes
                # unusable.  This guard protects a concurrent/stale picker
                # from ever treating a dependent turn as an independent call.
                continue
            prior_is_active = Execution.objects.filter(
                conversation_attempt_id=attempt.pk,
                conversation_turn__ordinal__lt=execution.conversation_turn.ordinal,
            ).exclude(outcome__in=(Execution.Outcome.SUCCESS, Execution.Outcome.ERROR, Execution.Outcome.TIMEOUT)).exists()
            if prior_is_active:
                continue
        # This immutable row is the durable target-wide capacity mutex. It is
        # held only while counting and recording a claim, never during I/O.
        TargetRevision.objects.select_for_update().get(pk=execution.target_revision_id)
        run_active = _active_claims(Execution.objects.filter(run_id=run.pk), now).count()
        target_active = _active_claims(
            Execution.objects.filter(target_revision_id=execution.target_revision_id), now
        ).count()
        if run_active >= run.actual_concurrency or target_active >= run.configured_max_concurrency:
            continue

        token = uuid.uuid4()
        _set_run_started(run, now)
        execution.outcome = Execution.Outcome.RUNNING
        execution.claim_worker_id = worker_id
        execution.claim_token = token
        execution.claim_attempt += 1
        execution.claimed_at = now
        execution.claim_heartbeat_at = now
        execution.claim_lease_expires_at = _lease_expiry(now)
        execution.target_call_phase = Execution.TargetCallPhase.CLAIMED
        execution.started_at = now
        execution.save(
            update_fields=(
                "outcome",
                "claim_worker_id",
                "claim_token",
                "claim_attempt",
                "claimed_at",
                "claim_heartbeat_at",
                "claim_lease_expires_at",
                "target_call_phase",
                "started_at",
            )
        )
        return ExecutionClaim(execution.pk, worker_id, token)
    return None


def refresh_claim_lease(claim: ExecutionClaim) -> bool:
    """Heartbeat active claim metadata without touching immutable observations."""

    with transaction.atomic():
        now = _database_now()
        updated = Execution.objects.filter(
            pk=claim.execution_id,
            outcome=Execution.Outcome.RUNNING,
            claim_worker_id=claim.worker_id,
            claim_token=claim.token,
            target_call_phase__in=(
                Execution.TargetCallPhase.CLAIMED,
                Execution.TargetCallPhase.SUBMISSION_STARTED,
            ),
        ).update(claim_heartbeat_at=now, claim_lease_expires_at=_lease_expiry(now))
        return updated == 1


class _ClaimHeartbeat:
    def __init__(self, claim: ExecutionClaim):
        self.claim = claim
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._stopped.set()
        self._thread.join(timeout=settings.WORKER_HEARTBEAT_SECONDS + 1)

    def _run(self):
        while not self._stopped.wait(settings.WORKER_HEARTBEAT_SECONDS):
            if not refresh_claim_lease(self.claim):
                logger.warning(
                    "worker claim ownership lost execution_id=%s worker_id=%s",
                    self.claim.execution_id,
                    self.claim.worker_id,
                )
                return


@transaction.atomic
def _mark_submission_started(claim: ExecutionClaim) -> bool:
    now = _database_now()
    execution = Execution.objects.select_for_update().get(pk=claim.execution_id)
    if (
        execution.outcome != Execution.Outcome.RUNNING
        or execution.claim_worker_id != claim.worker_id
        or execution.claim_token != claim.token
        or execution.target_call_phase != Execution.TargetCallPhase.CLAIMED
    ):
        return False
    execution.target_call_phase = Execution.TargetCallPhase.SUBMISSION_STARTED
    execution.claim_heartbeat_at = now
    execution.claim_lease_expires_at = _lease_expiry(now)
    execution.save(update_fields=("target_call_phase", "claim_heartbeat_at", "claim_lease_expires_at"))
    return True


def _record_runtime_metadata(execution: Execution, adapter, credential: str | None):
    snapshot = BuildSnapshot.objects.get(pk=execution.build_snapshot_id)
    if snapshot.runtime_state != BuildSnapshot.RuntimeState.NOT_ATTEMPTED:
        return snapshot
    target = execution.target_snapshot
    if not target.supports_runtime_metadata:
        values = {
            "runtime_state": BuildSnapshot.RuntimeState.UNAVAILABLE,
            "runtime_diagnostic": "Target revision does not declare runtime metadata support.",
            "runtime_observed_at": timezone.now(),
        }
    else:
        # The optional metadata call happens outside a database transaction.
        metadata = adapter.runtime_metadata(
            endpoint=target.endpoint,
            credential=credential,
            timeout_seconds=execution.run.question_timeout_seconds,
        )
        values = {
            "runtime_state": metadata.state,
            "runtime_metadata": metadata.metadata,
            "runtime_raw_response": metadata.raw_response,
            "runtime_diagnostic": metadata.diagnostic,
            "runtime_observed_at": metadata.observed_at,
        }
    with transaction.atomic():
        snapshot = BuildSnapshot.objects.select_for_update().get(pk=execution.build_snapshot_id)
        if snapshot.runtime_state != BuildSnapshot.RuntimeState.NOT_ATTEMPTED:
            return snapshot
        for field, value in values.items():
            setattr(snapshot, field, value)
        snapshot.save(update_fields=tuple(values))
    return snapshot


@transaction.atomic
def _complete_execution(claim: ExecutionClaim, *, outcome, values):
    execution = Execution.objects.select_for_update().select_related("run").get(pk=claim.execution_id)
    if (
        execution.is_terminal
        or execution.outcome != Execution.Outcome.RUNNING
        or execution.claim_worker_id != claim.worker_id
        or execution.claim_token != claim.token
    ):
        return False
    now = values.pop("completed_at", _database_now())
    _finalize_locked_execution(execution, outcome=outcome, values=values, now=now)
    # The item is appended only after the current terminal observation exists.
    # The comparison service never mutates it later, including after validity
    # corrections or future normalization/comparator changes.
    comparison_item = record_exact_comparison(current_execution=execution)
    if comparison_item:
        # M7 is exact-first: semantic work only receives a persisted terminal
        # comparison item and never changes the target Execution observation.
        record_semantic_comparison(comparison_item=comparison_item)
    run = EvaluationRun.objects.select_for_update().get(pk=execution.run_id)
    if not run.is_terminal and run.inter_question_delay_seconds:
        run.next_dispatch_at = now + timedelta(seconds=float(run.inter_question_delay_seconds))
        run.save(update_fields=("next_dispatch_at",))
    _finalize_run_if_complete(run, now)
    return True


def _worker_test_hook(execution_id: int, phase: str):
    """Opt-in process-test barrier; absent unless the harness sets its directory."""

    directory = os.environ.get("STEWARD_BENCH_WORKER_TEST_HOOK_DIRECTORY")
    if not directory:
        return
    enabled_phases = {
        item.strip()
        for item in os.environ.get("STEWARD_BENCH_WORKER_TEST_HOOK_PHASES", "pre_submit,post_response").split(",")
        if item.strip()
    }
    if phase not in enabled_phases:
        return
    hook_directory = Path(directory)
    ready = hook_directory / f"{execution_id}.{phase}.ready"
    release = hook_directory / f"{execution_id}.{phase}.release"
    ready.touch(exist_ok=True)
    while not release.exists():
        time.sleep(0.02)


def _ensure_conversation_session(execution: Execution, adapter, credential: str | None):
    """Open the one durable target session before the first turn only.

    The claim is already marked ``SUBMISSION_STARTED`` before this function is
    called.  If a worker dies during session creation, M4 recovery therefore
    records ambiguity rather than silently opening another session.
    """

    attempt = ConversationAttempt.objects.get(pk=execution.conversation_attempt_id)
    if attempt.session_state == ConversationAttempt.SessionState.UNUSABLE:
        raise ConversationFailure("SESSION_FAILED", "The historical conversation session is unusable.", continuity="UNUSABLE")
    if attempt.target_session_id:
        return attempt
    if execution.conversation_turn.ordinal != 1:
        raise ConversationFailure(
            "SESSION_FAILED",
            "A later conversation turn has no persisted shared session identity.",
            continuity="UNUSABLE",
        )
    session = adapter.open_conversation(
        endpoint=execution.target_snapshot.endpoint,
        credential=credential,
        timeout_seconds=execution.run.question_timeout_seconds,
    )
    with transaction.atomic():
        locked = ConversationAttempt.objects.select_for_update().get(pk=attempt.pk)
        if locked.target_session_id and locked.target_session_id != session.session_id:
            raise ConversationFailure(
                "SESSION_FAILED",
                "A different target session was returned after a historical session identity was recorded.",
                continuity="UNUSABLE",
            )
        if not locked.target_session_id:
            locked.target_session_id = session.session_id
            locked.session_metadata = {
                "open_request": session.raw_request,
                "open_response": session.raw_response,
                "target_metadata": session.session_metadata,
            }
            locked.session_state = ConversationAttempt.SessionState.ACTIVE
            locked.started_at = timezone.now()
            locked.save(update_fields=("target_session_id", "session_metadata", "session_state", "started_at"))
        return locked


@transaction.atomic
def _mark_conversation_session_unusable(*, execution_id: int, error_class: str, detail: str):
    """Block never-submitted dependent turns without inventing new sessions."""

    execution = Execution.objects.select_for_update().get(pk=execution_id)
    attempt = ConversationAttempt.objects.select_for_update().get(pk=execution.conversation_attempt_id)
    now = _database_now()
    attempt.session_state = ConversationAttempt.SessionState.UNUSABLE
    attempt.session_diagnostic = detail
    attempt.save(update_fields=("session_state", "session_diagnostic"))
    blocked = Execution.objects.select_for_update().filter(
        conversation_attempt=attempt,
        outcome=Execution.Outcome.PENDING,
    )
    for dependent in blocked:
        _finalize_locked_execution(
            dependent,
            outcome=Execution.Outcome.ERROR,
            now=now,
            values={
                "error_class": "SESSION_CONTINUITY_BLOCKED",
                "error_detail": (
                    "This dependent conversation turn was not submitted because the shared target session "
                    f"became unusable after {error_class}: {detail}"
                )[:2000],
            },
        )
    if not attempt.turn_executions.exclude(
        outcome__in=(Execution.Outcome.SUCCESS, Execution.Outcome.ERROR, Execution.Outcome.TIMEOUT)
    ).exists():
        attempt.completed_at = now
        attempt.save(update_fields=("completed_at",))
    run = EvaluationRun.objects.select_for_update().get(pk=execution.run_id)
    _finalize_run_if_complete(run, now)


def _close_conversation_if_complete(execution_id: int):
    """Close only after every turn reaches a terminal observation.

    Closing is adapter cleanup, not an Execution rewrite; a close error is
    retained as attempt diagnostic and does not alter per-turn evidence.
    """

    execution = Execution.objects.select_related("conversation_attempt", "run", "target_snapshot").get(pk=execution_id)
    if not execution.conversation_attempt_id:
        return
    attempt = execution.conversation_attempt
    if attempt.completed_at or attempt.session_state == ConversationAttempt.SessionState.UNUSABLE:
        return
    if attempt.turn_executions.exclude(
        outcome__in=(Execution.Outcome.SUCCESS, Execution.Outcome.ERROR, Execution.Outcome.TIMEOUT)
    ).exists():
        return
    if not attempt.target_session_id:
        return
    diagnostic = ""
    closed = True
    try:
        adapter = adapter_for(execution.adapter_key)
        credential = resolve_credential(execution.target_snapshot.credential_reference)
        adapter.close_conversation(
            endpoint=execution.target_snapshot.endpoint,
            credential=credential,
            session_id=attempt.target_session_id,
            timeout_seconds=execution.run.question_timeout_seconds,
        )
    except ConversationFailure as failure:
        closed = False
        diagnostic = f"Session close diagnostic: {failure.error_class}: {failure.detail}"
    except Exception:
        closed = False
        diagnostic = "Session close diagnostic: adapter cleanup failed unexpectedly."
    with transaction.atomic():
        locked = ConversationAttempt.objects.select_for_update().get(pk=attempt.pk)
        if locked.completed_at:
            return
        locked.completed_at = timezone.now()
        if closed:
            locked.session_state = ConversationAttempt.SessionState.CLOSED
            locked.save(update_fields=("completed_at", "session_state"))
        else:
            locked.session_diagnostic = diagnostic
            locked.save(update_fields=("completed_at", "session_diagnostic"))


def _conversation_finish(claim: ExecutionClaim, *, outcome, values, continuity="USABLE"):
    completed = _complete_execution(claim, outcome=outcome, values=values)
    if continuity != "USABLE":
        _mark_conversation_session_unusable(
            execution_id=claim.execution_id,
            error_class=values.get("error_class", "SESSION_FAILED"),
            detail=values.get("error_detail", "Conversation continuity could not be established."),
        )
    _close_conversation_if_complete(claim.execution_id)
    return completed


def _process_conversation_claim(claim: ExecutionClaim, execution: Execution):
    """Run one ordered session-bound turn under the normal M4 claim lease."""

    with _ClaimHeartbeat(claim):
        if execution.preflight_error_class:
            return _conversation_finish(
                claim,
                outcome=Execution.Outcome.ERROR,
                values={"error_class": execution.preflight_error_class, "error_detail": execution.preflight_error_detail},
                continuity="UNUSABLE",
            )
        try:
            adapter = adapter_for(execution.adapter_key)
            credential = resolve_credential(execution.target_snapshot.credential_reference)
            _record_runtime_metadata(execution, adapter, credential)
            _worker_test_hook(execution.pk, "pre_submit")
            if not _mark_submission_started(claim):
                return False
            attempt = _ensure_conversation_session(execution, adapter, credential)
            submission = adapter.submit_conversation_turn(
                endpoint=execution.target_snapshot.endpoint,
                credential=credential,
                request_id=str(execution.request_correlation_id),
                session_id=attempt.target_session_id,
                turn_ordinal=execution.conversation_turn.ordinal,
                question=execution.submitted_question,
                timeout_seconds=execution.run.question_timeout_seconds,
            )
            _worker_test_hook(execution.pk, "post_response")
        except ConversationFailure as failure:
            outcome = Execution.Outcome.TIMEOUT if failure.error_class == "TARGET_TIMEOUT" else Execution.Outcome.ERROR
            return _conversation_finish(
                claim,
                outcome=outcome,
                values={
                    "protocol_status": failure.protocol_status,
                    "raw_request": failure.raw_request,
                    "raw_response": failure.raw_response,
                    "error_class": failure.error_class,
                    "error_detail": failure.detail,
                },
                continuity=failure.continuity,
            )
        except TargetTimeout as failure:
            return _conversation_finish(
                claim,
                outcome=Execution.Outcome.TIMEOUT,
                values={
                    "protocol_status": failure.protocol_status,
                    "raw_request": failure.raw_request,
                    "raw_response": failure.raw_response,
                    "error_class": failure.error_class,
                    "error_detail": failure.detail,
                },
                continuity="UNKNOWN",
            )
        except AdapterFailure as failure:
            return _conversation_finish(
                claim,
                outcome=Execution.Outcome.ERROR,
                values={
                    "protocol_status": failure.protocol_status,
                    "raw_request": failure.raw_request,
                    "raw_response": failure.raw_response,
                    "error_class": failure.error_class,
                    "error_detail": failure.detail,
                },
                continuity="UNKNOWN",
            )
        except Exception:
            logger.error("unexpected conversation adapter failure execution_id=%s", execution.pk)
            return _conversation_finish(
                claim,
                outcome=Execution.Outcome.ERROR,
                values={"error_class": "ADAPTER_ERROR", "error_detail": "Unexpected adapter failure; no target answer was captured."},
                continuity="UNKNOWN",
            )
        return _conversation_finish(
            claim,
            outcome=Execution.Outcome.SUCCESS,
            values={
                "protocol_status": submission.protocol_status,
                "raw_request": submission.raw_request,
                "raw_response": submission.raw_response,
                "raw_answer": submission.raw_answer,
                "display_answer": submission.raw_answer,
                "evidence": submission.evidence if submission.evidence is not None else {},
                "response_metadata": submission.response_metadata,
                "input_tokens": submission.input_tokens,
                "output_tokens": submission.output_tokens,
                "total_tokens": submission.total_tokens,
                "token_usage_metadata": submission.token_usage_metadata,
                "runtime_telemetry": submission.runtime_telemetry,
                "internal_timing_metadata": submission.internal_timing_metadata,
                "target_correlation_id": submission.target_correlation_id,
                "adapter_key": submission.adapter_key,
                "adapter_version": submission.adapter_version,
                "normalizer_key": submission.normalizer_key,
                "normalizer_version": submission.normalizer_version,
                "completed_at": submission.completed_at,
            },
        )


def process_claim(claim: ExecutionClaim):
    """Perform one claimed execution, with all remote calls outside DB locks."""

    execution = Execution.objects.select_related("run", "target_snapshot", "build_snapshot").get(
        pk=claim.execution_id
    )
    if (
        execution.outcome != Execution.Outcome.RUNNING
        or execution.claim_worker_id != claim.worker_id
        or execution.claim_token != claim.token
    ):
        return False

    if execution.conversation_attempt_id:
        return _process_conversation_claim(claim, execution)

    with _ClaimHeartbeat(claim):
        if execution.preflight_error_class:
            return _complete_execution(
                claim,
                outcome=Execution.Outcome.ERROR,
                values={
                    "error_class": execution.preflight_error_class,
                    "error_detail": execution.preflight_error_detail,
                },
            )
        try:
            adapter = adapter_for(execution.adapter_key)
            credential = resolve_credential(execution.target_snapshot.credential_reference)
            _record_runtime_metadata(execution, adapter, credential)
            _worker_test_hook(execution.pk, "pre_submit")
            if not _mark_submission_started(claim):
                return False
            submission = adapter.submit_question(
                endpoint=execution.target_snapshot.endpoint,
                credential=credential,
                request_id=str(execution.request_correlation_id),
                question=execution.submitted_question,
                timeout_seconds=execution.run.question_timeout_seconds,
            )
            _worker_test_hook(execution.pk, "post_response")
        except TargetTimeout as failure:
            return _complete_execution(
                claim,
                outcome=Execution.Outcome.TIMEOUT,
                values={
                    "protocol_status": failure.protocol_status,
                    "raw_request": failure.raw_request,
                    "raw_response": failure.raw_response,
                    "error_class": failure.error_class,
                    "error_detail": failure.detail,
                },
            )
        except AdapterFailure as failure:
            return _complete_execution(
                claim,
                outcome=Execution.Outcome.ERROR,
                values={
                    "protocol_status": failure.protocol_status,
                    "raw_request": failure.raw_request,
                    "raw_response": failure.raw_response,
                    "error_class": failure.error_class,
                    "error_detail": failure.detail,
                },
            )
        except Exception:
            # Do not emit an arbitrary adapter exception: an upstream library
            # can include a secret-bearing response/body in its exception text.
            logger.error("unexpected adapter failure execution_id=%s", execution.pk)
            return _complete_execution(
                claim,
                outcome=Execution.Outcome.ERROR,
                values={
                    "error_class": "ADAPTER_ERROR",
                    "error_detail": "Unexpected adapter failure; no target answer was captured.",
                },
            )

        return _complete_execution(
            claim,
            outcome=Execution.Outcome.SUCCESS,
            values={
                "protocol_status": submission.protocol_status,
                "raw_request": submission.raw_request,
                "raw_response": submission.raw_response,
                "raw_answer": submission.raw_answer,
                "display_answer": submission.raw_answer,
                "evidence": submission.evidence if submission.evidence is not None else {},
                "response_metadata": submission.response_metadata,
                "input_tokens": submission.input_tokens,
                "output_tokens": submission.output_tokens,
                "total_tokens": submission.total_tokens,
                "token_usage_metadata": submission.token_usage_metadata,
                "runtime_telemetry": submission.runtime_telemetry,
                "internal_timing_metadata": submission.internal_timing_metadata,
                "target_correlation_id": submission.target_correlation_id,
                "adapter_key": submission.adapter_key,
                "adapter_version": submission.adapter_version,
                "normalizer_key": submission.normalizer_key,
                "normalizer_version": submission.normalizer_version,
                "completed_at": submission.completed_at,
            },
        )


def process_execution(execution_id, *, worker_id: str | None = None, claim_token: uuid.UUID | None = None):
    """Compatibility helper for a current claim; workers use ``process_claim``."""

    execution = Execution.objects.get(pk=execution_id)
    if execution.outcome != Execution.Outcome.RUNNING or not execution.claim_token:
        return False
    claim = ExecutionClaim(
        execution_id=execution.pk,
        worker_id=worker_id or execution.claim_worker_id,
        token=claim_token or execution.claim_token,
    )
    return process_claim(claim)


def process_next_execution(worker_id: str | None = None):
    claim = claim_next_execution(worker_id)
    if claim is None:
        return False
    process_claim(claim)
    return True
