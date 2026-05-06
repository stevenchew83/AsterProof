from __future__ import annotations

import re
import uuid
from contextlib import suppress
from dataclasses import dataclass

from django.db.models import Case
from django.db.models import Count
from django.db.models import F
from django.db.models import IntegerField
from django.db.models import Q
from django.db.models import Value
from django.db.models import When
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.asymptote_render import build_statement_render_segments
from inspinia.pages.contest_links import contest_dashboard_problem_url
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.statement_analytics import effective_mohs
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.topic_labels import FULL_TOPIC_LABEL_MAP
from inspinia.pages.topic_labels import display_topic_label
from inspinia.problemsets.models import ProblemList
from inspinia.problemsets.models import ProblemListVote

PROBLEM_LIST_PROBLEM_SEARCH_LIMIT = 50
PROBLEM_LIST_PROBLEM_SEARCH_MAX_LIMIT = 100
PROBLEM_LIST_PROBLEM_SEARCH_FACET_LIMIT = 8
_MOHS_QUERY_KEY = "mohs"
_PROBLEM_CODE_TOKEN_RE = re.compile(r"^p\d+[a-z]?$", re.IGNORECASE)
_QUERY_FIELD_ALIASES = {
    "c": "contest",
    "contest": "contest",
    _MOHS_QUERY_KEY: _MOHS_QUERY_KEY,
    "p": "problem",
    "problem": "problem",
    "tag": "tag",
    "topic": "topic",
    "y": "year",
    "year": "year",
}


@dataclass(frozen=True)
class ProblemSearchParams:
    query: str = ""
    contest: str = ""
    year: int | None = None
    problem: str = ""
    topic: str = ""
    mohs_min: int | None = None
    mohs_max: int | None = None
    tag: str = ""
    offset: int = 0
    limit: int = PROBLEM_LIST_PROBLEM_SEARCH_LIMIT
    exact_uuid: uuid.UUID | None = None


def problem_label(problem: ProblemSolveRecord) -> str:
    return problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"


def author_label(user) -> str:
    return user.name or user.email


def vote_annotations(queryset):
    return queryset.annotate(
        item_count=Count("items", distinct=True),
        upvote_count=Count("votes", filter=Q(votes__value=ProblemListVote.Value.UP), distinct=True),
        downvote_count=Count("votes", filter=Q(votes__value=ProblemListVote.Value.DOWN), distinct=True),
    ).annotate(score=F("upvote_count") - F("downvote_count"))


def public_problem_lists_queryset(search_text: str = ""):
    queryset = vote_annotations(
        ProblemList.objects.filter(visibility=ProblemList.Visibility.PUBLIC)
        .select_related("author")
        .prefetch_related("items__problem"),
    )

    search_text = (search_text or "").strip()
    if search_text:
        queryset = queryset.filter(
            Q(title__icontains=search_text)
            | Q(description__icontains=search_text)
            | Q(author__email__icontains=search_text)
            | Q(author__name__icontains=search_text)
            | Q(items__problem__contest__icontains=search_text)
            | Q(items__problem__problem__icontains=search_text)
            | Q(items__problem__contest_year_problem__icontains=search_text)
            | Q(items__problem__topic__icontains=search_text)
            | Q(items__problem__topic_tags__icontains=search_text)
            | Q(items__problem__topic_techniques__technique__icontains=search_text),
        ).distinct()

    return queryset.order_by("-score", "-published_at", "-updated_at", "-id")


def my_problem_lists_queryset(user):
    return vote_annotations(
        ProblemList.objects.filter(author=user).select_related("author").prefetch_related("items__problem"),
    ).order_by("-updated_at", "-id")


def problem_list_summary_rows(problem_lists: list[ProblemList]) -> list[dict]:
    return [
        {
            "author_label": author_label(problem_list.author),
            "description": problem_list.description,
            "detail_url": reverse("problemsets:detail", args=[problem_list.list_uuid]),
            "downvote_count": getattr(problem_list, "downvote_count", 0),
            "edit_url": reverse("problemsets:edit", args=[problem_list.list_uuid]),
            "item_count": getattr(problem_list, "item_count", problem_list.items.count()),
            "public_url": problem_list.public_url(),
            "score": getattr(problem_list, "score", 0),
            "share_token": str(problem_list.share_token),
            "title": problem_list.title,
            "upvote_count": getattr(problem_list, "upvote_count", 0),
            "visibility": problem_list.visibility,
            "visibility_label": problem_list.get_visibility_display(),
            "updated_at_label": timezone.localtime(problem_list.updated_at).strftime("%Y-%m-%d %H:%M"),
        }
        for problem_list in problem_lists
    ]


