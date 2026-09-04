from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.policy import require_admin
from evaluations.models import Execution
from evaluations.reporting import latency_statistics, prepare_runtime_telemetry_for_display, question_trend_rows

from .forms import (
    BindingDefinitionFormSet,
    ConversationScenarioForm,
    ConversationScenarioMetadataForm,
    ConversationScenarioVersionForm,
    ConversationTurnFormSet,
    DomainCreateForm,
    DomainUpdateForm,
    EnvironmentCreateForm,
    EnvironmentUpdateForm,
    HistoricalFixtureForm,
    ProductCreateForm,
    ProductUpdateForm,
    QuestionCreateForm,
    QuestionMetadataForm,
    QuestionVersionForm,
    TagCreateForm,
    TargetIdentityForm,
    TargetRevisionForm,
    TargetUpdateForm,
)
from .models import (
    Domain,
    ConversationScenario,
    Environment,
    EvaluationTarget,
    HistoricalFixture,
    Product,
    Question,
    Tag,
)
from .services import (
    create_domain,
    create_conversation_scenario,
    create_conversation_scenario_version,
    create_environment,
    create_historical_fixture,
    create_product,
    create_question,
    create_question_version,
    create_tag,
    create_target,
    create_target_revision,
    set_question_lifecycle,
    update_domain,
    update_conversation_scenario_metadata,
    update_environment,
    update_product,
    update_question_metadata,
    update_target,
)


def _require_admin(request):
    require_admin(request.user)


def _service_error(form, error):
    if hasattr(error, "message_dict"):
        for field, errors in error.message_dict.items():
            target = field if field in form.fields else None
            for message in errors:
                form.add_error(target, message)
    else:
        form.add_error(None, error)


def _binding_values(formset):
    return [
        {
            "name": row["name"],
            "value_type": row["value_type"],
            "is_required": row["is_required"],
            "description": row["description"],
            "fixed_value": row.get("fixed_value"),
        }
        for row in formset.cleaned_data
        if row and row.get("name") and not row.get("DELETE")
    ]


def _conversation_turn_values(formset):
    return [
        {
            "prompt_template": row.get("prompt_template", ""),
            "canonical_question_version": row.get("canonical_question_version"),
            "static_bindings": row.get("static_bindings") or {},
            "required_for_overall": row.get("required_for_overall", True),
        }
        for row in formset.cleaned_data
        if row
        and not row.get("DELETE")
        and (row.get("prompt_template", "").strip() or row.get("canonical_question_version"))
    ]


def _render_form(request, *, form, heading, cancel_url, template="catalog/form.html"):
    return render(
        request,
        template,
        {"form": form, "heading": heading, "cancel_url": cancel_url},
    )


@login_required
def product_list(request):
    return render(request, "catalog/product_list.html", {"products": Product.objects.all()})


@login_required
def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug)
    return render(
        request,
        "catalog/product_detail.html",
        {"product": product, "targets": product.targets.select_related("environment")},
    )


@login_required
def product_create(request):
    _require_admin(request)
    form = ProductCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            product = create_product(actor=request.user, **form.cleaned_data)
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Product {product.display_name} created.")
            return redirect("product-detail", slug=product.slug)
    return _render_form(
        request,
        form=form,
        heading="Create product",
        cancel_url="product-list",
    )


@login_required
def product_update(request, slug):
    _require_admin(request)
    product = get_object_or_404(Product, slug=slug)
    form = ProductUpdateForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid():
        try:
            product = update_product(actor=request.user, product=product, **form.cleaned_data)
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Product {product.display_name} updated.")
            return redirect("product-detail", slug=product.slug)
    return _render_form(
        request,
        form=form,
        heading=f"Edit {product.display_name}",
        cancel_url="product-list",
    )


@login_required
def environment_list(request):
    return render(
        request,
        "catalog/environment_list.html",
        {"environments": Environment.objects.all()},
    )


@login_required
def environment_detail(request, slug):
    environment = get_object_or_404(Environment, slug=slug)
    return render(
        request,
        "catalog/environment_detail.html",
        {
            "environment": environment,
            "targets": environment.targets.select_related("product"),
            "fixtures": environment.historical_fixtures.prefetch_related("tags"),
        },
    )


@login_required
def environment_create(request):
    _require_admin(request)
    form = EnvironmentCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            environment = create_environment(actor=request.user, **form.cleaned_data)
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Environment {environment.display_name} created.")
            return redirect("environment-detail", slug=environment.slug)
    return _render_form(
        request,
        form=form,
        heading="Create environment",
        cancel_url="environment-list",
    )


