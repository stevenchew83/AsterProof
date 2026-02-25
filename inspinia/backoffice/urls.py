from django.urls import path

from .views import dashboard
from .views import contest_submissions
from .views import grade_submission
from .views import global_analytics
from .views import ingestion_problem_request_action
from .views import ingestion_problem_requests
from .views import ingestion_problem_submission_action
from .views import ingestion_problem_submissions
from .views import moderation_logs
from .views import moderation_report_action
from .views import moderation_report_detail
from .views import moderation_report_list
from .views import problem_bulk_operations
from .views import problem_set_import
from .views import public_access_pages
from .views import rating_recalculate
from .views import rating_rollback
from .views import rating_runs
from .views import settings_abuse_policy
from .views import settings_branding
from .views import settings_feature_flags
from .views import settings_privacy_defaults
from .views import settings_rating_config
from .views import user_action
from .views import user_detail
from .views import users_list

app_name = "backoffice"

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("public-pages/", public_access_pages, name="public_access_pages"),
    path("moderation/reports/", moderation_report_list, name="moderation_reports"),
    path("moderation/reports/<int:report_id>/", moderation_report_detail, name="moderation_report_detail"),
    path("moderation/reports/<int:report_id>/action/", moderation_report_action, name="moderation_report_action"),
    path("moderation/logs/", moderation_logs, name="moderation_logs"),
    path("users/", users_list, name="users_list"),
    path("users/<int:user_id>/", user_detail, name="user_detail"),
    path("users/<int:user_id>/action/", user_action, name="user_action"),
    path("ingestion/problem-requests/", ingestion_problem_requests, name="ingestion_problem_requests"),
    path(
        "ingestion/problem-requests/<int:request_id>/action/",
        ingestion_problem_request_action,
        name="ingestion_problem_request_action",
    ),
    path("ingestion/problem-submissions/", ingestion_problem_submissions, name="ingestion_problem_submissions"),
    path(
        "ingestion/problem-submissions/<int:submission_id>/action/",
        ingestion_problem_submission_action,
        name="ingestion_problem_submission_action",
    ),
    path("ingestion/problem-import/", problem_set_import, name="problem_set_import"),
    path("ingestion/problem-bulk-ops/", problem_bulk_operations, name="problem_bulk_operations"),
    path("settings/abuse-policy/", settings_abuse_policy, name="settings_abuse_policy"),
    path("settings/feature-flags/", settings_feature_flags, name="settings_feature_flags"),
    path("settings/privacy-defaults/", settings_privacy_defaults, name="settings_privacy_defaults"),
    path("settings/branding/", settings_branding, name="settings_branding"),
    path("settings/rating-config/", settings_rating_config, name="settings_rating_config"),
    path("contests/submissions/", contest_submissions, name="contest_submissions"),
    path("contests/submissions/<int:submission_id>/grade/", grade_submission, name="grade_submission"),
    path("ratings/runs/", rating_runs, name="rating_runs"),
    path("ratings/recalculate/<int:contest_id>/", rating_recalculate, name="rating_recalculate"),
    path("ratings/rollback/<int:run_id>/", rating_rollback, name="rating_rollback"),
    path("analytics/global/", global_analytics, name="global_analytics"),
]