def problem_list_vote_totals(problem_list: ProblemList) -> dict[str, int]:
    rows = problem_list.votes.values("value").annotate(total=Count("id"))
    counts = {row["value"]: row["total"] for row in rows}
    upvotes = counts.get(ProblemListVote.Value.UP, 0)
    downvotes = counts.get(ProblemListVote.Value.DOWN, 0)
    return {
        "downvote_count": downvotes,
        "score": upvotes - downvotes,
        "upvote_count": upvotes,
    }


def problem_list_item_rows(problem_list: ProblemList, *, include_inactive: bool = False) -> list[dict]:
    item_queryset = problem_list.items.select_related("problem").order_by("position", "id")
    if not include_inactive:
        item_queryset = item_queryset.filter(problem__is_active=True)
    items = list(item_queryset)
    if not items:
        return []

    problems = [item.problem for item in items]
    problem_ids = [problem.id for problem in problems]
    latest_statement_by_problem_id = _latest_statement_by_problem_id(problem_ids)
    topic_tags_by_problem_id = _topic_tags_by_problem_id(problem_ids)

    rows: list[dict] = []
    for item in items:
        problem = item.problem
        statement = latest_statement_by_problem_id.get(problem.id)
        source_label = problem_label(problem)
        custom_title = item.custom_title.strip()
        topic_label = (
            display_topic_label(effective_topic(statement))
            if statement is not None
            else display_topic_label(problem.topic)
        )
        mohs = effective_mohs(statement) if statement is not None else problem.mohs
        topic_tags = topic_tags_by_problem_id.get(problem.id) or _raw_topic_tags(problem.topic_tags)
        display_label = custom_title or source_label
        if problem_list.hide_source and not custom_title:
            display_label = f"Problem {item.position}"
        rows.append(
            {
                "custom_title": custom_title,
                "display_label": display_label,
                "id": item.id,
                "is_active": problem.is_active,
                "mohs": mohs,
                "position": item.position,
                "problem": problem,
                "problem_label": source_label,
                "problem_uuid": str(problem.problem_uuid),
                "show_source_context": bool(custom_title and not problem_list.hide_source),
                "solution_editor_url": reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]),
                "statement": statement,
                "statement_render_segments": (
                    build_statement_render_segments(statement.statement_latex) if statement is not None else []
                ),
                "topic_label": topic_label,
                "topic_tags": topic_tags,
            },
        )
    return rows


def problem_list_picker_rows(problem_list: ProblemList) -> list[dict]:
    item_rows = problem_list_item_rows(problem_list, include_inactive=True)
    rows = []
    for row in item_rows:
        picker_row = _problem_picker_row(row["problem"], is_in_list=True, topic_tags=row["topic_tags"])
        picker_row["custom_title"] = row["custom_title"]
        rows.append(picker_row)
    return rows


def searchable_problem_rows(
    problem_list: ProblemList,
    search_text: str = "",
    *,
    limit: int = PROBLEM_LIST_PROBLEM_SEARCH_LIMIT,
) -> list[dict]:
    return searchable_problem_payload(
        problem_list,
        {"limit": str(limit), "q": search_text},
    )["results"]


def searchable_problem_payload(problem_list: ProblemList, raw_params) -> dict:
    params = _parse_problem_search_params(raw_params)
    existing_problem_uuids = set(problem_list.items.values_list("problem__problem_uuid", flat=True))
    filtered_queryset = _filtered_problem_search_queryset(params)
    total = filtered_queryset.count()
    problems = list(
        _ranked_problem_search_queryset(filtered_queryset, params)
        .prefetch_related("topic_techniques")[params.offset : params.offset + params.limit],
    )
    rows = [
        _problem_picker_row(
            problem,
            is_in_list=problem.problem_uuid in existing_problem_uuids,
        )
        for problem in problems
    ]
    return {
        "count": len(rows),
        "facets": _problem_search_facets(filtered_queryset),
        "has_more": params.offset + len(rows) < total,
        "limit": params.limit,
        "offset": params.offset,
        "results": rows,
        "total": total,
    }


