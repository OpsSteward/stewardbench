from collections import Counter
import hashlib
from io import StringIO
import json

import pytest
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone

from catalog.models import (
    BindingDefinition,
    Domain,
    Environment,
    EvaluationTarget,
    HistoricalFixture,
    Product,
    Question,
    QuestionVersion,
    Tag,
)
from catalog.services import create_domain, create_question, create_tag
from corpus.mapping import load_mapping
from corpus.models import (
    ImportedSourceCell,
    ImportedSourceRow,
    ImportWarning,
    LegacyImportBatch,
    LegacyObservation,
)
from corpus.services import CorpusImportConflict, apply_import, reconcile_import
from corpus.workbook import inspect_workbook


MAPPING_PATH = settings.BASE_DIR / "import_mappings/v2_dev_troubleshooting_v1.json"
WORKBOOK_PATH = settings.BASE_DIR / "docs/reference/v2-dev-troubleshooting.xlsx"


@pytest.fixture
def import_plan():
    return inspect_workbook(WORKBOOK_PATH, load_mapping(MAPPING_PATH))


def imported_counts():
    return {
        "batches": LegacyImportBatch.objects.count(),
        "domains": Domain.objects.count(),
        "tags": Tag.objects.count(),
        "questions": Question.objects.count(),
        "versions": QuestionVersion.objects.count(),
        "bindings": BindingDefinition.objects.count(),
        "fixtures": HistoricalFixture.objects.count(),
        "source_rows": ImportedSourceRow.objects.count(),
        "source_cells": ImportedSourceCell.objects.count(),
        "observations": LegacyObservation.objects.count(),
        "warnings": ImportWarning.objects.count(),
    }


@pytest.mark.django_db
def test_dry_run_is_non_mutating_and_reports_exact_reconciliation(admin_user, import_plan):
    before = imported_counts()

    report = reconcile_import(import_plan)

    assert imported_counts() == before
    assert report["mode"] == "DRY_RUN"
    assert report["fatal"] is False
    assert report["summary"] == {
        "physical_rows": 344,
        "meaningful_rows": 259,
        "header_rows": 4,
        "blank_or_separator_rows": 81,
        "canonical_questions": 199,
        "target_canonical_questions": 185,
        "random_canonical_questions": 13,
        "kb_rag_canonical_questions": 1,
        "question_versions": 199,
        "legacy_observations": 56,
        "domains": 18,
        "tags": 1,
        "binding_definitions": 0,
        "historical_fixtures": 0,
        "source_rows": 257,
        "source_cells": 489,
        "warnings": 62,
        "manual_review_items": 62,
        "ignored_interface_issue_rows": 17,
        "target_separator_rows": 15,
        "conflicts": 0,
    }
    assert report["changes"]["records_skipped"] == 98
    assert report["changes"]["questions_created"] == 199
    assert report["sheets"]["Interface Issues"]["ignored_meaningful_rows"] == 17


