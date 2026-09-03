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
