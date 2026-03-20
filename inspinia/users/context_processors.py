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
    return {
        "is_app_admin": admin,
        # Match `dashboard_analytics_view`: open in DEBUG, admin-only when DEBUG is off.
        "show_analytics_dashboard_link": admin or settings.DEBUG,
    }
