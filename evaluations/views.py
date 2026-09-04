import uuid
from io import StringIO
from urllib.parse import parse_qs, urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Case, IntegerField, OuterRef, Prefetch, Subquery, Value, When
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.policy import require_admin
from catalog.models import ConversationScenario, Question

from .forms import (
    BaselinePromotionForm,
    BaselineStateForm,
    CommentForm,
    ControlledComparisonRunForm,
    HumanReviewForm,
    LaunchConversationForm,
    LaunchRunForm,
    ReviewStateForm,
    ValidityForm,
)
from .models import (
    Baseline,
    Comparison,
    ComparisonItem,
    ConversationAttempt,
    EvaluationRun,
    EvaluationInvocation,
    Execution,
    HumanReview,
    LLMJudgeResult,
    SemanticComparisonResult,
)
from .operator_answers import operator_answer_presentation
from .reporting import (
    comparison_csv_row,
    csv_rows,
    filter_comparisons,
    execution_csv_row,
    filter_comparison_items,
    filter_executions,
    filter_options,
    filter_runs,
    run_performance_metrics,
    prepare_runtime_telemetry_for_display,
    run_export,
)
from .services import (
    append_execution_comment,
    append_run_comment,
    baseline_completeness,
    comparison_human_transition,
    comparison_summary,
    current_automated_results,
    current_judge_result,
    enqueue_evaluator_invocation,
    create_baseline,
    eligible_question_count,
    launch_controlled_comparison,
    launch_conversation_scenario,
    launch_run,
    judge_disagrees_with_human,
    mark_review_required,
    mark_reviewed_without_judgment,
    record_human_review,
    reevaluate_semantic_comparison,
    rerun_source_run,
    retry_execution,
    retry_conversation_attempt,
    run_progress,
    run_review_metrics,
    set_baseline_active,
    set_execution_validity,
)


def _require_admin(request):
    require_admin(request.user)


def _current_semantic_result_from_history(results):
    """Select the unsuperseded append-only semantic result for a rendered item."""

    history = list(results)
    superseded_ids = {result.supersedes_id for result in history if result.supersedes_id}
    return next((result for result in history if result.pk not in superseded_ids), None)


def _filters_from_request(request):
    return {
        key: request.POST.get(key, "").strip()
        for key in ("q", "domain", "tag", "lifecycle")
        if request.POST.get(key, "").strip()
    }


def _filter_query(request, *, drop: tuple[str, ...] = ("page",)):
    """Persist canonical GET filters through paging/export links."""

    preserved = request.GET.copy()
    for key in drop:
        preserved.pop(key, None)
    return preserved.urlencode()


def _csv_response(*, filename: str, columns: list[str], rows):
    """Return a bounded synchronous CSV response for the v1-sized corpus."""

    output = StringIO(newline="")
    import csv

    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(csv_rows(rows, columns))
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def run_list(request):
    runs = EvaluationRun.objects.select_related(
        "target", "target__product", "target__environment", "target_revision", "build_snapshot", "launched_by", "source_run"
    )
    runs = filter_runs(runs, request.GET)
    page = Paginator(runs, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "evaluations/run_list.html",
        {
            "page": page,
            "filter_query": _filter_query(request),
            "filter_options": filter_options(),
            "states": EvaluationRun.State.choices,
            "modes": EvaluationRun.ExecutionMode.choices,
        },
    )


@login_required
def run_detail(request, run_id):
    run = get_object_or_404(
        EvaluationRun.objects.select_related(
            "target",
            "target_revision",
            "target_snapshot",
            "build_snapshot",
            "launched_by",
            "source_run",
            "source_execution",
            "comparison_baseline",
            "comparison",
            "comparison__baseline",
        ).prefetch_related("comments__author"),
        pk=run_id,
    )
    executions = (
        run.executions.select_related("question_version", "current_human_review", "invalidated_by", "conversation_turn")
        .prefetch_related("resolved_bindings")
        .order_by("question_order")
    )
    executions = filter_executions(executions, request.GET)
    execution_page = Paginator(executions, 50).get_page(request.GET.get("page"))
    prepare_runtime_telemetry_for_display(execution_page.object_list)
    return render(
        request,
        "evaluations/run_detail.html",
        {
            "run": run,
            "progress": run_progress(run),
            "review_metrics": run_review_metrics(run),
            "performance_metrics": run_performance_metrics(run),
            "executions": execution_page,
            "execution_page": execution_page,
            "filter_query": _filter_query(request),
            "filter_options": filter_options(),
            "run_comment_form": CommentForm(),
            "baseline_promotion_form": BaselinePromotionForm(),
            "conversation_attempt": getattr(run, "conversation_attempt", None),
        },
    )


