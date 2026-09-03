from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connections, transaction
from django.utils import timezone

from catalog.models import (
    BindingDefinition,
    HistoricalFixture,
    Product,
    Question,
    QuestionVersion,
    TargetRevision,
)
from catalog.services import (
    create_historical_fixture,
    create_product,
    create_question,
    create_question_version,
    create_target_revision,
    set_question_lifecycle,
)


def revision_values(endpoint):
    return {
        "endpoint": endpoint,
        "adapter_key": "fixture",
        "adapter_version": "1",
        "credential_reference": "secrets/catalog-target",
        "classification": TargetRevision.Classification.STAGING,
        "supports_question_api": True,
        "supports_conversation_session": False,
        "supports_runtime_metadata": True,
        "supports_health_check": True,
        "default_execution_mode": TargetRevision.ExecutionMode.PARALLEL,
        "max_concurrency": 3,
        "question_timeout_seconds": 45,
        "inter_question_delay_seconds": 0.25,
        "declared_product_version": "",
        "declared_build_id": "",
        "declared_git_sha": "",
    }


@pytest.mark.django_db
def test_question_version_transition_preserves_history_and_bindings(minimal_domain):
    question = minimal_domain["question"]
    first = question.current_version
    first_text = first.question_text

    second = create_question_version(
        actor=minimal_domain["admin"],
        question=question,
        question_text="Quais transceivers estão em uso agora?",
        evaluation_guidance="Preserve exact identifiers.",
        change_type=QuestionVersion.ChangeType.PRODUCT_REQUIREMENT_CHANGE,
        change_reason="Operator requirement clarified.",
        bindings=[
            {
                "name": "site_id",
                "value_type": BindingDefinition.ValueType.IDENTIFIER,
                "is_required": True,
                "description": "Stable site identifier",
            }
        ],
    )

    first.refresh_from_db()
    assert first.valid_to == second.valid_from
    assert first.question_text == first_text
    assert second.version_number == 2
    assert question.versions.filter(valid_to__isnull=True).get() == second
    assert list(second.binding_definitions.values_list("name", flat=True)) == ["site_id"]
    with pytest.raises(ValidationError, match="immutable"):
        first.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        first.delete()
    with pytest.raises(ValidationError, match="immutable"):
        second.binding_definitions.get().save()


@pytest.mark.django_db
def test_target_revision_transition_preserves_prior_configuration(minimal_domain):
    target = minimal_domain["target"]
    first = target.current_revision
    first_endpoint = first.endpoint

    second = create_target_revision(
        actor=minimal_domain["admin"],
        target=target,
        **revision_values("https://new-target.example.invalid/api"),
    )

    first.refresh_from_db()
    assert first.valid_to == second.valid_from
    assert first.endpoint == first_endpoint
    assert second.revision_number == 2
    assert target.revisions.filter(valid_to__isnull=True).get() == second
    with pytest.raises(ValidationError, match="immutable"):
        first.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        first.delete()