def _parse_problem_search_params(raw_params) -> ProblemSearchParams:
    inline_filters, query = _parse_query_syntax(_param_value(raw_params, "q"))
    exact_uuid = _uuid_or_none(query)
    mohs_min, mohs_max = _parse_mohs_range(inline_filters.get("mohs", ""))

    contest = _clean_text(_param_value(raw_params, "contest")) or inline_filters.get("contest", "")
    year = _parse_int(_param_value(raw_params, "year")) or _parse_int(inline_filters.get("year", ""))
    problem = _clean_text(_param_value(raw_params, "problem")) or inline_filters.get("problem", "")
    topic = _clean_text(_param_value(raw_params, "topic")) or inline_filters.get("topic", "")
    tag = _clean_text(_param_value(raw_params, "tag")) or inline_filters.get("tag", "")
    explicit_mohs_min = _parse_int(_param_value(raw_params, "mohs_min"))
    explicit_mohs_max = _parse_int(_param_value(raw_params, "mohs_max"))

    return ProblemSearchParams(
        query=query,
        contest=contest,
        year=year,
        problem=problem.upper(),
        topic=topic,
        mohs_min=explicit_mohs_min if explicit_mohs_min is not None else mohs_min,
        mohs_max=explicit_mohs_max if explicit_mohs_max is not None else mohs_max,
        tag=tag,
        offset=_coerce_nonnegative_int(_param_value(raw_params, "offset"), default=0),
        limit=_coerce_limit(_param_value(raw_params, "limit")),
        exact_uuid=exact_uuid,
    )


def _parse_query_syntax(raw_query: str | None) -> tuple[dict[str, str], str]:
    filters: dict[str, str] = {}
    free_tokens: list[str] = []
    tokens = _clean_text(raw_query).split()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        normalized_piece = token.lower()
        if normalized_piece == _MOHS_QUERY_KEY and index + 1 < len(tokens):
            filters.setdefault(_MOHS_QUERY_KEY, tokens[index + 1])
            index += 2
            continue
        if ":" in token:
            field, value = token.split(":", 1)
            field = _QUERY_FIELD_ALIASES.get(field.strip().lower(), "")
            value = value.strip()
            if field and value:
                filters.setdefault(field, value)
                index += 1
                continue
        if re.fullmatch(r"(?:19|20)\d{2}", token) and "year" not in filters:
            filters["year"] = token
        elif _PROBLEM_CODE_TOKEN_RE.fullmatch(token) and "problem" not in filters:
            filters["problem"] = token.upper()
        else:
            free_tokens.append(token)
        index += 1
    return filters, " ".join(free_tokens).strip()


def _filtered_problem_search_queryset(params: ProblemSearchParams):
    queryset = ProblemSolveRecord.objects.filter(is_active=True)
    queryset = _apply_problem_search_text(queryset, params)
    return _apply_structured_problem_filters(queryset, params).distinct()


def _apply_problem_search_text(queryset, params: ProblemSearchParams):
    if params.exact_uuid is not None:
        return queryset.filter(problem_uuid=params.exact_uuid)
    if params.query:
        for token in _problem_search_tokens(params.query):
            queryset = queryset.filter(_problem_search_query(token))
    return queryset


def _apply_structured_problem_filters(queryset, params: ProblemSearchParams):
    if params.contest:
        queryset = queryset.filter(contest__icontains=params.contest)
    if params.year is not None:
        queryset = queryset.filter(year=params.year)
    if params.problem:
        queryset = queryset.filter(_problem_code_query(params.problem))
    if params.topic:
        topic_values = _topic_values_for_search(params.topic)
        topic_query = Q(topic__icontains=params.topic)
        if topic_values:
            topic_query |= Q(topic__in=topic_values)
        queryset = queryset.filter(topic_query)
    if params.mohs_min is not None:
        queryset = queryset.filter(mohs__gte=params.mohs_min)
    if params.mohs_max is not None:
        queryset = queryset.filter(mohs__lte=params.mohs_max)
    if params.tag:
        queryset = queryset.filter(
            Q(topic_tags__icontains=params.tag)
            | Q(topic_techniques__technique__icontains=params.tag),
        )
    return queryset