@login_required
def execution_list(request):
    """Attention and review queue list used by dashboard drill-down links."""

    executions = (
        Execution.objects.select_related(
            "run",
            "run__target",
            "question",
            "question__domain",
            "target_snapshot",
            "build_snapshot",
            "current_human_review",
            "conversation_attempt",
        )
        .prefetch_related("question__tags")
        .order_by("-completed_at", "-pk")
    )
    executions = filter_executions(executions, request.GET)
    page = Paginator(executions, 50).get_page(request.GET.get("page"))
    prepare_runtime_telemetry_for_display(page.object_list)
    return render(
        request,
        "evaluations/execution_list.html",
        {
            "page": page,
            "filter_query": _filter_query(request),
            "filter_options": filter_options(),
            "outcomes": Execution.Outcome.choices,
            "validities": Execution.Validity.choices,
            "review_states": Execution.ReviewState.choices,
            "human_judgments": HumanReview.Judgment.choices,
            "change_states": ComparisonItem.ChangeState.choices,
            "semantic_outcomes": SemanticComparisonResult.Outcome.choices,
        },
    )


@login_required
def execution_csv_export(request):
    executions = (
        Execution.objects.select_related("run", "target_snapshot", "build_snapshot", "current_human_review")
        .order_by("-completed_at", "-pk")
    )
    executions = filter_executions(executions, request.GET)
    columns = [
        "execution_id",
        "run_id",
        "question_id",
        "question_version",
        "question",
        "product",
        "environment",
        "target",
        "build_version",
        "build_id",
        "git_sha",
        "executed_at",
        "outcome",
        "observed_latency_ms",
        "performance_policy_version",
        "performance_classification",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "runtime",
        "model",
        "validity",
        "human_judgment",
        "review_state",
        "raw_answer",
        "display_answer",
    ]
    return _csv_response(filename="stewardbench-executions.csv", columns=columns, rows=(execution_csv_row(row) for row in executions))


@login_required
def run_csv_export(request, run_id):
    run = get_object_or_404(EvaluationRun, pk=run_id)
    executions = filter_executions(
        run.executions.select_related("run", "target_snapshot", "build_snapshot", "current_human_review").order_by("question_order"),
        request.GET,
    )
    columns = [
        "execution_id",
        "run_id",
        "question_id",
        "question_version",
        "question",
        "product",
        "environment",
        "target",
        "build_version",
        "build_id",
        "git_sha",
        "executed_at",
        "outcome",
        "observed_latency_ms",
        "performance_policy_version",
        "performance_classification",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "runtime",
        "model",
        "validity",
        "human_judgment",
        "review_state",
        "raw_answer",
        "display_answer",
    ]
    return _csv_response(
        filename=f"stewardbench-run-{run.pk}-executions.csv",
        columns=columns,
        rows=(execution_csv_row(row) for row in executions),
    )