@login_required
def environment_update(request, slug):
    _require_admin(request)
    environment = get_object_or_404(Environment, slug=slug)
    form = EnvironmentUpdateForm(request.POST or None, instance=environment)
    if request.method == "POST" and form.is_valid():
        try:
            environment = update_environment(
                actor=request.user,
                environment=environment,
                **form.cleaned_data,
            )
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Environment {environment.display_name} updated.")
            return redirect("environment-detail", slug=environment.slug)
    return _render_form(
        request,
        form=form,
        heading=f"Edit {environment.display_name}",
        cancel_url="environment-list",
    )


@login_required
def domain_list(request):
    return render(request, "catalog/domain_list.html", {"domains": Domain.objects.all()})


@login_required
def domain_create(request):
    _require_admin(request)
    form = DomainCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            domain = create_domain(actor=request.user, **form.cleaned_data)
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Domain {domain.name} created.")
            return redirect("domain-list")
    return _render_form(
        request,
        form=form,
        heading="Create domain",
        cancel_url="domain-list",
    )


@login_required
def domain_update(request, slug):
    _require_admin(request)
    domain = get_object_or_404(Domain, slug=slug)
    form = DomainUpdateForm(request.POST or None, instance=domain)
    if request.method == "POST" and form.is_valid():
        try:
            domain = update_domain(actor=request.user, domain=domain, **form.cleaned_data)
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Domain {domain.name} updated.")
            return redirect("domain-list")
    return _render_form(
        request,
        form=form,
        heading=f"Edit {domain.name}",
        cancel_url="domain-list",
    )


@login_required
def tag_list(request):
    return render(request, "catalog/tag_list.html", {"tags": Tag.objects.all()})


@login_required
def tag_create(request):
    _require_admin(request)
    form = TagCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            tag = create_tag(actor=request.user, **form.cleaned_data)
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Tag {tag.name} created.")
            return redirect("tag-list")
    return _render_form(
        request,
        form=form,
        heading="Create tag",
        cancel_url="tag-list",
    )


@login_required
def fixture_list(request):
    fixtures = HistoricalFixture.objects.select_related(
        "environment", "created_by"
    ).prefetch_related("tags")
    return render(request, "catalog/fixture_list.html", {"fixtures": fixtures})


@login_required
def fixture_create(request):
    _require_admin(request)
    form = HistoricalFixtureForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            fixture = create_historical_fixture(actor=request.user, **form.cleaned_data)
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Historical fixture {fixture.name} created.")
            return redirect("fixture-list")
    return _render_form(
        request,
        form=form,
        heading="Create historical fixture",
        cancel_url="fixture-list",
    )


@login_required
def target_list(request):
    targets = EvaluationTarget.objects.select_related("product", "environment").prefetch_related(
        "revisions"
    )
    if request.GET.get("active") == "1":
        targets = targets.filter(is_active=True, revisions__valid_to__isnull=True).distinct()
    return render(request, "catalog/target_list.html", {"targets": targets})


@login_required
def target_detail(request, slug):
    target = get_object_or_404(
        EvaluationTarget.objects.select_related("product", "environment"),
        slug=slug,
    )
    return render(
        request,
        "catalog/target_detail.html",
        {
            "target": target,
            "current_revision": target.current_revision,
            "revisions": target.revisions.all(),
            "latest_execution": Execution.objects.filter(run__target=target)
            .select_related("build_snapshot", "run")
            .order_by("-completed_at", "-pk")
            .first(),
        },
    )


@login_required
def target_create(request):
    _require_admin(request)
    identity_form = TargetIdentityForm(request.POST or None, prefix="target")
    revision_form = TargetRevisionForm(request.POST or None, prefix="revision")
    if request.method == "POST" and identity_form.is_valid() and revision_form.is_valid():
        try:
            target = create_target(
                actor=request.user,
                revision=revision_form.cleaned_data,
                **identity_form.cleaned_data,
            )
        except (PermissionDenied, ValidationError) as error:
            _service_error(revision_form, error)
        else:
            messages.success(request, f"Target {target.display_name} created with revision 1.")
            return redirect("target-detail", slug=target.slug)
    return render(
        request,
        "catalog/target_form.html",
        {"identity_form": identity_form, "revision_form": revision_form},
    )


@login_required
def target_update(request, slug):
    _require_admin(request)
    target = get_object_or_404(EvaluationTarget, slug=slug)
    form = TargetUpdateForm(
        request.POST or None,
        initial={"display_name": target.display_name, "is_active": target.is_active},
    )
    if request.method == "POST" and form.is_valid():
        try:
            target = update_target(actor=request.user, target=target, **form.cleaned_data)
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Target {target.display_name} updated.")
            return redirect("target-detail", slug=target.slug)
    return _render_form(
        request,
        form=form,
        heading=f"Edit {target.display_name}",
        cancel_url="target-list",
    )