def _ranked_problem_search_queryset(queryset, params: ProblemSearchParams):
    contest_rank_value = params.contest or _first_problem_search_token(params.query)
    label_rank_query = _label_rank_query(params.query, params.tag)
    return queryset.annotate(
        _exact_uuid_rank=_rank_case(Q(problem_uuid=params.exact_uuid) if params.exact_uuid else None),
        _contest_exact_rank=_rank_case(Q(contest__iexact=contest_rank_value) if contest_rank_value else None),
        _contest_prefix_rank=_rank_case(Q(contest__istartswith=contest_rank_value) if contest_rank_value else None),
        _label_rank=_rank_case(label_rank_query),
    ).order_by(
        "_exact_uuid_rank",
        "_contest_exact_rank",
        "_contest_prefix_rank",
        "_label_rank",
        "-year",
        "contest",
        "problem",
        "id",
    )


def _problem_search_facets(queryset) -> dict[str, list[dict]]:
    return {
        "contests": _field_facets(queryset, "contest"),
        "mohs": _field_facets(
            queryset,
            "mohs",
            label_func=lambda value: f"MOHS {value}",
            order_by=("_value",),
        ),
        "tags": _tag_facets(queryset),
        "topics": _field_facets(
            queryset,
            "topic",
            label_func=display_topic_label,
            order_by=("-_count", "_value"),
        ),
        "years": _field_facets(
            queryset,
            "year",
            order_by=("-_value",),
        ),
    }


def _field_facets(queryset, field_name: str, *, label_func=None, order_by=("-_count", "_value")) -> list[dict]:
    rows = list(
        queryset.exclude(**{f"{field_name}__isnull": True})
        .values(_value=F(field_name))
        .annotate(_count=Count("id", distinct=True))
        .order_by(*order_by)[:PROBLEM_LIST_PROBLEM_SEARCH_FACET_LIMIT],
    )
    facets = []
    for row in rows:
        value = row["_value"]
        if value == "":
            continue
        label = label_func(value) if label_func is not None else str(value)
        facets.append(
            {
                "count": int(row["_count"]),
                "label": str(label),
                "value": str(value),
            },
        )
    return facets


def _tag_facets(queryset) -> list[dict]:
    rows = list(
        ProblemTopicTechnique.objects.filter(record__in=queryset)
        .values(_value=F("technique"))
        .annotate(_count=Count("record_id", distinct=True))
        .order_by("-_count", "_value")[:PROBLEM_LIST_PROBLEM_SEARCH_FACET_LIMIT],
    )
    return [
        {
            "count": int(row["_count"]),
            "label": str(row["_value"]),
            "value": str(row["_value"]),
        }
        for row in rows
        if row["_value"]
    ]


def _problem_picker_row(
    problem: ProblemSolveRecord,
    *,
    is_in_list: bool,
    topic_tags: list[str] | None = None,
) -> dict:
    label = problem_label(problem)
    return {
        "archive_url": contest_dashboard_problem_url(
            problem.contest,
            year=int(problem.year),
            problem_label=label,
            fallback=f"{problem.year}-{problem.problem}",
        ),
        "contest": problem.contest,
        "custom_title": "",
        "is_active": problem.is_active,
        "is_in_list": is_in_list,
        "mohs": problem.mohs,
        "problem_code": problem.problem,
        "problem_label": label,
        "problem_uuid": str(problem.problem_uuid),
        "topic_label": display_topic_label(problem.topic),
        "topic_tags": topic_tags if topic_tags is not None else _problem_topic_tags(problem),
        "year": problem.year,
    }


def _problem_topic_tags(problem: ProblemSolveRecord) -> list[str]:
    techniques = [row.technique for row in problem.topic_techniques.all()]
    if techniques:
        return techniques
    return _raw_topic_tags(problem.topic_tags)


def _param_value(raw_params, key: str) -> str:
    if raw_params is None:
        return ""
    getter = getattr(raw_params, "get", None)
    if getter is None:
        return ""
    value = getter(key, "")
    return "" if value is None else str(value)


def _clean_text(value: str | None) -> str:
    return str(value or "").strip()


def _parse_int(value: str | None) -> int | None:
    raw_value = _clean_text(value)
    if not raw_value:
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _parse_mohs_range(value: str | None) -> tuple[int | None, int | None]:
    raw_value = _clean_text(value)
    if not raw_value:
        return None, None
    if "-" in raw_value:
        start, end = raw_value.split("-", 1)
        return _parse_int(start), _parse_int(end)
    mohs = _parse_int(raw_value)
    return mohs, mohs


def _coerce_nonnegative_int(value: str | None, *, default: int) -> int:
    parsed_value = _parse_int(value)
    if parsed_value is None or parsed_value < 0:
        return default
    return parsed_value


