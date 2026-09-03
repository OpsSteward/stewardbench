from datetime import UTC, datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder


@pytest.mark.django_db
@pytest.mark.postgresql
def test_migration_graph_has_accounts_leaf_and_is_applied():
    executor = MigrationExecutor(connection)
    leaves = set(executor.loader.graph.leaf_nodes())
    applied = set(MigrationRecorder(connection).applied_migrations())

    assert ("accounts", "0001_initial") in leaves
    assert ("corpus", "0001_initial") in leaves
    assert leaves <= applied
    assert connection.vendor == "postgresql"


@pytest.mark.django_db(transaction=True)
@pytest.mark.postgresql
def test_populated_m1_catalog_survives_corpus_schema_upgrade():
    executor = MigrationExecutor(connection)
    executor.migrate([("corpus", None)])
    old_apps = executor.loader.project_state(
        [("accounts", "0001_initial"), ("catalog", "0001_initial")]
    ).apps
    User = old_apps.get_model("accounts", "User")
    Domain = old_apps.get_model("catalog", "Domain")
    Question = old_apps.get_model("catalog", "Question")
    QuestionVersion = old_apps.get_model("catalog", "QuestionVersion")

    actor = User.objects.create(
        username="populated-m1-admin",
        password="!",
        role="ADMIN",
        is_active=True,
        is_staff=False,
        is_superuser=False,
    )
    domain = Domain.objects.create(
        slug="m1-preserved",
        name="M1 Preserved",
        description="Before M2",
        is_active=True,
        created_by=actor,
        updated_by=actor,
    )
    question = Question.objects.create(
        stable_id="M1-PRESERVED-001",
        kind="SINGLE_TURN",
        lifecycle="DRAFT",
        domain=domain,
        rationale="Existing M1 state",
        created_by=actor,
        updated_by=actor,
    )
    QuestionVersion.objects.create(
        question=question,
        version_number=1,
        question_text="Preserve this exact M1 text — São Paulo",
        evaluation_guidance="",
        change_type="",
        change_reason="",
        valid_from=datetime(2026, 9, 3, tzinfo=UTC),
        created_by=actor,
    )

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())

    from catalog.models import Question as CurrentQuestion
    from corpus.models import LegacyImportBatch

    preserved = CurrentQuestion.objects.get(stable_id="M1-PRESERVED-001")
    assert preserved.current_version.question_text == "Preserve this exact M1 text — São Paulo"
    assert preserved.domain.name == "M1 Preserved"
    assert LegacyImportBatch.objects.count() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.postgresql
def test_populated_m2_import_history_survives_m3_schema_upgrade():
    """M3 tables and nullable fixed binding configuration do not rewrite M2 evidence."""

    executor = MigrationExecutor(connection)
    executor.migrate([("catalog", "0001_initial"), ("corpus", "0001_initial")])
    old_apps = executor.loader.project_state(
        [
            ("accounts", "0001_initial"),
            ("catalog", "0001_initial"),
            ("corpus", "0001_initial"),
        ]
    ).apps
    User = old_apps.get_model("accounts", "User")
    Domain = old_apps.get_model("catalog", "Domain")
    Question = old_apps.get_model("catalog", "Question")
    QuestionVersion = old_apps.get_model("catalog", "QuestionVersion")
    LegacyImportBatch = old_apps.get_model("corpus", "LegacyImportBatch")
    ImportedSourceRow = old_apps.get_model("corpus", "ImportedSourceRow")
    LegacyObservation = old_apps.get_model("corpus", "LegacyObservation")

    actor = User.objects.create(
        username="populated-m2-admin",
        password="!",
        role="ADMIN",
        is_active=True,
        is_staff=False,
        is_superuser=False,
    )
    domain = Domain.objects.create(
        slug="m2-preserved",
        name="M2 Preserved",
        description="Before M3",
        is_active=True,
        created_by=actor,
        updated_by=actor,
    )
    question = Question.objects.create(
        stable_id="M2-PRESERVED-001",
        kind="SINGLE_TURN",
        lifecycle="DRAFT",
        domain=domain,
        rationale="M2 historical link",
        created_by=actor,
        updated_by=actor,
    )
    version = QuestionVersion.objects.create(
        question=question,
        version_number=1,
        question_text="M2 Unicode source text — São Paulo",
        evaluation_guidance="",
        change_type="",
        change_reason="",
        valid_from=datetime(2026, 9, 3, tzinfo=UTC),
        created_by=actor,
    )
    batch = LegacyImportBatch.objects.create(
        mapping_identifier="m2-upgrade",
        mapping_name="M2 upgrade fixture",
        mapping_version=1,
        importer_version="m2",
        source_filename="m2.xlsx",
        source_sha256="a" * 64,
        source_size_bytes=1,
        source_metadata={"fixture": True},
        workbook_inventory={},
        mapping_snapshot={},
        reconciliation_counts={},
        imported_at=datetime(2026, 9, 3, tzinfo=UTC),
        imported_by=actor,
    )
    source_row = ImportedSourceRow.objects.create(
        batch=batch,
        sheet_name="known questions",
        source_row_number=2,
        source_role="KNOWN_QUESTIONS",
        classification="LEGACY_OBSERVATION",
        interpretation_source="SOURCE_DATA",
        structural_kind="",
        source_fingerprint="b" * 64,
        mapping_context={},
        question=question,
        question_version=version,
    )
    LegacyObservation.objects.create(
        source_row=source_row,
        question=question,
        question_version=version,
        source_question_text="M2 Unicode source text — São Paulo",
        observed_answer_text="Resposta anterior ✓",
        answer_fidelity="SOURCE_TEXT_UNKNOWN_EXACTNESS",
        legacy_expectation=None,
        expected_answer_role="LEGACY_EXPECTATION",
        acceptable_source_value="Yes",
        legacy_judgment="GOOD",
        judgment_source="IMPORTED_LEGACY",
        comments="M2 preserved comment",
        secondary_comments=None,
        experiment_metadata={},
        unknown_metadata=["target"],
        imported_at=datetime(2026, 9, 3, tzinfo=UTC),
    )

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())

    from catalog.models import BindingDefinition as CurrentBindingDefinition
    from catalog.models import Question as CurrentQuestion
    from corpus.models import LegacyObservation as CurrentLegacyObservation
    from evaluations.models import EvaluationRun

    preserved_question = CurrentQuestion.objects.get(stable_id="M2-PRESERVED-001")
    preserved_observation = CurrentLegacyObservation.objects.get(source_row__batch__mapping_identifier="m2-upgrade")
    assert preserved_question.current_version.question_text == "M2 Unicode source text — São Paulo"
    assert preserved_observation.observed_answer_text == "Resposta anterior ✓"
    assert preserved_observation.comments == "M2 preserved comment"
    assert CurrentBindingDefinition.objects.count() == 0
    assert EvaluationRun.objects.count() == 0
