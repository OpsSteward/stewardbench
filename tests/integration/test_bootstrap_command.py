import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import User


@pytest.mark.django_db
def test_bootstrap_creates_first_product_admin(monkeypatch):
    password = "Bootstrap-Synthetic-Password-64!"
    monkeypatch.setenv("BOOTSTRAP_TEST_PASSWORD", password)
    stdout = io.StringIO()

    call_command(
        "create_stewardbench_admin",
        username="first-admin",
        email="first-admin@example.invalid",
        password_env="BOOTSTRAP_TEST_PASSWORD",
        stdout=stdout,
    )

    user = User.objects.get(username="first-admin")
    assert user.role == User.Role.ADMIN
    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser
    assert user.check_password(password)
    assert user.password != password
    assert password not in stdout.getvalue()


@pytest.mark.django_db
def test_bootstrap_rejects_duplicate_without_mutation(monkeypatch):
    password = "Bootstrap-Synthetic-Password-64!"
    monkeypatch.setenv("BOOTSTRAP_TEST_PASSWORD", password)
    call_command(
        "create_stewardbench_admin",
        username="first-admin",
        password_env="BOOTSTRAP_TEST_PASSWORD",
    )
    before = list(User.objects.values_list("id", "username", "role", "password"))

    with pytest.raises(CommandError, match="already exists"):
        call_command(
            "create_stewardbench_admin",
            username="second-admin",
            password_env="BOOTSTRAP_TEST_PASSWORD",
        )

    assert list(User.objects.values_list("id", "username", "role", "password")) == before


@pytest.mark.django_db
def test_bootstrap_requires_secure_password_source(monkeypatch):
    monkeypatch.delenv("MISSING_BOOTSTRAP_PASSWORD", raising=False)

    with pytest.raises(CommandError, match="is not set"):
        call_command(
            "create_stewardbench_admin",
            username="first-admin",
            password_env="MISSING_BOOTSTRAP_PASSWORD",
        )

    assert not User.objects.exists()
