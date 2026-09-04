"""Read-only M10 reporting projections and safe export serializers.

The functions in this module deliberately derive all operational views from the
immutable run, execution, review, comparison, and evaluator records.  They do
not maintain a second metrics store and never turn a transport or automated
signal into a human quality judgment.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, time
from statistics import median
from typing import Any

from django.conf import settings
from django.db.models import Prefetch, Q
from django.utils import timezone

from catalog.models import Domain, EvaluationTarget, Tag

from .models import (
    AutomatedEvaluationResult,
    Comparison,
    ComparisonItem,
    EvaluationInvocation,
    EvaluationRun,
    Execution,
    HumanReview,
    LLMJudgeResult,
    SemanticComparisonResult,
)
from .performance import PERFORMANCE_BANDS, PERFORMANCE_POLICY_VERSION, classify_latency, performance_comparison, token_delta
from .services import comparison_human_transition, comparison_summary, run_progress, run_review_metrics


RUN_EXPORT_SCHEMA_VERSION = "stewardbench-run-export-v1"
# Preserve factual token telemetry while still redacting credential-shaped keys.
SENSITIVE_KEY = re.compile(
    r"(^token$|authorization|password|secret|cookie|credential|api[_-]?key|access[_-]?token|refresh[_-]?token)",
    re.I,
)
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _runtime_secret_values() -> tuple[str, ...]:
    """Return runtime-only credential values without ever exposing their names."""

    return tuple(
        value
        for name, value in os.environ.items()
        if name.startswith("STEWARD_BENCH_TARGET_CREDENTIAL_") and value
    )


def redact_export_value(value: Any, *, secrets: tuple[str, ...] | None = None) -> Any:
    """Redact known runtime credentials and credential-shaped mapping keys.

    Values should already have been redacted before persistence.  Re-applying
    the guard at a reporting boundary protects historical exports if an upstream
    integration ever produces a surprising nested payload.
    """

    known_secrets = _runtime_secret_values() if secrets is None else secrets
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact_export_value(child, secrets=known_secrets)
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_export_value(item, secrets=known_secrets) for item in value]
    if isinstance(value, str):
        result = value
        for secret in known_secrets:
            if secret:
                result = result.replace(secret, "[REDACTED]")
        return result
    return value


def csv_safe(value: Any) -> str:
    """Return a spreadsheet-safe, Unicode-preserving scalar CSV value.

    Leading apostrophe is the documented export-only protection for formula-like
    cells.  It intentionally does *not* mutate immutable evidence or the JSON
    export, which retains the exact raw content.
    """

    if value is None:
        result = ""
    elif isinstance(value, bool):
        result = "true" if value else "false"
    elif isinstance(value, (dict, list, tuple)):
        result = json.dumps(redact_export_value(value), ensure_ascii=False, sort_keys=True, default=str)
    elif isinstance(value, datetime):
        result = value.isoformat()
    else:
        result = str(redact_export_value(value))
    return "'" + result if result.startswith(CSV_FORMULA_PREFIXES) else result


def csv_rows(rows: Iterable[Mapping[str, Any]], columns: list[str]) -> Iterable[list[str]]:
    """Yield values in a fixed documented column order for streaming responses."""

    for row in rows:
        yield [csv_safe(row.get(column)) for column in columns]


def _date_bound(value: str, *, end: bool = False):
    try:
        parsed = datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        return None
    bound = datetime.combine(parsed, time.max if end else time.min)
    return timezone.make_aware(bound, timezone.get_current_timezone())


def filter_executions(queryset, params: Mapping[str, str]):
    """Apply the canonical URL-addressable M10 execution filters.

    The filter keys intentionally remain object-oriented query parameters rather
    than a generic reporting language.  A comparison join is distinct because
    an execution can retain historical comparison items.
    """

    text = params.get("q", "").strip()
    if text:
        queryset = queryset.filter(
            Q(question_stable_id__icontains=text)
            | Q(question_template__icontains=text)
            | Q(submitted_question__icontains=text)
        )
    if value := params.get("product", "").strip():
        queryset = queryset.filter(run__target__product__slug=value)
    if value := params.get("environment", "").strip():
        queryset = queryset.filter(run__target__environment__slug=value)
    if value := params.get("target", "").strip():
        queryset = queryset.filter(run__target__slug=value)
    if value := params.get("run", "").strip():
        queryset = queryset.filter(run_id=value)
    if value := params.get("build", "").strip():
        queryset = queryset.filter(
            Q(build_snapshot__declared_product_version__icontains=value)
            | Q(build_snapshot__declared_build_id__icontains=value)
            | Q(build_snapshot__declared_git_sha__icontains=value)
            | Q(build_snapshot__runtime_metadata__product_version__icontains=value)
            | Q(build_snapshot__runtime_metadata__build_id__icontains=value)
            | Q(build_snapshot__runtime_metadata__git_sha__icontains=value)
        )
    if value := params.get("domain", "").strip():
        queryset = queryset.filter(question__domain__slug=value)
    if value := params.get("tag", "").strip():
        queryset = queryset.filter(question__tags__name=value)
    if value := params.get("outcome", "").strip():
        if value in Execution.Outcome.values:
            queryset = queryset.filter(outcome=value)
    if value := params.get("validity", "").strip():
        if value in Execution.Validity.values:
            queryset = queryset.filter(validity=value)
    if value := params.get("review", "").strip():
        if value in Execution.ReviewState.values:
            queryset = queryset.filter(review_state=value)
    if value := params.get("human", "").strip():
        if value in HumanReview.Judgment.values:
            queryset = queryset.filter(current_human_review__judgment=value)
        elif value == "UNREVIEWED":
            queryset = queryset.filter(current_human_review__isnull=True)
    if value := params.get("change", "").strip():
        if value in ComparisonItem.ChangeState.values:
            queryset = queryset.filter(current_comparison_items__change_state=value)
    if value := params.get("semantic", "").strip():
        if value in SemanticComparisonResult.Outcome.values:
            queryset = queryset.filter(
                current_comparison_items__semantic_results__superseded_by__isnull=True,
                current_comparison_items__semantic_results__outcome=value,
            )
        elif value == "NOT_RUN":
            queryset = queryset.filter(current_comparison_items__change_state=ComparisonItem.ChangeState.CHANGED).exclude(
                current_comparison_items__semantic_results__superseded_by__isnull=True
            )
    if value := params.get("transition", "").strip():
        if value == "GOOD_TO_BAD":
            queryset = queryset.filter(
                current_comparison_items__baseline_execution__current_human_review__judgment=HumanReview.Judgment.GOOD,
                current_human_review__judgment=HumanReview.Judgment.BAD,
            )
        elif value == "BAD_TO_GOOD":
            queryset = queryset.filter(
                current_comparison_items__baseline_execution__current_human_review__judgment=HumanReview.Judgment.BAD,
                current_human_review__judgment=HumanReview.Judgment.GOOD,
            )
    if value := params.get("performance", "").strip():
        if value in PERFORMANCE_BANDS:
            queryset = queryset.filter(
                outcome=Execution.Outcome.SUCCESS,
                validity=Execution.Validity.VALID,
                performance_classification=value,
            )
    if value := params.get("performance_change", "").strip():
        if value in {"IMPROVED", "STABLE", "REGRESSED", "UNKNOWN"}:
            queryset = queryset.filter(current_comparison_items__performance_change=value)
    if params.get("band_degraded", "").strip() == "1":
        queryset = queryset.filter(current_comparison_items__performance_band_degraded=True)
    if params.get("token_increase", "").strip() == "1":
        queryset = queryset.filter(current_comparison_items__total_token_delta__gt=0)
    if params.get("token_usage", "").strip() == "AVAILABLE":
        queryset = queryset.filter(total_tokens__isnull=False)
    elif params.get("token_usage", "").strip() == "UNAVAILABLE":
        queryset = queryset.filter(total_tokens__isnull=True)
    if value := params.get("scenario", "").strip():
        if value == "YES":
            queryset = queryset.filter(conversation_attempt__isnull=False)
        elif value == "NO":
            queryset = queryset.filter(conversation_attempt__isnull=True)
    if bound := _date_bound(params.get("date_from", "")):
        queryset = queryset.filter(completed_at__gte=bound)
    if bound := _date_bound(params.get("date_to", ""), end=True):
        queryset = queryset.filter(completed_at__lte=bound)
    sort = params.get("sort", "").strip()
    if sort == "slowest":
        queryset = queryset.order_by("-latency_ms", "-pk")
    elif sort == "token_desc":
        queryset = queryset.order_by("-total_tokens", "-pk")
    elif sort == "latency_regression":
        queryset = queryset.order_by("-current_comparison_items__latency_delta_ms", "-pk")
    elif sort == "token_increase":
        queryset = queryset.order_by("-current_comparison_items__total_token_delta", "-pk")
    return queryset.distinct()


def filter_runs(queryset, params: Mapping[str, str]):
    if value := params.get("product", "").strip():
        queryset = queryset.filter(target__product__slug=value)
    if value := params.get("environment", "").strip():
        queryset = queryset.filter(target__environment__slug=value)
    if value := params.get("target", "").strip():
        queryset = queryset.filter(target__slug=value)
    if value := params.get("build", "").strip():
        queryset = queryset.filter(
            Q(build_snapshot__declared_product_version__icontains=value)
            | Q(build_snapshot__declared_build_id__icontains=value)
            | Q(build_snapshot__declared_git_sha__icontains=value)
            | Q(build_snapshot__runtime_metadata__product_version__icontains=value)
            | Q(build_snapshot__runtime_metadata__build_id__icontains=value)
            | Q(build_snapshot__runtime_metadata__git_sha__icontains=value)
        )
    if value := params.get("state", "").strip():
        if value in EvaluationRun.State.values:
            queryset = queryset.filter(state=value)
    if params.get("active", "").strip() == "1":
        queryset = queryset.filter(state__in=(EvaluationRun.State.PENDING, EvaluationRun.State.RUNNING))
    if value := params.get("mode", "").strip():
        if value in EvaluationRun.ExecutionMode.values:
            queryset = queryset.filter(requested_mode=value)
    if value := params.get("scenario", "").strip():
        if value == "YES":
            queryset = queryset.filter(conversation_attempt__isnull=False)
        elif value == "NO":
            queryset = queryset.filter(conversation_attempt__isnull=True)
    if bound := _date_bound(params.get("date_from", "")):
        queryset = queryset.filter(created_at__gte=bound)
    if bound := _date_bound(params.get("date_to", ""), end=True):
        queryset = queryset.filter(created_at__lte=bound)
    return queryset


def filter_comparisons(queryset, params: Mapping[str, str]):
    """Apply ordinary operational context filters to comparison history."""

    if value := params.get("product", "").strip():
        queryset = queryset.filter(current_run__target__product__slug=value)
    if value := params.get("environment", "").strip():
        queryset = queryset.filter(current_run__target__environment__slug=value)
    if value := params.get("target", "").strip():
        queryset = queryset.filter(current_run__target__slug=value)
    if value := params.get("run", "").strip():
        queryset = queryset.filter(current_run_id=value)
    if value := params.get("build", "").strip():
        queryset = queryset.filter(
            Q(current_run__build_snapshot__declared_product_version__icontains=value)
            | Q(current_run__build_snapshot__declared_build_id__icontains=value)
            | Q(current_run__build_snapshot__declared_git_sha__icontains=value)
            | Q(current_run__build_snapshot__runtime_metadata__product_version__icontains=value)
            | Q(current_run__build_snapshot__runtime_metadata__build_id__icontains=value)
            | Q(current_run__build_snapshot__runtime_metadata__git_sha__icontains=value)
        )
    if bound := _date_bound(params.get("date_from", "")):
        queryset = queryset.filter(created_at__gte=bound)
    if bound := _date_bound(params.get("date_to", ""), end=True):
        queryset = queryset.filter(created_at__lte=bound)
    return queryset


def filter_comparison_items(queryset, params: Mapping[str, str]):
    if value := params.get("state", "").strip():
        if value in ComparisonItem.ChangeState.values:
            queryset = queryset.filter(change_state=value)
    if value := params.get("outcome", "").strip():
        if value in (Execution.Outcome.ERROR, Execution.Outcome.TIMEOUT):
            queryset = queryset.filter(current_execution__outcome=value)
    if value := params.get("review", "").strip():
        if value in Execution.ReviewState.values:
            queryset = queryset.filter(current_execution__review_state=value)
    if value := params.get("semantic", "").strip():
        if value in SemanticComparisonResult.Outcome.values:
            queryset = queryset.filter(semantic_results__superseded_by__isnull=True, semantic_results__outcome=value)
        elif value == "NOT_RUN":
            queryset = queryset.filter(change_state=ComparisonItem.ChangeState.CHANGED).exclude(
                pk__in=SemanticComparisonResult.objects.filter(superseded_by__isnull=True).values("comparison_item_id")
            )
    if value := params.get("transition", "").strip():
        if value == "GOOD_TO_BAD":
            queryset = queryset.filter(
                baseline_execution__current_human_review__judgment=HumanReview.Judgment.GOOD,
                current_execution__current_human_review__judgment=HumanReview.Judgment.BAD,
            )
        elif value == "BAD_TO_GOOD":
            queryset = queryset.filter(
                baseline_execution__current_human_review__judgment=HumanReview.Judgment.BAD,
                current_execution__current_human_review__judgment=HumanReview.Judgment.GOOD,
            )
    if value := params.get("performance_change", "").strip():
        if value in {"IMPROVED", "STABLE", "REGRESSED", "UNKNOWN"}:
            queryset = queryset.filter(performance_change=value)
    if params.get("band_degraded", "").strip() == "1":
        queryset = queryset.filter(performance_band_degraded=True)
    sort = params.get("sort", "").strip()
    if sort == "latency_regression":
        return queryset.order_by("-latency_delta_ms", "current_execution__question_order")
    if sort == "token_increase":
        return queryset.order_by("-total_token_delta", "current_execution__question_order")
    return queryset


def filter_options() -> dict[str, Any]:
    """Compact shared option lists for stable, URL-addressable list filters."""

    return {
        "products": EvaluationTarget.objects.values_list("product__slug", "product__display_name").distinct().order_by("product__display_name"),
        "environments": EvaluationTarget.objects.values_list("environment__slug", "environment__display_name").distinct().order_by("environment__display_name"),
        "targets": EvaluationTarget.objects.values_list("slug", "display_name").order_by("display_name"),
        "domains": Domain.objects.values_list("slug", "name").order_by("name"),
        "tags": Tag.objects.values_list("name", "name").order_by("name"),
    }


def execution_csv_row(execution: Execution) -> dict[str, Any]:
    return {
        "execution_id": execution.pk,
        "run_id": execution.run_id,
        "question_id": execution.question_stable_id,
        "question_version": execution.question_version_number,
        "question": execution.submitted_question,
        "product": execution.target_snapshot.product_display_name,
        "environment": execution.target_snapshot.environment_display_name,
        "target": execution.target_snapshot.target_display_name,
        "build_version": build_identity(execution.build_snapshot)["effective"]["product_version"],
        "build_id": build_identity(execution.build_snapshot)["effective"]["build_id"],
        "git_sha": build_identity(execution.build_snapshot)["effective"]["git_sha"],
        "executed_at": execution.completed_at,
        "outcome": execution.outcome,
        "observed_latency_ms": execution.latency_ms,
        "performance_policy_version": execution.performance_policy_version,
        "performance_classification": (
            execution.performance_classification
            or (classify_latency(execution.latency_ms) if execution.outcome == Execution.Outcome.SUCCESS else "")
            or ""
        ),
        "input_tokens": execution.input_tokens,
        "output_tokens": execution.output_tokens,
        "total_tokens": execution.total_tokens,
        "runtime": execution.runtime_telemetry.get("provider_or_runtime") or execution.runtime_telemetry.get("runtime") or "",
        "model": execution.runtime_telemetry.get("model") or "",
        "validity": execution.validity,
        "human_judgment": execution.current_human_review.judgment if execution.current_human_review else "",
        "review_state": execution.review_state,
        "raw_answer": execution.raw_answer,
        "display_answer": execution.display_answer,
    }


def comparison_csv_row(item: ComparisonItem) -> dict[str, Any]:
    history = list(item.semantic_results.all())
    superseded_ids = {result.supersedes_id for result in history if result.supersedes_id}
    current_semantic = next((result for result in history if result.pk not in superseded_ids), None)
    return {
        "comparison_id": item.comparison_id,
        "comparison_item_id": item.pk,
        "run_id": item.current_execution.run_id,
        "question_id": item.current_execution.question_stable_id,
        "question_version": item.current_execution.question_version_number,
        "current_outcome": item.current_execution.outcome,
        "validity": item.current_execution.validity,
        "review_state": item.current_execution.review_state,
        "exact_change_state": item.change_state,
        "semantic_result": current_semantic.outcome if current_semantic else "NOT_RUN",
        "human_transition": comparison_human_transition(item),
        "baseline_latency_ms": item.baseline_latency_ms,
        "current_latency_ms": item.current_latency_ms,
        "latency_delta_ms": item.latency_delta_ms,
        "latency_delta_percent": item.latency_delta_percent,
        "baseline_performance_classification": item.baseline_performance_classification,
        "current_performance_classification": item.current_performance_classification,
        "performance_change": item.performance_change or "UNKNOWN",
        "performance_band_degraded": item.performance_band_degraded,
        "baseline_input_tokens": item.baseline_execution.input_tokens,
        "current_input_tokens": item.current_execution.input_tokens,
        "input_token_delta": item.input_token_delta,
        "input_token_delta_percent": item.input_token_delta_percent,
        "baseline_output_tokens": item.baseline_execution.output_tokens,
        "current_output_tokens": item.current_execution.output_tokens,
        "output_token_delta": item.output_token_delta,
        "output_token_delta_percent": item.output_token_delta_percent,
        "baseline_total_tokens": item.baseline_execution.total_tokens,
        "current_total_tokens": item.current_execution.total_tokens,
        "total_token_delta": item.total_token_delta,
        "total_token_delta_percent": item.total_token_delta_percent,
        "baseline_runtime": item.baseline_execution.runtime_telemetry.get("provider_or_runtime") or item.baseline_execution.runtime_telemetry.get("runtime") or "",
        "current_runtime": item.current_execution.runtime_telemetry.get("provider_or_runtime") or item.current_execution.runtime_telemetry.get("runtime") or "",
        "baseline_model": item.baseline_execution.runtime_telemetry.get("model") or "",
        "current_model": item.current_execution.runtime_telemetry.get("model") or "",
        "baseline_answer": item.baseline_execution.raw_answer,
        "current_answer": item.current_execution.raw_answer,
    }


def build_identity(snapshot) -> dict[str, Any]:
    """Keep declared and observed identity distinct, with no fabricated values."""

    observed = redact_export_value(snapshot.runtime_metadata or {})
    effective = {
        "product_version": observed.get("product_version") or snapshot.declared_product_version or None,
        "build_id": observed.get("build_id") or snapshot.declared_build_id or None,
        "git_sha": observed.get("git_sha") or snapshot.declared_git_sha or None,
    }
    return {
        "declared": {
            "product_version": snapshot.declared_product_version or None,
            "build_id": snapshot.declared_build_id or None,
            "git_sha": snapshot.declared_git_sha or None,
        },
        "runtime": {
            "state": snapshot.runtime_state,
            "metadata": observed,
            "observed_at": snapshot.runtime_observed_at,
            "diagnostic": redact_export_value(snapshot.runtime_diagnostic),
        },
        "effective": effective,
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return redact_export_value(value)


def _result_payload(result) -> dict[str, Any]:
    """Serialize evaluator/judge/comparator history without flattening signals."""

    payload = {
        "id": result.pk,
        "created_at": result.created_at,
        "supersedes_id": result.supersedes_id,
        "status": getattr(result, "status", None),
        "outcome": getattr(result, "outcome", None),
        "latency_ms": result.latency_ms,
        "error": {
            "class": result.error_class or None,
            "detail": result.error_detail or None,
        },
        "input_fingerprint": result.input_fingerprint or None,
        "input_manifest": result.input_manifest,
        "raw_result": result.raw_result,
    }
    if isinstance(result, AutomatedEvaluationResult):
        payload.update(
            {
                "kind": "automated_evaluator",
                "evaluator": {
                    "key": result.evaluator_key,
                    "version": result.evaluator_version,
                    "mechanism": result.mechanism,
                    "configuration_version": result.configuration_version,
                },
                "details": result.details,
                "invocation_id": result.invocation_id,
            }
        )
    elif isinstance(result, LLMJudgeResult):
        payload.update(
            {
                "kind": "llm_judge",
                "judge": {
                    "provider": result.provider,
                    "model_identifier": result.model_identifier,
                    "judge_version": result.judge_version,
                    "rubric_id": result.rubric_id,
                    "rubric_version": result.rubric_version,
                    "prompt_version": result.prompt_version,
                },
                "dimensions": result.dimensions,
                "rationale": result.rationale,
                "advisory_disposition": result.advisory_disposition,
                "details": result.details,
                "provider_metadata": result.provider_metadata,
                "invocation_id": result.invocation_id,
            }
        )
    elif isinstance(result, SemanticComparisonResult):
        payload.update(
            {
                "kind": "semantic_comparison",
                "comparator": {
                    "provider_key": result.provider_key,
                    "model_identifier": result.model_identifier,
                    "comparator_version": result.comparator_version,
                    "prompt_version": result.prompt_version or None,
                },
                "rationale": result.rationale,
            }
        )
    return _json_value(payload)


def _execution_export(execution: Execution) -> dict[str, Any]:
    comparison_items = list(
        execution.current_comparison_items.select_related("comparison", "baseline_execution").prefetch_related("semantic_results")
    )
    return _json_value(
        {
            "id": execution.pk,
            "question": {
                "stable_id": execution.question_stable_id,
                "question_version": execution.question_version_number,
                "question_version_id": execution.question_version_id,
                "template": execution.question_template,
                "submitted_question": execution.submitted_question,
                "bindings": [
                    {
                        "name": binding.name,
                        "value": binding.value,
                        "display_value": binding.display_value,
                        "resolution_mode": binding.resolution_mode,
                    }
                    for binding in execution.resolved_bindings.all()
                ],
            },
            "conversation": {
                "attempt_id": execution.conversation_attempt_id,
                "turn_ordinal": execution.conversation_turn.ordinal if execution.conversation_turn_id else None,
                "session_id": execution.conversation_attempt.target_session_id if execution.conversation_attempt_id else None,
            },
            "observation": {
                "outcome": execution.outcome,
                "request_correlation_id": str(execution.request_correlation_id),
                "adapter": {"key": execution.adapter_key, "version": execution.adapter_version},
                "normalizer": {"key": execution.normalizer_key, "version": execution.normalizer_version},
                "raw_request": execution.raw_request,
                "protocol_status": execution.protocol_status,
                "raw_response": execution.raw_response,
                "raw_answer": execution.raw_answer,
                "display_answer": execution.display_answer,
                "evidence": execution.evidence,
                "response_metadata": execution.response_metadata,
                "target_correlation_id": execution.target_correlation_id or None,
                "error": {"class": execution.error_class or None, "detail": execution.error_detail or None},
                "preflight_error": {
                    "class": execution.preflight_error_class or None,
                    "detail": execution.preflight_error_detail or None,
                },
                "timing": {
                    "started_at": execution.started_at,
                    "completed_at": execution.completed_at,
                    "latency_ms": execution.latency_ms,
                    "observed_latency_ms": execution.latency_ms,
                },
                "performance": {
                    "policy_version": execution.performance_policy_version or PERFORMANCE_POLICY_VERSION,
                    "classification": execution.performance_classification or classify_latency(execution.latency_ms),
                    "population": "valid successful completed response" if execution.outcome == Execution.Outcome.SUCCESS else "not_applicable",
                },
                "efficiency": {
                    "source": execution.token_usage_metadata.get("source", "UNKNOWN"),
                    "input_tokens": execution.input_tokens,
                    "output_tokens": execution.output_tokens,
                    "total_tokens": execution.total_tokens,
                    "provider_specific_usage": execution.token_usage_metadata,
                },
                "runtime_telemetry": execution.runtime_telemetry,
                "internal_timing_metadata": execution.internal_timing_metadata,
            },
            "identity": {
                "target": {
                    "name": execution.target_snapshot.target_display_name,
                    "product": execution.target_snapshot.product_display_name,
                    "environment": execution.target_snapshot.environment_display_name,
                    "revision_id": execution.target_revision_id,
                    "classification": execution.target_snapshot.classification,
                    "endpoint": execution.target_snapshot.endpoint,
                },
                "build": build_identity(execution.build_snapshot),
            },
            "review": {
                "state": execution.review_state,
                "validity": execution.validity,
                "current_human_judgment": execution.current_human_review.judgment if execution.current_human_review else None,
                "human_history": [
                    {
                        "id": review.pk,
                        "judgment": review.judgment,
                        "reviewed_by": review.reviewed_by.username,
                        "reviewed_at": review.reviewed_at,
                        "supersedes_id": review.supersedes_id,
                    }
                    for review in execution.review_history.all()
                ],
                "review_tracking_history": [
                    {
                        "id": event.pk,
                        "state": event.state,
                        "actor": event.actor.username if event.actor else None,
                        "cause": event.cause,
                        "created_at": event.created_at,
                    }
                    for event in execution.review_tracking_events.all()
                ],
                "validity_history": [
                    {
                        "id": decision.pk,
                        "validity": decision.validity,
                        "decided_by": decision.decided_by.username,
                        "decided_at": decision.decided_at,
                        "supersedes_id": decision.supersedes_id,
                    }
                    for decision in execution.validity_history.all()
                ],
            },
            "comments": [
                {"id": comment.pk, "author": comment.author.username, "created_at": comment.created_at, "text": comment.text}
                for comment in execution.comments.all()
            ],
            "automated_evaluations": [_result_payload(result) for result in execution.automated_results.all()],
            "llm_judge_results": [_result_payload(result) for result in execution.llm_judge_results.all()],
            "comparison_items": [
                {
                    "id": item.pk,
                    "comparison_id": item.comparison_id,
                    "baseline_execution_id": item.baseline_execution_id,
                    "change_state": item.change_state,
                    "exact_equal": item.exact_equal,
                    "non_comparable_reason": item.non_comparable_reason or None,
                    "detail": item.detail or None,
                    "performance": {
                        "policy_version": item.performance_policy_version or PERFORMANCE_POLICY_VERSION,
                        "baseline_latency_ms": item.baseline_latency_ms,
                        "current_latency_ms": item.current_latency_ms,
                        "latency_delta_ms": item.latency_delta_ms,
                        "latency_delta_percent": item.latency_delta_percent,
                        "baseline_classification": item.baseline_performance_classification or None,
                        "current_classification": item.current_performance_classification or None,
                        "change": item.performance_change or "UNKNOWN",
                        "band_degraded": item.performance_band_degraded,
                    },
                    "efficiency": {
                        "baseline": {"input_tokens": item.baseline_execution.input_tokens, "output_tokens": item.baseline_execution.output_tokens, "total_tokens": item.baseline_execution.total_tokens},
                        "current": {"input_tokens": item.current_execution.input_tokens, "output_tokens": item.current_execution.output_tokens, "total_tokens": item.current_execution.total_tokens},
                        "input_token_delta": item.input_token_delta,
                        "output_token_delta": item.output_token_delta,
                        "total_token_delta": item.total_token_delta,
                        "input_token_delta_percent": item.input_token_delta_percent,
                        "output_token_delta_percent": item.output_token_delta_percent,
                        "total_token_delta_percent": item.total_token_delta_percent,
                    },
                    "semantic_history": [_result_payload(result) for result in item.semantic_results.all()],
                }
                for item in comparison_items
            ],
        }
    )


def run_export(run: EvaluationRun) -> dict[str, Any]:
    """Build the complete, versioned, secret-free JSON export for one Run."""

    run = (
        EvaluationRun.objects.select_related("target_snapshot", "build_snapshot", "launched_by", "comparison_baseline", "comparison")
        .prefetch_related(
            "comments__author",
            "executions__resolved_bindings",
            "executions__conversation_attempt",
            "executions__conversation_turn",
            "executions__current_human_review",
            "executions__review_history__reviewed_by",
            "executions__review_tracking_events__actor",
            "executions__validity_history__decided_by",
            "executions__comments__author",
            "executions__automated_results",
            "executions__llm_judge_results",
            "executions__current_comparison_items__semantic_results",
            "conversation_attempt__scenario_version__scenario",
        )
        .get(pk=run.pk)
    )
    attempt = getattr(run, "conversation_attempt", None)
    payload = {
        "schema_version": RUN_EXPORT_SCHEMA_VERSION,
        "exported_at": timezone.now(),
        "stewardbench": {
            "build_identity": os.environ.get("STEWARD_BENCH_BUILD_ID", "unknown"),
            "application_version": getattr(settings, "STEWARD_BENCH_APPLICATION_VERSION", "unknown"),
        },
        "run": {
            "id": str(run.pk),
            "state": run.state,
            "launched_by": run.launched_by.username,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "execution_mode": run.requested_mode,
            "configured_max_concurrency": run.configured_max_concurrency,
            "actual_concurrency": run.actual_concurrency,
            "question_timeout_seconds": run.question_timeout_seconds,
            "inter_question_delay_seconds": run.inter_question_delay_seconds,
            "total_planned": run.total_planned,
            "selection_filter": run.selection_filter,
            "diagnostic": {"class": run.diagnostic_class or None, "detail": run.diagnostic_detail or None},
            "source_run_id": str(run.source_run_id) if run.source_run_id else None,
            "source_execution_id": run.source_execution_id,
            "baseline_id": str(run.comparison_baseline_id) if run.comparison_baseline_id else None,
            "comparison_id": run.comparison.pk if hasattr(run, "comparison") else None,
        },
        "target": {
            "name": run.target_snapshot.target_display_name,
            "product": run.target_snapshot.product_display_name,
            "environment": run.target_snapshot.environment_display_name,
            "target_revision_id": run.target_snapshot.target_revision_id,
            "endpoint": run.target_snapshot.endpoint,
            "adapter": {"key": run.target_snapshot.adapter_key, "version": run.target_snapshot.adapter_version},
            "classification": run.target_snapshot.classification,
        },
        "build": build_identity(run.build_snapshot),
        "conversation": (
            {
                "attempt_id": attempt.pk,
                "scenario_id": attempt.scenario_version.scenario.stable_id,
                "scenario_version": attempt.scenario_version.version_number,
                "session_id": attempt.target_session_id or None,
                "session_state": attempt.session_state,
                "session_metadata": attempt.session_metadata,
                "session_diagnostic": attempt.session_diagnostic or None,
                "started_at": attempt.started_at,
                "completed_at": attempt.completed_at,
                "source_attempt_id": attempt.source_attempt_id,
                "baseline_attempt_id": attempt.baseline_attempt_id,
            }
            if attempt
            else None
        ),
        "run_comments": [
            {"id": comment.pk, "author": comment.author.username, "created_at": comment.created_at, "text": comment.text}
            for comment in run.comments.all()
        ],
        "executions": [_execution_export(execution) for execution in run.executions.all().order_by("question_order")],
    }
    return _json_value(payload)


def percentile(values: list[int], fraction: float) -> int | None:
    """Nearest-rank percentile for a small operational sample, not an inference."""

    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def latency_statistics(executions: Iterable[Execution]) -> dict[str, int | None]:
    values = [execution.latency_ms for execution in executions if execution.outcome == Execution.Outcome.SUCCESS and execution.validity == Execution.Validity.VALID and execution.latency_ms is not None]
    return {
        "count": len(values),
        "p50_ms": int(median(values)) if values else None,
        "p90_ms": percentile(values, 0.90),
        "p95_ms": percentile(values, 0.95),
    }


def token_statistics(executions: Iterable[Execution]) -> dict[str, int | None]:
    population = [execution for execution in executions if execution.outcome == Execution.Outcome.SUCCESS and execution.validity == Execution.Validity.VALID]
    values = {field: [getattr(execution, field) for execution in population if getattr(execution, field) is not None] for field in ("input_tokens", "output_tokens", "total_tokens")}
    return {
        "count": len(values["total_tokens"]),
        "median_input_tokens": int(median(values["input_tokens"])) if values["input_tokens"] else None,
        "median_output_tokens": int(median(values["output_tokens"])) if values["output_tokens"] else None,
        "median_total_tokens": int(median(values["total_tokens"])) if values["total_tokens"] else None,
        "total_tokens": sum(values["total_tokens"]) if values["total_tokens"] else None,
    }


def prepare_runtime_telemetry_for_display(executions: Iterable[Execution]) -> None:
    """Give server-rendered templates a harmless empty fallback key.

    Historical rows legitimately predate optional runtime telemetry.  This is
    deliberately an in-memory presentation normalization only: it neither
    persists a synthetic runtime value nor changes JSON export evidence.
    """

    for execution in executions:
        telemetry = execution.runtime_telemetry if isinstance(execution.runtime_telemetry, dict) else {}
        if "runtime" not in telemetry:
            execution.runtime_telemetry = {**telemetry, "runtime": ""}


def run_performance_metrics(run: EvaluationRun) -> dict[str, Any]:
    """One source of truth for run detail, trends, and exportable projections."""

    executions = list(run.executions.all())
    bands = {
        band: sum(
            execution.outcome == Execution.Outcome.SUCCESS
            and execution.validity == Execution.Validity.VALID
            and (execution.performance_classification or classify_latency(execution.latency_ms)) == band
            for execution in executions
        )
        for band in PERFORMANCE_BANDS
    }
    duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000) if run.completed_at and run.started_at else None
    terminal = sum(execution.is_terminal for execution in executions)
    return {
        "latency": latency_statistics(executions),
        "tokens": token_statistics(executions),
        "bands": bands,
        "timeouts": sum(execution.outcome == Execution.Outcome.TIMEOUT for execution in executions),
        "errors": sum(execution.outcome == Execution.Outcome.ERROR for execution in executions),
        "duration_ms": duration_ms,
        "throughput_questions_per_minute": round(terminal / (duration_ms / 60000), 2) if duration_ms else None,
    }


def run_trend_rows(limit: int = 30) -> list[dict[str, Any]]:
    """Return chronological run quality and performance context from persisted truth."""

    runs = list(
        EvaluationRun.objects.filter(state__in=(EvaluationRun.State.COMPLETED, EvaluationRun.State.COMPLETED_WITH_ERRORS))
        .select_related("target_snapshot", "build_snapshot")
        .prefetch_related(
            Prefetch(
                "executions",
                queryset=Execution.objects.select_related("current_human_review").order_by("question_order"),
            )
        )
        .order_by("-completed_at")[:limit]
    )
    rows = []
    for run in reversed(runs):
        executions = list(run.executions.all())
        valid = [execution for execution in executions if execution.validity == Execution.Validity.VALID]
        good = sum(
            execution.current_human_review_id is not None
            and execution.current_human_review.judgment == HumanReview.Judgment.GOOD
            for execution in valid
        )
        bad = sum(
            execution.current_human_review_id is not None
            and execution.current_human_review.judgment == HumanReview.Judgment.BAD
            for execution in valid
        )
        unreviewed = sum(execution.current_human_review_id is None for execution in valid)
        review_required = sum(execution.review_state == Execution.ReviewState.REQUIRED for execution in executions)
        completed = sum(
            execution.outcome in (Execution.Outcome.SUCCESS, Execution.Outcome.ERROR, Execution.Outcome.TIMEOUT)
            for execution in executions
        )
        duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000) if run.completed_at and run.started_at else None
        rows.append(
            {
                "run_id": str(run.pk),
                "timestamp": run.completed_at.isoformat() if run.completed_at else None,
                "label": run.completed_at.isoformat() if run.completed_at else str(run.pk),
                "good": good,
                "bad": bad,
                "unreviewed": unreviewed,
                "review_required": review_required,
                "duration_ms": duration_ms,
                "throughput_questions_per_minute": (
                    round(completed / (duration_ms / 60000), 2) if duration_ms and duration_ms > 0 else None
                ),
                "latency": latency_statistics(executions),
                "tokens": token_statistics(executions),
                "target": run.target_snapshot.target_display_name,
                "mode": run.requested_mode,
                "concurrency": run.actual_concurrency,
                "build": build_identity(run.build_snapshot)["effective"],
            }
        )
    return rows


def question_trend_rows(question_id: int) -> list[dict[str, Any]]:
    executions = (
        Execution.objects.filter(question_id=question_id)
        .select_related("run", "target_snapshot", "build_snapshot", "current_human_review", "question_version")
        .order_by("completed_at", "pk")
    )
    return [
        {
            "execution_id": execution.pk,
            "timestamp": execution.completed_at.isoformat() if execution.completed_at else None,
            "outcome": execution.outcome,
            "human_judgment": execution.current_human_review.judgment if execution.current_human_review else "UNREVIEWED",
            "review_state": execution.review_state,
            "validity": execution.validity,
            "latency_ms": execution.latency_ms,
            "performance_classification": (
                execution.performance_classification
                if execution.outcome == Execution.Outcome.SUCCESS
                else None
            ),
            "input_tokens": execution.input_tokens,
            "output_tokens": execution.output_tokens,
            "total_tokens": execution.total_tokens,
            "question_version": execution.question_version_number,
            "target": execution.target_snapshot.target_display_name,
            "mode": execution.run.requested_mode,
            "concurrency": execution.run.actual_concurrency,
            "build": build_identity(execution.build_snapshot)["effective"],
        }
        for execution in executions
    ]


def dashboard_projection() -> dict[str, Any]:
    """Compute small attention-first dashboard sets without materialized counters."""

    executions = Execution.objects.all()
    latest_run = EvaluationRun.objects.select_related("target_snapshot", "build_snapshot").first()
    latest_comparison = Comparison.objects.select_related("baseline", "current_run").first()
    return {
        "latest_run": latest_run,
        "latest_run_progress": run_progress(latest_run) if latest_run else None,
        "latest_run_metrics": run_review_metrics(latest_run) if latest_run else None,
        "latest_comparison": latest_comparison,
        "latest_comparison_summary": comparison_summary(latest_comparison) if latest_comparison else None,
        "active_runs": EvaluationRun.objects.filter(state__in=(EvaluationRun.State.PENDING, EvaluationRun.State.RUNNING)).count(),
        "execution_errors": executions.filter(outcome=Execution.Outcome.ERROR).count(),
        "execution_timeouts": executions.filter(outcome=Execution.Outcome.TIMEOUT).count(),
        "performance": {
            band: executions.filter(outcome=Execution.Outcome.SUCCESS, validity=Execution.Validity.VALID, performance_classification=band).count()
            for band in PERFORMANCE_BANDS
        },
        "performance_regressions": ComparisonItem.objects.filter(performance_change="REGRESSED").count(),
        "performance_band_degradations": ComparisonItem.objects.filter(performance_band_degraded=True).count(),
        "token_telemetry_available": executions.filter(total_tokens__isnull=False).count(),
        "token_telemetry_unavailable": executions.filter(total_tokens__isnull=True).count(),
        "efficiency": token_statistics(executions),
        "token_increases": ComparisonItem.objects.filter(total_token_delta__gt=0).count(),
        "review_required": executions.filter(review_state=Execution.ReviewState.REQUIRED).count(),
        "unreviewed": executions.filter(validity=Execution.Validity.VALID, current_human_review__isnull=True).count(),
        "bad": executions.filter(validity=Execution.Validity.VALID, current_human_review__judgment=HumanReview.Judgment.BAD).count(),
        "invalid": executions.filter(validity=Execution.Validity.INVALID).count(),
        "configured_targets": EvaluationTarget.objects.filter(is_active=True, revisions__valid_to__isnull=True).distinct().count(),
        "trend_rows": run_trend_rows(),
    }


def worker_readiness() -> dict[str, int | str]:
    """Expose durable queue truth without inventing a worker heartbeat."""

    executions = Execution.objects.all()
    return {
        "pending": executions.filter(outcome=Execution.Outcome.PENDING).count(),
        "running": executions.filter(outcome=Execution.Outcome.RUNNING).count(),
        "message": "No worker heartbeat is persisted; queue state is shown without inferring process health.",
    }


def automated_readiness() -> dict[str, Any]:
    """Honest optional-provider status for the ADMIN operational status page."""

    latest_semantic = SemanticComparisonResult.objects.order_by("-created_at", "-id").first()
    latest_judge = LLMJudgeResult.objects.order_by("-created_at", "-id").first()
    latest_invocation = EvaluationInvocation.objects.order_by("-requested_at", "-id").first()
    semantic_configured = bool(latest_semantic and latest_semantic.provider_key not in {"unconfigured", "deterministic-fake"})
    judge_configured = bool(latest_judge and latest_judge.provider not in {"unconfigured", "deterministic-fake"})
    return {
        "semantic": {
            "configured": semantic_configured,
            "latest": latest_semantic,
            "message": "Configured" if semantic_configured else "Not configured — automated semantic comparison unavailable; review remains required for unequal answers.",
        },
        "judge": {
            "configured": judge_configured,
            "latest": latest_judge,
            "latest_invocation": latest_invocation,
            "message": "Configured" if judge_configured else "Not configured — human review remains authoritative.",
        },
    }


def target_adapter_statuses() -> list[dict[str, Any]]:
    """Expose configuration and observed adapter state without probing targets.

    Opening this administrative page must not make an unrequested network call.
    A health response alone is deliberately never promoted to contract
    certification; that status needs separate approved integration evidence.
    """

    from .adapters import AdapterFailure, adapter_for

    rows = []
    revisions = (
        EvaluationTarget.objects.filter(is_active=True, revisions__valid_to__isnull=True)
        .select_related("product", "environment")
        .prefetch_related("revisions", "runs__build_snapshot")
        .distinct()
    )
    for target in revisions:
        revision = target.current_revision
        if revision is None:
            continue
        latest_execution = (
            Execution.objects.filter(target_revision=revision)
            .select_related("run", "build_snapshot")
            .order_by("-completed_at", "-pk")
            .first()
        )
        adapter_supported = False
        adapter_detail = ""
        try:
            adapter = adapter_for(revision.adapter_key)
            adapter_supported = True
            adapter_detail = f"Configured adapter {adapter.key} {adapter.version}."
        except AdapterFailure as error:
            adapter_detail = error.detail
        if not revision.supports_question_api:
            certification = "UNSUPPORTED"
            certification_detail = "Question API capability is disabled for this target revision."
        elif latest_execution and latest_execution.error_class == "AUTHENTICATION_FAILED":
            certification = "AUTHENTICATION_FAILED"
            certification_detail = "Latest observed target interaction rejected runtime credentials."
        elif latest_execution and latest_execution.outcome == Execution.Outcome.SUCCESS and revision.adapter_key == "fake-http":
            certification = "TEST_PATH_VERIFIED"
            certification_detail = "Deterministic fake-target path is verified; this is not OpsSteward contract certification."
        elif revision.adapter_key in {"opss-v1-chat", "opss-v2-chat"}:
            certification = "CONTRACT_IMPLEMENTED_NOT_LIVE_CERTIFIED"
            certification_detail = (
                "Source-derived /chat and /version fixtures verify the supported wire contract. "
                "No configured target credentials have established live certification."
            )
        elif latest_execution and latest_execution.outcome == Execution.Outcome.SUCCESS:
            certification = "LIVE_EVALUATION_OBSERVED"
            certification_detail = "A complete answer was observed. Contract certification still requires approved wire evidence."
        elif not adapter_supported:
            certification = "UNSUPPORTED"
            certification_detail = adapter_detail
        else:
            certification = "NOT_CERTIFIED"
            certification_detail = "No approved supported-API contract certification is recorded for this revision."
        rows.append(
            {
                "target": target,
                "revision": revision,
                "adapter_supported": adapter_supported,
                "adapter_detail": adapter_detail,
                "certification": certification,
                "certification_detail": certification_detail,
                "latest_execution": latest_execution,
                "runtime_state": latest_execution.build_snapshot.runtime_state if latest_execution else "NOT_OBSERVED",
            }
        )
    return rows
