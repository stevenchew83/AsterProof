from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlparse

from django.db.models import Count
from django.db.models import Max
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import PageViewEvent
from inspinia.users.models import User

if TYPE_CHECKING:
    from django.http import QueryDict

TOP_PAGE_VIEW_LIMIT = 10
RECENT_PAGE_VIEW_LIMIT = 50
PAGE_VIEW_DEFAULT_RANGE = "30d"
PAGE_VIEW_ANONYMOUS_USER_FILTER = "__anonymous__"
PAGE_VIEW_RANGE_OPTIONS = [
    {"value": "today", "label": "Today"},
    {"value": "7d", "label": "Last 7 days"},
    {"value": "30d", "label": "Last 30 days"},
    {"value": "all", "label": "All time"},
    {"value": "custom", "label": "Custom range"},
]
PAGE_VIEW_FIXED_RANGE_DAYS = {
    "today": 1,
    "7d": 7,
    "30d": 30,
}
VIEW_TYPE_ORDER = [
    PageViewEvent.ViewType.PROBLEM_STATEMENT,
    PageViewEvent.ViewType.SOLUTION,
    PageViewEvent.ViewType.LIST,
    PageViewEvent.ViewType.CONTEST,
]
VIEW_TYPE_META = {
    PageViewEvent.ViewType.PROBLEM_STATEMENT: {
        "badge_class": "bg-primary-subtle text-primary",
        "bar_class": "bg-primary",
        "icon_class": "ti ti-file-text",
        "kpi_label": "Statement views",
        "short_label": "Statement",
    },
    PageViewEvent.ViewType.SOLUTION: {
        "badge_class": "bg-info-subtle text-info",
        "bar_class": "bg-info",
        "icon_class": "ti ti-writing",
        "kpi_label": "Solution views",
        "short_label": "Solution",
    },
    PageViewEvent.ViewType.LIST: {
        "badge_class": "bg-warning-subtle text-warning",
        "bar_class": "bg-warning",
        "icon_class": "ti ti-list-details",
        "kpi_label": "List views",
        "short_label": "List",
    },
    PageViewEvent.ViewType.CONTEST: {
        "badge_class": "bg-success-subtle text-success",
        "bar_class": "bg-success",
        "icon_class": "ti ti-trophy",
        "kpi_label": "Contest views",
        "short_label": "Contest",
    },
}


@dataclass(frozen=True)
class PageViewDateRange:
    range_key: str
    start_at: datetime | None
    end_at: datetime | None
    previous_start_at: datetime | None
    previous_end_at: datetime | None
    start_label: str
    end_label: str
    label: str


def _datetime_label(value) -> str:
    if value is None:
        return ""
    local_value = timezone.localtime(value)
    local_date = local_value.date()
    today = timezone.localdate()
    if local_date == today:
        return f"Today {local_value:%H:%M}"
    if local_date == today - timedelta(days=1):
        return f"Yesterday {local_value:%H:%M}"
    return local_value.strftime("%Y-%m-%d")


def _datetime_title(value) -> str:
    if value is None:
        return ""
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


def _parse_iso_date(value: str):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _day_start(value) -> datetime:
    return timezone.make_aware(datetime.combine(value, time.min))


def _resolve_date_range(params: QueryDict | None, *, today=None) -> PageViewDateRange:
    today = today or timezone.localdate()
    raw_range = (params.get("range") if params is not None else "") or PAGE_VIEW_DEFAULT_RANGE
    valid_range_keys = {option["value"] for option in PAGE_VIEW_RANGE_OPTIONS}
    range_key = raw_range if raw_range in valid_range_keys else PAGE_VIEW_DEFAULT_RANGE

    if range_key == "custom":
        start_date = _parse_iso_date((params.get("start") if params is not None else "") or "")
        end_date = _parse_iso_date((params.get("end") if params is not None else "") or "")
        if start_date is not None and end_date is not None:
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            start_at = _day_start(start_date)
            end_at = _day_start(end_date + timedelta(days=1))
            previous_start_at, previous_end_at = _previous_period(start_at, end_at)
            return PageViewDateRange(
                range_key="custom",
                start_at=start_at,
                end_at=end_at,
                previous_start_at=previous_start_at,
                previous_end_at=previous_end_at,
                start_label=start_date.isoformat(),
                end_label=end_date.isoformat(),
                label=f"{start_date.isoformat()} to {end_date.isoformat()}",
            )
        range_key = PAGE_VIEW_DEFAULT_RANGE

    if range_key == "all":
        return PageViewDateRange(
            range_key="all",
            start_at=None,
            end_at=None,
            previous_start_at=None,
            previous_end_at=None,
            start_label="",
            end_label="",
            label="All time",
        )

    days = PAGE_VIEW_FIXED_RANGE_DAYS.get(range_key, PAGE_VIEW_FIXED_RANGE_DAYS[PAGE_VIEW_DEFAULT_RANGE])
    start_date = today - timedelta(days=days - 1)
    end_date = today
    start_at = _day_start(start_date)
    end_at = _day_start(today + timedelta(days=1))
    previous_start_at, previous_end_at = _previous_period(start_at, end_at)
    return PageViewDateRange(
        range_key=range_key,
        start_at=start_at,
        end_at=end_at,
        previous_start_at=previous_start_at,
        previous_end_at=previous_end_at,
        start_label=start_date.isoformat(),
        end_label=end_date.isoformat(),
        label="Today" if range_key == "today" else f"Last {days} days",
    )


