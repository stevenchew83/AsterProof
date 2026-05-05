from __future__ import annotations

from collections import Counter
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from datetime import timedelta
from typing import TYPE_CHECKING

from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.statement_analytics import effective_mohs
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.topic_labels import display_topic_label
from inspinia.solutions.models import ProblemSolution
from inspinia.users.models import User

if TYPE_CHECKING:
    from collections.abc import Iterable

COMPLETION_PROGRESS_RANGE_OPTIONS = [
    {"value": "7d", "label": "Last 7 days"},
    {"value": "30d", "label": "Last 30 days"},
    {"value": "90d", "label": "Last 90 days"},
    {"value": "365d", "label": "Last 365 days"},
    {"value": "all", "label": "All dates"},
    {"value": "custom", "label": "Custom range"},
]
COMPLETION_PROGRESS_DEFAULT_RANGE = "30d"
COMPLETION_PROGRESS_FIXED_RANGE_DAYS = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "365d": 365,
}
MAIN_TOPIC_CODE_MAP = {
    "A": "A",
    "ALG": "A",
    "ALGEBRA": "A",
    "C": "C",
    "COMB": "C",
    "COMBINATORICS": "C",
    "G": "G",
    "GEO": "G",
    "GEOMETRY": "G",
    "N": "N",
    "NT": "N",
    "NUMBER THEORY": "N",
}
MAIN_TOPIC_CODE_ORDER = ("A", "C", "G", "N")


@dataclass(frozen=True)
class CompletionProgressDateRange:
    range_key: str
    start_date: date | None
    end_date: date | None
    start_label: str
    end_label: str
    label: str


@dataclass(frozen=True)
class CompletionProgressRow:
    completion_id: int
    completion_date: date | None
    contest: str
    mohs: int | None
    problem_code: str
    problem_id: int | None
    problem_label: str
    problem_url: str
    problem_uuid: str
    solution_status: str
    solution_status_badge_class: str
    solution_status_label: str
    statement_uuid: str
    topic: str
    updated_at_label: str
    updated_at_sort: str
    user_email: str
    user_id: int
    user_label: str
    year: int | str


@dataclass(frozen=True)
class CompletionProgressFilters:
    start_date: date | None
    end_date: date | None
    contest: str = ""
    topic: str = ""
    mohs_min: str = ""
    mohs_max: str = ""
    solution_status: str = ""
    search_query: str = ""


def default_completion_progress_user() -> User | None:
    completion = UserProblemCompletion.objects.select_related("user").order_by("-updated_at", "-id").first()
    return completion.user if completion is not None else None


def completion_progress_user_options() -> list[dict[str, str]]:
    options = []
    for user in User.objects.filter(problem_completions__isnull=False).distinct().order_by("name", "email"):
        user_label = user.name or user.email
        options.append(
            {
                "label": user_label if user_label == user.email else f"{user_label} ({user.email})",
                "value": str(user.pk),
            },
        )
    return options


def resolve_completion_progress_date_range(
    *,
    raw_range: str,
    raw_start: str,
    raw_end: str,
    today: date,
) -> CompletionProgressDateRange:
    range_key = raw_range if raw_range in {option["value"] for option in COMPLETION_PROGRESS_RANGE_OPTIONS} else ""
    if range_key == "custom":
        start_date = _parse_iso_date(raw_start)
        end_date = _parse_iso_date(raw_end)
        if start_date is not None and end_date is not None:
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            return CompletionProgressDateRange(
                range_key="custom",
                start_date=start_date,
                end_date=end_date,
                start_label=start_date.isoformat(),
                end_label=end_date.isoformat(),
                label=f"{start_date.isoformat()} to {end_date.isoformat()}",
            )
        range_key = ""

    if range_key == "all":
        return CompletionProgressDateRange(
            range_key="all",
            start_date=None,
            end_date=None,
            start_label="",
            end_label="",
            label="All dates",
        )

    days = COMPLETION_PROGRESS_FIXED_RANGE_DAYS.get(range_key or COMPLETION_PROGRESS_DEFAULT_RANGE, 30)
    start_date = today - timedelta(days=days - 1)
    return CompletionProgressDateRange(
        range_key=range_key or COMPLETION_PROGRESS_DEFAULT_RANGE,
        start_date=start_date,
        end_date=today,
        start_label=start_date.isoformat(),
        end_label=today.isoformat(),
        label=f"{start_date.isoformat()} to {today.isoformat()}",
    )


