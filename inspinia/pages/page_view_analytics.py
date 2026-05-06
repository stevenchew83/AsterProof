from __future__ import annotations

from urllib.parse import urlencode

from django.db.models import Count
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import PageViewEvent

TOP_PAGE_VIEW_LIMIT = 10
RECENT_PAGE_VIEW_LIMIT = 50
VIEW_TYPE_ORDER = [
    PageViewEvent.ViewType.PROBLEM_STATEMENT,
    PageViewEvent.ViewType.SOLUTION,
    PageViewEvent.ViewType.LIST,
    PageViewEvent.ViewType.CONTEST,
]


def _datetime_label(value) -> str:
    if value is None:
        return ""
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


def _view_type_label(view_type: str) -> str:
    try:
        return str(PageViewEvent.ViewType(view_type).label)
    except ValueError:
        return view_type.replace("_", " ").title()


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


def _type_rows(queryset) -> list[dict[str, object]]:
    aggregate_rows = {
        row["view_type"]: row
        for row in queryset.values("view_type").annotate(
            latest_at=Max("created_at"),
            unique_user_total=Count("user", distinct=True),
            view_total=Count("id"),
        )
    }
    rows: list[dict[str, object]] = []
    for view_type in VIEW_TYPE_ORDER:
        row = aggregate_rows.get(view_type, {})
        latest_at = row.get("latest_at")
        rows.append(
            {
                "latest_at": latest_at,
                "latest_at_label": _datetime_label(latest_at),
                "unique_user_total": int(row.get("unique_user_total") or 0),
                "view_total": int(row.get("view_total") or 0),
                "view_type": view_type,
                "view_type_label": _view_type_label(view_type),
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
            unique_user_total=Count("user", distinct=True),
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
                "label": row["label"] or str(row["object_uuid"] or ""),
                "latest_at": latest_at,
                "latest_at_label": _datetime_label(latest_at),
                "unique_user_total": int(row["unique_user_total"] or 0),
                "url": _object_url(view_type, row["object_uuid"], contest_name=contest_name),
                "view_total": int(row["view_total"] or 0),
            },
        )
    return rows


def _top_list_rows(queryset) -> list[dict[str, object]]:
    rows = []
    aggregate_rows = (
        queryset.filter(view_type=PageViewEvent.ViewType.LIST)
        .values("object_uuid", "label", "path")
        .annotate(
            latest_at=Max("created_at"),
            unique_user_total=Count("user", distinct=True),
            view_total=Count("id"),
        )
        .order_by("-view_total", "-latest_at", "label")[:TOP_PAGE_VIEW_LIMIT]
    )
    for row in aggregate_rows:
        latest_at = row["latest_at"]
        rows.append(
            {
                "label": row["label"] or "Problem statement list",
                "latest_at": latest_at,
                "latest_at_label": _datetime_label(latest_at),
                "path": row["path"],
                "unique_user_total": int(row["unique_user_total"] or 0),
                "url": _path_url(str(row["path"])) or reverse("pages:problem_statement_list"),
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
            unique_user_total=Count("user", distinct=True),
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
                "unique_user_total": int(row["unique_user_total"] or 0),
                "url": _object_url(PageViewEvent.ViewType.CONTEST, None, contest_name=contest_name),
                "view_total": int(row["view_total"] or 0),
            },
        )
    return rows


def _recent_rows(queryset) -> list[dict[str, object]]:
    rows = []
    for event in queryset.select_related("user").order_by("-created_at", "-id")[:RECENT_PAGE_VIEW_LIMIT]:
        user_label = ""
        if event.user_id is not None:
            user_label = event.user.name or event.user.email
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
                "label": event.label,
                "path": event.path,
                "url": event_url,
                "user_label": user_label,
                "view_type": event.view_type,
                "view_type_label": event.get_view_type_display(),
            },
        )
    return rows


def build_page_view_analytics_context() -> dict[str, object]:
    queryset = PageViewEvent.objects.all()
    aggregate = queryset.aggregate(
        total=Count("id"),
        unique_user_total=Count("user", distinct=True),
    )
    counts_by_type = {
        row["view_type"]: int(row["view_total"] or 0)
        for row in queryset.values("view_type").annotate(view_total=Count("id"))
    }

    return {
        "page_view_recent_rows": _recent_rows(queryset),
        "page_view_stats": {
            "contest_view_total": counts_by_type.get(PageViewEvent.ViewType.CONTEST, 0),
            "list_view_total": counts_by_type.get(PageViewEvent.ViewType.LIST, 0),
            "problem_statement_view_total": counts_by_type.get(
                PageViewEvent.ViewType.PROBLEM_STATEMENT,
                0,
            ),
            "solution_view_total": counts_by_type.get(PageViewEvent.ViewType.SOLUTION, 0),
            "total": int(aggregate["total"] or 0),
            "unique_user_total": int(aggregate["unique_user_total"] or 0),
        },
        "page_view_top_contests": _top_contest_rows(queryset),
        "page_view_top_lists": _top_list_rows(queryset),
        "page_view_top_solutions": _top_object_rows(queryset, PageViewEvent.ViewType.SOLUTION),
        "page_view_top_statements": _top_object_rows(queryset, PageViewEvent.ViewType.PROBLEM_STATEMENT),
        "page_view_type_rows": _type_rows(queryset),
    }
