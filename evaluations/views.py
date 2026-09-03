import uuid
from urllib.parse import parse_qs, urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.policy import require_admin
from catalog.models import Question

from .forms import CommentForm, HumanReviewForm, LaunchRunForm, ReviewStateForm, ValidityForm
from .models import EvaluationRun, Execution
from .services import (
    append_execution_comment,
    append_run_comment,
    eligible_question_count,
    launch_run,
    mark_review_required,
    mark_reviewed_without_judgment,
    record_human_review,
    rerun_source_run,
    retry_execution,
    run_progress,
    run_review_metrics,
    set_execution_validity,
)


def _require_admin(request):
    require_admin(request.user)


def _filters_from_request(request):
    return {
        key: request.POST.get(key, "").strip()
        for key in ("q", "domain", "tag", "lifecycle")
        if request.POST.get(key, "").strip()
    }


@login_required
def run_list(request):
    runs = EvaluationRun.objects.select_related(
        "target", "target__product", "target__environment", "build_snapshot", "launched_by", "source_run"
    )
    return render(request, "evaluations/run_list.html", {"runs": runs})


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
        ).prefetch_related("comments__author"),
        pk=run_id,
    )
    executions = (
        run.executions.select_related("question_version", "current_human_review", "invalidated_by")
        .prefetch_related("resolved_bindings")
        .order_by("question_order")
    )
    return render(
        request,
        "evaluations/run_detail.html",
        {
            "run": run,
            "progress": run_progress(run),
            "review_metrics": run_review_metrics(run),
            "executions": executions,
            "run_comment_form": CommentForm(),
        },
    )


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
        ).prefetch_related(
            "resolved_bindings",
            "comments__author",
            "review_history__reviewed_by",
            "review_tracking_events__actor",
            "validity_history__decided_by",
            "automated_results",
            "llm_judge_results",
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
    return render(
        request,
        "evaluations/execution_detail.html",
        {
            "execution": execution,
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
        },
    )


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