def _coerce_limit(value: str | None) -> int:
    limit = _parse_int(value)
    if limit is None or limit <= 0:
        return PROBLEM_LIST_PROBLEM_SEARCH_LIMIT
    return min(limit, PROBLEM_LIST_PROBLEM_SEARCH_MAX_LIMIT)


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    with suppress(ValueError, TypeError):
        return uuid.UUID(_clean_text(value))
    return None


def _problem_search_tokens(search_text: str) -> list[str]:
    return [token for token in re.split(r"\s+", _clean_text(search_text)) if token]


def _first_problem_search_token(search_text: str) -> str:
    tokens = _problem_search_tokens(search_text)
    return tokens[0] if tokens else ""


def _problem_code_query(problem_code: str) -> Q:
    normalized_problem_code = _clean_text(problem_code).upper()
    query = Q(problem__iexact=normalized_problem_code)
    if normalized_problem_code.isdigit():
        query |= Q(problem__iexact=f"P{normalized_problem_code}")
    return query


def _topic_values_for_search(search_text: str) -> list[str]:
    normalized_search = _clean_text(search_text).lower()
    if not normalized_search:
        return []
    return [
        topic_value
        for topic_value, topic_label in FULL_TOPIC_LABEL_MAP.items()
        if normalized_search in topic_value.lower() or normalized_search in topic_label.lower()
    ]


def _label_rank_query(search_text: str, tag: str) -> Q | None:
    query = Q()
    has_query = False
    for token in _problem_search_tokens(search_text):
        query |= (
            Q(contest_year_problem__icontains=token)
            | Q(topic_tags__icontains=token)
            | Q(topic_techniques__technique__icontains=token)
        )
        has_query = True
    if tag:
        query |= Q(topic_tags__icontains=tag) | Q(topic_techniques__technique__icontains=tag)
        has_query = True
    return query if has_query else None


def _rank_case(condition: Q | None):
    if condition is None:
        return Value(1, output_field=IntegerField())
    return Case(
        When(condition, then=Value(0)),
        default=Value(1),
        output_field=IntegerField(),
    )


def _problem_search_query(search_text: str) -> Q:
    normalized_search = search_text.lower()
    query = (
        Q(contest__icontains=search_text)
        | Q(problem__icontains=search_text)
        | Q(contest_year_problem__icontains=search_text)
        | Q(topic__icontains=search_text)
        | Q(topic_tags__icontains=search_text)
        | Q(topic_techniques__technique__icontains=search_text)
    )
    if search_text.isdigit():
        numeric_value = int(search_text)
        query |= Q(year=numeric_value) | Q(mohs=numeric_value)
    for year_match in re.findall(r"\b(?:19|20)\d{2}\b", search_text):
        query |= Q(year=int(year_match))
    for mohs_match in re.findall(r"\bmohs\s*(\d+)\b", search_text, flags=re.IGNORECASE):
        query |= Q(mohs=int(mohs_match))
    topic_values = _topic_values_for_search(normalized_search)
    if topic_values:
        query |= Q(topic__in=topic_values)
    with suppress(ValueError):
        query |= Q(problem_uuid=uuid.UUID(search_text))
    return query


def _latest_statement_by_problem_id(problem_ids: list[int]) -> dict[int, ContestProblemStatement]:
    statements = list(
        ContestProblemStatement.objects.filter(is_active=True, linked_problem_id__in=problem_ids)
        .select_related("linked_problem")
        .order_by("linked_problem_id", "-updated_at", "-id"),
    )
    latest_by_problem_id: dict[int, ContestProblemStatement] = {}
    for statement in statements:
        if statement.linked_problem_id in latest_by_problem_id:
            continue
        latest_by_problem_id[statement.linked_problem_id] = statement
    return latest_by_problem_id


def _topic_tags_by_problem_id(problem_ids: list[int]) -> dict[int, list[str]]:
    rows = ProblemTopicTechnique.objects.filter(record_id__in=problem_ids).order_by("record_id", "technique")
    tags_by_problem_id: dict[int, list[str]] = {}
    for row in rows:
        tags_by_problem_id.setdefault(row.record_id, []).append(row.technique)
    return tags_by_problem_id


def _raw_topic_tags(topic_tags: str | None) -> list[str]:
    raw_value = (topic_tags or "").strip()
    if not raw_value:
        return []
    return [piece.strip() for piece in raw_value.replace(";", "\n").splitlines() if piece.strip()]
