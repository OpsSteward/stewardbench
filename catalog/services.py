from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.policy import require_admin

from .models import (
    BindingDefinition,
    ConversationScenario,
    ConversationScenarioVersion,
    ConversationTurn,
    Domain,
    Environment,
    EvaluationTarget,
    HistoricalFixture,
    Product,
    Question,
    QuestionVersion,
    Tag,
    TargetRevision,
)


def _validate_and_save(instance):
    instance.full_clean()
    instance.save()
    return instance


@transaction.atomic
def create_product(*, actor, slug, display_name, description="", is_active=True):
    require_admin(actor)
    return _validate_and_save(
        Product(
            slug=slug,
            display_name=display_name,
            description=description,
            is_active=is_active,
            created_by=actor,
            updated_by=actor,
        )
    )


@transaction.atomic
def update_product(*, actor, product, display_name, description, is_active):
    require_admin(actor)
    product.display_name = display_name
    product.description = description
    product.is_active = is_active
    product.updated_by = actor
    return _validate_and_save(product)


@transaction.atomic
def create_environment(*, actor, slug, display_name, description="", is_active=True):
    require_admin(actor)
    return _validate_and_save(
        Environment(
            slug=slug,
            display_name=display_name,
            description=description,
            is_active=is_active,
            created_by=actor,
            updated_by=actor,
        )
    )


@transaction.atomic
def update_environment(*, actor, environment, display_name, description, is_active):
    require_admin(actor)
    environment.display_name = display_name
    environment.description = description
    environment.is_active = is_active
    environment.updated_by = actor
    return _validate_and_save(environment)


@transaction.atomic
def create_domain(*, actor, slug, name, description="", is_active=True):
    require_admin(actor)
    return _validate_and_save(
        Domain(
            slug=slug,
            name=name,
            description=description,
            is_active=is_active,
            created_by=actor,
            updated_by=actor,
        )
    )


@transaction.atomic
def update_domain(*, actor, domain, name, description, is_active):
    require_admin(actor)
    domain.name = name
    domain.description = description
    domain.is_active = is_active
    domain.updated_by = actor
    return _validate_and_save(domain)


@transaction.atomic
def create_tag(*, actor, name):
    require_admin(actor)
    return _validate_and_save(Tag(name=name, created_by=actor))


def _create_target_revision(*, target, actor, revision_number, valid_from, values):
    revision = TargetRevision(
        target=target,
        revision_number=revision_number,
        valid_from=valid_from,
        created_by=actor,
        **values,
    )
    return _validate_and_save(revision)


@transaction.atomic
def create_target(*, actor, slug, display_name, product, environment, revision, is_active=True):
    require_admin(actor)
    target = _validate_and_save(
        EvaluationTarget(
            slug=slug,
            display_name=display_name,
            product=product,
            environment=environment,
            is_active=is_active,
            created_by=actor,
            updated_by=actor,
        )
    )
    _create_target_revision(
        target=target,
        actor=actor,
        revision_number=1,
        valid_from=timezone.now(),
        values=revision,
    )
    return target


@transaction.atomic
def update_target(*, actor, target, display_name, is_active):
    require_admin(actor)
    target.display_name = display_name
    target.is_active = is_active
    target.updated_by = actor
    return _validate_and_save(target)


@transaction.atomic
def create_target_revision(*, actor, target, effective_at=None, **values):
    require_admin(actor)
    locked_target = EvaluationTarget.objects.select_for_update().get(pk=target.pk)
    current = locked_target.revisions.filter(valid_to__isnull=True).first()
    transition_at = effective_at or timezone.now()
    if current and transition_at <= current.valid_from:
        raise ValidationError(
            {"valid_from": "A new revision must begin after the current revision."}
        )
    next_number = (
        locked_target.revisions.aggregate(maximum=Max("revision_number"))["maximum"] or 0
    ) + 1
    if current:
        TargetRevision.objects.filter(pk=current.pk, valid_to__isnull=True).update(
            valid_to=transition_at
        )
    return _create_target_revision(
        target=locked_target,
        actor=actor,
        revision_number=next_number,
        valid_from=transition_at,
        values=values,
    )


