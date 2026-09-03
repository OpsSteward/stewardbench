"""Application services for M3 frozen run creation and sequential execution."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from accounts.policy import require_admin
from catalog.models import EvaluationTarget, Question, TargetRevision

from .adapters import AdapterFailure, TargetTimeout, adapter_for, resolve_credential
from .models import BuildSnapshot, EvaluationRun, Execution, ResolvedBinding, TargetSnapshot


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
            {
                "name": definition.name,
                "value": definition.fixed_value,
                "display_value": rendered,
            }
        )
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


@transaction.atomic
def launch_run(*, actor, target: EvaluationTarget, question_ids: Iterable[int] = (), select_all=False, filters=None):
    """Persist the complete M3 manifest before any worker or target interaction."""

    require_admin(actor)
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
        requested_mode=EvaluationRun.ExecutionMode.SEQUENTIAL,
        configured_max_concurrency=revision.max_concurrency,
        actual_concurrency=1,
        question_timeout_seconds=revision.question_timeout_seconds,
        inter_question_delay_seconds=revision.inter_question_delay_seconds,
        total_planned=len(selected),
        selection_filter={"select_all_matching": bool(select_all), **filters},
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
    run.save(update_fields=("state", "completed_at"))
    return run


@transaction.atomic
def recover_interrupted_executions():
    """M3 intentionally never replays a RUNNING call after a worker restart."""

    now = timezone.now()
    interrupted = list(
        Execution.objects.select_for_update()
        .filter(outcome=Execution.Outcome.RUNNING)
        .select_related("run")
        .order_by("run__created_at", "question_order")
    )
    affected_runs = set()
    for execution in interrupted:
        execution.outcome = Execution.Outcome.ERROR
        execution.error_class = "AMBIGUOUS_INFRASTRUCTURE"
        execution.error_detail = (
            "M3 worker restarted while this execution was RUNNING; remote completion is unknown "
            "and StewardBench will not resubmit it."
        )
        execution.completed_at = now
        if execution.started_at:
            execution.latency_ms = max(0, int((now - execution.started_at).total_seconds() * 1000))
        execution.save()
        affected_runs.add(execution.run_id)
    for run_id in affected_runs:
        run = EvaluationRun.objects.select_for_update().get(pk=run_id)
        _finalize_run_if_complete(run, now)
    return len(interrupted)


@transaction.atomic
def claim_next_execution():
    """The M3 worker is intentionally single-process and claims one item at a time."""

    execution = (
        Execution.objects.select_for_update()
        .select_related("run", "target_snapshot", "build_snapshot")
        .filter(
            outcome=Execution.Outcome.PENDING,
            run__state__in=(EvaluationRun.State.PENDING, EvaluationRun.State.RUNNING),
        )
        .order_by("run__created_at", "question_order")
        .first()
    )
    if not execution:
        return None
    now = timezone.now()
    _set_run_started(execution.run, now)
    execution.outcome = Execution.Outcome.RUNNING
    execution.started_at = now
    execution.save(update_fields=("outcome", "started_at"))
    return execution.pk


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
        # This is intentionally outside a transaction: no database lock remains
        # open while a target metadata endpoint is contacted.
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
def _complete_execution(execution_id, *, outcome, values):
    execution = Execution.objects.select_for_update().select_related("run").get(pk=execution_id)
    if execution.is_terminal:
        return False
    now = values.pop("completed_at", timezone.now())
    for field, value in values.items():
        setattr(execution, field, value)
    execution.outcome = outcome
    execution.completed_at = now
    if execution.started_at:
        execution.latency_ms = max(0, int((now - execution.started_at).total_seconds() * 1000))
    execution.save()
    run = EvaluationRun.objects.select_for_update().get(pk=execution.run_id)
    _finalize_run_if_complete(run, now)
    return True


def process_execution(execution_id):
    """Run exactly one claimed item outside database transactions."""

    execution = Execution.objects.select_related("run", "target_snapshot", "build_snapshot").get(pk=execution_id)
    if execution.outcome != Execution.Outcome.RUNNING:
        return False
    if execution.preflight_error_class:
        return _complete_execution(
            execution.pk,
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
        submission = adapter.submit_question(
            endpoint=execution.target_snapshot.endpoint,
            credential=credential,
            request_id=str(execution.request_correlation_id),
            question=execution.submitted_question,
            timeout_seconds=execution.run.question_timeout_seconds,
        )
    except TargetTimeout as failure:
        return _complete_execution(
            execution.pk,
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
            execution.pk,
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
        return _complete_execution(
            execution.pk,
            outcome=Execution.Outcome.ERROR,
            values={
                "error_class": "ADAPTER_ERROR",
                "error_detail": "Unexpected adapter failure; no target answer was captured.",
            },
        )
    completed = _complete_execution(
        execution.pk,
        outcome=Execution.Outcome.SUCCESS,
        values={
            "protocol_status": submission.protocol_status,
            "raw_request": submission.raw_request,
            "raw_response": submission.raw_response,
            "raw_answer": submission.raw_answer,
            "display_answer": submission.raw_answer,
            "evidence": submission.evidence if submission.evidence is not None else {},
            "response_metadata": submission.response_metadata,
            "target_correlation_id": submission.target_correlation_id,
            "adapter_key": submission.adapter_key,
            "adapter_version": submission.adapter_version,
            "completed_at": submission.completed_at,
        },
    )
    if completed and execution.run.inter_question_delay_seconds:
        time.sleep(float(execution.run.inter_question_delay_seconds))
    return completed


def process_next_execution():
    execution_id = claim_next_execution()
    if execution_id is None:
        return False
    process_execution(execution_id)
    return True
