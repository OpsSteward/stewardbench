import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse

from catalog.models import QuestionVersion, TargetRevision
from catalog.services import create_question_version, create_target_revision
from tests.integration.test_catalog_services import revision_values


@pytest.mark.acceptance
@pytest.mark.django_db
def test_m1_temporal_catalog_history_and_current_uniqueness(minimal_domain):
    question = minimal_domain["question"]
    old_version = question.current_version
    target = minimal_domain["target"]
    old_revision = target.current_revision

    new_version = create_question_version(
        actor=minimal_domain["admin"],
        question=question,
        question_text="M1 acceptance — exact new question text",
        change_type=QuestionVersion.ChangeType.DATA_MODEL_EVOLUTION,
        change_reason="M1 temporal acceptance",
    )
    new_revision = create_target_revision(
        actor=minimal_domain["admin"],
        target=target,
        **revision_values("https://m1-acceptance.example.invalid/api"),
    )

    old_version.refresh_from_db()
    old_revision.refresh_from_db()
    assert old_version.valid_to == new_version.valid_from
    assert old_revision.valid_to == new_revision.valid_from
    assert question.versions.filter(valid_to__isnull=True).count() == 1
    assert target.revisions.filter(valid_to__isnull=True).count() == 1
    assert old_version.question_text == "Quantos transceivers estão em uso?"
    assert old_revision.endpoint == "https://target.example.invalid/api"
    with pytest.raises(ValidationError):
        old_version.save()
    with pytest.raises(IntegrityError), transaction.atomic():
        QuestionVersion.objects.create(
            question=question,
            version_number=3,
            question_text="Overlapping current",
            valid_from=new_version.valid_from,
            created_by=minimal_domain["admin"],
        )


@pytest.mark.acceptance
@pytest.mark.django_db
def test_m1_operator_read_only_catalog_http_boundary(minimal_domain):
    client = Client()
    client.force_login(minimal_domain["operator"])
    question = minimal_domain["question"]
    target = minimal_domain["target"]
    before = (
        question.lifecycle,
        question.versions.count(),
        target.revisions.count(),
    )

    assert client.get(reverse("question-detail", args=[question.stable_id])).status_code == 200
    assert client.get(reverse("target-detail", args=[target.slug])).status_code == 200
    assert (
        client.post(
            reverse("question-lifecycle-update", args=[question.stable_id, "RETIRED"])
        ).status_code
        == 403
    )
    assert client.post(reverse("target-revision-create", args=[target.slug]), {}).status_code == 403
    question.refresh_from_db()
    assert (question.lifecycle, question.versions.count(), target.revisions.count()) == before
