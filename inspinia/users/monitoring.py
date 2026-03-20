from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any

from django.contrib.sessions.models import Session
from django.db import connections
from django.db import router
from django.db.models import F
from django.db.utils import OperationalError
from django.db.utils import ProgrammingError
from django.utils import timezone

from inspinia.users.models import AuditEvent
from inspinia.users.models import User
from inspinia.users.models import UserSession

if TYPE_CHECKING:
    from django.http import HttpRequest

SESSION_TOUCH_INTERVAL = timedelta(minutes=5)
SESSION_TOUCH_CACHE_KEY = "_asterproof_session_last_touch_ts"
USER_AGENT_MAX_LENGTH = 1000
PATH_MAX_LENGTH = 255


def _trim(value: str | None, *, max_length: int) -> str:
    if not value:
        return ""
    return value.strip()[:max_length]


def _model_table_exists(model) -> bool:
    connection = connections[router.db_for_write(model)]
    try:
        return model._meta.db_table in connection.introspection.table_names()  # noqa: SLF001
    except (OperationalError, ProgrammingError):
        return False


def get_client_ip(request: HttpRequest | None) -> str | None:
    if request is None:
        return None
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        first_hop = forwarded_for.split(",", maxsplit=1)[0].strip()
        if first_hop:
            return first_hop
    remote_addr = request.META.get("REMOTE_ADDR")
    return remote_addr.strip() if remote_addr else None


def get_session_key(request: HttpRequest | None, *, create: bool = False) -> str:
    if request is None or not hasattr(request, "session"):
        return ""

    session_key = request.session.session_key or ""
    if session_key or not create:
        return session_key

    request.session.save()
    return request.session.session_key or ""


def record_event(  # noqa: PLR0913
    *,
    event_type: str,
    message: str,
    request: HttpRequest | None = None,
    actor: User | None = None,
    target_user: User | None = None,
    metadata: dict[str, Any] | None = None,
    session_key: str | None = None,
) -> AuditEvent | None:
    effective_actor = actor
    request_user = getattr(request, "user", None) if request is not None else None
    if effective_actor is None and getattr(request_user, "is_authenticated", False):
        effective_actor = request_user
    if not _model_table_exists(AuditEvent):
        return None

    try:
        return AuditEvent.objects.create(
            actor=effective_actor,
            target_user=target_user,
            event_type=event_type,
            message=message[:255],
            session_key=session_key if session_key is not None else get_session_key(request),
            path=_trim(getattr(request, "path", ""), max_length=PATH_MAX_LENGTH),
            ip_address=get_client_ip(request),
            user_agent=_trim(
                request.META.get("HTTP_USER_AGENT") if request is not None else "",
                max_length=USER_AGENT_MAX_LENGTH,
            ),
            metadata=metadata or {},
        )
    except (OperationalError, ProgrammingError):
        return None


def ensure_tracked_session(request: HttpRequest) -> UserSession | None:  # noqa: C901
    request_user = getattr(request, "user", None)
    if not getattr(request_user, "is_authenticated", False):
        return None
    assert request_user is not None
    if not _model_table_exists(UserSession):
        return None

    session_key = get_session_key(request, create=True)
    if not session_key:
        return None

    expires_at = request.session.get_expiry_date()
    ip_address = get_client_ip(request)
    user_agent = _trim(request.META.get("HTTP_USER_AGENT"), max_length=USER_AGENT_MAX_LENGTH)

    try:
        tracked_session, created = UserSession.objects.get_or_create(
            session_key=session_key,
            defaults={
                "user": request_user,
                "expires_at": expires_at,
                "ip_address": ip_address,
                "user_agent": user_agent,
            },
        )
    except (OperationalError, ProgrammingError):
        return None
    if created:
        return tracked_session

    update_fields: list[str] = []
    if tracked_session.user_id != request_user.id:
        tracked_session.user = request_user
        update_fields.append("user")
    if tracked_session.expires_at != expires_at:
        tracked_session.expires_at = expires_at
        update_fields.append("expires_at")
    if ip_address and tracked_session.ip_address != ip_address:
        tracked_session.ip_address = ip_address
        update_fields.append("ip_address")
    if user_agent and tracked_session.user_agent != user_agent:
        tracked_session.user_agent = user_agent
        update_fields.append("user_agent")
    if tracked_session.ended_at is not None:
        tracked_session.ended_at = None
        update_fields.append("ended_at")
    if tracked_session.ended_reason:
        tracked_session.ended_reason = ""
        update_fields.append("ended_reason")

    if update_fields:
        tracked_session.save(update_fields=update_fields)
    return tracked_session