def normalize_completion_progress_rows(
    completions: Iterable[UserProblemCompletion],
) -> list[CompletionProgressRow]:
    completion_list = list(completions)
    solution_status_by_key = _solution_status_lookup(completion_list)
    rows = [_completion_progress_row(completion, solution_status_by_key) for completion in completion_list]
    return sort_completion_progress_rows(rows)


def sort_completion_progress_rows(rows: Iterable[CompletionProgressRow]) -> list[CompletionProgressRow]:
    return sorted(
        rows,
        key=lambda row: (
            row.completion_date is None,
            -(row.completion_date.toordinal() if row.completion_date is not None else 0),
            row.contest,
            str(row.year),
            row.problem_code,
            -row.completion_id,
        ),
    )


def filter_completion_progress_rows(
    rows: Iterable[CompletionProgressRow],
    filters: CompletionProgressFilters,
) -> list[CompletionProgressRow]:
    parsed_mohs_min = _parse_int(filters.mohs_min)
    parsed_mohs_max = _parse_int(filters.mohs_max)
    tokens = filters.search_query.lower().split()
    filtered_rows = []
    for row in rows:
        if not _row_in_date_range(row, start_date=filters.start_date, end_date=filters.end_date):
            continue
        if filters.contest and row.contest != filters.contest:
            continue
        if filters.topic and row.topic != filters.topic:
            continue
        if not _row_matches_mohs(row, mohs_min=parsed_mohs_min, mohs_max=parsed_mohs_max):
            continue
        if not _row_matches_solution_status(row, filters.solution_status):
            continue
        if tokens and not _row_matches_search(row, tokens):
            continue
        filtered_rows.append(row)
    return sort_completion_progress_rows(filtered_rows)


def completion_progress_filter_options(rows: Iterable[CompletionProgressRow]) -> dict[str, list]:
    row_list = list(rows)
    return {
        "contests": sorted({row.contest for row in row_list if row.contest}),
        "mohs_values": sorted({row.mohs for row in row_list if row.mohs is not None}),
        "solution_statuses": _solution_status_options(row_list),
        "topics": sorted({row.topic for row in row_list if row.topic}),
    }


def completion_progress_stats(
    rows: Iterable[CompletionProgressRow],
    *,
    today: date,
) -> dict[str, int | float | None]:
    row_list = list(rows)
    dated_rows = [row for row in row_list if row.completion_date is not None]
    mohs_values = [int(row.mohs) for row in row_list if row.mohs is not None]
    active_dates = {row.completion_date for row in dated_rows}
    return {
        "active_day_total": len(active_dates),
        "average_mohs": round(sum(mohs_values) / len(mohs_values), 1) if mohs_values else None,
        "current_streak": _current_streak(active_dates, today=today),
        "known_date_total": len(dated_rows),
        "longest_streak": _longest_streak(active_dates),
        "max_mohs": max(mohs_values, default=None),
        "missing_date_total": len(row_list) - len(dated_rows),
        "missing_mohs_total": len(row_list) - len(mohs_values),
        "no_solution_total": sum(1 for row in row_list if not row.solution_status),
        "solved_total": len(row_list),
        "total_mohs": sum(mohs_values),
    }


def completion_progress_charts_payload(
    rows: Iterable[CompletionProgressRow],
    *,
    start_date: date | None,
    end_date: date | None,
) -> dict[str, object]:
    row_list = list(rows)
    day_values = _chart_days(row_list, start_date=start_date, end_date=end_date)
    return {
        "dailyCompletions": _daily_completion_payload(row_list, day_values),
        "dailyMohs": _daily_mohs_payload(row_list, day_values),
        "dailyTopicMix": _daily_topic_mix_payload(row_list, day_values),
        "mohsDistribution": _mohs_distribution_payload(row_list),
        "solutionStatus": _solution_status_payload(row_list),
        "topicMohsHeatmap": _topic_mohs_heatmap_payload(row_list),
        "topicTotals": _topic_totals_payload(row_list),
    }