def _previous_period(start_at: datetime, end_at: datetime) -> tuple[datetime, datetime]:
    duration = end_at - start_at
    return start_at - duration, start_at


def _audience_flags(params: QueryDict | None) -> tuple[bool, bool]:
    include_admins = ((params.get("include_admins") if params is not None else "") or "") == "1"
    include_anonymous = ((params.get("include_anonymous") if params is not None else "1") or "1") != "0"
    return include_admins, include_anonymous


def _filtered_queryset(
    *,
    date_range: PageViewDateRange,
    include_admins: bool,
    include_anonymous: bool,
    use_previous_period: bool = False,
):
    queryset = PageViewEvent.objects.select_related("user")
    start_at = date_range.previous_start_at if use_previous_period else date_range.start_at
    end_at = date_range.previous_end_at if use_previous_period else date_range.end_at
    if start_at is not None:
        queryset = queryset.filter(created_at__gte=start_at)
    if end_at is not None:
        queryset = queryset.filter(created_at__lt=end_at)
    if not include_admins:
        queryset = queryset.filter(
            Q(user__isnull=True) | (Q(user__is_superuser=False) & ~Q(user__role=User.Role.ADMIN)),
        )
    if not include_anonymous:
        queryset = queryset.filter(user__isnull=False)
    return queryset


def _view_type_label(view_type: str) -> str:
    try:
        return str(PageViewEvent.ViewType(view_type).label)
    except ValueError:
        return view_type.replace("_", " ").title()


def _view_type_meta(view_type: str) -> dict[str, str]:
    return VIEW_TYPE_META.get(
        view_type,
        {
            "badge_class": "bg-secondary-subtle text-secondary",
            "bar_class": "bg-secondary",
            "icon_class": "ti ti-eye",
            "kpi_label": _view_type_label(view_type),
            "short_label": _view_type_label(view_type),
        },
    )


def _object_url(view_type: str, object_uuid, *, contest_name: str = "") -> str:
    if view_type == PageViewEvent.ViewType.PROBLEM_STATEMENT and object_uuid:
        return reverse("pages:problem_statement_detail", args=[object_uuid])
    if view_type == PageViewEvent.ViewType.SOLUTION and object_uuid:
        return reverse("solutions:problem_solution_list", args=[object_uuid])
    if view_type == PageViewEvent.ViewType.LIST:
        return reverse("pages:problem_statement_list")
    if view_type == PageViewEvent.ViewType.CONTEST and contest_name:
        return reverse("pages:contest_dashboard_listing") + "?" + urlencode({"contest": contest_name})
    return ""


def _path_url(path: str) -> str:
    return path if path.startswith("/") else ""


def _counts_by_type(queryset) -> dict[str, int]:
    return {
        row["view_type"]: int(row["view_total"] or 0)
        for row in queryset.values("view_type").annotate(view_total=Count("id"))
    }


def _delta_label(delta: int | None) -> str:
    if delta is None:
        return "No previous period"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta} vs previous period"


def _delta_badge_class(delta: int | None) -> str:
    if delta is None or delta == 0:
        return "bg-secondary-subtle text-secondary"
    if delta > 0:
        return "bg-success-subtle text-success"
    return "bg-danger-subtle text-danger"


