import pytest
from django.core.management import call_command
from django.urls import reverse


@pytest.mark.django_db
def test_health_distinguishes_liveness_and_postgresql_readiness(client, capsys, admin_user):
    client.force_login(admin_user)
    live = client.get(reverse("health-live"))
    ready = client.get(reverse("health-ready"))

    assert live.status_code == 200
    assert live.json() == {"status": "alive"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "postgresql"}

    call_command("check_database")
    assert "PostgreSQL ready." in capsys.readouterr().out


@pytest.mark.django_db
def test_worker_foundation_checks_database_once():
    call_command("run_worker", once=True)
