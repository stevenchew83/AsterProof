from django.conf import settings

from inspinia.users.roles import user_can_access_app_features
from inspinia.users.roles import user_can_curate_training
from inspinia.users.roles import user_has_admin_role
from inspinia.users.roles import user_has_moderator_or_admin_role
from inspinia.users.roles import user_has_trainer_or_admin_role


def allauth_settings(request):
    """Expose some settings from django-allauth in templates."""
    return {
        "ACCOUNT_ALLOW_REGISTRATION": settings.ACCOUNT_ALLOW_REGISTRATION,
    }


def app_roles(request):
    """Navigation and UI flags derived from roles."""
    approved = user_can_access_app_features(request.user)
    admin = user_has_admin_role(request.user)
    trainer = user_has_trainer_or_admin_role(request.user)
    can_access_rankings = approved and user_has_moderator_or_admin_role(request.user)
    can_access_admin_tools = approved and (admin or settings.DEBUG)
    can_curate_training = user_can_curate_training(request.user)
    return {
        "is_app_admin": admin,
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
        "show_training_library_link": approved,
        "show_completion_quick_update_link": approved,
        "show_user_activity_dashboard_link": approved,
        "show_contest_advanced_dashboard_link": approved,
    }
