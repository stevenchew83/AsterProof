from __future__ import annotations

import csv
from collections import defaultdict
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from django.db.models import F
from django.http import HttpResponse
from django.urls import reverse

from inspinia.pages.completion_record_fields import is_completion_status_solved
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.topic_labels import display_topic_label
from inspinia.users.models import User
from inspinia.users.roles import user_has_admin_role

if TYPE_CHECKING:
    from collections.abc import Mapping

NEXT_GAP_LIMIT = 6
GAP_PAGE_SIZE = 50
GAP_CSV_CONTENT_TYPE = "text/csv; charset=utf-8"
GAP_CSV_FIELDNAMES = [
    "Area",
    "Type",
    "Topic",
    "Completed",
    "Remaining",
    "Coverage",
    "Practice URL",
]
GAP_KIND_SUBTOPICS = "subtopics"
GAP_KIND_TECHNIQUES = "techniques"
GAP_KIND_ALL = "all"
GAP_KIND_CHOICES = {GAP_KIND_SUBTOPICS, GAP_KIND_TECHNIQUES, GAP_KIND_ALL}
GAP_DATATABLE_DEFAULT_SORT_FIELD = "completion_percent"
GAP_DATATABLE_SORT_FIELDS = {
    "completion_percent",
    "label",
    "main_topic_label",
    "remaining",
    "solved_total_label",
    "type",
}
MAIN_TOPIC_ORDER = ["Algebra", "Number Theory", "Geometry", "Combinatorics"]
OTHER_TOPIC_LABEL = "Other"
MAIN_TOPIC_SLUGS = {
    "algebra": "Algebra",
    "number-theory": "Number Theory",
    "geometry": "Geometry",
    "combinatorics": "Combinatorics",
    "other": OTHER_TOPIC_LABEL,
}
GAP_TOPIC_ALL = "all"
GAP_TOPIC_SLUGS = {
    GAP_TOPIC_ALL: "All",
    "algebra": "Algebra",
    "number-theory": "Number Theory",
    "geometry": "Geometry",
    "combinatorics": "Combinatorics",
}


def technique_progress_user_options() -> list[dict[str, str]]:
    options = []
    for user in User.objects.filter(is_active=True).order_by("name", "email", "id"):
        user_label = user.name or user.email
        options.append(
            {
                "label": user_label if user_label == user.email else f"{user_label} ({user.email})",
                "value": str(user.pk),
            },
        )
    return options


def resolve_technique_progress_user(
    *,
    request_user: User,
    raw_user_id: str,
) -> tuple[User, bool]:
    can_select_user = user_has_admin_role(request_user)
    if not can_select_user:
        return request_user, False

    selected_user = None
    if raw_user_id:
        try:
            selected_user_id = int(raw_user_id)
        except (TypeError, ValueError):
            selected_user_id = None
        if selected_user_id is not None:
            selected_user = User.objects.filter(pk=selected_user_id, is_active=True).first()
    return selected_user or request_user, True


def build_technique_progress_context(
    *,
    request_user: User,
    raw_user_id: str = "",
) -> dict[str, object]:
    payload = _build_progress_payload(request_user=request_user, raw_user_id=raw_user_id)
    return {
        **payload["base_context"],
        "technique_progress_main_topic_rows": payload["main_topic_rows"],
        "technique_progress_next_gaps": payload["next_gaps"],
        "technique_progress_stats": payload["stats"],
        "technique_progress_subtopic_rows": payload["subtopic_rows"],
        "technique_progress_technique_rows": payload["technique_rows"],
    }


