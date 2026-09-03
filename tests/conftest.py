import pytest
from django.db import connection

from accounts.models import User


@pytest.fixture(scope="session", autouse=True)
def require_postgresql(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        connection.ensure_connection()
        assert connection.vendor == "postgresql", "StewardBench tests require PostgreSQL"


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin-fixture",
        password="Admin-Fixture-Password-42!",
        role=User.Role.ADMIN,
    )


@pytest.fixture
def operator_user(db):
    return User.objects.create_user(
        username="operator-fixture",
        password="Operator-Fixture-Password-42!",
        role=User.Role.OPERATOR,
    )


@pytest.fixture
def inactive_user(db):
    return User.objects.create_user(
        username="inactive-fixture",
        password="Inactive-Fixture-Password-42!",
        role=User.Role.OPERATOR,
        is_active=False,
    )


@pytest.fixture
def minimal_domain(admin_user, operator_user, inactive_user):
    return {
        "admin": admin_user,
        "operator": operator_user,
        "inactive": inactive_user,
    }
