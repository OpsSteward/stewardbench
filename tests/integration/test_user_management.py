import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from accounts.models import User
from accounts.services import create_user, update_user


@pytest.mark.django_db
def test_admin_can_create_and_change_product_user(admin_user):
    user = create_user(
        actor=admin_user,
        username="managed-user",
        email="managed@example.invalid",
        role=User.Role.OPERATOR,
        password="Managed-User-Password-42!",
    )
    assert user.check_password("Managed-User-Password-42!")

    update_user(
        actor=admin_user,
        user=user,
        email=user.email,
        role=User.Role.ADMIN,
        is_active=False,
    )
    user.refresh_from_db()
    assert user.role == User.Role.ADMIN
    assert not user.is_active


@pytest.mark.django_db
def test_operator_service_mutation_is_rejected(operator_user):
    with pytest.raises(PermissionDenied):
        create_user(
            actor=operator_user,
            username="forbidden-user",
            email="",
            role=User.Role.ADMIN,
            password="Forbidden-User-Password-42!",
        )
    assert not User.objects.filter(username="forbidden-user").exists()


@pytest.mark.django_db
def test_service_rejects_unsupported_role(admin_user):
    with pytest.raises(ValidationError, match="ADMIN or OPERATOR"):
        create_user(
            actor=admin_user,
            username="unsupported-role",
            email="",
            role="REVIEWER",
            password="Unsupported-Role-Password-42!",
        )


@pytest.mark.django_db
def test_operator_direct_post_is_forbidden_with_unchanged_database(operator_user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(operator_user)
    client.get(reverse("dashboard"))
    token = client.cookies["csrftoken"].value
    before = list(User.objects.order_by("pk").values_list("pk", "username", "role", "is_active"))

    response = client.post(
        reverse("user-create"),
        {
            "csrfmiddlewaretoken": token,
            "username": "crafted-admin",
            "role": User.Role.ADMIN,
            "is_active": "on",
            "password1": "Crafted-Admin-Password-42!",
            "password2": "Crafted-Admin-Password-42!",
        },
        HTTP_REFERER="http://testserver/",
    )

    assert response.status_code == 403
    assert list(User.objects.order_by("pk").values_list("pk", "username", "role", "is_active")) == before


@pytest.mark.django_db
def test_framework_privileges_do_not_bypass_request_policy(operator_user):
    operator_user.is_staff = True
    operator_user.is_superuser = True
    operator_user.groups.add(Group.objects.create(name="arbitrary-framework-group"))
    operator_user.save(update_fields=["is_staff", "is_superuser"])
    client = Client()
    client.force_login(operator_user)

    assert client.get(reverse("dashboard")).status_code == 200
    assert client.get(reverse("user-list")).status_code == 403
    assert client.post(reverse("user-create"), {}).status_code == 403


@pytest.mark.django_db
def test_admin_mutation_requires_csrf(admin_user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)

    response = client.post(reverse("user-create"), {})
    assert response.status_code == 403
