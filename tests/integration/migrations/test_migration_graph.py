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
    assert leaves <= applied
    assert connection.vendor == "postgresql"