def completion_progress_table_rows(rows: Iterable[CompletionProgressRow]) -> list[dict[str, object]]:
    return [
        {
            "completion_date": row.completion_date.isoformat() if row.completion_date is not None else "Unknown",
            "completion_date_sort": (
                row.completion_date.isoformat() if row.completion_date is not None else "0000-00-00"
            ),
            "contest": row.contest,
            "mohs": row.mohs if row.mohs is not None else "",
            "problem": row.problem_code,
            "problem_label": row.problem_label,
            "problem_url": row.problem_url,
            "problem_uuid": row.problem_uuid,
            "solution_status": row.solution_status,
            "solution_status_badge_class": row.solution_status_badge_class,
            "solution_status_label": row.solution_status_label,
            "statement_uuid": row.statement_uuid,
            "topic": row.topic,
            "updated_at": row.updated_at_label,
            "updated_at_sort": row.updated_at_sort,
            "user_email": row.user_email,
            "user_label": row.user_label,
            "year": row.year,
        }
        for row in rows
    ]


def completion_progress_csv_rows(rows: Iterable[CompletionProgressRow]) -> list[dict[str, object]]:
    return [
        {
            "User": row.user_label,
            "User email": row.user_email,
            "Completion date": row.completion_date.isoformat() if row.completion_date is not None else "Unknown",
            "Contest": row.contest,
            "Year": row.year,
            "Problem": row.problem_label,
            "Problem code": row.problem_code,
            "Topic": row.topic,
            "MOHS": row.mohs if row.mohs is not None else "",
            "Solution status": row.solution_status_label,
            "Updated at": row.updated_at_label,
            "Problem UUID": row.problem_uuid,
            "Statement UUID": row.statement_uuid,
        }
        for row in rows
    ]


def _completion_progress_row(
    completion: UserProblemCompletion,
    solution_status_by_key: dict[tuple[int, int], str],
) -> CompletionProgressRow:
    statement = completion.statement
    problem = (
        statement.linked_problem
        if statement is not None and statement.linked_problem is not None
        else completion.problem
    )
    contest = statement.contest_name if statement is not None else (problem.contest if problem is not None else "")
    year = statement.contest_year if statement is not None else (problem.year if problem is not None else "")
    problem_code = (
        statement.problem_code
        if statement is not None
        else (problem.problem if problem is not None else "")
    )
    problem_label = _problem_label(completion)
    topic = _row_topic(completion)
    mohs = _row_mohs(completion)
    solution_status = solution_status_by_key.get((completion.user_id, problem.id), "") if problem is not None else ""
    problem_uuid = (
        str(problem.problem_uuid)
        if problem is not None
        else (str(statement.problem_uuid) if statement else "")
    )
    return CompletionProgressRow(
        completion_id=completion.id,
        completion_date=completion.completion_date,
        contest=contest,
        mohs=mohs,
        problem_code=problem_code,
        problem_id=problem.id if problem is not None else None,
        problem_label=problem_label,
        problem_url=(
            reverse("solutions:problem_solution_list", args=[problem.problem_uuid])
            if problem is not None
            else ""
        ),
        problem_uuid=problem_uuid,
        solution_status=solution_status,
        solution_status_badge_class=_solution_status_badge_class(solution_status),
        solution_status_label=_solution_status_label(solution_status),
        statement_uuid=str(statement.statement_uuid) if statement is not None else "",
        topic=topic,
        updated_at_label=timezone.localtime(completion.updated_at).strftime("%Y-%m-%d %H:%M"),
        updated_at_sort=completion.updated_at.isoformat(),
        user_email=completion.user.email,
        user_id=completion.user_id,
        user_label=completion.user.name or completion.user.email,
        year=year,
    )


def _solution_status_lookup(completions: list[UserProblemCompletion]) -> dict[tuple[int, int], str]:
    problem_ids = {
        _effective_problem(completion).id
        for completion in completions
        if _effective_problem(completion) is not None
    }
    user_ids = {completion.user_id for completion in completions}
    if not problem_ids or not user_ids:
        return {}
    return {
        (row["author_id"], row["problem_id"]): row["status"]
        for row in ProblemSolution.objects.filter(author_id__in=user_ids, problem_id__in=problem_ids).values(
            "author_id",
            "problem_id",
            "status",
        )
    }