def _create_bindings(*, question_version, actor, bindings):
    for binding in bindings or ():
        _validate_and_save(
            BindingDefinition(
                question_version=question_version,
                created_by=actor,
                **binding,
            )
        )


def _create_question_version(
    *, question, actor, version_number, valid_from, question_text, evaluation_guidance,
    change_type, change_reason, bindings
):
    version = _validate_and_save(
        QuestionVersion(
            question=question,
            version_number=version_number,
            question_text=question_text,
            evaluation_guidance=evaluation_guidance,
            change_type=change_type,
            change_reason=change_reason,
            valid_from=valid_from,
            created_by=actor,
        )
    )
    _create_bindings(question_version=version, actor=actor, bindings=bindings)
    return version


@transaction.atomic
def create_question(
    *, actor, stable_id, kind, lifecycle, domain, tags, rationale, question_text,
    evaluation_guidance="", bindings=None
):
    require_admin(actor)
    if kind == Question.Kind.CONVERSATION:
        raise ValidationError(
            "Create a ConversationScenario for ordered conversation behavior; it creates the paired CONVERSATION Question."
        )
    question = _validate_and_save(
        Question(
            stable_id=stable_id,
            kind=kind,
            lifecycle=lifecycle,
            domain=domain,
            rationale=rationale,
            created_by=actor,
            updated_by=actor,
        )
    )
    question.tags.set(tags)
    _create_question_version(
        question=question,
        actor=actor,
        version_number=1,
        valid_from=timezone.now(),
        question_text=question_text,
        evaluation_guidance=evaluation_guidance,
        change_type="",
        change_reason="",
        bindings=bindings,
    )
    return question


@transaction.atomic
def update_question_metadata(*, actor, question, domain, tags, rationale):
    require_admin(actor)
    locked_question = Question.objects.select_for_update().get(pk=question.pk)
    if locked_question.kind == Question.Kind.CONVERSATION and hasattr(locked_question, "conversation_scenario"):
        raise ValidationError(
            "Conversation companion Question metadata is managed with its ConversationScenario."
        )
    locked_question.domain = domain
    locked_question.rationale = rationale
    locked_question.updated_by = actor
    locked_question = _validate_and_save(locked_question)
    locked_question.tags.set(tags)
    return locked_question


@transaction.atomic
def create_question_version(
    *, actor, question, question_text, evaluation_guidance="", change_type="",
    change_reason="", bindings=None, effective_at=None
):
    require_admin(actor)
    locked_question = Question.objects.select_for_update().get(pk=question.pk)
    if locked_question.kind == Question.Kind.CONVERSATION and hasattr(locked_question, "conversation_scenario"):
        raise ValidationError(
            "Conversation companion Questions are versioned through a complete ConversationScenarioVersion."
        )
    current = locked_question.versions.filter(valid_to__isnull=True).first()
    transition_at = effective_at or timezone.now()
    if current and transition_at <= current.valid_from:
        raise ValidationError(
            {"valid_from": "A new version must begin after the current version."}
        )
    next_number = (
        locked_question.versions.aggregate(maximum=Max("version_number"))["maximum"] or 0
    ) + 1
    if current:
        QuestionVersion.objects.filter(pk=current.pk, valid_to__isnull=True).update(
            valid_to=transition_at
        )
    version = _create_question_version(
        question=locked_question,
        actor=actor,
        version_number=next_number,
        valid_from=transition_at,
        question_text=question_text,
        evaluation_guidance=evaluation_guidance,
        change_type=change_type,
        change_reason=change_reason,
        bindings=bindings,
    )
    locked_question.updated_by = actor
    locked_question.save(update_fields=("updated_by", "updated_at"))
    return version


