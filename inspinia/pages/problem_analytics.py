"""Problem analytics dashboard context builders."""

from __future__ import annotations

import re
from collections import Counter
from collections import defaultdict
from typing import Any

from django.utils import timezone

from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.topic_labels import display_topic_label

CHART_LIMIT = 18
CONTEST_CHART_LIMIT = 12
DUPLICATE_GROUP_MIN_NAMES = 2
PLURAL_SUFFIX_MIN_LENGTH = 5

MOHS_COLOR_STOPS = (
    (15, "#198754"),
    (25, "#20c997"),
    (35, "#ffc107"),
    (45, "#fd7e14"),
    (10**9, "#dc3545"),
)

TOPIC_COLORS = {
    "Algebra": "#0d6efd",
    "Geometry": "#198754",
    "Number Theory": "#fd7e14",
    "Combinatorics": "#6f42c1",
}

CONFUSABLE_TRANSLATION = str.maketrans(
    {
        chr(0x0410): "A",
        chr(0x0430): "a",
        chr(0x0412): "B",
        chr(0x0415): "E",
        chr(0x0435): "e",
        chr(0x041A): "K",
        chr(0x041C): "M",
        chr(0x041D): "H",
        chr(0x041E): "O",
        chr(0x043E): "o",
        chr(0x0420): "P",
        chr(0x0440): "p",
        chr(0x0421): "C",
        chr(0x0441): "c",
        chr(0x0422): "T",
        chr(0x0425): "X",
        chr(0x0445): "x",
        chr(0x0443): "y",
    },
)


def build_problem_analytics_context(query_params, base_queryset) -> dict[str, object]:
    """Build filtered problem analytics payloads for the admin dashboard."""
    all_rows = _dashboard_statement_rows(base_queryset)
    filters = _filters_from_query(query_params)
    filtered_rows = _filter_rows(all_rows, filters)
    pivot_payload = _contest_year_mohs_pivot_payload(filtered_rows, hide_empty=filters["hide_empty"])
    summary = _summary_payload(all_rows, filtered_rows, pivot_payload)
    quality = _quality_payload(all_rows, filtered_rows, pivot_payload)
    charts_payload = {
        "byYear": _year_payload(filtered_rows),
        "byTopic": _topic_payload(filtered_rows),
        "byContest": _contest_payload(filtered_rows),
        "byMohs": _mohs_payload(filtered_rows),
        "topTechniques": _technique_payload(filtered_rows),
        "contestYearMohsPivotTable": pivot_payload,
    }

    return {
        "analytics_total": summary["active_statements"],
        "analytics_stats": {
            "year_min": summary["year_min"],
            "year_max": summary["year_max"],
            "contest_n": summary["distinct_contests"],
            "topic_n": summary["distinct_topics"],
        },
        "analytics_technique_total": summary["technique_rows"],
        "analytics_filters": filters,
        "analytics_filter_options": _filter_options(all_rows),
        "analytics_summary": summary,
        "analytics_quality": quality,
        "charts_payload": charts_payload,
    }


def _filters_from_query(query_params) -> dict[str, object]:
    return {
        "q": (query_params.get("q") or "").strip(),
        "contest": (query_params.get("contest") or "").strip(),
        "year": (query_params.get("year") or "").strip(),
        "mohs": (query_params.get("mohs") or "").strip(),
        "topic": (query_params.get("topic") or "").strip(),
        "hide_empty": (query_params.get("hide_empty", "1") or "1") != "0",
    }