@login_required
def run_json_export(request, run_id):
    run = get_object_or_404(EvaluationRun, pk=run_id)
    response = JsonResponse(run_export(run), json_dumps_params={"ensure_ascii": False, "indent": 2})
    response["Content-Disposition"] = f'attachment; filename="stewardbench-run-{run.pk}.json"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def run_progress_view(request, run_id):
    run = get_object_or_404(EvaluationRun, pk=run_id)
    return JsonResponse(
        {
            "state": run.state,
            **run_progress(run),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
    )


def _review_queue(run, request):
    scope = request.GET.get("queue", "all")
    if scope not in {"all", "unreviewed", "required"}:
        scope = "all"
    supplied_ids = []
    for value in request.GET.get("queue_ids", "").split(","):
        if not value:
            continue
        try:
            supplied_ids.append(int(value))
        except ValueError:
            continue
    base = run.executions.order_by("question_order")
    if supplied_ids:
        available = set(base.filter(pk__in=supplied_ids).values_list("pk", flat=True))
        ids = [value for value in supplied_ids if value in available]
    else:
        if scope == "unreviewed":
            base = base.filter(
                outcome__in=(Execution.Outcome.SUCCESS, Execution.Outcome.ERROR, Execution.Outcome.TIMEOUT),
                current_human_review__isnull=True,
            )
        elif scope == "required":
            base = base.filter(review_state=Execution.ReviewState.REQUIRED)
        ids = list(base.values_list("pk", flat=True))
    return scope, ids


def _execution_detail_redirect(execution, return_queue: str = ""):
    """Return to the same bounded review queue after an M5 action.

    Review actions change the live state of an item.  The explicit queue id
    list is retained so the reviewer stays at the same position instead of
    quietly losing the reviewed item from an ``unreviewed`` filter.
    """

    supplied = parse_qs(return_queue, keep_blank_values=False)
    scope = supplied.get("queue", ["all"])[0]
    if scope not in {"all", "unreviewed", "required"}:
        scope = "all"
    ids = []
    for value in supplied.get("queue_ids", [""])[0].split(","):
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    query = urlencode({"queue": scope, "queue_ids": ",".join(str(value) for value in ids)})
    return redirect(f"{reverse('execution-detail', args=[execution.pk])}?{query}")


@login_required
def execution_detail(request, execution_id):
    execution = get_object_or_404(
        Execution.objects.select_related(
            "run",
            "question",
            "question_version",
            "target_snapshot",
            "build_snapshot",
            "current_human_review",
            "current_human_review__reviewed_by",
            "invalidated_by",
            "source_execution",
            "source_execution__run",
            "conversation_attempt",
            "conversation_attempt__scenario_version",
            "conversation_attempt__scenario_version__scenario",
            "conversation_turn",
        ).prefetch_related(
            "resolved_bindings",
            "comments__author",
            "review_history__reviewed_by",
            "review_tracking_events__actor",
            "validity_history__decided_by",
            "automated_results",
            Prefetch("llm_judge_results", queryset=LLMJudgeResult.objects.select_related("invocation", "supersedes")),
            "evaluation_invocations",
            "retried_executions__run",
        ),
        pk=execution_id,
    )

    queue_scope, queue_ids = _review_queue(execution.run, request)
    try:
        queue_position = queue_ids.index(execution.pk)
    except ValueError:
        queue_position = None
    previous_execution_id = queue_ids[queue_position - 1] if queue_position not in {None, 0} else None
    next_execution_id = (
        queue_ids[queue_position + 1]
        if queue_position is not None and queue_position + 1 < len(queue_ids)
        else None
    )
    queue_query = urlencode({"queue": queue_scope, "queue_ids": ",".join(str(value) for value in queue_ids)})
    next_unreviewed = (
        execution.run.executions.filter(
            outcome__in=(Execution.Outcome.SUCCESS, Execution.Outcome.ERROR, Execution.Outcome.TIMEOUT),
            current_human_review__isnull=True,
        )
        .exclude(pk=execution.pk)
        .order_by("question_order")
        .first()
    )
    next_required = (
        execution.run.executions.filter(review_state=Execution.ReviewState.REQUIRED)
        .exclude(pk=execution.pk)
        .order_by("question_order")
        .first()
    )
    comparison_item = (
        ComparisonItem.objects.filter(current_execution=execution)
        .select_related(
            "comparison",
            "comparison__baseline",
            "baseline_execution",
            "baseline_execution__target_snapshot",
            "baseline_execution__build_snapshot",
            "baseline_execution__current_human_review",
            "current_execution__current_human_review",
        )
        .prefetch_related(
            "baseline_execution__resolved_bindings",
            Prefetch(
                "semantic_results",
                queryset=SemanticComparisonResult.objects.select_related("supersedes").order_by(
                    "-created_at", "-id"
                ),
            ),
        )
        .first()
    )
    prepare_runtime_telemetry_for_display(
        (execution, comparison_item.baseline_execution) if comparison_item else (execution,)
    )
    semantic_history = list(comparison_item.semantic_results.all()) if comparison_item else []
    current_semantic_result = _current_semantic_result_from_history(semantic_history)
    judge_history = list(execution.llm_judge_results.all())
    current_judge = current_judge_result(execution)
    return render(
        request,
        "evaluations/execution_detail.html",
        {
            "execution": execution,
            "execution_operator_answer": operator_answer_presentation(execution.response_metadata),
            "review_form": HumanReviewForm(),
            "execution_comment_form": CommentForm(),
            "review_state_form": ReviewStateForm(),
            "validity_form": ValidityForm(initial={"validity": Execution.Validity.INVALID}),
            "retry_request_key": uuid.uuid4(),
            "queue_scope": queue_scope,
            "queue_ids": queue_ids,
            "queue_position": queue_position,
            "queue_query": queue_query,
            "previous_execution_id": previous_execution_id,
            "next_execution_id": next_execution_id,
            "next_unreviewed": next_unreviewed,
            "next_required": next_required,
            "comparison_item": comparison_item,
            "comparison_transition": comparison_human_transition(comparison_item) if comparison_item else None,
            "baseline_operator_answer": (
                operator_answer_presentation(comparison_item.baseline_execution.response_metadata)
                if comparison_item
                else None
            ),
            "semantic_history": semantic_history,
            "current_semantic_result": current_semantic_result,
            "current_automated_results": current_automated_results(execution),
            "automated_history": list(execution.automated_results.all()),
            "judge_history": judge_history,
            "current_judge_result": current_judge,
            "judge_disagreement": judge_disagrees_with_human(execution, current_judge),
            "evaluation_invocations": list(execution.evaluation_invocations.all()),
            "conversation_transcript": (
                execution.run.executions.select_related("conversation_turn", "current_human_review")
                .filter(conversation_attempt=execution.conversation_attempt)
                .order_by("conversation_turn__ordinal")
                if execution.conversation_attempt_id
                else None
            ),
        },
    )


@login_required
def judge_reevaluate_view(request, execution_id):
    """ADMIN-only M9 re-evaluation request for a stored answer.

    This POST creates evaluator work only.  It does not launch a Run, retry an
    Execution, or make an evaluated-product request.
    """

    if request.method != "POST":
        raise PermissionDenied("A POST is required to re-evaluate a stored answer.")
    _require_admin(request)
    execution = get_object_or_404(Execution, pk=execution_id)
    try:
        invocation = enqueue_evaluator_invocation(
            actor=request.user,
            execution=execution,
            kind=EvaluationInvocation.Kind.JUDGE,
        )
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Queued LLM judge evaluation {invocation.pk} for the stored answer; no target request was created.",
        )
    return redirect("execution-detail", execution_id=execution.pk)