@login_required
def target_revision_create(request, slug):
    _require_admin(request)
    target = get_object_or_404(EvaluationTarget, slug=slug)
    current = target.current_revision
    form = TargetRevisionForm(request.POST or None, instance=current)
    if request.method == "POST" and form.is_valid():
        try:
            revision = create_target_revision(
                actor=request.user,
                target=target,
                **form.cleaned_data,
            )
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Target revision {revision.revision_number} created.")
            return redirect("target-detail", slug=target.slug)
    return _render_form(
        request,
        form=form,
        heading=f"New revision for {target.display_name}",
        cancel_url="target-list",
    )


@login_required
def question_list(request):
    questions = Question.objects.select_related("domain").prefetch_related("tags", "versions")
    text = request.GET.get("q", "").strip()
    domain = request.GET.get("domain", "").strip()
    tag = request.GET.get("tag", "").strip()
    lifecycle = request.GET.get("lifecycle", "").strip()
    if text:
        questions = questions.filter(
            Q(stable_id__icontains=text)
            | Q(versions__valid_to__isnull=True, versions__question_text__icontains=text)
        )
    if domain:
        questions = questions.filter(domain__slug=domain)
    if tag:
        questions = questions.filter(tags__name=tag)
    if lifecycle in Question.Lifecycle.values:
        questions = questions.filter(lifecycle=lifecycle)
    questions = questions.distinct()
    page = Paginator(questions, 50).get_page(request.GET.get("page"))
    preserved = request.GET.copy()
    preserved.pop("page", None)
    return render(
        request,
        "catalog/question_list.html",
        {
            "page": page,
            "domains": Domain.objects.filter(is_active=True),
            "tags": Tag.objects.all(),
            "lifecycles": Question.Lifecycle.choices,
            "filter_query": preserved.urlencode(),
        },
    )


@login_required
def question_detail(request, stable_id):
    question = get_object_or_404(
        Question.objects.select_related("domain", "created_by", "updated_by").prefetch_related(
            "tags", "versions__created_by", "versions__binding_definitions"
        ),
        stable_id=stable_id,
    )
    execution_history = (
        Execution.objects.filter(question=question)
        .select_related("run", "target_snapshot", "build_snapshot", "current_human_review", "question_version")
        .order_by("-completed_at", "-pk")
    )
    page = Paginator(execution_history, 50).get_page(request.GET.get("page"))
    prepare_runtime_telemetry_for_display(page.object_list)
    return render(
        request,
        "catalog/question_detail.html",
        {
            "question": question,
            "current_version": question.current_version,
            "versions": question.versions.all(),
            "execution_page": page,
            "question_trends": question_trend_rows(question.pk),
            "latency_statistics": latency_statistics(list(execution_history[:500])),
        },
    )


@login_required
def question_create(request):
    _require_admin(request)
    form = QuestionCreateForm(request.POST or None)
    binding_formset = BindingDefinitionFormSet(request.POST or None, prefix="bindings")
    if request.method == "POST" and form.is_valid() and binding_formset.is_valid():
        try:
            question = create_question(
                actor=request.user,
                bindings=_binding_values(binding_formset),
                **form.cleaned_data,
            )
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Question {question.stable_id} created.")
            return redirect("question-detail", stable_id=question.stable_id)
    return render(
        request,
        "catalog/question_form.html",
        {
            "form": form,
            "binding_formset": binding_formset,
            "heading": "Create question",
        },
    )


