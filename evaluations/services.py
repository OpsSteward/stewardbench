"""Frozen-run services and the M4 PostgreSQL-backed durable worker.

The worker deliberately uses the Execution rows as its queue. Claims are short
PostgreSQL transactions; adapter calls are deliberately outside them.
"""

from __future__ import annotations

import json
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
from django.db import connection, transaction
from django.db.models import Count, Q
from django.utils import timezone

from accounts.policy import require_admin
from catalog.models import EvaluationTarget, Question, TargetRevision

from .adapters import AdapterFailure, TargetTimeout, adapter_for, resolve_credential
from .models import BuildSnapshot, EvaluationRun, Execution, ResolvedBinding, TargetSnapshot


logger = logging.getLogger("stewardbench.worker")
_IN_PROCESS_WORKER_ID = f"in-process-{uuid.uuid4()}"


@dataclass(frozen=True)
class ExecutionClaim:
    execution_id: int
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
def launch_run(
    *,
    actor,
    target: EvaluationTarget,
    question_ids: Iterable[int] = (),
    select_all=False,
    filters=None,
    execution_mode: str | None = None,
):
    """Persist the entire immutable manifest before a worker sees any work."""

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
        ambiguous += 1
        finalized_runs.add(execution.run_id)
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
        Execution.objects.select_for_update(skip_locked=True)
        .select_related("run")
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
                "target_correlation_id": submission.target_correlation_id,
                "adapter_key": submission.adapter_key,
                "adapter_version": submission.adapter_version,
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
