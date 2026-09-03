from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.policy import require_admin

from .models import (
    BindingDefinition,
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
    question.domain = domain
    question.rationale = rationale
    question.updated_by = actor
    question = _validate_and_save(question)
    question.tags.set(tags)
    return question


@transaction.atomic
def create_question_version(
    *, actor, question, question_text, evaluation_guidance="", change_type="",
    change_reason="", bindings=None, effective_at=None
):
    require_admin(actor)
    locked_question = Question.objects.select_for_update().get(pk=question.pk)
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
    if lifecycle == Question.Lifecycle.ACTIVE:
        if locked_question.domain_id is None:
            raise ValidationError({"domain": "A domain is required before activation."})
        if not locked_question.versions.filter(valid_to__isnull=True).exists():
            raise ValidationError("A current QuestionVersion is required before activation.")
    locked_question.lifecycle = lifecycle
    locked_question.updated_by = actor
    return _validate_and_save(locked_question)


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
