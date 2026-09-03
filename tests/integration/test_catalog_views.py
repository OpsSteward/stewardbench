import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from catalog.models import (
    Domain,
    Environment,
    EvaluationTarget,
    HistoricalFixture,
    Product,
    Question,
    QuestionVersion,
    Tag,
    TargetRevision,
)


def revision_post(endpoint):
    return {
        "endpoint": endpoint,
        "adapter_key": "fixture",
        "adapter_version": "2",
        "credential_reference": "secrets/next-target",
        "classification": TargetRevision.Classification.DEVELOPMENT,
        "supports_question_api": "on",
        "supports_runtime_metadata": "on",
        "default_execution_mode": TargetRevision.ExecutionMode.PARALLEL,
        "max_concurrency": "2",
        "question_timeout_seconds": "60",
        "inter_question_delay_seconds": "0.500",
        "declared_product_version": "",
        "declared_build_id": "",
        "declared_git_sha": "",
    }


@pytest.mark.django_db
def test_operator_can_browse_catalog_and_mutation_controls_are_absent(minimal_domain):
    client = Client()
    client.force_login(minimal_domain["operator"])
    read_urls = [
        reverse("product-list"),
        reverse("product-detail", args=[minimal_domain["product"].slug]),
        reverse("environment-list"),
        reverse("environment-detail", args=[minimal_domain["environment"].slug]),
        reverse("domain-list"),
        reverse("tag-list"),
        reverse("fixture-list"),
        reverse("target-list"),
        reverse("target-detail", args=[minimal_domain["target"].slug]),
        reverse("question-list"),
        reverse("question-detail", args=[minimal_domain["question"].stable_id]),
    ]
    for url in read_urls:
        assert client.get(url).status_code == 200

    response = client.get(reverse("question-detail", args=["FIXTURE-001"]))
    assert "Quantos transceivers estão em uso?" in response.content.decode()
    assert "New version" not in response.content.decode()


@pytest.mark.django_db
def test_operator_direct_catalog_mutations_are_forbidden_and_state_is_unchanged(
    minimal_domain,
):
    client = Client(enforce_csrf_checks=True)
    client.force_login(minimal_domain["operator"])
    client.get(reverse("dashboard"))
    token = client.cookies["csrftoken"].value
    target = minimal_domain["target"]
    question = minimal_domain["question"]
    mutation_urls = [
        reverse("product-create"),
        reverse("product-update", args=[minimal_domain["product"].slug]),
        reverse("environment-create"),
        reverse("environment-update", args=[minimal_domain["environment"].slug]),
        reverse("domain-create"),
        reverse("domain-update", args=[minimal_domain["domain"].slug]),
        reverse("tag-create"),
        reverse("fixture-create"),
        reverse("target-create"),
        reverse("target-update", args=[target.slug]),
        reverse("target-revision-create", args=[target.slug]),
        reverse("question-create"),
        reverse("question-update", args=[question.stable_id]),
        reverse("question-version-create", args=[question.stable_id]),
        reverse("question-lifecycle-update", args=[question.stable_id, "RETIRED"]),
    ]
    before = {
        "products": list(Product.objects.values_list("pk", "display_name", "is_active")),
        "question": list(
            Question.objects.values_list("pk", "lifecycle", "domain_id", "rationale")
        ),
        "versions": list(
            QuestionVersion.objects.values_list(
                "pk", "version_number", "question_text", "valid_from", "valid_to"
            )
        ),
        "revisions": list(
            TargetRevision.objects.values_list(
                "pk", "revision_number", "endpoint", "valid_from", "valid_to"
            )
        ),
    }
    for url in mutation_urls:
        response = client.post(
            url,
            {"csrfmiddlewaretoken": token},
            HTTP_REFERER="http://testserver/",
        )
        assert response.status_code == 403, url

    after = {
        "products": list(Product.objects.values_list("pk", "display_name", "is_active")),
        "question": list(
            Question.objects.values_list("pk", "lifecycle", "domain_id", "rationale")
        ),
        "versions": list(
            QuestionVersion.objects.values_list(
                "pk", "version_number", "question_text", "valid_from", "valid_to"
            )
        ),
        "revisions": list(
            TargetRevision.objects.values_list(
                "pk", "revision_number", "endpoint", "valid_from", "valid_to"
            )
        ),
    }
    assert after == before