@pytest.mark.django_db
def test_apply_persists_exact_provenance_and_honest_legacy_evidence(admin_user, import_plan):
    report = apply_import(plan=import_plan, actor=admin_user)

    assert report["applied"] is True
    assert imported_counts() == {
        "batches": 1,
        "domains": 18,
        "tags": 1,
        "questions": 199,
        "versions": 199,
        "bindings": 0,
        "fixtures": 0,
        "source_rows": 257,
        "source_cells": 489,
        "observations": 56,
        "warnings": 62,
    }
    batch = LegacyImportBatch.objects.get()
    assert batch.mapping_version == 1
    assert batch.source_sha256 == import_plan.source_sha256
    assert batch.source_filename == "v2-dev-troubleshooting.xlsx"
    assert batch.mapping_snapshot["mapping_name"] == "StewardBench workbook mapping v1"

    split_rows = list(
        ImportedSourceRow.objects.filter(
            sheet_name="target questions", source_row_number__in=(155, 156)
        ).order_by("source_row_number")
    )
    assert [row.question.stable_id for row in split_rows] == ["PROV-013", "PROV-013"]
    assert len({row.question_version_id for row in split_rows}) == 1
    assert split_rows[0].question_version.question_text == (
        "Which validation findings affect this device, interface, adjacency, service, "
        "or infrastructure segment?"
    )
    assert all(
        row.interpretation_source == ImportedSourceRow.InterpretationSource.PRODUCT_OWNER_MAPPING
        for row in split_rows
    )
    assert ImportedSourceRow.objects.filter(
        sheet_name="target questions", classification="STRUCTURAL"
    ).count() == 15
    assert not ImportedSourceRow.objects.filter(sheet_name="Interface Issues").exists()

    portuguese = Question.objects.get(stable_id="GEN-006")
    assert portuguese.current_version.question_text == (
        "Quantos transceivers no total estão em uso?"
    )
    assert list(portuguese.tags.values_list("name", flat=True)) == ["generalization"]
    assert portuguese.lifecycle == Question.Lifecycle.DRAFT

    assert Counter(
        LegacyObservation.objects.values_list("legacy_judgment", flat=True)
    ) == {"GOOD": 25, "BAD": 27, None: 4}
    known = LegacyObservation.objects.get(
        source_row__sheet_name="known questions", source_row__source_row_number=8
    )
    assert known.observed_answer_text == "Table with No matching rows"
    assert known.legacy_expectation.startswith("There were SEVERAL BGP flaps")
    assert known.expected_answer_role == "LEGACY_EXPECTATION"
    assert known.legacy_judgment == "BAD"
    assert known.acceptable_source_value == "No"
    assert known.question is None
    assert known.question_version is None
    assert known.judgment_source == "IMPORTED_LEGACY"
    assert known.unknown_metadata == [
        "product",
        "environment",
        "target",
        "build",
        "git_sha",
        "executed_at",
        "reviewed_at",
        "reviewer",
        "bindings",
        "session",
    ]
    assert known.source_row.batch.imported_by == admin_user
    assert "reviewer" in known.unknown_metadata

    kb = list(
        LegacyObservation.objects.filter(
            source_row__sheet_name="knowledge base - rag questions"
        ).order_by("source_row__source_row_number")
    )
    assert len(kb) == 4
    assert len({observation.question_id for observation in kb}) == 1
    assert kb[0].question.stable_id == "KB-001"
    assert kb[0].observed_answer_text is None
    assert kb[0].comments == 'A text answer was provided but capped at "When an operator"'
    assert kb[0].secondary_comments.startswith("Answer shouldn't be capped")
    assert kb[0].experiment_metadata == {
        "answer_size": "Small",
        "token": {
            "source_value": "1668",
            "unit": None,
            "meaning": "Unspecified beyond source column label",
        },
        "total_time": {
            "source_value": "12.7",
            "unit": None,
            "meaning": "Unspecified beyond source column label",
        },
    }
    assert QuestionVersion.objects.exclude(evaluation_guidance="").count() == 0


@pytest.mark.django_db
def test_unchanged_reimport_is_a_complete_noop(admin_user, import_plan):
    first = apply_import(plan=import_plan, actor=admin_user)
    before = imported_counts()
    provenance = list(
        ImportedSourceRow.objects.order_by("pk").values_list(
            "pk", "source_fingerprint", "question_id", "question_version_id"
        )
    )

    post_apply_dry_run = reconcile_import(import_plan)
    assert imported_counts() == before
    assert post_apply_dry_run["already_applied"] is True
    assert post_apply_dry_run["changes"]["questions_created"] == 0

    second = apply_import(plan=import_plan, actor=admin_user)

    assert second["applied"] is False
    assert second["already_applied"] is True
    assert second["batch_id"] == first["batch_id"]
    assert second["changes"]["questions_created"] == 0
    assert second["changes"]["questions_reused"] == 199
    assert second["changes"]["legacy_observations_created"] == 0
    assert second["changes"]["legacy_observations_reused"] == 56
    assert imported_counts() == before
    assert list(
        ImportedSourceRow.objects.order_by("pk").values_list(
            "pk", "source_fingerprint", "question_id", "question_version_id"
        )
    ) == provenance


@pytest.mark.django_db
def test_matching_manual_records_are_reused_and_unrelated_catalog_is_untouched(
    minimal_domain, import_plan
):
    admin = minimal_domain["admin"]
    generalization = create_domain(
        actor=admin, slug="generalization", name="Generalization"
    )
    tag = create_tag(actor=admin, name="generalization")
    expected = next(
        question for question in import_plan.questions if question.stable_id == "GEN-001"
    )
    manual = create_question(
        actor=admin,
        stable_id=expected.stable_id,
        kind=Question.Kind.SINGLE_TURN,
        lifecycle=Question.Lifecycle.DRAFT,
        domain=generalization,
        tags=[tag],
        rationale="",
        question_text=expected.question_text,
    )
    unrelated = {
        "product": Product.objects.get(pk=minimal_domain["product"].pk),
        "environment": Environment.objects.get(pk=minimal_domain["environment"].pk),
        "target": EvaluationTarget.objects.get(pk=minimal_domain["target"].pk),
        "question": Question.objects.get(pk=minimal_domain["question"].pk),
    }

    report = apply_import(plan=import_plan, actor=admin)

    assert report["changes"]["domains_reused"] == 1
    assert report["changes"]["tags_reused"] == 1
    assert report["changes"]["questions_reused"] == 1
    assert Question.objects.get(stable_id="GEN-001").pk == manual.pk
    for key, value in unrelated.items():
        value.refresh_from_db()
        assert value.pk == unrelated[key].pk
    assert Product.objects.count() == 1
    assert Environment.objects.count() == 1
    assert EvaluationTarget.objects.count() == 1


