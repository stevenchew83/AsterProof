from http import HTTPStatus

import pytest
from allauth.account.models import EmailAddress
from django.contrib.sessions.models import Session
from django.test import Client
from django.urls import reverse

from inspinia.users.models import AuditEvent
from inspinia.users.models import User
from inspinia.users.models import UserSession
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

TEST_PASSWORD = "StrongPass123!"  # noqa: S105
WRONG_TEST_PASSWORD = "wrong-password"  # noqa: S105


def _verify_email(user: User) -> None:
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": True},
    )


def _login_via_account_view(client, user: User, password: str):
    _verify_email(user)
    return client.post(
        reverse("account_login"),
        {"login": user.email, "password": password},
        follow=True,
    )


def test_login_creates_tracked_session_and_login_event(client):
    user = UserFactory(password=TEST_PASSWORD)

    response = _login_via_account_view(client, user, TEST_PASSWORD)

    assert response.status_code == HTTPStatus.OK
    session_key = client.session.session_key
    tracked_session = UserSession.objects.get(session_key=session_key)
    assert tracked_session.user == user
    assert tracked_session.ended_at is None
    assert AuditEvent.objects.filter(
        event_type=AuditEvent.EventType.LOGIN_SUCCEEDED,
        actor=user,
        target_user=user,
        session_key=session_key,
    ).exists()


def test_logout_marks_tracked_session_as_logged_out(client):
    user = UserFactory(password=TEST_PASSWORD)
    _login_via_account_view(client, user, TEST_PASSWORD)
    session_key = client.session.session_key

    response = client.post(reverse("account_logout"), follow=True)

    assert response.status_code == HTTPStatus.OK
    tracked_session = UserSession.objects.get(session_key=session_key)
    assert tracked_session.ended_reason == UserSession.Status.LOGGED_OUT
    assert tracked_session.ended_at is not None
    assert AuditEvent.objects.filter(
        event_type=AuditEvent.EventType.LOGOUT,
        actor=user,
        target_user=user,
        session_key=session_key,
    ).exists()


def test_failed_login_creates_audit_event(client):
    user = UserFactory(password=TEST_PASSWORD)

    logged_in = client.login(email=user.email, password=WRONG_TEST_PASSWORD)

    assert logged_in is False
    event = AuditEvent.objects.get(event_type=AuditEvent.EventType.LOGIN_FAILED)
    assert event.metadata["identifier"] == user.email


def test_monitoring_pages_forbid_non_admin_users(client):
    user = UserFactory()
    client.force_login(user)

    session_response = client.get(reverse("users:session_monitor"))
    event_log_response = client.get(reverse("users:event_log"))

    assert session_response.status_code == HTTPStatus.FORBIDDEN
    assert event_log_response.status_code == HTTPStatus.FORBIDDEN


def test_admin_can_revoke_another_users_session(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    member = UserFactory(password=TEST_PASSWORD)
    member_client = Client()
    response = _login_via_account_view(member_client, member, TEST_PASSWORD)
    assert response.status_code == HTTPStatus.OK
    session_key = member_client.session.session_key

    client.force_login(admin_user)
    response = client.post(
        reverse("users:session_monitor"),
        {"session_key": session_key},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    tracked_session = UserSession.objects.get(session_key=session_key)
    assert tracked_session.ended_reason == UserSession.Status.REVOKED
    assert not Session.objects.filter(session_key=session_key).exists()
    assert AuditEvent.objects.filter(
        event_type=AuditEvent.EventType.SESSION_REVOKED,
        actor=admin_user,
        target_user=member,
        session_key=session_key,
    ).exists()


def test_event_log_page_lists_recent_events(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    target_user = UserFactory()
    AuditEvent.objects.create(
        actor=admin_user,
        target_user=target_user,
        event_type=AuditEvent.EventType.ROLE_CHANGED,
        message=f"Changed role for {target_user.email}.",
    )
    client.force_login(admin_user)

    response = client.get(reverse("users:event_log"))

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode("utf-8")
    assert "Changed role for" in content
    assert "Role changed" in content
