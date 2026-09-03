from django.urls import path

from . import views


urlpatterns = [
    path("runs/", views.run_list, name="run-list"),
    path("runs/launch/", views.launch_run_view, name="run-launch"),
    path("runs/launch/question/<int:question_id>/", views.launch_one_question_view, name="run-launch-one"),
    path("runs/<uuid:run_id>/", views.run_detail, name="run-detail"),
    path("runs/<uuid:run_id>/progress/", views.run_progress_view, name="run-progress"),
    path("executions/<int:execution_id>/", views.execution_detail, name="execution-detail"),
]
