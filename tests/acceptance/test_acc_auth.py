import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from accounts.models import User


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_auth_001_first_admin_bootstrap_and_password_safety(client, monkeypatch):
    password = "ACC-Auth-Canary-001-Password-94!"
    monkeypatch.setenv("ACC_AUTH_001_PASSWORD", password)
    stdout = io.StringIO()
    stderr = io.StringIO()

    call_command(
        "create_stewardbench_admin",
        username="acc-first-admin",
        password_env="ACC_AUTH_001_PASSWORD",
        stdout=stdout,
        stderr=stderr,
    )
    user = User.objects.get(username="acc-first-admin")
    stored_snapshot = list(User.objects.values_list("pk", "username", "role", "password"))

    assert user.role == User.Role.ADMIN
    assert user.check_password(password)
    assert password not in user.password
    assert password not in stdout.getvalue()
    assert password not in stderr.getvalue()
    assert client.login(username=user.username, password=password)

    with pytest.raises(CommandError, match="already exists"):
        call_command(
            "create_stewardbench_admin",
            username="acc-second-admin",
            password_env="ACC_AUTH_001_PASSWORD",
        )
    assert list(User.objects.values_list("pk", "username", "role", "password")) == stored_snapshot


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_auth_002_login_inactive_logout_and_session_reuse(client, minimal_domain):
    admin = minimal_domain["admin"]
    inactive = minimal_domain["inactive"]
    wrong_canary = "ACC-Auth-Wrong-Secret-002!"

    assert not client.login(username=admin.username, password=wrong_canary)
    assert not client.login(username=inactive.username, password="Inactive-Fixture-Password-42!")
    assert client.login(username=admin.username, password="Admin-Fixture-Password-42!")
    assert client.get(reverse("dashboard")).status_code == 200

    response = client.post(reverse("logout"))
    assert response.status_code == 302
    assert client.get(reverse("dashboard")).status_code == 302
    assert wrong_canary.encode() not in response.content