def _type_rows(queryset) -> list[dict[str, object]]:
    aggregate_rows = {
        row["view_type"]: row
        for row in queryset.values("view_type").annotate(
            latest_at=Max("created_at"),
            known_user_total=Count("user", distinct=True),
            view_total=Count("id"),
        )
    }
    max_view_total = max([int(row.get("view_total") or 0) for row in aggregate_rows.values()] or [0])
    rows: list[dict[str, object]] = []
    for view_type in VIEW_TYPE_ORDER:
        row = aggregate_rows.get(view_type, {})
        latest_at = row.get("latest_at")
        view_total = int(row.get("view_total") or 0)
        meta = _view_type_meta(view_type)
        rows.append(
            {
                "badge_class": meta["badge_class"],
                "bar_width": round((view_total / max_view_total) * 100) if max_view_total else 0,
                "bar_class": meta["bar_class"],
                "icon_class": meta["icon_class"],
                "kpi_label": meta["kpi_label"],
                "latest_at": latest_at,
                "latest_at_label": _datetime_label(latest_at),
                "latest_at_title": _datetime_title(latest_at),
                "known_user_total": int(row.get("known_user_total") or 0),
                "short_label": meta["short_label"],
                "unique_user_total": int(row.get("known_user_total") or 0),
                "view_total": view_total,
                "view_type": view_type,
                "view_type_label": _view_type_label(view_type),
            },
        )
    return rows


def _kpi_rows(queryset, previous_queryset) -> list[dict[str, object]]:
    type_rows = _type_rows(queryset)
    previous_counts = _counts_by_type(previous_queryset) if previous_queryset is not None else {}
    rows = []
    for row in type_rows:
        previous_view_total = previous_counts.get(row["view_type"]) if previous_queryset is not None else None
        delta = row["view_total"] - previous_view_total if previous_view_total is not None else None
        rows.append(
            {
                **row,
                "delta": delta,
                "delta_badge_class": _delta_badge_class(delta),
                "delta_label": _delta_label(delta),
                "previous_view_total": previous_view_total,
            },
        )
    return rows


def _top_object_rows(queryset, view_type: str) -> list[dict[str, object]]:
    rows = []
    aggregate_rows = (
        queryset.filter(view_type=view_type)
        .values("object_uuid", "label", "contest_name", "contest_year")
        .annotate(
            latest_at=Max("created_at"),
            known_user_total=Count("user", distinct=True),
            view_total=Count("id"),
        )
        .order_by("-view_total", "-latest_at", "label")[:TOP_PAGE_VIEW_LIMIT]
    )
    for row in aggregate_rows:
        latest_at = row["latest_at"]
        contest_name = row["contest_name"] or ""
        rows.append(
            {
                "contest_name": contest_name,
                "contest_year": row["contest_year"],
                "display_label": row["label"] or str(row["object_uuid"] or ""),
                "label": row["label"] or str(row["object_uuid"] or ""),
                "latest_at": latest_at,
                "latest_at_label": _datetime_label(latest_at),
                "latest_at_title": _datetime_title(latest_at),
                "known_user_total": int(row["known_user_total"] or 0),
                "unique_user_total": int(row["known_user_total"] or 0),
                "url": _object_url(view_type, row["object_uuid"], contest_name=contest_name),
                "view_total": int(row["view_total"] or 0),
            },
        )
    return rows


def _query_value(query_params: dict[str, list[str]], metadata: dict, key: str) -> str:
    query_value = (query_params.get(key) or [""])[0]
    metadata_value = metadata.get(key, "")
    return str(query_value or metadata_value or "").strip()


def _chip(label: str, badge_class: str = "bg-secondary-subtle text-secondary") -> dict[str, str]:
    return {"badge_class": badge_class, "label": label}


def _list_filter_chips(path: str, metadata: dict) -> list[dict[str, str]]:
    query_params = parse_qs(urlparse(path).query)
    search_query = _query_value(query_params, metadata, "q")
    year = _query_value(query_params, metadata, "year")
    topic = _query_value(query_params, metadata, "topic")
    confidence = _query_value(query_params, metadata, "confidence")
    mohs_min = _query_value(query_params, metadata, "mohs_min")
    mohs_max = _query_value(query_params, metadata, "mohs_max")

    chips = []
    if search_query:
        chips.append(_chip(search_query, "bg-info-subtle text-info"))
    if year:
        chips.append(_chip(f"Year {year}", "bg-secondary-subtle text-secondary"))
    if topic:
        chips.append(_chip(topic, "bg-info-subtle text-info"))
    if confidence:
        chips.append(_chip(f"{confidence} confidence", "bg-secondary-subtle text-secondary"))
    if mohs_min and mohs_max:
        chips.append(_chip(f"MOHS {mohs_min}-{mohs_max}", "bg-warning-subtle text-warning"))
    elif mohs_min:
        chips.append(_chip(f"MOHS >= {mohs_min}", "bg-warning-subtle text-warning"))
    elif mohs_max:
        chips.append(_chip(f"MOHS <= {mohs_max}", "bg-warning-subtle text-warning"))
    return chips


