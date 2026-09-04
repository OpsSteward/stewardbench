from django.urls import path

from . import views


urlpatterns = [
    path("baselines/", views.baseline_list, name="baseline-list"),
    path("baselines/<uuid:baseline_id>/", views.baseline_detail, name="baseline-detail"),
    path("baselines/<uuid:baseline_id>/state/", views.baseline_state_view, name="baseline-state"),
    path(
        "baselines/<uuid:baseline_id>/controlled-replay/",
        views.launch_controlled_comparison_view,
        name="baseline-controlled-replay",
    ),
    path("comparisons/", views.comparison_list, name="comparison-list"),
    path("comparisons/<int:comparison_id>/export.csv", views.comparison_csv_export, name="comparison-csv-export"),
    path("comparisons/<int:comparison_id>/", views.comparison_detail, name="comparison-detail"),
    path(
        "comparison-items/<int:item_id>/semantic-reevaluate/",
        views.semantic_reevaluate_view,
        name="semantic-reevaluate",
    ),
    path("runs/", views.run_list, name="run-list"),
    path("runs/<uuid:run_id>/export.json", views.run_json_export, name="run-json-export"),
    path("runs/<uuid:run_id>/executions.csv", views.run_csv_export, name="run-csv-export"),
    path("runs/launch/", views.launch_run_view, name="run-launch"),
    path("runs/launch/question/<int:question_id>/", views.launch_one_question_view, name="run-launch-one"),
    path(
        "conversation-scenarios/<str:stable_id>/launch/",
        views.launch_conversation_scenario_view,
        name="conversation-scenario-launch",
    ),
    path("runs/<uuid:run_id>/", views.run_detail, name="run-detail"),
    path("runs/<uuid:run_id>/progress/", views.run_progress_view, name="run-progress"),
    path("runs/<uuid:run_id>/comments/", views.run_comment_view, name="run-comment"),
    path("runs/<uuid:run_id>/rerun/", views.rerun_source_run_view, name="run-rerun"),
    path("runs/<uuid:run_id>/baselines/", views.create_baseline_view, name="baseline-create"),
    path("executions/", views.execution_list, name="execution-list"),
    path("executions/export.csv", views.execution_csv_export, name="execution-csv-export"),
    path("executions/<int:execution_id>/", views.execution_detail, name="execution-detail"),
    path(
        "executions/<int:execution_id>/judge-reevaluate/",
        views.judge_reevaluate_view,
        name="judge-reevaluate",
    ),
    path(
        "executions/<int:execution_id>/evaluator-reevaluate/",
        views.evaluator_reevaluate_view,
        name="evaluator-reevaluate",
    ),
    path("executions/<int:execution_id>/review/", views.record_human_review_view, name="execution-review"),
    path("executions/<int:execution_id>/review-state/", views.review_state_view, name="execution-review-state"),
    path("executions/<int:execution_id>/comments/", views.execution_comment_view, name="execution-comment"),
    path("executions/<int:execution_id>/validity/", views.execution_validity_view, name="execution-validity"),
    path("executions/<int:execution_id>/retry/", views.retry_execution_view, name="execution-retry"),
    path(
        "conversation-attempts/<int:attempt_id>/retry/",
        views.retry_conversation_attempt_view,
        name="conversation-attempt-retry",
    ),
]
