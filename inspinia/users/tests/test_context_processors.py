import pytest
from django.contrib.auth.models import AnonymousUser

from inspinia.users.context_processors import app_roles
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_anonymous_user_has_no_approved_feature_links(rf):
    request = rf.get("/")
    request.user = AnonymousUser()

    flags = app_roles(request)

    assert flags["is_app_approved"] is False
    assert flags["show_user_activity_dashboard_link"] is False
    assert flags["show_solution_workspace_link"] is False


def test_unapproved_user_has_no_approved_feature_links(rf):
    request = rf.get("/")
    request.user = UserFactory(is_approved=False)

    flags = app_roles(request)

    assert flags["is_app_approved"] is False
    assert flags["show_user_activity_dashboard_link"] is False
    assert flags["show_completion_quick_update_link"] is False
    assert flags["show_solution_workspace_link"] is False
    assert flags["show_my_progress_analytics_link"] is False


def test_approved_user_keeps_personal_feature_links(rf):
    request = rf.get("/")
    request.user = UserFactory(is_approved=True)

    flags = app_roles(request)

    assert flags["is_app_approved"] is True
    assert flags["show_user_activity_dashboard_link"] is True
    assert flags["show_completion_quick_update_link"] is True
    assert flags["show_solution_workspace_link"] is True


def test_admin_keeps_admin_links_without_stored_approval(rf):
    request = rf.get("/")
    request.user = UserFactory(role=User.Role.ADMIN, is_approved=False)

    flags = app_roles(request)

    assert flags["is_app_approved"] is True
    assert flags["is_app_admin"] is True
    assert flags["show_event_log_link"] is True
    assert flags["show_session_monitor_link"] is True