def build_technique_progress_gaps_context(
    *,
    request_user: User,
    raw_user_id: str = "",
    raw_kind: str = "",
    raw_topic: str = "",
    raw_min_total: str = "",
) -> dict[str, object]:
    payload = _build_progress_payload(request_user=request_user, raw_user_id=raw_user_id)
    base_context = payload["base_context"]
    selected_user = base_context["technique_progress_selected_user"]
    can_select_user = bool(base_context["technique_progress_can_select_user"])
    gap_kind = _gap_kind(raw_kind)
    gap_topic = _gap_topic(raw_topic)
    gap_min_total = _gap_min_total(raw_min_total)
    gap_rows = _filtered_gap_rows(
        payload=payload,
        gap_kind=gap_kind,
        gap_topic=gap_topic,
        gap_min_total=gap_min_total,
    )
    return {
        **base_context,
        "technique_progress_gap_export_url": _gap_url(
            selected_user=selected_user,
            can_select_user=can_select_user,
            gap_kind=gap_kind,
            gap_topic=gap_topic,
            gap_min_total=gap_min_total,
            extra_query={"export": "csv"},
        ),
        "technique_progress_gap_kind": gap_kind,
        "technique_progress_gap_kind_options": _gap_kind_options(
            selected_user=selected_user,
            can_select_user=can_select_user,
            active_kind=gap_kind,
            active_topic=gap_topic,
            active_min_total=gap_min_total,
        ),
        "technique_progress_gap_min_total": gap_min_total,
        "technique_progress_gap_min_total_reset_url": _gap_url(
            selected_user=selected_user,
            can_select_user=can_select_user,
            gap_kind=gap_kind,
            gap_topic=gap_topic,
        ),
        "technique_progress_gap_result_summary": _gap_result_summary(
            gap_rows,
            gap_kind=gap_kind,
        ),
        "technique_progress_gap_rows": gap_rows,
        "technique_progress_gap_show_type_column": gap_kind == GAP_KIND_ALL,
        "technique_progress_gap_title": _gap_title(gap_kind),
        "technique_progress_gap_topic": gap_topic,
        "technique_progress_gap_topic_tabs": _gap_topic_tabs(
            selected_user=selected_user,
            can_select_user=can_select_user,
            active_kind=gap_kind,
            active_topic=gap_topic,
            active_min_total=gap_min_total,
        ),
        "technique_progress_stats": payload["stats"],
    }


def build_technique_progress_gaps_csv_response(
    *,
    request_user: User,
    raw_user_id: str = "",
    raw_kind: str = "",
    raw_topic: str = "",
    raw_min_total: str = "",
) -> HttpResponse:
    payload = _build_progress_payload(request_user=request_user, raw_user_id=raw_user_id)
    gap_min_total = _gap_min_total(raw_min_total)
    gap_rows = _filtered_gap_rows(
        payload=payload,
        gap_kind=_gap_kind(raw_kind),
        gap_topic=_gap_topic(raw_topic),
        gap_min_total=gap_min_total,
    )
    response = HttpResponse(content_type=GAP_CSV_CONTENT_TYPE)
    response["Content-Disposition"] = 'attachment; filename="technique-progress-gaps.csv"'
    writer = csv.DictWriter(response, fieldnames=GAP_CSV_FIELDNAMES)
    writer.writeheader()
    writer.writerows(_gap_csv_row(row) for row in gap_rows)
    return response


def build_technique_progress_gaps_datatable_payload(  # noqa: PLR0913
    *,
    request_user: User,
    raw_user_id: str = "",
    raw_kind: str = "",
    raw_topic: str = "",
    raw_min_total: str = "",
    params: Mapping[str, str] | None = None,
) -> dict[str, object]:
    params = params or {}
    payload = _build_progress_payload(request_user=request_user, raw_user_id=raw_user_id)
    gap_kind = _gap_kind(raw_kind)
    gap_topic = _gap_topic(raw_topic)
    gap_min_total = _gap_min_total(raw_min_total)
    gap_rows = _filtered_gap_rows(
        payload=payload,
        gap_kind=gap_kind,
        gap_topic=gap_topic,
        gap_min_total=gap_min_total,
    )

    draw = _datatable_int(params.get("draw"), default=0)
    start = _datatable_int(params.get("start"), default=0)
    requested_length = _datatable_int(params.get("length"), default=GAP_PAGE_SIZE)
    page_length = min(max(requested_length, 1), GAP_PAGE_SIZE)

    records_total = len(gap_rows)
    searched_rows = _search_gap_rows(gap_rows, raw_search=params.get("search[value]", ""))
    sorted_rows = _sort_gap_rows_for_datatable(
        searched_rows,
        params=params,
        gap_kind=gap_kind,
    )
    page_rows = sorted_rows[start : start + page_length]

    return {
        "draw": draw,
        "recordsTotal": records_total,
        "recordsFiltered": len(searched_rows),
        "data": [_gap_datatable_row(row) for row in page_rows],
    }