def _list_display_label(label: str, path: str, metadata: dict) -> str:
    if metadata.get("kind") == "statement_list" or path.startswith(reverse("pages:problem_statement_list")):
        return "Problem statements"
    return label or "List"


def _top_list_rows(queryset) -> list[dict[str, object]]:
    rows = []
    aggregate_rows = (
        queryset.filter(view_type=PageViewEvent.ViewType.LIST)
        .values("object_uuid", "label", "path", "metadata")
        .annotate(
            latest_at=Max("created_at"),
            known_user_total=Count("user", distinct=True),
            view_total=Count("id"),
        )
        .order_by("-view_total", "-latest_at", "label")[:TOP_PAGE_VIEW_LIMIT]
    )
    for row in aggregate_rows:
        latest_at = row["latest_at"]
        metadata = row["metadata"] or {}
        path = str(row["path"] or "")
        label = row["label"] or "Problem statement list"
        rows.append(
            {
                "display_label": _list_display_label(label, path, metadata),
                "filter_chips": _list_filter_chips(path, metadata),
                "label": label,
                "latest_at": latest_at,
                "latest_at_label": _datetime_label(latest_at),
                "latest_at_title": _datetime_title(latest_at),
                "path": path,
                "known_user_total": int(row["known_user_total"] or 0),
                "unique_user_total": int(row["known_user_total"] or 0),
                "url": _path_url(path) or reverse("pages:problem_statement_list"),
                "view_total": int(row["view_total"] or 0),
            },
        )
    return rows


def _top_contest_rows(queryset) -> list[dict[str, object]]:
    rows = []
    aggregate_rows = (
        queryset.filter(view_type=PageViewEvent.ViewType.CONTEST)
        .values("contest_name", "contest_year")
        .annotate(
            latest_at=Max("created_at"),
            known_user_total=Count("user", distinct=True),
            view_total=Count("id"),
        )
        .order_by("-view_total", "-latest_at", "contest_name", "contest_year")[:TOP_PAGE_VIEW_LIMIT]
    )
    for row in aggregate_rows:
        latest_at = row["latest_at"]
        contest_name = row["contest_name"] or ""
        rows.append(
            {
                "contest_name": contest_name,
                "contest_year": row["contest_year"],
                "label": (
                    f"{contest_name} {row['contest_year']}"
                    if row["contest_year"]
                    else contest_name
                ),
                "latest_at": latest_at,
                "latest_at_label": _datetime_label(latest_at),
                "latest_at_title": _datetime_title(latest_at),
                "known_user_total": int(row["known_user_total"] or 0),
                "unique_user_total": int(row["known_user_total"] or 0),
                "url": _object_url(PageViewEvent.ViewType.CONTEST, None, contest_name=contest_name),
                "view_total": int(row["view_total"] or 0),
            },
        )
    return rows


def _user_label(user) -> str:
    if user is None:
        return "Anonymous"
    return user.name or user.email


def _recent_filter_queryset(queryset, *, surface: str, user_filter: str, search_query: str):
    if surface:
        queryset = queryset.filter(view_type=surface)
    if user_filter == PAGE_VIEW_ANONYMOUS_USER_FILTER:
        queryset = queryset.filter(user__isnull=True)
    elif user_filter.isdigit():
        queryset = queryset.filter(user_id=int(user_filter))
    for token in search_query.lower().split():
        queryset = queryset.filter(
            Q(label__icontains=token)
            | Q(path__icontains=token)
            | Q(user__name__icontains=token)
            | Q(user__email__icontains=token),
        )
    return queryset


def _recent_rows(queryset) -> list[dict[str, object]]:
    rows = []
    for event in queryset.select_related("user").order_by("-created_at", "-id")[:RECENT_PAGE_VIEW_LIMIT]:
        meta = _view_type_meta(event.view_type)
        event_url = _object_url(
            event.view_type,
            event.object_uuid,
            contest_name=event.contest_name,
        )
        if event.view_type == PageViewEvent.ViewType.LIST:
            event_url = _path_url(event.path) or event_url
        rows.append(
            {
                "created_at": event.created_at,
                "created_at_label": _datetime_label(event.created_at),
                "created_at_title": _datetime_title(event.created_at),
                "filter_chips": _list_filter_chips(event.path, event.metadata or {})
                if event.view_type == PageViewEvent.ViewType.LIST
                else [],
                "label": event.label,
                "path": event.path,
                "path_title": event.path,
                "surface_badge_class": meta["badge_class"],
                "url": event_url,
                "user_label": _user_label(event.user),
                "view_type": event.view_type,
                "view_type_label": event.get_view_type_display(),
                "view_type_short_label": meta["short_label"],
            },
        )
    return rows