def _dashboard_statement_rows(base_queryset) -> list[dict[str, Any]]:
    statement_rows = list(
        base_queryset.values(
            "id",
            "contest_name",
            "contest_year",
            "contest_year_problem",
            "problem_code",
            "problem_uuid",
            "topic",
            "mohs",
            "updated_at",
            "linked_problem_id",
            "linked_problem__topic",
            "linked_problem__mohs",
        ).order_by("contest_name", "-contest_year", "problem_code", "problem_uuid"),
    )
    if not statement_rows:
        return []

    problem_by_uuid = _problem_rows_by_uuid(statement_rows)
    problem_by_statement_key = _problem_rows_by_statement_key(statement_rows)
    techniques_by_statement_id = _techniques_by_statement_id([row["id"] for row in statement_rows])
    statement_key_counts = Counter(_statement_key(row) for row in statement_rows if _statement_key(row) is not None)

    hydrated_rows = []
    for row in statement_rows:
        statement_key = _statement_key(row)
        uuid_problem = problem_by_uuid.get(row["problem_uuid"])
        key_problem = (
            problem_by_statement_key.get(statement_key)
            if statement_key is not None and statement_key_counts[statement_key] == 1
            else None
        )
        topic_value = _first_text(
            row.get("topic"),
            row.get("linked_problem__topic"),
            uuid_problem.get("topic") if uuid_problem else "",
            key_problem.get("topic") if key_problem else "",
        )
        mohs_value = _first_number(
            row.get("mohs"),
            row.get("linked_problem__mohs"),
            uuid_problem.get("mohs") if uuid_problem else None,
            key_problem.get("mohs") if key_problem else None,
        )
        topic_label = display_topic_label(topic_value) if topic_value else "Unlinked"
        contest_name = str(row["contest_name"] or "").strip()
        contest_year = int(row["contest_year"])
        problem_code = str(row["problem_code"] or "").strip().upper()
        contest_year_label = f"{contest_name} {contest_year}"
        hydrated_rows.append(
            {
                "id": row["id"],
                "contest_name": contest_name,
                "contest_year": contest_year,
                "contest_year_label": contest_year_label,
                "contest_year_problem": row.get("contest_year_problem") or f"{contest_year_label} {problem_code}",
                "problem_code": problem_code,
                "problem_uuid": row["problem_uuid"],
                "topic": topic_value,
                "topic_label": topic_label,
                "mohs": mohs_value,
                "updated_at": row.get("updated_at"),
                "techniques": techniques_by_statement_id.get(row["id"], []),
            },
        )
    return hydrated_rows


def _problem_rows_by_uuid(statement_rows: list[dict[str, Any]]) -> dict[object, dict[str, Any]]:
    problem_uuids = {row["problem_uuid"] for row in statement_rows if row.get("problem_uuid")}
    if not problem_uuids:
        return {}
    return {
        row["problem_uuid"]: {"topic": row["topic"], "mohs": row["mohs"]}
        for row in ProblemSolveRecord.objects.filter(problem_uuid__in=problem_uuids).values(
            "problem_uuid",
            "topic",
            "mohs",
        )
    }


def _problem_rows_by_statement_key(statement_rows: list[dict[str, Any]]) -> dict[tuple[str, int, str], dict[str, Any]]:
    statement_keys = {_statement_key(row) for row in statement_rows if _statement_key(row) is not None}
    if not statement_keys:
        return {}
    years = {key[1] for key in statement_keys}
    contests = {key[0] for key in statement_keys}
    problem_codes = {key[2] for key in statement_keys}
    problem_rows = list(
        ProblemSolveRecord.objects.filter(
            year__in=years,
            contest__in=contests,
            problem__in=problem_codes,
        ).values("contest", "year", "problem", "topic", "mohs"),
    )
    problem_key_counts = Counter(_problem_key(row) for row in problem_rows)
    return {
        key: {"topic": row["topic"], "mohs": row["mohs"]}
        for row in problem_rows
        if (key := _problem_key(row)) in statement_keys and problem_key_counts[key] == 1
    }


def _techniques_by_statement_id(statement_ids: list[int]) -> dict[int, list[str]]:
    if not statement_ids:
        return {}
    techniques_by_statement_id: dict[int, list[str]] = defaultdict(list)
    seen: dict[int, set[str]] = defaultdict(set)
    technique_rows = (
        StatementTopicTechnique.objects.filter(statement_id__in=statement_ids)
        .exclude(technique="")
        .values("statement_id", "technique")
        .order_by("technique", "statement_id")
    )
    for row in technique_rows:
        statement_id = row["statement_id"]
        technique = str(row["technique"] or "").strip()
        if not technique or technique in seen[statement_id]:
            continue
        seen[statement_id].add(technique)
        techniques_by_statement_id[statement_id].append(technique)
    return techniques_by_statement_id