@login_required
def evaluator_reevaluate_view(request, execution_id):
    """ADMIN-only request to rerun the selected deterministic evaluator later."""

    if request.method != "POST":
        raise PermissionDenied("A POST is required to re-evaluate a stored answer.")
    _require_admin(request)
    execution = get_object_or_404(Execution, pk=execution_id)
    try:
        invocation = enqueue_evaluator_invocation(
            actor=request.user,
            execution=execution,
            kind=EvaluationInvocation.Kind.EVALUATOR,
        )
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Queued evaluator evaluation {invocation.pk} for the stored answer; no target request was created.",
        )
    return redirect("execution-detail", execution_id=execution.pk)


@login_required
def baseline_list(request):
    baselines = (
        Baseline.objects.select_related(
            "source_run",
            "source_run__target_snapshot",
            "source_run__build_snapshot",
            "source_target",
            "source_target__product",
            "source_target__environment",
            "created_by",
        )
        .prefetch_related("attention_events")
        .all()
    )
    return render(
        request,
        "evaluations/baseline_list.html",
        {"baseline_rows": [(baseline, baseline_completeness(baseline)) for baseline in baselines]},
    )


@login_required
def baseline_detail(request, baseline_id):
    baseline = get_object_or_404(
        Baseline.objects.select_related(
            "source_run",
            "source_run__target_snapshot",
            "source_run__build_snapshot",
            "source_target",
            "source_target__product",
            "source_target__environment",
            "created_by",
        ).prefetch_related(
            "state_history__actor",
            "attention_events__execution",
            "attention_events__actor",
        ),
        pk=baseline_id,
    )
    memberships = baseline.memberships.select_related(
        "execution",
        "execution__question_version",
        "execution__target_snapshot",
        "execution__build_snapshot",
        "execution__current_human_review",
    ).prefetch_related("execution__resolved_bindings").order_by("execution__question_order")
    return render(
        request,
        "evaluations/baseline_detail.html",
        {
            "baseline": baseline,
            "completeness": baseline_completeness(baseline),
            "memberships": memberships,
            "state_form": BaselineStateForm(initial={"is_active": not baseline.is_active}),
            "comparison_form": ControlledComparisonRunForm(
                baseline=baseline,
                conversation_required=ConversationAttempt.objects.filter(run=baseline.source_run).exists(),
                initial={"target": baseline.source_target_id},
            ),
        },
    )