def build_technique_progress_topic_context(
    *,
    request_user: User,
    raw_user_id: str = "",
    topic_slug: str,
) -> dict[str, object]:
    topic_label = MAIN_TOPIC_SLUGS.get(topic_slug)
    if topic_label is None:
        raise ValueError(topic_slug)

    selected_user, can_select_user = resolve_technique_progress_user(
        request_user=request_user,
        raw_user_id=raw_user_id,
    )
    tagged_rows = _tagged_statement_rows(user=selected_user)
    topic_tagged_rows = [
        row
        for row in tagged_rows
        if _main_topic_label(row) == topic_label
    ]
    topic_subtopic_rows = _aggregate_progress_rows(
        topic_tagged_rows,
        label_key="subtopic",
        type_label="Subtopic",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    summary = _summary_from_tagged_rows(topic_tagged_rows)
    summary["incomplete_subtopic_total"] = sum(1 for row in topic_subtopic_rows if row["remaining"])
    summary["subtopic_total"] = len(topic_subtopic_rows)
    return {
        **_base_context(
            selected_user=selected_user,
            can_select_user=can_select_user,
        ),
        "technique_progress_dashboard_url": _page_url(
            "pages:technique_dashboard",
            selected_user=selected_user,
            can_select_user=can_select_user,
        ),
        "technique_progress_topic_label": topic_label,
        "technique_progress_topic_slug": topic_slug,
        "technique_progress_topic_subtopic_rows": topic_subtopic_rows,
        "technique_progress_topic_summary": summary,
    }


def _build_progress_payload(
    *,
    request_user: User,
    raw_user_id: str,
) -> dict[str, object]:
    selected_user, can_select_user = resolve_technique_progress_user(
        request_user=request_user,
        raw_user_id=raw_user_id,
    )
    tagged_rows = _tagged_statement_rows(user=selected_user)
    technique_rows = _aggregate_progress_rows(
        tagged_rows,
        label_key="technique",
        type_label="Technique",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    subtopic_rows = _aggregate_progress_rows(
        tagged_rows,
        label_key="subtopic",
        type_label="Subtopic",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    summary = _summary_from_tagged_rows(tagged_rows)
    stats = {
        "completion_percent": summary["completion_percent"],
        "completed_statement_total": summary["solved"],
        "incomplete_subtopic_total": sum(1 for row in subtopic_rows if row["remaining"]),
        "incomplete_technique_total": sum(1 for row in technique_rows if row["remaining"]),
        "subtopic_total": len(subtopic_rows),
        "tagged_statement_total": summary["total"],
        "technique_total": len(technique_rows),
    }
    gap_rows = _gap_rows(subtopic_rows=subtopic_rows, technique_rows=technique_rows)
    next_gaps = _next_gap_rows(subtopic_rows=subtopic_rows, technique_rows=technique_rows)
    return {
        "base_context": _base_context(
            selected_user=selected_user,
            can_select_user=can_select_user,
            has_completed=bool(summary["solved"]),
            has_tagged_statements=bool(summary["total"]),
        ),
        "gap_rows": gap_rows,
        "main_topic_rows": _main_topic_rows(
            tagged_rows,
            selected_user=selected_user,
            can_select_user=can_select_user,
        ),
        "next_gaps": next_gaps,
        "stats": stats,
        "subtopic_rows": subtopic_rows,
        "technique_rows": technique_rows,
    }


def _base_context(
    *,
    selected_user: User,
    can_select_user: bool,
    has_completed: bool = False,
    has_tagged_statements: bool = False,
) -> dict[str, object]:
    return {
        "technique_progress_all_gaps_url": _page_url(
            "pages:technique_progress_gaps",
            selected_user=selected_user,
            can_select_user=can_select_user,
        ),
        "technique_progress_can_select_user": can_select_user,
        "technique_progress_dashboard_url": _page_url(
            "pages:technique_dashboard",
            selected_user=selected_user,
            can_select_user=can_select_user,
        ),
        "technique_progress_filters": {
            "user": str(selected_user.pk) if can_select_user else "",
        },
        "technique_progress_has_completed": has_completed,
        "technique_progress_has_tagged_statements": has_tagged_statements,
        "technique_progress_quick_update_url": reverse("pages:completion_quick_update"),
        "technique_progress_selected_user": selected_user,
        "technique_progress_user_options": technique_progress_user_options() if can_select_user else [],
    }


def _gap_rows(
    *,
    subtopic_rows: list[dict[str, object]],
    technique_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    return sorted(
        [
            *[dict(row, type="Subtopic") for row in subtopic_rows if row["remaining"]],
            *[dict(row, type="Technique") for row in technique_rows if row["remaining"]],
        ],
        key=lambda row: (-int(row["remaining"]), str(row["label"]).casefold(), str(row["type"]).casefold()),
    )


def _next_gap_rows(
    *,
    subtopic_rows: list[dict[str, object]],
    technique_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    return sorted(
        [
            *[dict(row, type="Subtopic") for row in subtopic_rows if row["remaining"]],
            *[dict(row, type="Technique") for row in technique_rows if row["remaining"]],
        ],
        key=lambda row: (
            -int(row["remaining"]),
            0 if row["type"] == "Subtopic" else 1,
            str(row["label"]).casefold(),
        ),
    )[:NEXT_GAP_LIMIT]


def _gap_kind(raw_kind: str) -> str:
    normalized_kind = (raw_kind or "").strip().casefold()
    return normalized_kind if normalized_kind in GAP_KIND_CHOICES else GAP_KIND_SUBTOPICS


def _gap_topic(raw_topic: str) -> str:
    normalized_topic = (raw_topic or "").strip().casefold()
    return normalized_topic if normalized_topic in GAP_TOPIC_SLUGS else GAP_TOPIC_ALL


def _gap_min_total(raw_min_total: str) -> int:
    return _datatable_int(raw_min_total, default=0)


def _rows_for_gap_kind(
    *,
    gap_kind: str,
    subtopic_rows: list[dict[str, object]],
    technique_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    visible_subtopic_rows = [dict(row, type="Subtopic") for row in subtopic_rows if row["remaining"]]
    visible_technique_rows = [dict(row, type="Technique") for row in technique_rows if row["remaining"]]
    if gap_kind == GAP_KIND_TECHNIQUES:
        return visible_technique_rows
    if gap_kind == GAP_KIND_ALL:
        subtopic_labels = {str(row["label"]).casefold() for row in visible_subtopic_rows}
        non_duplicate_technique_rows = [
            row
            for row in visible_technique_rows
            if str(row["label"]).casefold() not in subtopic_labels
        ]
        return [*visible_subtopic_rows, *non_duplicate_technique_rows]
    return visible_subtopic_rows


def _filter_gap_rows_by_topic(
    rows: list[dict[str, object]],
    *,
    gap_topic: str,
) -> list[dict[str, object]]:
    if gap_topic == GAP_TOPIC_ALL:
        return rows
    topic_label = GAP_TOPIC_SLUGS[gap_topic]
    return [
        row
        for row in rows
        if topic_label in row.get("main_topic_labels", [])
    ]


def _filtered_gap_rows(
    *,
    payload: dict[str, object],
    gap_kind: str,
    gap_topic: str,
    gap_min_total: int,
) -> list[dict[str, object]]:
    gap_rows = _rows_for_gap_kind(
        gap_kind=gap_kind,
        subtopic_rows=payload["subtopic_rows"],
        technique_rows=payload["technique_rows"],
    )
    gap_rows = _filter_gap_rows_by_topic(gap_rows, gap_topic=gap_topic)
    return _filter_gap_rows_by_min_total(gap_rows, gap_min_total=gap_min_total)


def _filter_gap_rows_by_min_total(
    rows: list[dict[str, object]],
    *,
    gap_min_total: int,
) -> list[dict[str, object]]:
    if gap_min_total <= 0:
        return rows
    return [
        row
        for row in rows
        if int(row.get("total", 0)) >= gap_min_total
    ]


def _gap_kind_options(
    *,
    selected_user: User,
    can_select_user: bool,
    active_kind: str,
    active_topic: str,
    active_min_total: int,
) -> list[dict[str, object]]:
    options = [
        {"label": "Subtopics", "value": GAP_KIND_SUBTOPICS},
        {"label": "Technique gaps", "value": GAP_KIND_TECHNIQUES},
        {"label": "All", "value": GAP_KIND_ALL},
    ]
    return [
        {
            **option,
            "is_active": option["value"] == active_kind,
            "url": _gap_url(
                selected_user=selected_user,
                can_select_user=can_select_user,
                gap_kind=str(option["value"]),
                gap_topic=active_topic,
                gap_min_total=active_min_total,
            ),
        }
        for option in options
    ]


def _gap_topic_tabs(
    *,
    selected_user: User,
    can_select_user: bool,
    active_kind: str,
    active_topic: str,
    active_min_total: int,
) -> list[dict[str, object]]:
    return [
        {
            "is_active": topic_slug == active_topic,
            "label": topic_label,
            "url": _gap_url(
                selected_user=selected_user,
                can_select_user=can_select_user,
                gap_kind=active_kind,
                gap_topic=topic_slug,
                gap_min_total=active_min_total,
            ),
            "value": topic_slug,
        }
        for topic_slug, topic_label in GAP_TOPIC_SLUGS.items()
    ]


def _gap_url(  # noqa: PLR0913
    *,
    selected_user: User,
    can_select_user: bool,
    gap_kind: str,
    gap_topic: str,
    gap_min_total: int = 0,
    extra_query: dict[str, str] | None = None,
) -> str:
    query: dict[str, str] = {}
    if can_select_user:
        query["user"] = str(selected_user.pk)
    query["kind"] = gap_kind
    query["topic"] = gap_topic
    if gap_min_total > 0:
        query["min_total"] = str(gap_min_total)
    if extra_query:
        query.update(extra_query)
    return f"{reverse('pages:technique_progress_gaps')}?{urlencode(query)}"


def _gap_pagination_suffix(
    *,
    selected_user: User,
    can_select_user: bool,
    gap_kind: str,
    gap_topic: str,
    gap_min_total: int = 0,
) -> str:
    query: dict[str, str] = {}
    if can_select_user:
        query["user"] = str(selected_user.pk)
    query["kind"] = gap_kind
    query["topic"] = gap_topic
    if gap_min_total > 0:
        query["min_total"] = str(gap_min_total)
    query_string = urlencode(query)
    return f"&{query_string}" if query_string else ""


def _gap_result_summary(rows: list[dict[str, object]], *, gap_kind: str) -> str:
    row_total = len(rows)
    noun = {
        GAP_KIND_SUBTOPICS: "subtopic gaps",
        GAP_KIND_TECHNIQUES: "technique gaps",
        GAP_KIND_ALL: "practice gaps",
    }[gap_kind]
    if not row_total:
        return f"Showing 0 of 0 {noun}"
    return f"Showing {row_total} {noun}"


def _gap_title(gap_kind: str) -> str:
    return {
        GAP_KIND_SUBTOPICS: "Subtopic practice gaps",
        GAP_KIND_TECHNIQUES: "Technique practice gaps",
        GAP_KIND_ALL: "All practice gaps",
    }[gap_kind]


def _datatable_int(raw_value: str | None, *, default: int = 0) -> int:
    try:
        value = int(raw_value or "")
    except (TypeError, ValueError):
        return default
    return max(value, 0)


def _search_gap_rows(
    rows: list[dict[str, object]],
    *,
    raw_search: str | None,
) -> list[dict[str, object]]:
    search_term = str(raw_search or "").strip().casefold()
    if not search_term:
        return rows
    return [
        row
        for row in rows
        if search_term in _gap_search_haystack(row)
    ]


def _gap_search_haystack(row: dict[str, object]) -> str:
    values = [
        row.get("label", ""),
        row.get("type", ""),
        row.get("main_topic_label", ""),
        row.get("solved", ""),
        row.get("total", ""),
        row.get("remaining", ""),
        row.get("completion_percent", ""),
        f"{row.get('solved', '')} of {row.get('total', '')}",
    ]
    return " ".join(str(value) for value in values).casefold()


def _sort_gap_rows_for_datatable(
    rows: list[dict[str, object]],
    *,
    params: Mapping[str, str],
    gap_kind: str,
) -> list[dict[str, object]]:
    sort_field = _gap_datatable_sort_field(params, gap_kind=gap_kind)
    sort_direction = str(params.get("order[0][dir]") or "desc").casefold()
    sort_descending = sort_direction != "asc"
    sorted_rows = sorted(rows, key=lambda row: str(row.get("label", "")).casefold())
    return sorted(
        sorted_rows,
        key=lambda row: _gap_datatable_sort_value(row, sort_field),
        reverse=sort_descending,
    )


def _gap_datatable_sort_field(params: Mapping[str, str], *, gap_kind: str) -> str:
    default_column_index = 5 if gap_kind == GAP_KIND_ALL else 4
    column_index = _datatable_int(
        params.get("order[0][column]"),
        default=default_column_index,
    )
    requested_field = str(
        params.get(f"columns[{column_index}][data]")
        or params.get(f"columns[{column_index}][name]")
        or "",
    )
    if requested_field in GAP_DATATABLE_SORT_FIELDS:
        return requested_field
    return GAP_DATATABLE_DEFAULT_SORT_FIELD


def _gap_datatable_sort_value(row: dict[str, object], sort_field: str) -> object:
    if sort_field == "solved_total_label":
        return int(row.get("solved", 0))
    if sort_field in {"completion_percent", "remaining"}:
        return int(row.get(sort_field, 0))
    return str(row.get(sort_field, "")).casefold()


def _gap_datatable_row(row: dict[str, object]) -> dict[str, object]:
    solved = int(row["solved"])
    total = int(row["total"])
    return {
        "completion_percent": int(row["completion_percent"]),
        "coverage_label": f"{row['completion_percent']}%",
        "label": row["label"],
        "main_topic_label": row["main_topic_label"] or "-",
        "practice_url": row["practice_url"],
        "remaining": int(row["remaining"]),
        "solved": solved,
        "solved_total_label": f"{solved} of {total}",
        "total": total,
        "type": row["type"],
    }


def _gap_csv_row(row: dict[str, object]) -> dict[str, object]:
    solved = int(row["solved"])
    total = int(row["total"])
    return {
        "Area": row["label"],
        "Type": row["type"],
        "Topic": row["main_topic_label"] or "-",
        "Completed": f"{solved} of {total}",
        "Remaining": int(row["remaining"]),
        "Coverage": f"{row['completion_percent']}%",
        "Practice URL": row["practice_url"],
    }


def _tagged_statement_rows(*, user: User) -> list[dict[str, object]]:
    statements = list(
        ContestProblemStatement.objects.filter(is_active=True)
        .select_related("linked_problem")
        .order_by("-contest_year", "contest_name", "problem_number", "problem_code", "id"),
    )
    if not statements:
        return []

    statement_ids = [statement.id for statement in statements]
    linked_problem_ids = sorted(
        {
            statement.linked_problem_id
            for statement in statements
            if statement.linked_problem_id is not None
        },
    )
    statement_tags = _statement_tags_by_statement_id(statement_ids)
    linked_tags = _problem_tags_by_record_id(linked_problem_ids)
    completion_by_statement_id = _completion_by_statement_id(
        statements=statements,
        user=user,
    )

    rows = []
    seen_statement_labels: set[tuple[int, str]] = set()
    for statement in statements:
        tags = statement_tags.get(statement.id) or linked_tags.get(statement.linked_problem_id, [])
        if not tags:
            continue
        completion = completion_by_statement_id.get(statement.id)
        is_solved = completion is not None and is_completion_status_solved(completion.status)
        fallback_topic = display_topic_label(effective_topic(statement)) if effective_topic(statement) else ""
        for tag in tags:
            technique = str(tag["technique"] or "").strip()
            if not technique:
                continue
            dedupe_key = (statement.id, technique.casefold())
            if dedupe_key in seen_statement_labels:
                continue
            seen_statement_labels.add(dedupe_key)
            main_topic = str(tag.get("main_topic") or "").strip()
            rows.append(
                {
                    "is_solved": is_solved,
                    "main_topic": display_topic_label(main_topic) if main_topic else fallback_topic,
                    "statement_id": statement.id,
                    "subtopic": str(tag.get("canonical_subtopic") or "").strip() or technique,
                    "technique": technique,
                },
            )
    return rows


def _statement_tags_by_statement_id(statement_ids: list[int]) -> dict[int, list[dict[str, object]]]:
    tags_by_statement_id: dict[int, list[dict[str, object]]] = defaultdict(list)
    seen: set[tuple[int, str]] = set()
    for tag_row in (
        StatementTopicTechnique.objects.filter(statement_id__in=statement_ids)
        .values("statement_id", "technique", "main_topic", "canonical_subtopic")
        .order_by("technique", "statement_id", "id")
    ):
        statement_id = int(tag_row["statement_id"])
        technique = str(tag_row["technique"] or "")
        dedupe_key = (statement_id, technique.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        tags_by_statement_id[statement_id].append(tag_row)
    return tags_by_statement_id


def _problem_tags_by_record_id(record_ids: list[int]) -> dict[int, list[dict[str, object]]]:
    tags_by_record_id: dict[int, list[dict[str, object]]] = defaultdict(list)
    seen: set[tuple[int, str]] = set()
    if not record_ids:
        return tags_by_record_id
    for tag_row in (
        ProblemTopicTechnique.objects.filter(record_id__in=record_ids)
        .values("record_id", "technique", "main_topic", "canonical_subtopic")
        .order_by("technique", "record_id", "id")
    ):
        record_id = int(tag_row["record_id"])
        technique = str(tag_row["technique"] or "")
        dedupe_key = (record_id, technique.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        tags_by_record_id[record_id].append(tag_row)
    return tags_by_record_id


def _completion_by_statement_id(
    *,
    statements: list[ContestProblemStatement],
    user: User,
) -> dict[int, UserProblemCompletion]:
    statement_ids = [statement.id for statement in statements]
    linked_problem_ids = sorted(
        {
            statement.linked_problem_id
            for statement in statements
            if statement.linked_problem_id is not None
        },
    )
    completion_by_statement_id = {
        completion.statement_id: completion
        for completion in UserProblemCompletion.objects.filter(
            user=user,
            statement_id__in=statement_ids,
        ).order_by(F("completion_date").desc(nulls_last=True), "-updated_at", "-id")
        if completion.statement_id is not None
    }
    if not linked_problem_ids:
        return completion_by_statement_id

    legacy_completion_by_problem_id = {
        completion.problem_id: completion
        for completion in UserProblemCompletion.objects.filter(
            user=user,
            problem_id__in=linked_problem_ids,
        ).order_by(F("completion_date").desc(nulls_last=True), "-updated_at", "-id")
        if completion.problem_id is not None
    }
    for statement in statements:
        if statement.id in completion_by_statement_id:
            continue
        if statement.linked_problem_id in legacy_completion_by_problem_id:
            completion_by_statement_id[statement.id] = legacy_completion_by_problem_id[statement.linked_problem_id]
    return completion_by_statement_id


def _aggregate_progress_rows(
    tagged_rows: list[dict[str, object]],
    *,
    label_key: str,
    type_label: str,
    selected_user: User,
    can_select_user: bool,
) -> list[dict[str, object]]:
    buckets: dict[str, dict[str, object]] = {}
    for tagged_row in tagged_rows:
        label = str(tagged_row[label_key] or "").strip()
        if not label:
            continue
        bucket = buckets.setdefault(
            label,
            {
                "label": label,
                "main_topics": set(),
                "solved_statement_ids": set(),
                "statement_ids": set(),
                "type": type_label,
            },
        )
        bucket["statement_ids"].add(tagged_row["statement_id"])
        if tagged_row["is_solved"]:
            bucket["solved_statement_ids"].add(tagged_row["statement_id"])
        main_topic = str(tagged_row.get("main_topic") or "").strip()
        if main_topic:
            bucket["main_topics"].add(main_topic)

    rows = []
    for bucket in buckets.values():
        statement_ids = bucket["statement_ids"]
        solved_statement_ids = bucket["solved_statement_ids"]
        total = len(statement_ids)
        solved = len(solved_statement_ids)
        remaining = total - solved
        label = str(bucket["label"])
        main_topics = sorted(bucket["main_topics"])
        rows.append(
            {
                "completion_percent": _percent(solved, total),
                "label": label,
                "main_topic_labels": main_topics,
                "main_topic_label": ", ".join(main_topics),
                "practice_url": _practice_url(
                    label,
                    selected_user=selected_user,
                    can_select_user=can_select_user,
                ),
                "remaining": remaining,
                "solved": solved,
                "total": total,
                "type": bucket["type"],
            },
        )
    return sorted(
        rows,
        key=lambda row: (
            int(row["remaining"]) == 0,
            -int(row["remaining"]),
            str(row["label"]).casefold(),
        ),
    )


def _main_topic_rows(
    tagged_rows: list[dict[str, object]],
    *,
    selected_user: User,
    can_select_user: bool,
) -> list[dict[str, object]]:
    topics_with_data = {_main_topic_label(row) for row in tagged_rows}
    topic_labels = [
        *MAIN_TOPIC_ORDER,
        *sorted(topics_with_data - set(MAIN_TOPIC_ORDER) - {OTHER_TOPIC_LABEL}),
    ]
    if OTHER_TOPIC_LABEL in topics_with_data:
        topic_labels.append(OTHER_TOPIC_LABEL)

    rows = []
    for topic_label in topic_labels:
        topic_rows = [
            row
            for row in tagged_rows
            if _main_topic_label(row) == topic_label
        ]
        summary = _summary_from_tagged_rows(topic_rows)
        subtopic_rows = _aggregate_progress_rows(
            topic_rows,
            label_key="subtopic",
            type_label="Subtopic",
            selected_user=selected_user,
            can_select_user=can_select_user,
        )
        rows.append(
            {
                "completion_percent": summary["completion_percent"],
                "incomplete_subtopic_total": sum(1 for row in subtopic_rows if row["remaining"]),
                "label": topic_label,
                "remaining": summary["remaining"],
                "slug": _topic_slug(topic_label),
                "solved": summary["solved"],
                "subtopic_total": len(subtopic_rows),
                "topic_detail_url": _page_url(
                    "pages:technique_progress_topic_detail",
                    selected_user=selected_user,
                    can_select_user=can_select_user,
                    kwargs={"topic_slug": _topic_slug(topic_label)},
                ),
                "total": summary["total"],
            },
        )
    return rows


def _summary_from_tagged_rows(tagged_rows: list[dict[str, object]]) -> dict[str, int]:
    statement_ids = {row["statement_id"] for row in tagged_rows}
    solved_statement_ids = {
        row["statement_id"]
        for row in tagged_rows
        if row["is_solved"]
    }
    total = len(statement_ids)
    solved = len(solved_statement_ids)
    remaining = total - solved
    return {
        "completion_percent": _percent(solved, total),
        "remaining": remaining,
        "solved": solved,
        "total": total,
    }


def _main_topic_label(row: dict[str, object]) -> str:
    label = str(row.get("main_topic") or "").strip()
    return label if label in MAIN_TOPIC_ORDER else OTHER_TOPIC_LABEL


def _topic_slug(label: str) -> str:
    return label.casefold().replace(" ", "-")


def _page_url(
    route_name: str,
    *,
    selected_user: User,
    can_select_user: bool,
    kwargs: dict[str, str] | None = None,
) -> str:
    base_url = reverse(route_name, kwargs=kwargs)
    if not can_select_user:
        return base_url
    return f"{base_url}?{urlencode({'user': str(selected_user.pk)})}"


def _practice_url(label: str, *, selected_user: User, can_select_user: bool) -> str:
    query: dict[str, str] = {}
    if can_select_user:
        query["target_user_id"] = str(selected_user.pk)
    query["subtopics"] = label
    return f"{reverse('pages:completion_quick_update')}?{urlencode(query)}"


def _percent(numerator: int, denominator: int) -> int:
    if not denominator:
        return 0
    return round((numerator / denominator) * 100)