def touch_tracked_session(request: HttpRequest, *, force: bool = False) -> UserSession | None:
    tracked_session = ensure_tracked_session(request)
    if tracked_session is None:
        return None

    now = timezone.now()
    last_touch_raw = request.session.get(SESSION_TOUCH_CACHE_KEY)
    touch_due = force
    if not touch_due:
        if not isinstance(last_touch_raw, int | float):
            touch_due = True
        else:
            last_touch = datetime.fromtimestamp(last_touch_raw, tz=UTC)
            touch_due = now - last_touch >= SESSION_TOUCH_INTERVAL

    if not touch_due:
        return tracked_session

    expires_at = request.session.get_expiry_date()
    tracked_session.last_seen_at = now
    tracked_session.expires_at = expires_at
    tracked_session.save(update_fields=["last_seen_at", "expires_at"])
    request.session[SESSION_TOUCH_CACHE_KEY] = int(now.timestamp())
    return tracked_session


def end_tracked_session(*, session_key: str, reason: str) -> UserSession | None:
    if not session_key:
        return None
    if not _model_table_exists(UserSession):
        return None

    try:
        tracked_session = UserSession.objects.filter(session_key=session_key).first()
    except (OperationalError, ProgrammingError):
        return None
    if tracked_session is None:
        return None

    update_fields: list[str] = []
    if tracked_session.ended_at is None:
        tracked_session.ended_at = timezone.now()
        update_fields.append("ended_at")
    if tracked_session.ended_reason != reason:
        tracked_session.ended_reason = reason
        update_fields.append("ended_reason")

    if update_fields:
        tracked_session.save(update_fields=update_fields)
    return tracked_session


def sync_expired_sessions() -> int:
    if not _model_table_exists(UserSession):
        return 0

    try:
        open_session_keys = list(
            UserSession.objects.filter(ended_at__isnull=True).values_list("session_key", flat=True),
        )
    except (OperationalError, ProgrammingError):
        return 0
    if not open_session_keys:
        return 0

    active_session_keys = set(
        Session.objects.filter(
            session_key__in=open_session_keys,
            expire_date__gt=timezone.now(),
        ).values_list("session_key", flat=True),
    )
    expired_session_keys = [key for key in open_session_keys if key not in active_session_keys]
    if not expired_session_keys:
        return 0

    return UserSession.objects.filter(
        session_key__in=expired_session_keys,
        ended_at__isnull=True,
    ).update(
        ended_at=F("expires_at"),
        ended_reason=UserSession.Status.EXPIRED,
    )


def revoke_tracked_session(
    *,
    tracked_session: UserSession,
    request: HttpRequest,
    actor: User,
) -> UserSession | None:
    Session.objects.filter(session_key=tracked_session.session_key).delete()
    revoked_session = end_tracked_session(
        session_key=tracked_session.session_key,
        reason=UserSession.Status.REVOKED,
    )
    record_event(
        event_type=AuditEvent.EventType.SESSION_REVOKED,
        message=f"Revoked session for {tracked_session.user.email}.",
        request=request,
        actor=actor,
        target_user=tracked_session.user,
        metadata={
            "revoked_session_key": tracked_session.session_key,
        },
        session_key=tracked_session.session_key,
    )
    return revoked_session