@login_required
def create_baseline_view(request, run_id):
    _require_admin(request)
    run = get_object_or_404(EvaluationRun, pk=run_id)
    if request.method != "POST":
        return redirect("run-detail", run_id=run.pk)
    form = BaselinePromotionForm(request.POST)
    if form.is_valid():
        try:
            baseline = create_baseline(actor=request.user, source_run=run, **form.cleaned_data)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(
                request,
                f"Baseline {baseline.name} was created from fixed historical observations; it is not ground truth.",
            )
            return redirect("baseline-detail", baseline_id=baseline.pk)
    else:
        messages.error(request, "Baseline could not be created. Provide a name and review the completeness warning.")
    return redirect("run-detail", run_id=run.pk)


@login_required
def baseline_state_view(request, baseline_id):
    _require_admin(request)
    baseline = get_object_or_404(Baseline, pk=baseline_id)
    if request.method == "POST":
        form = BaselineStateForm(request.POST)
        if form.is_valid():
            try:
                event = set_baseline_active(
                    actor=request.user,
                    baseline=baseline,
                    is_active=form.cleaned_data["is_active"],
                )
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                if event:
                    messages.success(request, f"Baseline is now {'ACTIVE' if event.is_active else 'INACTIVE'}.")
                else:
                    messages.info(request, "Baseline already has that active state.")
        else:
            messages.error(request, "Baseline state could not be changed.")
    return redirect("baseline-detail", baseline_id=baseline.pk)


@login_required
def launch_controlled_comparison_view(request, baseline_id):
    _require_admin(request)
    baseline = get_object_or_404(Baseline.objects.select_related("source_target"), pk=baseline_id)
    if request.method != "POST":
        return redirect("baseline-detail", baseline_id=baseline.pk)
    conversation_required = ConversationAttempt.objects.filter(run=baseline.source_run).exists()
    form = ControlledComparisonRunForm(request.POST, baseline=baseline, conversation_required=conversation_required)
    if form.is_valid():
        try:
            run = launch_controlled_comparison(
                actor=request.user,
                baseline=baseline,
                target=form.cleaned_data["target"],
            )
        except (PermissionDenied, ValidationError) as error:
            messages.error(request, getattr(error, "messages", [str(error)])[0])
        else:
            messages.success(
                request,
                f"Controlled comparison Run {run.id} created with current target identity and exact baseline inputs.",
            )
            return redirect("run-detail", run_id=run.pk)
    else:
        messages.error(request, "Controlled comparison could not be launched.")
    return redirect("baseline-detail", baseline_id=baseline.pk)


@login_required
def comparison_list(request):
    comparisons = Comparison.objects.select_related(
        "baseline",
        "current_run",
        "current_run__target_snapshot",
        "current_run__build_snapshot",
    ).all()
    comparisons = filter_comparisons(comparisons, request.GET)
    page = Paginator(comparisons, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "evaluations/comparison_list.html",
        {
            "page": page,
            "comparison_rows": [(comparison, comparison_summary(comparison)) for comparison in page],
            "filter_query": _filter_query(request),
            "filter_options": filter_options(),
        },
    )