@pytest.mark.django_db
def test_admin_catalog_forms_create_and_version_objects(minimal_domain):
    client = Client()
    client.force_login(minimal_domain["admin"])

    response = client.post(
        reverse("product-create"),
        {
            "slug": "other-product",
            "display_name": "Other Product",
            "description": "No vendor assumptions",
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    created = Product.objects.get(slug="other-product")
    assert created.created_by == minimal_domain["admin"]

    question = minimal_domain["question"]
    response = client.post(
        reverse("question-version-create", args=[question.stable_id]),
        {
            "question_text": "Versão nova — conteúdo exato.",
            "evaluation_guidance": "",
            "change_type": QuestionVersion.ChangeType.TEST_BUG_FIX,
            "change_reason": "Corrected test wording",
            "bindings-TOTAL_FORMS": "1",
            "bindings-INITIAL_FORMS": "0",
            "bindings-MIN_NUM_FORMS": "0",
            "bindings-MAX_NUM_FORMS": "1000",
            "bindings-0-name": "device_id",
            "bindings-0-value_type": "IDENTIFIER",
            "bindings-0-is_required": "on",
            "bindings-0-description": "Stable device identifier",
        },
    )
    assert response.status_code == 302
    assert question.versions.get(valid_to__isnull=True).question_text == "Versão nova — conteúdo exato."
    assert question.versions.count() == 2
    assert question.versions.get(valid_to__isnull=True).binding_definitions.get().name == "device_id"

    target = minimal_domain["target"]
    response = client.post(
        reverse("target-revision-create", args=[target.slug]),
        revision_post("https://target-v2.example.invalid/api"),
    )
    assert response.status_code == 302
    assert target.revisions.count() == 2
    assert target.revisions.get(valid_to__isnull=True).endpoint.endswith("/api")


@pytest.mark.django_db
def test_admin_can_create_complete_catalog_graph_through_product_ui(minimal_domain):
    client = Client()
    client.force_login(minimal_domain["admin"])

    assert client.post(
        reverse("environment-create"),
        {
            "slug": "ui-environment",
            "display_name": "UI Environment",
            "description": "Created through product UI",
            "is_active": "on",
        },
    ).status_code == 302
    assert client.post(
        reverse("domain-create"),
        {
            "slug": "ui-domain",
            "name": "UI Domain",
            "description": "Controlled domain",
            "is_active": "on",
        },
    ).status_code == 302
    assert client.post(reverse("tag-create"), {"name": "São-Paulo"}).status_code == 302

    environment = Environment.objects.get(slug="ui-environment")
    domain = Domain.objects.get(slug="ui-domain")
    tag = Tag.objects.get(name="São-Paulo")
    target_data = {
        "target-slug": "ui-target",
        "target-display_name": "UI Target",
        "target-product": str(minimal_domain["product"].pk),
        "target-environment": str(environment.pk),
        "target-is_active": "on",
    }
    target_data.update(
        {
            f"revision-{key}": value
            for key, value in revision_post(
                "https://ui-target.example.invalid/api"
            ).items()
        }
    )
    response = client.post(reverse("target-create"), target_data)
    assert response.status_code == 302, response.context and response.context["revision_form"].errors
    target = EvaluationTarget.objects.get(slug="ui-target")
    assert target.current_revision.classification == TargetRevision.Classification.DEVELOPMENT

    response = client.post(
        reverse("question-create"),
        {
            "stable_id": "RUBIN-CONV-01.1",
            "kind": Question.Kind.SINGLE_TURN,
            "lifecycle": Question.Lifecycle.ACTIVE,
            "domain": str(domain.pk),
            "tags": [str(tag.pk)],
            "rationale": "Razão operacional",
            "question_text": "Qual caminho está ativo em São Paulo?",
            "evaluation_guidance": "",
            "bindings-TOTAL_FORMS": "1",
            "bindings-INITIAL_FORMS": "0",
            "bindings-MIN_NUM_FORMS": "0",
            "bindings-MAX_NUM_FORMS": "1000",
            "bindings-0-name": "path_id",
            "bindings-0-value_type": "IDENTIFIER",
            "bindings-0-is_required": "on",
            "bindings-0-description": "Path identifier",
        },
    )
    assert response.status_code == 302, response.context and response.context["form"].errors
    question = Question.objects.get(stable_id="RUBIN-CONV-01.1")
    assert question.lifecycle == Question.Lifecycle.ACTIVE
    assert question.current_version.binding_definitions.get().name == "path_id"
    assert client.post(
        reverse("question-lifecycle-update", args=[question.stable_id, "RETIRED"])
    ).status_code == 302
    question.refresh_from_db()
    assert question.lifecycle == Question.Lifecycle.RETIRED

    response = client.post(
        reverse("fixture-create"),
        {
            "stable_id": "UI-WINDOW-01",
            "name": "UI quiet window",
            "environment": str(environment.pk),
            "window_start": "2026-01-01T00:00",
            "window_end": "2026-01-01T01:00",
            "description": "Input context only",
            "tags": [str(tag.pk)],
            "fixed_parameters": '{"site_id": "São Paulo"}',
            "is_active": "on",
        },
    )
    assert response.status_code == 302, response.context and response.context["form"].errors
    fixture = HistoricalFixture.objects.get(stable_id="UI-WINDOW-01")
    assert fixture.fixed_parameters == {"site_id": "São Paulo"}


@pytest.mark.django_db
def test_question_filters_are_url_addressable_and_reconcile_records(minimal_domain):
    client = Client()
    client.force_login(minimal_domain["operator"])
    response = client.get(
        reverse("question-list"),
        {
            "q": "transceivers",
            "domain": minimal_domain["domain"].slug,
            "tag": minimal_domain["tag"].name,
            "lifecycle": Question.Lifecycle.ACTIVE,
        },
    )
    body = response.content.decode()
    assert response.status_code == 200
    assert "FIXTURE-001" in body
    assert "1 questions" in body

    response = client.get(reverse("question-list"), {"q": "does-not-exist"})
    assert "No questions match these filters." in response.content.decode()


@pytest.mark.django_db
def test_question_list_paginates_catalog_records(minimal_domain):
    created = Question.objects.bulk_create(
        [
            Question(
                stable_id=f"PAGE-{number:03d}",
                kind=Question.Kind.SINGLE_TURN,
                lifecycle=Question.Lifecycle.DRAFT,
                created_by=minimal_domain["admin"],
                updated_by=minimal_domain["admin"],
            )
            for number in range(50)
        ]
    )
    now = timezone.now()
    QuestionVersion.objects.bulk_create(
        [
            QuestionVersion(
                question=question,
                version_number=1,
                question_text=f"Pagination question {number}",
                valid_from=now,
                created_by=minimal_domain["admin"],
            )
            for number, question in enumerate(created)
        ]
    )
    client = Client()
    client.force_login(minimal_domain["operator"])

    response = client.get(reverse("question-list"), {"page": 2})
    body = response.content.decode()
    assert response.status_code == 200
    assert "Page 2 of 2" in body
    assert "51 questions" in body
    assert "PAGE-049" in body


@pytest.mark.django_db
def test_catalog_mutations_require_authentication_and_csrf(minimal_domain):
    anonymous = Client()
    assert anonymous.get(reverse("question-list")).status_code == 302
    assert anonymous.post(reverse("product-create"), {}).status_code == 302

    admin = Client(enforce_csrf_checks=True)
    admin.force_login(minimal_domain["admin"])
    assert admin.post(reverse("product-create"), {}).status_code == 403
