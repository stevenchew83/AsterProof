from __future__ import annotations

import re
from collections import Counter
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
from typing import TYPE_CHECKING

from inspinia.pages.contest_links import contest_dashboard_problem_url

if TYPE_CHECKING:
    from collections.abc import Iterable

    from inspinia.pages.models import ContestProblemStatement

ASY_BLOCK_RE = re.compile(r"\[asy\].*?\[/asy\]", re.IGNORECASE | re.DOTALL)
WHITESPACE_RE = re.compile(r"\s+")
SIMILARITY_SHINGLE_SIZE = 5
SIMILARITY_MIN_CHAR_COUNT = 80
SIMILARITY_MIN_TOKEN_COUNT = 12
SIMILARITY_MAX_BUCKET_SIZE = 24
SIMILARITY_MIN_SHARED_SHINGLES = 2
SIMILARITY_MAX_LENGTH_DELTA_RATIO = 0.2
SIMILARITY_THRESHOLD = 0.9


@dataclass(frozen=True)
class StatementComparisonRow:
    statement_id: int
    contest_name: str
    contest_year: int
    contest_year_problem: str
    problem_url: str
    day_label: str
    linked_problem_label: str
    problem_uuid: str
    statement_length: int
    preview: str
    exact_text: str
    similarity_text: str
    tokens: tuple[str, ...]

    @property
    def line_label(self) -> str:
        parts = [self.contest_year_problem, self.day_label or "Unlabeled"]
        if self.linked_problem_label:
            parts.append(f"Linked to {self.linked_problem_label}")
        else:
            parts.append("Unlinked")
        parts.append(f"UUID {self.problem_uuid}")
        return " · ".join(parts)


def _collapse_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", (text or "").strip())


def _normalize_exact_text(statement_latex: str) -> str:
    return _collapse_whitespace(statement_latex).casefold()


def _normalize_similarity_text(statement_latex: str) -> str:
    return _collapse_whitespace(ASY_BLOCK_RE.sub(" [diagram] ", statement_latex or "")).casefold()


def _statement_preview(statement_latex: str, *, max_length: int = 200) -> str:
    collapsed = _collapse_whitespace(statement_latex)
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 1].rstrip() + "…"


def _build_statement_rows(
    statements: Iterable[ContestProblemStatement],
) -> list[StatementComparisonRow]:
    from inspinia.pages.models import ProblemSolveRecord

    statement_list = list(statements)
    existing_problem_uuid_strings = {
        str(problem_uuid)
        for problem_uuid in ProblemSolveRecord.objects.filter(
            problem_uuid__in=[statement.problem_uuid for statement in statement_list],
        ).values_list("problem_uuid", flat=True)
    }
    rows: list[StatementComparisonRow] = []
    for statement in statement_list:
        similarity_text = _normalize_similarity_text(statement.statement_latex)
        problem_url = ""
        if (
            (statement.linked_problem_id and statement.linked_problem is not None)
            or str(statement.problem_uuid) in existing_problem_uuid_strings
        ):
            problem_url = contest_dashboard_problem_url(
                statement.contest_name,
                year=statement.contest_year,
                problem_label=statement.contest_year_problem,
                fallback=f"{statement.contest_year}-{statement.problem_code}",
            )
        rows.append(
            StatementComparisonRow(
                statement_id=statement.id,
                contest_name=statement.contest_name,
                contest_year=statement.contest_year,
                contest_year_problem=statement.contest_year_problem,
                problem_url=problem_url,
                day_label=statement.day_label or "",
                linked_problem_label=(
                    statement.linked_problem.contest_year_problem
                    if statement.linked_problem_id and statement.linked_problem is not None
                    else ""
                ),
                problem_uuid=str(statement.problem_uuid),
                statement_length=len(statement.statement_latex or ""),
                preview=_statement_preview(statement.statement_latex),
                exact_text=_normalize_exact_text(statement.statement_latex),
                similarity_text=similarity_text,
                tokens=tuple(similarity_text.split()),
            ),
        )
    return rows


def _year_span_label(years: list[int]) -> str:
    year_min = min(years)
    year_max = max(years)
    return str(year_min) if year_min == year_max else f"{year_min}-{year_max}"