@login_required
def comparison_detail(request, comparison_id):
    comparison = get_object_or_404(
        Comparison.objects.select_related(
            "baseline",
            "current_run",
            "current_run__target_snapshot",
            "current_run__build_snapshot",
        ),
        pk=comparison_id,
    )
    current_semantic_results = SemanticComparisonResult.objects.filter(
        superseded_by__isnull=True
    ).order_by("-created_at", "-id")
    semantic_outcome = current_semantic_results.filter(
        comparison_item_id=OuterRef("pk")
    ).values("outcome")[:1]
    items = comparison.items.select_related(
        "baseline_execution",
        "baseline_execution__current_human_review",
        "current_execution",
        "current_execution__current_human_review",
        "current_execution__target_snapshot",
        "current_execution__build_snapshot",
    ).prefetch_related(Prefetch("semantic_results", queryset=current_semantic_results))
    items = filter_comparison_items(items, request.GET)
    items = items.annotate(
        semantic_outcome=Subquery(semantic_outcome),
        triage_priority=Case(
            When(current_execution__outcome__in=(Execution.Outcome.ERROR, Execution.Outcome.TIMEOUT), then=Value(1)),
            When(
                baseline_execution__current_human_review__judgment="GOOD",
                current_execution__current_human_review__judgment="BAD",
                then=Value(2),
            ),
            When(
                current_execution__current_human_review__judgment="BAD",
                then=Value(3),
            ),
            When(
                semantic_outcome=SemanticComparisonResult.Outcome.MATERIAL_CHANGE,
                then=Value(4),
            ),
            When(
                semantic_outcome=SemanticComparisonResult.Outcome.UNCERTAIN,
                then=Value(5),
            ),
            When(
                semantic_outcome=SemanticComparisonResult.Outcome.ERROR,
                then=Value(6),
            ),
            When(change_state=ComparisonItem.ChangeState.NON_COMPARABLE, then=Value(7)),
            When(
                change_state=ComparisonItem.ChangeState.CHANGED,
                current_execution__review_state=Execution.ReviewState.REQUIRED,
                then=Value(8),
            ),
            When(
                baseline_execution__current_human_review__judgment="BAD",
                current_execution__current_human_review__judgment="GOOD",
                then=Value(9),
            ),
            default=Value(10),
            output_field=IntegerField(),
        )
    ).order_by("triage_priority", "current_execution__question_order")
    page = Paginator(items, 50).get_page(request.GET.get("page"))
    for item in page.object_list:
        prepare_runtime_telemetry_for_display((item.baseline_execution, item.current_execution))
    return render(
        request,
        "evaluations/comparison_detail.html",
        {
            "comparison": comparison,
            "summary": comparison_summary(comparison),
            "item_rows": [
                (
                    item,
                    comparison_human_transition(item),
                    _current_semantic_result_from_history(item.semantic_results.all()),
                )
                for item in page
            ],
            "page": page,
            "filter_query": _filter_query(request),
            "selected_state": request.GET.get("state", ""),
            "selected_outcome": request.GET.get("outcome", ""),
            "selected_review": request.GET.get("review", ""),
            "selected_transition": request.GET.get("transition", ""),
            "selected_semantic": request.GET.get("semantic", ""),
            "selected_performance_change": request.GET.get("performance_change", ""),
            "selected_band_degraded": request.GET.get("band_degraded", ""),
            "selected_sort": request.GET.get("sort", ""),
        },
    )


@login_required
def comparison_csv_export(request, comparison_id):
    comparison = get_object_or_404(Comparison, pk=comparison_id)
    items = (
        comparison.items.select_related("comparison", "baseline_execution", "current_execution")
        .prefetch_related("semantic_results")
        .order_by("current_execution__question_order")
    )
    items = filter_comparison_items(items, request.GET)
    columns = [
        "comparison_id",
        "comparison_item_id",
        "run_id",
        "question_id",
        "question_version",
        "current_outcome",
        "validity",
        "review_state",
        "exact_change_state",
        "semantic_result",
        "human_transition",
        "baseline_latency_ms",
        "current_latency_ms",
        "latency_delta_ms",
        "latency_delta_percent",
        "baseline_performance_classification",
        "current_performance_classification",
        "performance_change",
        "performance_band_degraded",
        "baseline_input_tokens",
        "current_input_tokens",
        "input_token_delta",
        "input_token_delta_percent",
        "baseline_output_tokens",
        "current_output_tokens",
        "output_token_delta",
        "output_token_delta_percent",
        "baseline_total_tokens",
        "current_total_tokens",
        "total_token_delta",
        "total_token_delta_percent",
        "baseline_runtime",
        "current_runtime",
        "baseline_model",
        "current_model",
        "baseline_answer",
        "current_answer",
    ]
    return _csv_response(
        filename=f"stewardbench-comparison-{comparison.pk}.csv",
        columns=columns,
        rows=(comparison_csv_row(item) for item in items),
    )


@login_required
def semantic_reevaluate_view(request, item_id):
    _require_admin(request)
    item = get_object_or_404(ComparisonItem, pk=item_id)
    if request.method != "POST":
        return redirect("execution-detail", execution_id=item.current_execution_id)
    try:
        result = reevaluate_semantic_comparison(actor=request.user, comparison_item=item)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(
            request,
            f"Appended semantic result {result.outcome} using {result.provider_key} "
            f"{result.comparator_version}; exact comparison history is unchanged.",
        )
    return redirect("execution-detail", execution_id=item.current_execution_id)