def _statement_key(row: dict[str, Any]) -> tuple[str, int, str] | None:
    problem_code = str(row.get("problem_code") or "").strip().upper()
    if not problem_code:
        return None
    return (str(row.get("contest_name") or "").strip(), int(row["contest_year"]), problem_code)


def _problem_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return (
        str(row.get("contest") or "").strip(),
        int(row["year"]),
        str(row.get("problem") or "").strip().upper(),
    )


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_number(*values: object) -> int | None:
    for value in values:
        if value is not None:
            return int(value)
    return None


def _filter_rows(rows: list[dict[str, Any]], filters: dict[str, object]) -> list[dict[str, Any]]:
    filtered_rows = rows
    query = str(filters["q"]).casefold()
    if query:
        filtered_rows = [
            row
            for row in filtered_rows
            if query
            in " ".join(
                [
                    row["contest_name"],
                    row["contest_year_label"],
                    row["contest_year_problem"],
                    row["problem_code"],
                    row["topic"],
                    row["topic_label"],
                ],
            ).casefold()
        ]
    if filters["contest"]:
        filtered_rows = [row for row in filtered_rows if row["contest_name"] == filters["contest"]]
    if filters["year"]:
        filtered_rows = [row for row in filtered_rows if str(row["contest_year"]) == filters["year"]]
    if filters["mohs"]:
        filtered_rows = [
            row for row in filtered_rows if row["mohs"] is not None and str(row["mohs"]) == filters["mohs"]
        ]
    if filters["topic"]:
        filtered_rows = [row for row in filtered_rows if row["topic"] == filters["topic"]]
    return filtered_rows


def _filter_options(rows: list[dict[str, Any]]) -> dict[str, object]:
    topic_pairs = {(row["topic"], row["topic_label"]) for row in rows if row["topic"]}
    return {
        "contest_names": sorted({row["contest_name"] for row in rows}, key=str.casefold),
        "year_values": [str(year) for year in sorted({row["contest_year"] for row in rows}, reverse=True)],
        "mohs_values": [str(mohs) for mohs in sorted({row["mohs"] for row in rows if row["mohs"] is not None})],
        "topic_values": [
            {"value": topic, "label": label}
            for topic, label in sorted(topic_pairs, key=lambda pair: (pair[1].casefold(), pair[0].casefold()))
        ],
    }


def _summary_payload(
    all_rows: list[dict[str, Any]],
    filtered_rows: list[dict[str, Any]],
    pivot_payload: dict[str, object],
) -> dict[str, object]:
    active_total = len(all_rows)
    filtered_total = len(filtered_rows)
    with_mohs_total = sum(1 for row in filtered_rows if row["mohs"] is not None)
    missing_mohs_total = filtered_total - with_mohs_total
    with_mohs_percentage = (with_mohs_total / filtered_total * 100) if filtered_total else 0
    contest_counts = Counter(row["contest_name"] for row in filtered_rows)
    top_contest_name = ""
    top_contest_count = 0
    if contest_counts:
        top_contest_name, top_contest_count = sorted(
            contest_counts.items(),
            key=lambda item: (-item[1], item[0].casefold()),
        )[0]
    years = [row["contest_year"] for row in filtered_rows]
    all_years = [row["contest_year"] for row in all_rows]
    latest_updated = max((row["updated_at"] for row in all_rows if row["updated_at"] is not None), default=None)
    technique_rows = sum(len(row["techniques"]) for row in filtered_rows)
    summary = {
        "active_statements": active_total,
        "filtered_statements": filtered_total,
        "with_mohs": with_mohs_total,
        "missing_mohs": missing_mohs_total,
        "with_mohs_percentage": round(with_mohs_percentage, 1),
        "distinct_contests": len(contest_counts),
        "distinct_topics": len({row["topic"] for row in filtered_rows if row["topic"]}),
        "latest_year": max(years) if years else None,
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "active_year_min": min(all_years) if all_years else None,
        "active_year_max": max(all_years) if all_years else None,
        "top_contest": top_contest_name,
        "top_contest_count": top_contest_count,
        "technique_rows": technique_rows,
        "last_updated": latest_updated,
        "last_updated_label": _format_datetime(latest_updated),
        "source_label": "ContestProblemStatement + linked ProblemSolveRecord",
        "pivot_grand_total": pivot_payload["grand_total"],
    }
    summary.update(
        {
            "active_statements_label": _format_int(active_total),
            "filtered_statements_label": _format_int(filtered_total),
            "with_mohs_label": _format_int(with_mohs_total),
            "missing_mohs_label": _format_int(missing_mohs_total),
            "with_mohs_percentage_label": f"{summary['with_mohs_percentage']:.1f}%",
            "distinct_contests_label": _format_int(summary["distinct_contests"]),
            "top_contest_count_label": _format_int(top_contest_count),
            "technique_rows_label": _format_int(technique_rows),
        },
    )
    return summary