@pytest.mark.django_db
def test_conflicting_manual_question_is_reported_and_never_overwritten(admin_user, import_plan):
    domain = create_domain(
        actor=admin_user, slug="service-traversal", name="Service Traversal"
    )
    manual = create_question(
        actor=admin_user,
        stable_id="TRAV-001",
        kind=Question.Kind.SINGLE_TURN,
        lifecycle=Question.Lifecycle.DRAFT,
        domain=domain,
        tags=(),
        rationale="Manually curated",
        question_text="Conflicting manual definition",
    )

    dry_run = reconcile_import(import_plan)
    assert dry_run["fatal"] is True
    assert dry_run["conflicts"][0]["code"] == "SOURCE_CONFLICT"
    with pytest.raises(CorpusImportConflict) as captured:
        apply_import(plan=import_plan, actor=admin_user)

    manual.refresh_from_db()
    assert manual.current_version.question_text == "Conflicting manual definition"
    assert captured.value.report["fatal"] is True
    assert LegacyImportBatch.objects.count() == 0
    assert Question.objects.count() == 1
    assert Domain.objects.count() == 1


@pytest.mark.django_db
def test_only_admin_can_apply_import(operator_user, import_plan):
    with pytest.raises(PermissionDenied):
        apply_import(plan=import_plan, actor=operator_user)
    assert LegacyImportBatch.objects.count() == 0


@pytest.mark.django_db
def test_import_evidence_is_immutable(admin_user, import_plan):
    apply_import(plan=import_plan, actor=admin_user)
    batch = LegacyImportBatch.objects.get()
    source_row = ImportedSourceRow.objects.first()
    observation = LegacyObservation.objects.first()

    batch.source_filename = "rewritten.xlsx"
    with pytest.raises(ValidationError, match="immutable"):
        batch.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        source_row.delete()
    observation.comments = "rewritten"
    with pytest.raises(ValidationError, match="immutable"):
        observation.save()


@pytest.mark.django_db
def test_provenance_identity_is_one_based_at_the_database_boundary(admin_user):
    batch_values = {
        "mapping_identifier": "constraint-probe",
        "mapping_name": "Constraint probe",
        "importer_version": "test",
        "source_filename": "probe.xlsx",
        "source_sha256": "a" * 64,
        "source_size_bytes": 1,
        "source_metadata": {},
        "workbook_inventory": {},
        "mapping_snapshot": {},
        "reconciliation_counts": {},
        "imported_at": timezone.now(),
        "imported_by": admin_user,
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        LegacyImportBatch.objects.create(mapping_version=0, **batch_values)

    batch = LegacyImportBatch.objects.create(mapping_version=1, **batch_values)
    with pytest.raises(IntegrityError), transaction.atomic():
        ImportedSourceRow.objects.create(
            batch=batch,
            sheet_name="known questions",
            source_row_number=0,
            source_role=ImportedSourceRow.SourceRole.KNOWN_QUESTIONS,
            classification=ImportedSourceRow.Classification.LEGACY_OBSERVATION,
            interpretation_source=ImportedSourceRow.InterpretationSource.SOURCE_DATA,
            source_fingerprint="b" * 64,
        )


@pytest.mark.django_db
def test_management_command_defaults_to_dry_run_and_requires_explicit_admin(
    admin_user, import_plan
):
    before = imported_counts()
    stdout = StringIO()
    call_command(
        "import_stewardbench_workbook",
        path=str(WORKBOOK_PATH),
        mapping=str(MAPPING_PATH),
        json=True,
        stdout=stdout,
    )
    report = json.loads(stdout.getvalue())
    assert report["mode"] == "DRY_RUN"
    assert imported_counts() == before

    stdout = StringIO()
    call_command(
        "import_stewardbench_workbook",
        path=str(WORKBOOK_PATH),
        mapping=str(MAPPING_PATH),
        apply=True,
        actor=admin_user.username,
        json=True,
        stdout=stdout,
    )
    report = json.loads(stdout.getvalue())
    assert report["mode"] == "APPLY"
    assert report["applied"] is True
    assert report["source"]["sha256"] == report["source"]["sha256_after"]
    assert hashlib.sha256(WORKBOOK_PATH.read_bytes()).hexdigest() == report["source"]["sha256"]