@login_required
def record_human_review_view(request, execution_id):
    _require_admin(request)
    execution = get_object_or_404(Execution, pk=execution_id)
    if request.method != "POST":
        return _execution_detail_redirect(execution)
    form = HumanReviewForm(request.POST)
    if form.is_valid():
        try:
            review = record_human_review(
                actor=request.user,
                execution=execution,
                judgment=form.cleaned_data["judgment"],
                comment_text=form.cleaned_data["comment"],
            )
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, f"Recorded human {review.judgment} review.")
    else:
        messages.error(request, "Review could not be recorded.")
    return _execution_detail_redirect(execution, request.POST.get("return_queue", ""))


@login_required
def execution_comment_view(request, execution_id):
    _require_admin(request)
    execution = get_object_or_404(Execution, pk=execution_id)
    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            try:
                append_execution_comment(actor=request.user, execution=execution, text=form.cleaned_data["text"])
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                messages.success(request, "Execution comment appended.")
        else:
            messages.error(request, "A non-empty execution comment is required.")
    return _execution_detail_redirect(execution, request.POST.get("return_queue", ""))


@login_required
def review_state_view(request, execution_id):
    _require_admin(request)
    execution = get_object_or_404(Execution, pk=execution_id)
    if request.method == "POST":
        form = ReviewStateForm(request.POST)
        if form.is_valid():
            try:
                if form.cleaned_data["state"] == Execution.ReviewState.REQUIRED:
                    mark_review_required(actor=request.user, execution=execution)
                    messages.success(request, "Execution marked review required.")
                else:
                    mark_reviewed_without_judgment(
                        actor=request.user,
                        execution=execution,
                        comment_text=form.cleaned_data["comment"],
                    )
                    messages.success(request, "Infrastructure triage recorded without a human judgment.")
            except ValidationError as error:
                messages.error(request, error.messages[0])
        else:
            messages.error(request, "Review state could not be changed.")
    return _execution_detail_redirect(execution, request.POST.get("return_queue", ""))


@login_required
def execution_validity_view(request, execution_id):
    _require_admin(request)
    execution = get_object_or_404(Execution, pk=execution_id)
    if request.method == "POST":
        form = ValidityForm(request.POST)
        if form.is_valid():
            try:
                decision = set_execution_validity(
                    actor=request.user,
                    execution=execution,
                    validity=form.cleaned_data["validity"],
                    comment_text=form.cleaned_data["comment"],
                )
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                if decision:
                    messages.success(request, f"Validity changed to {decision.validity}.")
                else:
                    messages.info(request, "Execution already has that validity.")
        else:
            messages.error(request, "Validity could not be changed.")
    return _execution_detail_redirect(execution, request.POST.get("return_queue", ""))


@login_required
def retry_execution_view(request, execution_id):
    _require_admin(request)
    execution = get_object_or_404(Execution, pk=execution_id)
    if request.method != "POST":
        return _execution_detail_redirect(execution, request.POST.get("return_queue", ""))
    try:
        run = retry_execution(
            actor=request.user,
            execution=execution,
            retry_request_key=request.POST.get("retry_request_key"),
        )
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return _execution_detail_redirect(execution, request.POST.get("return_queue", ""))
    messages.success(request, f"Created new retry Run {run.id}; the original Execution is unchanged.")
    return redirect("run-detail", run_id=run.pk)


@login_required
def run_comment_view(request, run_id):
    _require_admin(request)
    run = get_object_or_404(EvaluationRun, pk=run_id)
    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            try:
                append_run_comment(actor=request.user, run=run, text=form.cleaned_data["text"])
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                messages.success(request, "Run comment appended.")
        else:
            messages.error(request, "A non-empty run comment is required.")
    return redirect("run-detail", run_id=run.pk)