def _quality_payload(
    all_rows: list[dict[str, Any]],
    filtered_rows: list[dict[str, Any]],
    pivot_payload: dict[str, object],
) -> dict[str, object]:
    missing_mohs_count = sum(1 for row in filtered_rows if row["mohs"] is None)
    duplicate_groups = _suspected_duplicate_contest_groups(all_rows)
    return {
        "missing_mohs_count": missing_mohs_count,
        "missing_mohs_count_label": _format_int(missing_mohs_count),
        "hidden_empty_rows_count": pivot_payload["hidden_empty_rows"],
        "hidden_empty_rows_count_label": _format_int(pivot_payload["hidden_empty_rows"]),
        "empty_rows_available": pivot_payload["empty_rows_available"],
        "empty_rows_available_label": _format_int(pivot_payload["empty_rows_available"]),
        "duplicate_contest_groups": duplicate_groups,
        "duplicate_contest_group_count": len(duplicate_groups),
        "duplicate_contest_group_count_label": _format_int(len(duplicate_groups)),
    }


def _year_payload(rows: list[dict[str, Any]]) -> dict[str, object]:
    counts = Counter(row["contest_year"] for row in rows)
    years = sorted(counts)
    return {"labels": [str(year) for year in years], "values": [counts[year] for year in years]}


def _topic_payload(rows: list[dict[str, Any]]) -> dict[str, object]:
    counts = Counter(row["topic_label"] for row in rows if row["topic"])
    labels, values = _ranked_items(counts, CHART_LIMIT)
    return {
        "labels": labels,
        "values": values,
        "colors": [TOPIC_COLORS.get(label, "#6c757d") for label in labels],
    }


def _contest_payload(rows: list[dict[str, Any]]) -> dict[str, object]:
    labels, values = _ranked_items(Counter(row["contest_name"] for row in rows), CONTEST_CHART_LIMIT)
    return {"labels": labels, "values": values}


def _mohs_payload(rows: list[dict[str, Any]]) -> dict[str, object]:
    counts = Counter(row["mohs"] for row in rows if row["mohs"] is not None)
    mohs_values = sorted(counts)
    return {
        "labels": [str(mohs) for mohs in mohs_values],
        "values": [counts[mohs] for mohs in mohs_values],
        "colors": [_mohs_color(mohs) for mohs in mohs_values],
    }


def _technique_payload(rows: list[dict[str, Any]]) -> dict[str, object]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(row["techniques"])
    labels, values = _ranked_items(counts, CHART_LIMIT)
    return {"labels": labels, "values": values}


def _ranked_items(counts: Counter[str], limit: int) -> tuple[list[str], list[int]]:
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))[:limit]
    return [label for label, _count in ranked], [count for _label, count in ranked]


