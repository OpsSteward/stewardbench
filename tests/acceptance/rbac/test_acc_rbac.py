import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from accounts.models import User
from accounts.services import create_user, update_user


def fingerprint_users():
    return list(
        User.objects.order_by("pk").values_list(
            "pk", "username", "email", "role", "is_active", "password"
        )
    )


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_rbac_001_m0_operator_is_server_side_read_only(admin_user, operator_user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(operator_user)
    dashboard = client.get(reverse("dashboard"))
    token = client.cookies["csrftoken"].value
    before = fingerprint_users()

    denied_create = client.post(
        reverse("user-create"),
        {
            "csrfmiddlewaretoken": token,
            "username": "rbac-bypass",
            "role": User.Role.ADMIN,
            "password1": "RBAC-Bypass-Password-74!",
            "password2": "RBAC-Bypass-Password-74!",
        },
        HTTP_REFERER="http://testserver/",
    )
    denied_edit = client.post(
        reverse("user-update", args=[admin_user.pk]),
        {
            "csrfmiddlewaretoken": token,
            "email": "changed@example.invalid",
            "role": User.Role.OPERATOR,
            "is_active": "on",
        },
        HTTP_REFERER="http://testserver/",
    )

    assert dashboard.status_code == 200
    assert denied_create.status_code == 403
    assert denied_edit.status_code == 403
    assert fingerprint_users() == before
    with pytest.raises(PermissionDenied):
        update_user(
            actor=operator_user,
            user=admin_user,
            email="changed@example.invalid",
            role=User.Role.OPERATOR,
            is_active=True,
        )
    assert fingerprint_users() == before


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_rbac_002_admin_exact_roles_and_no_framework_elevation(admin_user, operator_user):
    created = create_user(
        actor=admin_user,
        username="accepted-operator",
        email="accepted@example.invalid",
        role=User.Role.OPERATOR,
        password="Horizon-Cobalt-42!Orbit",
    )
    update_user(
        actor=admin_user,
        user=created,
        email=created.email,
        role=User.Role.ADMIN,
        is_active=True,
    )
    created.refresh_from_db()
    assert created.role == User.Role.ADMIN
    assert set(User.Role.values) == {"ADMIN", "OPERATOR"}

    changed_role_client = Client()
    changed_role_client.force_login(created)
    assert changed_role_client.get(reverse("user-list")).status_code == 200
    update_user(
        actor=admin_user,
        user=created,
        email=created.email,
        role=User.Role.OPERATOR,
        is_active=True,
    )
    assert changed_role_client.get(reverse("user-list")).status_code == 403

    with pytest.raises(ValidationError):
        create_user(
            actor=admin_user,
            username="unsupported-role",
            email="",
            role="REVIEWER",
            password="Unsupported-Role-Password-77!",
        )

    operator_user.is_staff = True
    operator_user.is_superuser = True
    operator_user.groups.add(Group.objects.create(name="qa-extra-framework-group"))
    operator_user.save(update_fields=["is_staff", "is_superuser"])
    before = fingerprint_users()
    client = Client()
    client.force_login(operator_user)

    assert client.get(reverse("dashboard")).status_code == 200
    assert client.get(reverse("user-list")).status_code == 403
    assert client.post(reverse("user-create"), {}).status_code == 403
    with pytest.raises(PermissionDenied):
        create_user(
            actor=operator_user,
            username="self-elevated",
            email="",
            role=User.Role.ADMIN,
            password="Self-Elevation-Password-42!",
        )
    assert fingerprint_users() == before
