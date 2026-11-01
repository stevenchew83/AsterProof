"""Admin summaries of measured visits, separate from historical page-open counts."""

from django.conf import settings
from django.db import transaction
from django.db.models import Avg
from django.db.models import Count
from django.db.models import Sum
from django.db.utils import OperationalError
from django.db.utils import ProgrammingError
from django.utils import timezone

from inspinia.pages.learning_activity import ACTION_LABELS
from inspinia.pages.learning_activity import LEARNING_PAGES
from inspinia.pages.models import LearningPageAction
from inspinia.pages.models import LearningPageVisit
from inspinia.users.models import User

TABLE_LIMIT = 10
RECENT_LIMIT = 20
USER_LIMIT = 500
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600


def duration_label(milliseconds):
    seconds = round((milliseconds or 0) / 1000)
    if seconds >= SECONDS_PER_HOUR:
        return f"{seconds // SECONDS_PER_HOUR}h {(seconds % SECONDS_PER_HOUR) // SECONDS_PER_MINUTE}m"
    if seconds >= SECONDS_PER_MINUTE:
        return f"{seconds // SECONDS_PER_MINUTE}m {seconds % SECONDS_PER_MINUTE}s"
    return f"{seconds}s"


def _build(date_range, include_admins, params):
    visits = LearningPageVisit.objects.all()
    if date_range.start_at:
        visits = visits.filter(started_at__gte=date_range.start_at)
    if date_range.end_at:
        visits = visits.filter(started_at__lt=date_range.end_at)
    if not include_admins:
        visits = visits.filter(user__is_superuser=False).exclude(user__role=User.Role.ADMIN)
    user_options = list(
        visits.values("user_id", "user__name", "user__email")
        .distinct().order_by("user__name", "user_id")[:USER_LIMIT],
    )
    selected_user = ((params.get("activity_user") if params is not None else "") or "").strip()
    for option in user_options:
        option["value"] = str(option["user_id"])
        option["selected"] = option["value"] == selected_user
    if selected_user.isdigit():
        visits = visits.filter(user_id=int(selected_user))
    aggregate = visits.aggregate(
        total=Count("pk"),
        users=Count("user", distinct=True),
        total_visible_ms=Sum("visible_ms"),
        average_ms=Avg("visible_ms"),
        clicks=Sum("click_total"),
    )
    pages = list(
        visits.values("page_name", "path")
        .annotate(
            visits=Count("pk"),
            total_ms=Sum("visible_ms"),
            average_ms=Avg("visible_ms"),
            clicks=Sum("click_total"),
        )
        .order_by("-total_ms", "page_name", "path")[:TABLE_LIMIT],
    )
    maximum = max((row["total_ms"] for row in pages), default=0) or 1
    for row in pages:
        row.update(
            label=LEARNING_PAGES.get(row["page_name"], "Learning page"),
            duration=duration_label(row["total_ms"]),
            average=duration_label(row["average_ms"]),
            width=round(row["total_ms"] / maximum * 100),
        )
    actions = list(
        LearningPageAction.objects.filter(visit__in=visits)
        .values("action", "visit__page_name")
        .annotate(
            clicks=Sum("count"),
            users=Count("visit__user", distinct=True),
        )
        .order_by("-clicks", "action", "visit__page_name")[:TABLE_LIMIT],
    )
    maximum = max((row["clicks"] for row in actions), default=0) or 1
    for row in actions:
        row.update(
            label=ACTION_LABELS.get(row["action"], "Other button"),
            page=LEARNING_PAGES.get(row["visit__page_name"], "Learning page"),
            width=round(row["clicks"] / maximum * 100),
        )
    recent = []
    for visit in visits.select_related("user").order_by("-started_at")[:RECENT_LIMIT]:
        recent.append(  # noqa: PERF401 -- Keep the bounded formatting row readable.
            {
                "user": visit.user.name or visit.user.email,
                "page": LEARNING_PAGES.get(visit.page_name, "Learning page"),
                "path": visit.path,
                "time": timezone.localtime(visit.started_at).strftime("%Y-%m-%d %H:%M"),
                "duration": duration_label(visit.visible_ms),
                "clicks": visit.click_total,
            },
        )
    hidden_filters = [
        {"name": name, "value": params.get(name, "") if params is not None else ""}
        for name in ("range", "start", "end", "include_admins", "include_anonymous", "surface", "user", "q")
    ]
    return {
        "available": True,
        "enabled": settings.LEARNING_ACTIVITY_ENABLED,
        "visits": aggregate["total"],
        "users": aggregate["users"],
        "clicks": aggregate["clicks"] or 0,
        "duration": duration_label(aggregate["total_visible_ms"]),
        "average": duration_label(aggregate["average_ms"]),
        "pages": pages,
        "actions": actions,
        "recent": recent,
        "user_options": user_options,
        "selected_user": selected_user,
        "hidden_filters": hidden_filters,
    }


def build_learning_activity_analytics(date_range, include_admins, params):
    try:
        with transaction.atomic():
            return _build(date_range, include_admins, params)
    except (OperationalError, ProgrammingError):
        return {"available": False, "enabled": settings.LEARNING_ACTIVITY_ENABLED}
