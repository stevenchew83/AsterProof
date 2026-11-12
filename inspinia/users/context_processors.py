from django.conf import settings
from django.utils.functional import SimpleLazyObject

from inspinia.pages.models import StatementIssueReport
from inspinia.pages.shared_progress import LEARNER_LABELS
from inspinia.pages.shared_progress import shared_progress_learners
from inspinia.users.models import UserAccessSettings
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.roles import user_can_curate_training
from inspinia.users.roles import user_has_admin_role
from inspinia.users.roles import user_has_moderator_or_admin_role
from inspinia.users.roles import user_has_trainer_or_admin_role


def allauth_settings(request):
    """Expose the effective signup policy in templates."""
    return {
        "ACCOUNT_ALLOW_REGISTRATION": SimpleLazyObject(UserAccessSettings.public_registration_is_open),
    }


def app_roles(request):
    """Navigation and UI flags derived from roles."""
    # Early error pages can render before authentication middleware runs.
    user = getattr(request, "user", None)
    approved = user_can_access_app_features(user)
    admin = user_has_admin_role(user)
    trainer = user_has_trainer_or_admin_role(user)
    can_access_rankings = approved and user_has_moderator_or_admin_role(user)
    can_access_admin_tools = approved and (admin or settings.DEBUG)
    can_curate_training = user_can_curate_training(user)
    shared_links = shared_progress_learners(user)
    return {
        "is_app_admin": admin,
        "statement_report_open_count": (
            StatementIssueReport.objects.filter(status=StatementIssueReport.Status.OPEN).count() if admin else 0
        ),
        "is_app_approved": approved,
        "is_app_trainer": trainer,
        "show_training_dashboard_link": approved,
        "show_training_roadmap_link": approved,
        "show_training_submissions_link": approved,
        "show_training_trainer_links": approved and trainer,
        "show_training_admin_links": approved and admin,
        "show_rankings_link": can_access_rankings,
        "show_analytics_dashboard_link": can_access_admin_tools,
        "show_event_log_link": approved and admin,
        "show_my_progress_analytics_link": approved,
        "show_problem_lists_link": approved,
        "show_problem_list_discovery_link": approved,
        "show_problem_import_link": can_access_admin_tools,
        "show_session_monitor_link": approved and admin,
        "show_solution_workspace_link": approved,
        "show_training_curation_link": can_curate_training,
        "shared_progress_links": shared_links,
        "shared_progress_comparison_available": len(shared_links) == len(LEARNER_LABELS),
        "show_management_links": can_access_admin_tools or can_access_rankings or can_curate_training or trainer,
        "show_training_library_link": approved,
        "show_completion_quick_update_link": approved,
        "show_user_activity_dashboard_link": approved,
        "show_contest_advanced_dashboard_link": approved,
    }