def _contest_year_mohs_pivot_payload(rows: list[dict[str, Any]], *, hide_empty: bool) -> dict[str, object]:
    mohs_values = sorted({row["mohs"] for row in rows if row["mohs"] is not None})
    counts_by_contest_year: dict[tuple[str, int], Counter[int]] = defaultdict(Counter)
    contest_year_names: dict[tuple[str, int], str] = {}
    for row in rows:
        key = (row["contest_name"], row["contest_year"])
        contest_year_names[key] = row["contest_year_label"]
        if row["mohs"] is not None:
            counts_by_contest_year[key][row["mohs"]] += 1

    ordered_keys = sorted(
        contest_year_names,
        key=lambda key: (key[0].casefold(), -key[1]),
    )
    table_rows = []
    hidden_empty_rows = 0
    empty_rows_available = 0
    max_cell_count = 0
    for contest_name, contest_year in ordered_keys:
        mohs_counts = {
            str(mohs): counts_by_contest_year[(contest_name, contest_year)].get(mohs, 0)
            for mohs in mohs_values
        }
        row_total = sum(mohs_counts.values())
        if row_total == 0:
            empty_rows_available += 1
            if hide_empty:
                hidden_empty_rows += 1
                continue
        max_cell_count = max(max_cell_count, *(mohs_counts.values() or [0]))
        table_rows.append(
            {
                "contest_name": contest_name,
                "contest_year": contest_year,
                "contest_year_label": contest_year_names[(contest_name, contest_year)],
                "row_total": row_total,
                "has_mohs": row_total > 0,
                "mohs_counts": mohs_counts,
            },
        )

    column_totals = {
        str(mohs): sum(row["mohs_counts"].get(str(mohs), 0) for row in table_rows)
        for mohs in mohs_values
    }
    grand_total = sum(row["row_total"] for row in table_rows)
    return {
        "contest_names": sorted({row["contest_name"] for row in table_rows}, key=str.casefold),
        "mohs_values": [str(mohs) for mohs in mohs_values],
        "table_rows": table_rows,
        "year_values": [str(year) for year in sorted({row["contest_year"] for row in table_rows}, reverse=True)],
        "column_totals": column_totals,
        "grand_total": grand_total,
        "grand_total_label": _format_int(grand_total),
        "max_cell_count": max_cell_count,
        "hidden_empty_rows": hidden_empty_rows,
        "empty_rows_available": empty_rows_available,
        "hide_empty": hide_empty,
    }


def _suspected_duplicate_contest_groups(rows: list[dict[str, Any]]) -> list[dict[str, object]]:
    names_by_fingerprint: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        name = row["contest_name"]
        fingerprint = _contest_name_fingerprint(name)
        if fingerprint:
            names_by_fingerprint[fingerprint][name] += 1

    groups = []
    for fingerprint, name_counts in names_by_fingerprint.items():
        if len(name_counts) < DUPLICATE_GROUP_MIN_NAMES:
            continue
        names = sorted(name_counts, key=str.casefold)
        groups.append(
            {
                "fingerprint": fingerprint,
                "names": names,
                "label": " / ".join(names),
                "count": sum(name_counts.values()),
                "count_label": _format_int(sum(name_counts.values())),
            },
        )
    return sorted(groups, key=lambda group: (-int(group["count"]), str(group["label"]).casefold()))[:8]


def _contest_name_fingerprint(name: str) -> str:
    normalized = name.translate(CONFUSABLE_TRANSLATION).casefold()
    normalized = re.sub(r"[^a-z0-9]+", "", normalized)
    normalized = normalized.replace("maths", "math")
    if normalized.endswith("s") and len(normalized) > PLURAL_SUFFIX_MIN_LENGTH:
        normalized = normalized[:-1]
    return normalized


def _mohs_color(mohs: int) -> str:
    for limit, color in MOHS_COLOR_STOPS:
        if mohs <= limit:
            return color
    return "#6c757d"


def _format_datetime(value) -> str:
    if value is None:
        return "Never"
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


def _format_int(value: object) -> str:
    return f"{int(value or 0):,}"