def _effective_problem(completion: UserProblemCompletion):
    statement = completion.statement
    if statement is not None and statement.linked_problem is not None:
        return statement.linked_problem
    return completion.problem


def _problem_label(completion: UserProblemCompletion) -> str:
    if completion.statement is not None:
        return completion.statement.contest_year_problem
    if completion.problem is not None:
        return completion.problem.contest_year_problem or (
            f"{completion.problem.contest} {completion.problem.year} {completion.problem.problem}"
        )
    return "Unknown problem"


def _row_topic(completion: UserProblemCompletion) -> str:
    if completion.statement is not None:
        topic = effective_topic(completion.statement)
        if topic:
            return display_topic_label(topic)
    problem = _effective_problem(completion)
    return display_topic_label(problem.topic) if problem is not None else "Unlinked"


def _row_mohs(completion: UserProblemCompletion) -> int | None:
    if completion.statement is not None:
        statement_mohs = effective_mohs(completion.statement)
        if statement_mohs is not None:
            return int(statement_mohs)
    problem = _effective_problem(completion)
    return int(problem.mohs) if problem is not None else None


def _solution_status_label(status: str) -> str:
    return str(ProblemSolution.Status(status).label) if status else "No solution"


def _solution_status_badge_class(status: str) -> str:
    return {
        ProblemSolution.Status.ARCHIVED: "text-bg-secondary",
        ProblemSolution.Status.DRAFT: "text-bg-warning",
        ProblemSolution.Status.PUBLISHED: "text-bg-success",
        ProblemSolution.Status.SUBMITTED: "text-bg-info",
    }.get(status, "text-bg-light")


def _parse_iso_date(raw_value: str) -> date | None:
    try:
        return date.fromisoformat((raw_value or "").strip())
    except ValueError:
        return None


def _parse_int(raw_value: str) -> int | None:
    try:
        return int(str(raw_value).strip())
    except (TypeError, ValueError):
        return None


def _row_in_date_range(
    row: CompletionProgressRow,
    *,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    if row.completion_date is None:
        return True
    if start_date is not None and row.completion_date < start_date:
        return False
    return not (end_date is not None and row.completion_date > end_date)


def _row_matches_mohs(
    row: CompletionProgressRow,
    *,
    mohs_min: int | None,
    mohs_max: int | None,
) -> bool:
    if mohs_min is None and mohs_max is None:
        return True
    if row.mohs is None:
        return False
    if mohs_min is not None and row.mohs < mohs_min:
        return False
    return not (mohs_max is not None and row.mohs > mohs_max)


def _row_matches_solution_status(row: CompletionProgressRow, solution_status: str) -> bool:
    if solution_status == "none":
        return not row.solution_status
    if solution_status:
        return row.solution_status == solution_status
    return True


def _row_matches_search(row: CompletionProgressRow, tokens: list[str]) -> bool:
    haystack = " ".join(
        [
            row.user_label,
            row.user_email,
            row.completion_date.isoformat() if row.completion_date is not None else "Unknown",
            row.contest,
            str(row.year),
            row.problem_code,
            row.problem_label,
            row.topic,
            str(row.mohs or ""),
            row.solution_status_label,
        ],
    ).lower()
    return all(token in haystack for token in tokens)


def _solution_status_options(rows: list[CompletionProgressRow]) -> list[dict[str, str]]:
    statuses = []
    if any(not row.solution_status for row in rows):
        statuses.append({"label": "No solution", "value": "none"})
    for status, label in ProblemSolution.Status.choices:
        if any(row.solution_status == status for row in rows):
            statuses.append({"label": str(label), "value": status})
    return statuses


def _current_streak(active_dates: set[date | None], *, today: date) -> int:
    streak = 0
    current_day = today
    while current_day in active_dates:
        streak += 1
        current_day -= timedelta(days=1)
    return streak


def _longest_streak(active_dates: set[date | None]) -> int:
    longest = 0
    current = 0
    previous_day = None
    for active_date in sorted(day for day in active_dates if day is not None):
        if previous_day is not None and active_date == previous_day + timedelta(days=1):
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        previous_day = active_date
    return longest


def _chart_days(
    rows: list[CompletionProgressRow],
    *,
    start_date: date | None,
    end_date: date | None,
) -> list[date]:
    if start_date is None or end_date is None:
        dated_values = [row.completion_date for row in rows if row.completion_date is not None]
        if not dated_values:
            return []
        start_date = min(dated_values)
        end_date = max(dated_values)
    if start_date > end_date:
        return []
    return [start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)]


