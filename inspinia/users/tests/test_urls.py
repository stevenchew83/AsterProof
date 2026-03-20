from django.urls import resolve
from django.urls import reverse

from inspinia.users.models import User


def test_detail(user: User):
    assert reverse("users:detail", kwargs={"pk": user.pk}) == f"/users/{user.pk}/"
    assert resolve(f"/users/{user.pk}/").view_name == "users:detail"


def test_update():
    assert reverse("users:update") == "/users/~update/"
    assert resolve("/users/~update/").view_name == "users:update"


def test_profile():
    assert reverse("users:profile") == "/users/profile/"
    assert resolve("/users/profile/").view_name == "users:profile"


def test_profile_edit():
    assert reverse("users:profile_edit") == "/users/profile/edit/"
    assert resolve("/users/profile/edit/").view_name == "users:profile_edit"


def test_redirect():
    assert reverse("users:redirect") == "/users/~redirect/"
    assert resolve("/users/~redirect/").view_name == "users:redirect"


def test_session_monitor():
    assert reverse("users:session_monitor") == "/users/monitor/sessions/"
    assert resolve("/users/monitor/sessions/").view_name == "users:session_monitor"


def test_event_log():
    assert reverse("users:event_log") == "/users/monitor/events/"
    assert resolve("/users/monitor/events/").view_name == "users:event_log"