def _exact_duplicate_rows(rows: list[StatementComparisonRow]) -> list[dict[str, object]]:
    grouped_rows: dict[str, list[StatementComparisonRow]] = defaultdict(list)
    for row in rows:
        if row.exact_text:
            grouped_rows[row.exact_text].append(row)

    duplicate_rows: list[dict[str, object]] = []
    for group in grouped_rows.values():
        if len(group) < 2:
            continue
        ordered_group = sorted(
            group,
            key=lambda row: (-row.contest_year, row.contest_name, row.day_label, row.contest_year_problem),
        )
        problem_items_by_label: dict[str, dict[str, object]] = {}
        for row in ordered_group:
            existing_item = problem_items_by_label.get(row.contest_year_problem)
            if existing_item is None:
                problem_items_by_label[row.contest_year_problem] = {
                    "contest_year": row.contest_year,
                    "label": row.contest_year_problem,
                    "url": row.problem_url,
                }
                continue
            if not existing_item["url"] and row.problem_url:
                existing_item["url"] = row.problem_url

        problem_items = sorted(
            problem_items_by_label.values(),
            key=lambda item: (int(item["contest_year"]), str(item["label"])),
        )
        duplicate_rows.append(
            {
                "duplicate_count": len(ordered_group),
                "statement_length": ordered_group[0].statement_length,
                "year_span_label": _year_span_label([row.contest_year for row in ordered_group]),
                "problem_items": problem_items,
                "problem_labels": "\n".join(str(item["label"]) for item in problem_items),
                "preview": ordered_group[0].preview,
                "members_text": "\n".join(row.line_label for row in ordered_group),
            },
        )

    duplicate_rows.sort(
        key=lambda row: (
            -int(row["duplicate_count"]),
            -int(row["statement_length"]),
            str(row["problem_labels"]),
            str(row["preview"]),
        ),
    )
    return duplicate_rows


def _similarity_shingles(tokens: tuple[str, ...]) -> set[str]:
    if len(tokens) < SIMILARITY_SHINGLE_SIZE:
        return {" ".join(tokens)} if tokens else set()
    return {
        " ".join(tokens[index : index + SIMILARITY_SHINGLE_SIZE])
        for index in range(len(tokens) - SIMILARITY_SHINGLE_SIZE + 1)
    }


def _similar_statement_rows(
    rows: list[StatementComparisonRow],
    *,
    limit: int,
) -> tuple[list[dict[str, object]], int]:
    eligible_rows = [
        row
        for row in rows
        if len(row.similarity_text) >= SIMILARITY_MIN_CHAR_COUNT and len(row.tokens) >= SIMILARITY_MIN_TOKEN_COUNT
    ]
    if len(eligible_rows) < 2:
        return [], 0

    rows_by_id = {row.statement_id: row for row in eligible_rows}
    buckets: dict[str, list[int]] = defaultdict(list)
    for row in eligible_rows:
        for shingle in _similarity_shingles(row.tokens):
            buckets[shingle].append(row.statement_id)

    pair_overlap_counts: Counter[tuple[int, int]] = Counter()
    for statement_ids in buckets.values():
        unique_ids = sorted(set(statement_ids))
        if len(unique_ids) < 2 or len(unique_ids) > SIMILARITY_MAX_BUCKET_SIZE:
            continue
        for left_id, right_id in combinations(unique_ids, 2):
            pair_overlap_counts[(left_id, right_id)] += 1

    similar_rows: list[dict[str, object]] = []
    for (left_id, right_id), shared_shingles in pair_overlap_counts.items():
        if shared_shingles < SIMILARITY_MIN_SHARED_SHINGLES:
            continue

        left_row = rows_by_id[left_id]
        right_row = rows_by_id[right_id]
        if left_row.exact_text == right_row.exact_text:
            continue

        max_length = max(len(left_row.similarity_text), len(right_row.similarity_text))
        if not max_length:
            continue

        length_delta_ratio = abs(len(left_row.similarity_text) - len(right_row.similarity_text)) / max_length
        if length_delta_ratio > SIMILARITY_MAX_LENGTH_DELTA_RATIO:
            continue

        similarity_score = SequenceMatcher(None, left_row.similarity_text, right_row.similarity_text).ratio()
        if similarity_score < SIMILARITY_THRESHOLD:
            continue

        similar_rows.append(
            {
                "similarity_score": similarity_score,
                "similarity_percent": round(similarity_score * 100, 1),
                "shared_shingles": shared_shingles,
                "left_statement": left_row.line_label,
                "left_preview": left_row.preview,
                "right_statement": right_row.line_label,
                "right_preview": right_row.preview,
            },
        )

    similar_rows.sort(
        key=lambda row: (
            -float(row["similarity_score"]),
            -int(row["shared_shingles"]),
            str(row["left_statement"]),
            str(row["right_statement"]),
        ),
    )
    return similar_rows[:limit], len(similar_rows)


def build_statement_duplicate_report(
    statements: Iterable[ContestProblemStatement],
    *,
    similar_pair_limit: int = 250,
) -> dict[str, object]:
    statement_rows = _build_statement_rows(statements)
    exact_rows = _exact_duplicate_rows(statement_rows)
    similar_rows, similar_pair_total = _similar_statement_rows(statement_rows, limit=similar_pair_limit)

    return {
        "statement_total": len(statement_rows),
        "exact_duplicate_group_total": len(exact_rows),
        "exact_duplicate_row_total": sum(int(row["duplicate_count"]) for row in exact_rows),
        "exact_duplicate_rows": exact_rows,
        "similar_pair_total": similar_pair_total,
        "similar_pair_display_total": len(similar_rows),
        "similar_pair_limit": similar_pair_limit,
        "similar_pair_rows": similar_rows,
    }