@pytest.mark.django_db
def test_database_rejects_duplicate_current_question_and_target_records(minimal_domain):
    question = minimal_domain["question"]
    target = minimal_domain["target"]
    now = timezone.now()

    with pytest.raises(IntegrityError), transaction.atomic():
        QuestionVersion.objects.create(
            question=question,
            version_number=2,
            question_text="Forbidden overlapping current version",
            valid_from=now,
            created_by=minimal_domain["admin"],
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        TargetRevision.objects.create(
            target=target,
            revision_number=2,
            valid_from=now,
            created_by=minimal_domain["admin"],
            **revision_values("https://overlap.example.invalid/api"),
        )


@pytest.mark.django_db
def test_activation_requires_domain_and_enum_constraints_are_database_owned(
    admin_user, minimal_domain,
):
    question = create_question(
        actor=admin_user,
        stable_id="BLAST-017",
        kind=Question.Kind.SINGLE_TURN,
        lifecycle=Question.Lifecycle.DRAFT,
        domain=None,
        tags=(),
        rationale="",
        question_text="Which links are affected?",
    )
    with pytest.raises(ValidationError, match="domain is required"):
        set_question_lifecycle(
            actor=admin_user,
            question=question,
            lifecycle=Question.Lifecycle.ACTIVE,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Question.objects.filter(pk=question.pk).update(lifecycle="REVIEW")
    with pytest.raises(IntegrityError), transaction.atomic():
        TargetRevision.objects.filter(pk=minimal_domain["target"].current_revision.pk).update(
            classification="HISTORICAL"
        )


@pytest.mark.django_db
def test_stable_id_unicode_and_optional_fixture_round_trip(minimal_domain):
    question = create_question(
        actor=minimal_domain["admin"],
        stable_id="RUBIN-CONV-01.1",
        kind=Question.Kind.SINGLE_TURN,
        lifecycle=Question.Lifecycle.DRAFT,
        domain=None,
        tags=[minimal_domain["tag"]],
        rationale="Razão operacional — preservada.",
        question_text="Qual é o estado da conexão São Paulo–Miami?",
    )
    fixture = create_historical_fixture(
        actor=minimal_domain["admin"],
        stable_id="QUIET-2026.01",
        name="Quiet window",
        environment=minimal_domain["environment"],
        window_start=timezone.now() - timedelta(hours=2),
        window_end=timezone.now() - timedelta(hours=1),
        tags=[minimal_domain["tag"]],
        fixed_parameters={"site_id": "São Paulo"},
    )

    question.refresh_from_db()
    fixture.refresh_from_db()
    assert question.current_version.question_text == "Qual é o estado da conexão São Paulo–Miami?"
    assert question.rationale == "Razão operacional — preservada."
    assert fixture.fixed_parameters == {"site_id": "São Paulo"}
    assert list(fixture.tags.values_list("name", flat=True)) == ["Português"]


@pytest.mark.django_db
def test_secret_bearing_target_endpoint_and_fixture_keys_are_rejected(minimal_domain):
    with pytest.raises(ValidationError, match="must not contain credentials"):
        create_target_revision(
            actor=minimal_domain["admin"],
            target=minimal_domain["target"],
            **revision_values("https://user:canary-password@example.invalid/api?token=canary"),
        )
    assert not TargetRevision.objects.filter(endpoint__contains="canary-password").exists()

    with pytest.raises(ValidationError, match="credential material"):
        create_historical_fixture(
            actor=minimal_domain["admin"],
            stable_id="UNSAFE-FIXTURE",
            name="Unsafe fixture",
            environment=minimal_domain["environment"],
            window_start=timezone.now() - timedelta(hours=2),
            window_end=timezone.now() - timedelta(hours=1),
            fixed_parameters={"nested": {"api_token": "canary-token"}},
        )
    assert not HistoricalFixture.objects.filter(stable_id="UNSAFE-FIXTURE").exists()


@pytest.mark.django_db
def test_operator_cannot_mutate_catalog_services(operator_user):
    with pytest.raises(PermissionDenied):
        create_product(
            actor=operator_user,
            slug="forbidden-product",
            display_name="Forbidden Product",
        )
    assert not Product.objects.filter(slug="forbidden-product").exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_question_versions_serialize_to_one_current(minimal_domain):
    question_id = minimal_domain["question"].pk
    actor_id = minimal_domain["admin"].pk

    def version(text):
        connections.close_all()
        from accounts.models import User

        try:
            actor = User.objects.get(pk=actor_id)
            question = Question.objects.get(pk=question_id)
            result = create_question_version(
                actor=actor,
                question=question,
                question_text=text,
                change_type=QuestionVersion.ChangeType.TEST_BUG_FIX,
                change_reason="Concurrent acceptance probe",
            )
            return result.pk
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(version, ("Concurrent version A", "Concurrent version B")))

    assert len(set(ids)) == 2
    versions = QuestionVersion.objects.filter(question_id=question_id).order_by("version_number")
    assert list(versions.values_list("version_number", flat=True)) == [1, 2, 3]
    assert versions.filter(valid_to__isnull=True).count() == 1
    boundaries = list(versions.values_list("valid_from", "valid_to"))
    assert boundaries[0][1] == boundaries[1][0]
    assert boundaries[1][1] == boundaries[2][0]


@pytest.mark.django_db(transaction=True)
def test_concurrent_target_revisions_serialize_to_one_current(minimal_domain):
    target_id = minimal_domain["target"].pk
    actor_id = minimal_domain["admin"].pk

    def revise(endpoint):
        connections.close_all()
        from accounts.models import User
        from catalog.models import EvaluationTarget

        try:
            actor = User.objects.get(pk=actor_id)
            target = EvaluationTarget.objects.get(pk=target_id)
            result = create_target_revision(
                actor=actor,
                target=target,
                **revision_values(endpoint),
            )
            return result.pk
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(
            pool.map(
                revise,
                (
                    "https://concurrent-a.example.invalid/api",
                    "https://concurrent-b.example.invalid/api",
                ),
            )
        )

    assert len(set(ids)) == 2
    revisions = TargetRevision.objects.filter(target_id=target_id).order_by("revision_number")
    assert list(revisions.values_list("revision_number", flat=True)) == [1, 2, 3]
    assert revisions.filter(valid_to__isnull=True).count() == 1
    boundaries = list(revisions.values_list("valid_from", "valid_to"))
    assert boundaries[0][1] == boundaries[1][0]
    assert boundaries[1][1] == boundaries[2][0]