@transaction.atomic
def set_question_lifecycle(*, actor, question, lifecycle):
    require_admin(actor)
    if lifecycle not in Question.Lifecycle.values:
        raise ValidationError({"lifecycle": "Unsupported question lifecycle."})
    locked_question = Question.objects.select_for_update().get(pk=question.pk)
    if locked_question.kind == Question.Kind.CONVERSATION and hasattr(locked_question, "conversation_scenario"):
        raise ValidationError(
            "Conversation companion Question lifecycle is managed with its ConversationScenario."
        )
    if lifecycle == Question.Lifecycle.ACTIVE:
        if locked_question.domain_id is None:
            raise ValidationError({"domain": "A domain is required before activation."})
        if not locked_question.versions.filter(valid_to__isnull=True).exists():
            raise ValidationError("A current QuestionVersion is required before activation.")
    locked_question.lifecycle = lifecycle
    locked_question.updated_by = actor
    return _validate_and_save(locked_question)


def _scenario_turn_values(*, scenario_version, actor, turns):
    """Validate and materialize one immutable, gap-free turn definition."""

    normalized = []
    for ordinal, supplied in enumerate(turns or (), start=1):
        supplied = dict(supplied)
        prompt_template = str(supplied.get("prompt_template", "")).strip()
        canonical_version = supplied.get("canonical_question_version")
        canonical_question = supplied.get("canonical_question")
        if canonical_version:
            if canonical_question and canonical_question.pk != canonical_version.question_id:
                raise ValidationError("A canonical turn's QuestionVersion must belong to its selected Question.")
            canonical_question = canonical_version.question
            # A linked canonical definition is the authoritative exact prompt.
            # This avoids a second mutable copy of existing corpus text.
            if prompt_template and prompt_template != canonical_version.question_text:
                raise ValidationError(
                    "A linked canonical QuestionVersion must use its exact question text as the turn prompt."
                )
            prompt_template = canonical_version.question_text
        if not prompt_template:
            raise ValidationError(f"Conversation turn {ordinal} needs a prompt or canonical QuestionVersion.")
        turn = ConversationTurn(
            scenario_version=scenario_version,
            ordinal=ordinal,
            stable_turn_id=str(supplied.get("stable_turn_id") or f"{scenario_version.scenario.stable_id}.{ordinal}"),
            prompt_template=prompt_template,
            canonical_question=canonical_question,
            canonical_question_version=canonical_version,
            static_bindings=supplied.get("static_bindings") or {},
            required_for_overall=bool(supplied.get("required_for_overall", True)),
            source_sheet=str(supplied.get("source_sheet") or ""),
            source_row=supplied.get("source_row") or None,
            created_by=actor,
        )
        turn.full_clean()
        normalized.append(turn)
    if not normalized:
        raise ValidationError("A scenario version needs at least one ordered turn.")
    return normalized


@transaction.atomic
def create_conversation_scenario(
    *, actor, stable_id, name, description="", lifecycle=ConversationScenario.Lifecycle.DRAFT,
    domain=None, tags=(), definition="", turns=(), expected_session_behavior="shared-session-required"
):
    """Create a stable scenario plus its first immutable executable version."""

    require_admin(actor)
    companion = _validate_and_save(
        Question(
            stable_id=stable_id,
            kind=Question.Kind.CONVERSATION,
            lifecycle=lifecycle,
            domain=domain,
            rationale=description,
            created_by=actor,
            updated_by=actor,
        )
    )
    companion.tags.set(tags)
    companion_version = _create_question_version(
        question=companion,
        actor=actor,
        version_number=1,
        valid_from=timezone.now(),
        question_text=name,
        evaluation_guidance=definition,
        change_type="",
        change_reason="",
        bindings=(),
    )
    scenario = _validate_and_save(
        ConversationScenario(
            stable_id=stable_id,
            question=companion,
            name=name,
            description=description,
            lifecycle=lifecycle,
            domain=domain,
            created_by=actor,
            updated_by=actor,
        )
    )
    scenario.tags.set(tags)
    version = _validate_and_save(
        ConversationScenarioVersion(
            scenario=scenario,
            version_number=1,
            scenario_question_version=companion_version,
            definition=definition,
            expected_session_behavior=expected_session_behavior,
            valid_from=timezone.now(),
            created_by=actor,
        )
    )
    ConversationTurn.objects.bulk_create(_scenario_turn_values(scenario_version=version, actor=actor, turns=turns))
    return scenario