@login_required
def rerun_source_run_view(request, run_id):
    _require_admin(request)
    source_run = get_object_or_404(EvaluationRun, pk=run_id)
    if request.method != "POST":
        return redirect("run-detail", run_id=source_run.pk)
    selected = request.POST.getlist("execution_ids")
    try:
        run = rerun_source_run(
            actor=request.user,
            source_run=source_run,
            source_execution_ids=selected if request.POST.get("rerun_scope") == "selected" else None,
        )
    except (TypeError, ValueError, ValidationError) as error:
        messages.error(request, getattr(error, "messages", [str(error)])[0])
        return redirect("run-detail", run_id=source_run.pk)
    messages.success(request, f"Created new rerun {run.id}; source Run {source_run.id} is unchanged.")
    return redirect("run-detail", run_id=run.pk)


@login_required
def launch_run_view(request):
    _require_admin(request)
    selected_ids = request.GET.getlist("question")
    if request.method == "POST":
        form = LaunchRunForm(request.POST)
        if form.is_valid():
            try:
                run = launch_run(
                    actor=request.user,
                    target=form.cleaned_data["target"],
                    question_ids=request.POST.getlist("question_ids"),
                    select_all=form.cleaned_data["select_all_matching"],
                    filters=_filters_from_request(request),
                    execution_mode=form.cleaned_data["execution_mode"],
                )
            except (PermissionDenied, ValidationError) as error:
                form.add_error(None, error)
            else:
                messages.success(request, f"{run.get_requested_mode_display()} run {run.id} was created and is awaiting the worker.")
                return redirect("run-detail", run_id=run.id)
    else:
        form = LaunchRunForm(initial={"select_all_matching": request.GET.get("all") == "1"})
    filters = {
        key: request.POST.get(key, request.GET.get(key, "")).strip()
        for key in ("q", "domain", "tag", "lifecycle")
        if request.POST.get(key, request.GET.get(key, "")).strip()
    }
    return render(
        request,
        "evaluations/run_launch.html",
        {
            "form": form,
            "selected_ids": selected_ids if request.method == "GET" else request.POST.getlist("question_ids"),
            "filters": filters,
            "eligible_count": eligible_question_count(filters),
        },
    )


@login_required
def launch_one_question_view(request, question_id):
    _require_admin(request)
    question = get_object_or_404(Question, pk=question_id)
    if request.method == "POST":
        form = LaunchRunForm(request.POST)
        if form.is_valid():
            try:
                run = launch_run(
                    actor=request.user,
                    target=form.cleaned_data["target"],
                    question_ids=(question.pk,),
                    execution_mode=form.cleaned_data["execution_mode"],
                )
            except (PermissionDenied, ValidationError) as error:
                form.add_error(None, error)
            else:
                messages.success(request, f"{run.get_requested_mode_display()} run {run.id} was created and is awaiting the worker.")
                return redirect("run-detail", run_id=run.id)
    else:
        form = LaunchRunForm()
    return render(
        request,
        "evaluations/run_launch.html",
        {
            "form": form,
            "single_question": question,
            "selected_ids": [str(question.pk)],
            "filters": {},
            "eligible_count": 1,
        },
    )


@login_required
def launch_conversation_scenario_view(request, stable_id):
    _require_admin(request)
    scenario = get_object_or_404(ConversationScenario, stable_id=stable_id)
    if request.method == "POST":
        form = LaunchConversationForm(request.POST)
        if form.is_valid():
            try:
                run = launch_conversation_scenario(
                    actor=request.user,
                    scenario=scenario,
                    target=form.cleaned_data["target"],
                )
            except (PermissionDenied, ValidationError) as error:
                form.add_error(None, error)
            else:
                messages.success(request, f"Conversation Run {run.id} was created from turn 1 with a fresh target session.")
                return redirect("run-detail", run_id=run.pk)
    else:
        form = LaunchConversationForm()
    return render(
        request,
        "evaluations/conversation_launch.html",
        {"form": form, "scenario": scenario, "version": scenario.current_version},
    )


@login_required
def retry_conversation_attempt_view(request, attempt_id):
    _require_admin(request)
    attempt = get_object_or_404(ConversationAttempt, pk=attempt_id)
    if request.method != "POST":
        return redirect("run-detail", run_id=attempt.run_id)
    try:
        run = retry_conversation_attempt(
            actor=request.user,
            attempt=attempt,
            retry_request_key=request.POST.get("retry_request_key"),
        )
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect("run-detail", run_id=attempt.run_id)
    messages.success(request, f"Created complete conversation retry Run {run.id} from turn 1 in a fresh session.")
    return redirect("run-detail", run_id=run.pk)
