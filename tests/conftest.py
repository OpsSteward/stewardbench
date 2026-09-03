import pytest
from django.db import connection

from accounts.models import User
from catalog.models import Question, TargetRevision
from catalog.services import (
    create_domain,
    create_environment,
    create_product,
    create_question,
    create_tag,
    create_target,
)


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
    product = create_product(
        actor=admin_user,
        slug="fixture-product",
        display_name="Fixture Product",
        description="Product-neutral acceptance fixture",
    )
    environment = create_environment(
        actor=admin_user,
        slug="fixture-environment",
        display_name="Fixture Environment",
        description="Logical fixture context",
    )
    domain = create_domain(
        actor=admin_user,
        slug="network-operations",
        name="Network Operations",
    )
    tag = create_tag(actor=admin_user, name="Português")
    target = create_target(
        actor=admin_user,
        slug="fixture-target",
        display_name="Fixture Target",
        product=product,
        environment=environment,
        revision={
            "endpoint": "https://target.example.invalid/api",
            "adapter_key": "fixture",
            "adapter_version": "1",
            "credential_reference": "secrets/fixture-target",
            "classification": TargetRevision.Classification.LAB_TEST,
            "supports_question_api": True,
            "supports_conversation_session": False,
            "supports_runtime_metadata": False,
            "supports_health_check": True,
            "default_execution_mode": TargetRevision.ExecutionMode.SEQUENTIAL,
            "max_concurrency": 1,
            "question_timeout_seconds": 30,
            "inter_question_delay_seconds": 0,
            "declared_product_version": "",
            "declared_build_id": "",
            "declared_git_sha": "",
        },
    )
    question = create_question(
        actor=admin_user,
        stable_id="FIXTURE-001",
        kind=Question.Kind.SINGLE_TURN,
        lifecycle=Question.Lifecycle.ACTIVE,
        domain=domain,
        tags=[tag],
        rationale="Exercises exact Unicode question storage.",
        question_text="Quantos transceivers estão em uso?",
        bindings=(),
    )
    return {
        "admin": admin_user,
        "operator": operator_user,
        "inactive": inactive_user,
        "product": product,
        "environment": environment,
        "domain": domain,
        "tag": tag,
        "target": target,
        "question": question,
    }
