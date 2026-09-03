from django.urls import path

from . import views


urlpatterns = [
    path("runs/", views.run_list, name="run-list"),
    path("runs/launch/", views.launch_run_view, name="run-launch"),
    path("runs/launch/question/<int:question_id>/", views.launch_one_question_view, name="run-launch-one"),
    path("runs/<uuid:run_id>/", views.run_detail, name="run-detail"),
    path("runs/<uuid:run_id>/progress/", views.run_progress_view, name="run-progress"),
    path("runs/<uuid:run_id>/comments/", views.run_comment_view, name="run-comment"),
    path("runs/<uuid:run_id>/rerun/", views.rerun_source_run_view, name="run-rerun"),
    path("executions/<int:execution_id>/", views.execution_detail, name="execution-detail"),
    path("executions/<int:execution_id>/review/", views.record_human_review_view, name="execution-review"),
    path("executions/<int:execution_id>/review-state/", views.review_state_view, name="execution-review-state"),
    path("executions/<int:execution_id>/comments/", views.execution_comment_view, name="execution-comment"),
    path("executions/<int:execution_id>/validity/", views.execution_validity_view, name="execution-validity"),
    path("executions/<int:execution_id>/retry/", views.retry_execution_view, name="execution-retry"),
]
