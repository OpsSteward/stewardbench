import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from corpus.mapping import load_mapping
from corpus.models import LegacyImportBatch, LegacyObservation
from corpus.services import apply_import
from corpus.workbook import inspect_workbook


MAPPING_PATH = settings.BASE_DIR / "import_mappings/v2_dev_troubleshooting_v1.json"
WORKBOOK_PATH = settings.BASE_DIR / "docs/reference/v2-dev-troubleshooting.xlsx"


@pytest.mark.django_db
def test_imported_history_is_visible_and_explicitly_uncontrolled(
    admin_user, operator_user
):
    plan = inspect_workbook(WORKBOOK_PATH, load_mapping(MAPPING_PATH))
    apply_import(plan=plan, actor=admin_user)
    batch = LegacyImportBatch.objects.get()
    observation = LegacyObservation.objects.get(
        source_row__sheet_name="known questions", source_row__source_row_number=8
    )
    client = Client()

    assert client.get(reverse("import-batch-list")).status_code == 302
    client.force_login(operator_user)
    listing = client.get(reverse("import-batch-list"))
    detail = client.get(reverse("import-batch-detail", args=[batch.pk]))
    legacy = client.get(reverse("legacy-observation-detail", args=[observation.pk]))

    assert listing.status_code == detail.status_code == legacy.status_code == 200
    assert b"StewardBench workbook mapping v1" in listing.content
    assert b"product-owner semantic mapping" in detail.content
    assert b"CONVERSATION_GROUPING_DEFERRED" in detail.content
    assert b"not universal ground truth" in legacy.content
    assert b"No target, build, execution/review time, reviewer" in legacy.content


@pytest.mark.django_db
def test_imported_question_detail_shows_source_and_legacy_links(admin_user):
    plan = inspect_workbook(WORKBOOK_PATH, load_mapping(MAPPING_PATH))
    apply_import(plan=plan, actor=admin_user)
    client = Client()
    client.force_login(admin_user)

    response = client.get(reverse("question-detail", args=["GEN-006"]))

    assert response.status_code == 200
    assert "Quantos transceivers no total estão em uso?" in response.content.decode()
    assert b"Imported source provenance" in response.content
    assert b"Imported legacy/manual observations" in response.content
    assert b"not Executions or attributed HumanReviews" in response.content