def _user_options(queryset, *, include_anonymous: bool) -> list[dict[str, str]]:
    options = []
    if include_anonymous and queryset.filter(user__isnull=True).exists():
        options.append({"label": "Anonymous", "value": PAGE_VIEW_ANONYMOUS_USER_FILTER})
    user_rows = (
        queryset.filter(user__isnull=False)
        .values("user_id", "user__name", "user__email")
        .distinct()
        .order_by("user__name", "user__email")
    )
    for row in user_rows:
        user_name = row["user__name"] or ""
        user_email = row["user__email"] or ""
        label = user_email if not user_name or user_name == user_email else f"{user_name} ({user_email})"
        options.append({"label": label, "value": str(row["user_id"])})
    return options


def _surface_options() -> list[dict[str, str]]:
    return [
        {
            "label": _view_type_meta(view_type)["short_label"],
            "value": view_type,
        }
        for view_type in VIEW_TYPE_ORDER
    ]


def build_page_view_analytics_context(params: QueryDict | None = None) -> dict[str, object]:
    date_range = _resolve_date_range(params)
    include_admins, include_anonymous = _audience_flags(params)
    queryset = _filtered_queryset(
        date_range=date_range,
        include_admins=include_admins,
        include_anonymous=include_anonymous,
    )
    previous_queryset = None
    if date_range.previous_start_at is not None and date_range.previous_end_at is not None:
        previous_queryset = _filtered_queryset(
            date_range=date_range,
            include_admins=include_admins,
            include_anonymous=include_anonymous,
            use_previous_period=True,
        )
    requested_surface = ((params.get("surface") if params is not None else "") or "").strip()
    surface = requested_surface if requested_surface in set(VIEW_TYPE_ORDER) else ""
    user_filter = ((params.get("user") if params is not None else "") or "").strip()
    search_query = ((params.get("q") if params is not None else "") or "").strip()
    recent_queryset = _recent_filter_queryset(
        queryset,
        surface=surface,
        user_filter=user_filter,
        search_query=search_query,
    )
    aggregate = queryset.aggregate(
        anonymous_view_total=Count("id", filter=Q(user__isnull=True)),
        known_user_total=Count("user", distinct=True),
        total=Count("id"),
    )
    counts_by_type = _counts_by_type(queryset)

    return {
        "page_view_date_range": date_range,
        "page_view_filters": {
            "end": date_range.end_label,
            "include_admins": "1" if include_admins else "",
            "include_anonymous": "1" if include_anonymous else "0",
            "q": search_query,
            "range": date_range.range_key,
            "start": date_range.start_label,
            "surface": surface,
            "user": user_filter,
        },
        "page_view_kpi_rows": _kpi_rows(queryset, previous_queryset),
        "page_view_range_options": PAGE_VIEW_RANGE_OPTIONS,
        "page_view_recent_rows": _recent_rows(recent_queryset),
        "page_view_recent_unfiltered_rows": _recent_rows(queryset),
        "page_view_stats": {
            "anonymous_view_total": int(aggregate["anonymous_view_total"] or 0),
            "contest_view_total": counts_by_type.get(PageViewEvent.ViewType.CONTEST, 0),
            "known_user_total": int(aggregate["known_user_total"] or 0),
            "list_view_total": counts_by_type.get(PageViewEvent.ViewType.LIST, 0),
            "problem_statement_view_total": counts_by_type.get(
                PageViewEvent.ViewType.PROBLEM_STATEMENT,
                0,
            ),
            "solution_view_total": counts_by_type.get(PageViewEvent.ViewType.SOLUTION, 0),
            "total": int(aggregate["total"] or 0),
            "unique_user_total": int(aggregate["known_user_total"] or 0),
        },
        "page_view_surface_options": _surface_options(),
        "page_view_top_contests": _top_contest_rows(queryset),
        "page_view_top_lists": _top_list_rows(queryset),
        "page_view_top_solutions": _top_object_rows(queryset, PageViewEvent.ViewType.SOLUTION),
        "page_view_top_statements": _top_object_rows(queryset, PageViewEvent.ViewType.PROBLEM_STATEMENT),
        "page_view_type_rows": _type_rows(queryset),
        "page_view_user_options": _user_options(queryset, include_anonymous=include_anonymous),
    }
