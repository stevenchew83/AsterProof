from django.conf import settings

from inspinia.users.roles import user_has_admin_role


def allauth_settings(request):
    """Expose some settings from django-allauth in templates."""
    return {
        "ACCOUNT_ALLOW_REGISTRATION": settings.ACCOUNT_ALLOW_REGISTRATION,
    }


def app_roles(request):
    """Navigation and UI flags derived from roles."""
    admin = user_has_admin_role(request.user)
    can_access_admin_tools = admin or settings.DEBUG
    return {
        "is_app_admin": admin,
        "show_analytics_dashboard_link": can_access_admin_tools,
        "show_event_log_link": admin,
        "show_problem_import_link": can_access_admin_tools,
        "show_session_monitor_link": admin,
        "show_solution_workspace_link": request.user.is_authenticated,
        "show_completion_quick_update_link": request.user.is_authenticated,
        "show_user_activity_dashboard_link": request.user.is_authenticated,
        "show_contest_advanced_dashboard_link": request.user.is_authenticated,
    }