def _daily_completion_payload(rows: list[CompletionProgressRow], day_values: list[date]) -> dict[str, object]:
    counts = Counter(row.completion_date for row in rows if row.completion_date is not None)
    return {
        "labels": [day.isoformat() for day in day_values],
        "values": [counts.get(day, 0) for day in day_values],
    }


def _daily_mohs_payload(rows: list[CompletionProgressRow], day_values: list[date]) -> dict[str, object]:
    totals: dict[date, int] = defaultdict(int)
    counts: dict[date, int] = defaultdict(int)
    for row in rows:
        if row.completion_date is None or row.mohs is None:
            continue
        totals[row.completion_date] += row.mohs
        counts[row.completion_date] += 1
    return {
        "averageValues": [
            round(totals[day] / counts[day], 1) if counts.get(day) else 0
            for day in day_values
        ],
        "labels": [day.isoformat() for day in day_values],
        "totalValues": [totals.get(day, 0) for day in day_values],
    }


def _daily_topic_mix_payload(rows: list[CompletionProgressRow], day_values: list[date]) -> dict[str, object]:
    topic_day_counts: dict[str, Counter[date]] = defaultdict(Counter)
    for row in rows:
        if row.completion_date is None:
            continue
        topic_day_counts[row.topic][row.completion_date] += 1
    topics = sorted(topic_day_counts, key=_topic_sort_key)
    return {
        "labels": [day.isoformat() for day in day_values],
        "series": [
            {
                "data": [topic_day_counts[topic].get(day, 0) for day in day_values],
                "name": topic,
            }
            for topic in topics
        ],
    }


def _topic_totals_payload(rows: list[CompletionProgressRow]) -> dict[str, object]:
    counts = Counter(row.topic for row in rows if row.topic)
    topics = sorted(counts, key=_topic_sort_key)
    return {"labels": topics, "values": [counts[topic] for topic in topics]}


def _mohs_distribution_payload(rows: list[CompletionProgressRow]) -> dict[str, object]:
    counts = Counter(row.mohs for row in rows if row.mohs is not None)
    values = sorted(counts)
    return {"labels": [str(value) for value in values], "values": [counts[value] for value in values]}


def _solution_status_payload(rows: list[CompletionProgressRow]) -> dict[str, object]:
    counts = Counter(row.solution_status_label for row in rows)
    labels = sorted(counts, key=lambda label: (label == "No solution", label))
    return {"labels": labels, "values": [counts[label] for label in labels]}


def _topic_mohs_heatmap_payload(rows: list[CompletionProgressRow]) -> dict[str, object]:
    value_by_topic_mohs: dict[str, Counter[int]] = defaultdict(Counter)
    mohs_values = sorted({row.mohs for row in rows if row.mohs is not None})
    for row in rows:
        if row.mohs is None:
            continue
        value_by_topic_mohs[row.topic][row.mohs] += 1
    topics = sorted(value_by_topic_mohs, key=_topic_sort_key)
    max_value = max(
        (value_by_topic_mohs[topic].get(mohs, 0) for topic in topics for mohs in mohs_values),
        default=0,
    )
    return {
        "max_value": max_value,
        "mohs_values": [str(mohs) for mohs in mohs_values],
        "series": [
            {
                "data": [
                    {"x": str(mohs), "y": value_by_topic_mohs[topic].get(mohs, 0)}
                    for mohs in mohs_values
                ],
                "name": topic,
            }
            for topic in topics
        ],
    }


def _topic_sort_key(topic_label: str) -> tuple[int, str]:
    topic_code = MAIN_TOPIC_CODE_MAP.get((topic_label or "").strip().upper(), (topic_label or "?")[:1].upper())
    if topic_code in MAIN_TOPIC_CODE_ORDER:
        return (MAIN_TOPIC_CODE_ORDER.index(topic_code), topic_label)
    return (len(MAIN_TOPIC_CODE_ORDER), topic_label)