@transaction.atomic
def create_conversation_scenario_version(
    *, actor, scenario, definition="", turns=(), expected_session_behavior="shared-session-required", effective_at=None
):
    """Close the current definition and add a complete immutable replacement."""

    require_admin(actor)
    locked_scenario = ConversationScenario.objects.select_for_update().get(pk=scenario.pk)
    current = locked_scenario.versions.filter(valid_to__isnull=True).first()
    transition_at = effective_at or timezone.now()
    if current and transition_at <= current.valid_from:
        raise ValidationError("A new scenario version must begin after the current version.")
    next_number = (locked_scenario.versions.aggregate(maximum=Max("version_number"))["maximum"] or 0) + 1
    if current:
        ConversationScenarioVersion.objects.filter(pk=current.pk, valid_to__isnull=True).update(valid_to=transition_at)
    companion_question = Question.objects.select_for_update().get(pk=locked_scenario.question_id)
    current_question_version = companion_question.versions.filter(valid_to__isnull=True).first()
    if current_question_version:
        QuestionVersion.objects.filter(pk=current_question_version.pk, valid_to__isnull=True).update(valid_to=transition_at)
    companion_version = _create_question_version(
        question=companion_question,
        actor=actor,
        version_number=(companion_question.versions.aggregate(maximum=Max("version_number"))["maximum"] or 0) + 1,
        valid_from=transition_at,
        question_text=locked_scenario.name,
        evaluation_guidance=definition,
        change_type=QuestionVersion.ChangeType.DATA_MODEL_EVOLUTION,
        change_reason="Conversation scenario definition changed.",
        bindings=(),
    )
    version = _validate_and_save(
        ConversationScenarioVersion(
            scenario=locked_scenario,
            version_number=next_number,
            scenario_question_version=companion_version,
            definition=definition,
            expected_session_behavior=expected_session_behavior,
            valid_from=transition_at,
            created_by=actor,
        )
    )
    ConversationTurn.objects.bulk_create(_scenario_turn_values(scenario_version=version, actor=actor, turns=turns))
    ConversationScenario.objects.filter(pk=locked_scenario.pk).update(updated_by=actor)
    return version


@transaction.atomic
def update_conversation_scenario_metadata(*, actor, scenario, name, description, lifecycle, domain, tags):
    require_admin(actor)
    locked = ConversationScenario.objects.select_for_update().get(pk=scenario.pk)
    if lifecycle not in ConversationScenario.Lifecycle.values:
        raise ValidationError({"lifecycle": "Unsupported scenario lifecycle."})
    if lifecycle == ConversationScenario.Lifecycle.ACTIVE:
        if domain is None:
            raise ValidationError({"domain": "A domain is required before activation."})
        if not locked.versions.filter(valid_to__isnull=True).exists():
            raise ValidationError("A current ScenarioVersion is required before activation.")
    locked.name = name
    locked.description = description
    locked.lifecycle = lifecycle
    locked.domain = domain
    locked.updated_by = actor
    locked = _validate_and_save(locked)
    locked.tags.set(tags)
    Question.objects.filter(pk=locked.question_id).update(
        lifecycle=lifecycle,
        domain=domain,
        rationale=description,
        updated_by=actor,
        updated_at=timezone.now(),
    )
    locked.question.tags.set(tags)
    return locked


@transaction.atomic
def create_historical_fixture(
    *, actor, stable_id, name, environment, window_start, window_end,
    description="", tags=(), fixed_parameters=None, is_active=True
):
    require_admin(actor)
    fixture = _validate_and_save(
        HistoricalFixture(
            stable_id=stable_id,
            name=name,
            environment=environment,
            window_start=window_start,
            window_end=window_end,
            description=description,
            fixed_parameters={} if fixed_parameters is None else fixed_parameters,
            is_active=is_active,
            created_by=actor,
        )
    )
    fixture.tags.set(tags)
    return fixture
