from __future__ import annotations

from allauth.account.signals import user_signed_up
from django.contrib.auth.signals import user_logged_in
from django.contrib.auth.signals import user_logged_out
from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

from inspinia.users.models import AuditEvent
from inspinia.users.models import UserSession
from inspinia.users.monitoring import end_tracked_session
from inspinia.users.monitoring import get_session_key
from inspinia.users.monitoring import record_event
from inspinia.users.monitoring import touch_tracked_session


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs) -> None:
    tracked_session = touch_tracked_session(request, force=True)
    record_event(
        event_type=AuditEvent.EventType.LOGIN_SUCCEEDED,
        message=f"Signed in as {user.email}.",
        request=request,
        actor=user,
        target_user=user,
        session_key=tracked_session.session_key if tracked_session else get_session_key(request),
    )


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs) -> None:
    if user is None:
        return

    session_key = get_session_key(request)
    end_tracked_session(session_key=session_key, reason=UserSession.Status.LOGGED_OUT)
    record_event(
        event_type=AuditEvent.EventType.LOGOUT,
        message=f"Signed out {user.email}.",
        request=request,
        actor=user,
        target_user=user,
        session_key=session_key,
    )


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs) -> None:
    login_identifier = (
        credentials.get("login")
        or credentials.get("email")
        or credentials.get("username")
        or ""
    )
    message = "Login failed."
    if login_identifier:
        message = f"Login failed for {login_identifier}."

    record_event(
        event_type=AuditEvent.EventType.LOGIN_FAILED,
        message=message,
        request=request,
        metadata={"identifier": login_identifier} if login_identifier else {},
    )


@receiver(user_signed_up)
def log_user_signed_up(request, user, **kwargs) -> None:
    record_event(
        event_type=AuditEvent.EventType.SIGNUP,
        message=f"Created account for {user.email}.",
        request=request,
        actor=user,
        target_user=user,
    )
