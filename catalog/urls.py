from django.urls import path

from . import views


urlpatterns = [
    path("products/", views.product_list, name="product-list"),
    path("products/new/", views.product_create, name="product-create"),
    path("products/<slug:slug>/", views.product_detail, name="product-detail"),
    path("products/<slug:slug>/edit/", views.product_update, name="product-update"),
    path("environments/", views.environment_list, name="environment-list"),
    path("environments/new/", views.environment_create, name="environment-create"),
    path("environments/<slug:slug>/", views.environment_detail, name="environment-detail"),
    path("environments/<slug:slug>/edit/", views.environment_update, name="environment-update"),
    path("domains/", views.domain_list, name="domain-list"),
    path("domains/new/", views.domain_create, name="domain-create"),
    path("domains/<slug:slug>/edit/", views.domain_update, name="domain-update"),
    path("tags/", views.tag_list, name="tag-list"),
    path("tags/new/", views.tag_create, name="tag-create"),
    path("fixtures/", views.fixture_list, name="fixture-list"),
    path("fixtures/new/", views.fixture_create, name="fixture-create"),
    path("targets/", views.target_list, name="target-list"),
    path("targets/new/", views.target_create, name="target-create"),
    path("targets/<slug:slug>/", views.target_detail, name="target-detail"),
    path("targets/<slug:slug>/edit/", views.target_update, name="target-update"),
    path(
        "targets/<slug:slug>/revisions/new/",
        views.target_revision_create,
        name="target-revision-create",
    ),
    path("questions/", views.question_list, name="question-list"),
    path("questions/new/", views.question_create, name="question-create"),
    path("questions/<str:stable_id>/", views.question_detail, name="question-detail"),
    path(
        "questions/<str:stable_id>/edit/",
        views.question_update,
        name="question-update",
    ),
    path(
        "questions/<str:stable_id>/versions/new/",
        views.question_version_create,
        name="question-version-create",
    ),
    path(
        "questions/<str:stable_id>/lifecycle/<str:lifecycle>/",
        views.question_lifecycle_update,
        name="question-lifecycle-update",
    ),
]