@login_required
def question_update(request, stable_id):
    _require_admin(request)
    question = get_object_or_404(Question, stable_id=stable_id)
    form = QuestionMetadataForm(
        request.POST or None,
        initial={
            "domain": question.domain,
            "tags": question.tags.all(),
            "rationale": question.rationale,
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            question = update_question_metadata(
                actor=request.user,
                question=question,
                **form.cleaned_data,
            )
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Question {question.stable_id} metadata updated.")
            return redirect("question-detail", stable_id=question.stable_id)
    return _render_form(
        request,
        form=form,
        heading=f"Edit metadata for {question.stable_id}",
        cancel_url="question-list",
    )


@login_required
def question_version_create(request, stable_id):
    _require_admin(request)
    question = get_object_or_404(Question, stable_id=stable_id)
    current = question.current_version
    form = QuestionVersionForm(
        request.POST or None,
        initial={
            "question_text": current.question_text if current else "",
            "evaluation_guidance": current.evaluation_guidance if current else "",
        },
    )
    binding_initial = []
    if current:
        binding_initial = list(
            current.binding_definitions.values(
                "name", "value_type", "is_required", "description", "fixed_value"
            )
        )
    binding_formset = BindingDefinitionFormSet(
        request.POST or None,
        prefix="bindings",
        initial=binding_initial,
    )
    if request.method == "POST" and form.is_valid() and binding_formset.is_valid():
        try:
            version = create_question_version(
                actor=request.user,
                question=question,
                bindings=_binding_values(binding_formset),
                **form.cleaned_data,
            )
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Question version {version.version_number} created.")
            return redirect("question-detail", stable_id=question.stable_id)
    return render(
        request,
        "catalog/question_form.html",
        {
            "form": form,
            "binding_formset": binding_formset,
            "heading": f"New version for {question.stable_id}",
        },
    )


@login_required
@require_POST
def question_lifecycle_update(request, stable_id, lifecycle):
    _require_admin(request)
    question = get_object_or_404(Question, stable_id=stable_id)
    try:
        set_question_lifecycle(actor=request.user, question=question, lifecycle=lifecycle)
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(request, f"Question {question.stable_id} is now {lifecycle}.")
    return redirect("question-detail", stable_id=question.stable_id)


@login_required
def conversation_scenario_list(request):
    scenarios = ConversationScenario.objects.select_related("domain").prefetch_related("tags", "versions")
    return render(request, "catalog/conversation_scenario_list.html", {"scenarios": scenarios})


@login_required
def conversation_scenario_detail(request, stable_id):
    scenario = get_object_or_404(
        ConversationScenario.objects.select_related("domain", "created_by", "updated_by").prefetch_related(
            "tags",
            "versions__created_by",
            "versions__turns__canonical_question",
            "versions__turns__canonical_question_version",
        ),
        stable_id=stable_id,
    )
    from evaluations.models import ConversationAttempt

    attempts = (
        ConversationAttempt.objects.filter(scenario_version__scenario=scenario)
        .select_related("run", "run__target_snapshot", "scenario_version")
        .order_by("-run__created_at")
    )
    return render(
        request,
        "catalog/conversation_scenario_detail.html",
        {
            "scenario": scenario,
            "current_version": scenario.current_version,
            "versions": scenario.versions.all(),
            "attempts": attempts,
        },
    )


@login_required
def conversation_scenario_create(request):
    _require_admin(request)
    form = ConversationScenarioForm(request.POST or None)
    turn_formset = ConversationTurnFormSet(request.POST or None, prefix="turns")
    if request.method == "POST" and form.is_valid() and turn_formset.is_valid():
        try:
            scenario = create_conversation_scenario(
                actor=request.user,
                turns=_conversation_turn_values(turn_formset),
                **form.cleaned_data,
            )
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Conversation scenario {scenario.stable_id} created.")
            return redirect("conversation-scenario-detail", stable_id=scenario.stable_id)
    return render(
        request,
        "catalog/conversation_scenario_form.html",
        {"form": form, "turn_formset": turn_formset, "heading": "Create conversation scenario"},
    )


@login_required
def conversation_scenario_update(request, stable_id):
    _require_admin(request)
    scenario = get_object_or_404(ConversationScenario, stable_id=stable_id)
    form = ConversationScenarioMetadataForm(
        request.POST or None,
        initial={
            "name": scenario.name,
            "description": scenario.description,
            "lifecycle": scenario.lifecycle,
            "domain": scenario.domain,
            "tags": scenario.tags.all(),
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_conversation_scenario_metadata(actor=request.user, scenario=scenario, **form.cleaned_data)
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Conversation scenario {scenario.stable_id} metadata updated.")
            return redirect("conversation-scenario-detail", stable_id=scenario.stable_id)
    return _render_form(
        request,
        form=form,
        heading=f"Edit metadata for {scenario.stable_id}",
        cancel_url="conversation-scenario-list",
    )


@login_required
def conversation_scenario_version_create(request, stable_id):
    _require_admin(request)
    scenario = get_object_or_404(ConversationScenario, stable_id=stable_id)
    current = scenario.current_version
    initial_turns = []
    if current:
        initial_turns = [
            {
                "prompt_template": turn.prompt_template,
                "canonical_question_version": turn.canonical_question_version,
                "static_bindings": turn.static_bindings,
                "required_for_overall": turn.required_for_overall,
            }
            for turn in current.turns.all()
        ]
    form = ConversationScenarioVersionForm(
        request.POST or None,
        initial={"definition": current.definition if current else ""},
    )
    turn_formset = ConversationTurnFormSet(request.POST or None, prefix="turns", initial=initial_turns)
    if request.method == "POST" and form.is_valid() and turn_formset.is_valid():
        try:
            version = create_conversation_scenario_version(
                actor=request.user,
                scenario=scenario,
                turns=_conversation_turn_values(turn_formset),
                **form.cleaned_data,
            )
        except (PermissionDenied, ValidationError) as error:
            _service_error(form, error)
        else:
            messages.success(request, f"Scenario version {version.version_number} created.")
            return redirect("conversation-scenario-detail", stable_id=scenario.stable_id)
    return render(
        request,
        "catalog/conversation_scenario_form.html",
        {
            "form": form,
            "turn_formset": turn_formset,
            "heading": f"New version for {scenario.stable_id}",
            "scenario": scenario,
        },
    )
