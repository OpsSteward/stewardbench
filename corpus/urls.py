from django.urls import path

from . import views


urlpatterns = [
    path("", views.import_batch_list, name="import-batch-list"),
    path("<int:pk>/", views.import_batch_detail, name="import-batch-detail"),
    path(
        "legacy-observations/<int:pk>/",
        views.legacy_observation_detail,
        name="legacy-observation-detail",
    ),
]
