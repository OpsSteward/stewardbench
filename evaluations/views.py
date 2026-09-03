from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.policy import require_admin
from catalog.models import Question

from .forms import LaunchRunForm
from .models import EvaluationRun, Execution
from .services import eligible_question_count, launch_run, run_progress


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
        "target", "target__product", "target__environment", "build_snapshot", "launched_by"
    )
    return render(request, "evaluations/run_list.html", {"runs": runs})


@login_required
def run_detail(request, run_id):
    run = get_object_or_404(
        EvaluationRun.objects.select_related(
            "target", "target_revision", "target_snapshot", "build_snapshot", "launched_by"
        ),
        pk=run_id,
    )
    executions = run.executions.select_related("question_version").prefetch_related("resolved_bindings")
    return render(
        request,
        "evaluations/run_detail.html",
        {"run": run, "progress": run_progress(run), "executions": executions},
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


@login_required
def execution_detail(request, execution_id):
    execution = get_object_or_404(
        Execution.objects.select_related(
            "run",
            "question",
            "question_version",
            "target_snapshot",
            "build_snapshot",
        ).prefetch_related("resolved_bindings"),
        pk=execution_id,
    )
    return render(request, "evaluations/execution_detail.html", {"execution": execution})


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
