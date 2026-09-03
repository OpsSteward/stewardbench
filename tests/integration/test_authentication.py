import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_valid_login_and_logout_invalidates_session(client, admin_user):
    response = client.post(
        reverse("login"),
        {"username": admin_user.username, "password": "Admin-Fixture-Password-42!"},
    )
    assert response.status_code == 302
    assert response.url == reverse("dashboard")
    assert client.get(reverse("dashboard")).status_code == 200

    response = client.post(reverse("logout"))
    assert response.status_code == 302
    assert client.get(reverse("dashboard")).status_code == 302


@pytest.mark.django_db
def test_invalid_and_inactive_credentials_are_denied_without_echo(
    client, admin_user, inactive_user
):
    canary = "Wrong-Password-Canary-219!"
    failed = client.post(
        reverse("login"),
        {"username": admin_user.username, "password": canary},
    )
    inactive = client.post(
        reverse("login"),
        {"username": inactive_user.username, "password": "Inactive-Fixture-Password-42!"},
    )

    assert failed.status_code == 200
    assert inactive.status_code == 200
    assert canary.encode() not in failed.content
    assert reverse("dashboard").encode() not in inactive.get("Location", "").encode()
    assert client.get(reverse("dashboard")).status_code == 302


@pytest.mark.django_db
def test_deactivation_invalidates_subsequent_authenticated_request(client, operator_user):
    client.force_login(operator_user)
    assert client.get(reverse("dashboard")).status_code == 200
    operator_user.is_active = False
    operator_user.save(update_fields=["is_active"])

    assert client.get(reverse("dashboard")).status_code == 302


@pytest.mark.django_db
def test_anonymous_product_views_redirect_to_login(client):
    for url in [
        reverse("dashboard"),
        reverse("user-list"),
        reverse("user-create"),
        reverse("health-live"),
        reverse("health-ready"),
    ]:
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))
