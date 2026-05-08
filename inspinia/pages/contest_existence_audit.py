from __future__ import annotations

import csv
import re
from collections import OrderedDict
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from io import StringIO
from typing import TypedDict

from django.db.models import Count

from inspinia.pages.contest_names import normalize_contest_name
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord


class ContestExistenceAuditValidationError(ValueError):
    """Raised when pasted contest-audit text cannot be parsed."""


@dataclass(frozen=True)
class ParsedContestHeader:
    year: int
    contest_name: str
    first_line_number: int
    occurrence_count: int


class ContestExistenceAuditRow(TypedDict):
    analytics_count: int
    analytics_status: str
    contest_name: str
    first_line_number: int
    occurrence_count: int
    overall_status: str
    statement_count: int
    statement_status: str
    suggestions: list[str]
    suggestions_label: str
    year: int


class ContestExistenceAuditPayload(TypedDict):
    export_tsv: str
    row_count: int
    rows: list[ContestExistenceAuditRow]
    summary: dict[str, int]


YEAR_HEADER_RE = re.compile(r"^(?P<year>\d{4})\s+(?P<title>.+?)\s*$")
TRAILING_YEAR_RE = re.compile(r"\s+\d{4}\s*$")
GENERIC_HEADER_WORDS = {"contest", "contests"}
SUGGESTION_LIMIT = 3
SUGGESTION_MIN_RATIO = 0.35


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def _is_generic_header(title: str) -> bool:
    letters_only = re.sub(r"[^a-z]", "", title.lower())
    return letters_only in GENERIC_HEADER_WORDS


def _dedupe_concatenated_title(title: str) -> str:
    for split_index in range(1, len(title)):
        prefix = title[:split_index].strip()
        suffix = title[split_index:].strip()
        if not prefix or not suffix:
            continue
        if suffix == prefix:
            return prefix
        if re.fullmatch(rf"\d{{4}}\s*{re.escape(prefix)}", suffix):
            return prefix
    return title


def _clean_parsed_contest_name(raw_title: str) -> str:
    title = _collapse_whitespace(raw_title)
    title = TRAILING_YEAR_RE.sub("", title).strip()
    title = _dedupe_concatenated_title(title)
    return normalize_contest_name(title)


def parse_contest_existence_audit_text(raw_text: str) -> tuple[ParsedContestHeader, ...]:
    if not raw_text.strip():
        msg = "Paste contest text before checking."
        raise ContestExistenceAuditValidationError(msg)

    headers_by_key: OrderedDict[tuple[int, str], dict[str, int | str]] = OrderedDict()
    skipped_year_lines = 0
    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.lstrip()
        match = YEAR_HEADER_RE.match(line)
        if match is None:
            continue

        raw_title = match.group("title")
        if _is_generic_header(raw_title):
            skipped_year_lines += 1
            continue

        contest_name = _clean_parsed_contest_name(raw_title)
        if not contest_name or _is_generic_header(contest_name):
            skipped_year_lines += 1
            continue

        key = (int(match.group("year")), contest_name)
        if key not in headers_by_key:
            headers_by_key[key] = {
                "contest_name": contest_name,
                "first_line_number": line_number,
                "occurrence_count": 0,
                "year": key[0],
            }
        headers_by_key[key]["occurrence_count"] = int(headers_by_key[key]["occurrence_count"]) + 1

    if not headers_by_key:
        if skipped_year_lines:
            msg = "Only generic year headings were detected; paste contest header lines such as '2026 USAMO'."
            raise ContestExistenceAuditValidationError(msg)
        msg = "No year-prefixed contest headers were detected."
        raise ContestExistenceAuditValidationError(msg)

    return tuple(
        ParsedContestHeader(
            year=int(row["year"]),
            contest_name=str(row["contest_name"]),
            first_line_number=int(row["first_line_number"]),
            occurrence_count=int(row["occurrence_count"]),
        )
        for row in headers_by_key.values()
    )


def _statement_counts_by_key() -> dict[tuple[int, str], int]:
    counts: dict[tuple[int, str], int] = {}
    rows = (
        ContestProblemStatement.objects.values("contest_year", "contest_name")
        .annotate(row_count=Count("id"))
        .order_by("contest_year", "contest_name")
    )
    for row in rows:
        key = (int(row["contest_year"]), normalize_contest_name(str(row["contest_name"])))
        counts[key] = counts.get(key, 0) + int(row["row_count"])
    return counts


def _analytics_counts_by_key() -> dict[tuple[int, str], int]:
    counts: dict[tuple[int, str], int] = {}
    rows = (
        ProblemSolveRecord.objects.values("year", "contest")
        .annotate(row_count=Count("id"))
        .order_by("year", "contest")
    )
    for row in rows:
        key = (int(row["year"]), normalize_contest_name(str(row["contest"])))
        counts[key] = counts.get(key, 0) + int(row["row_count"])
    return counts


def _contest_names_by_year(
    statement_counts: dict[tuple[int, str], int],
    analytics_counts: dict[tuple[int, str], int],
) -> dict[int, list[str]]:
    names_by_year: dict[int, set[str]] = defaultdict(set)
    for year, contest_name in list(statement_counts) + list(analytics_counts):
        names_by_year[year].add(contest_name)
    return {
        year: sorted(contest_names)
        for year, contest_names in names_by_year.items()
    }


def _status_for_counts(statement_count: int, analytics_count: int) -> str:
    if statement_count and analytics_count:
        return "both_found"
    if statement_count:
        return "statements_only"
    if analytics_count:
        return "analytics_only"
    return "missing"


def _suggest_contests(*, contest_name: str, year: int, names_by_year: dict[int, list[str]]) -> list[str]:
    scored_names: list[tuple[float, str]] = []
    needle = contest_name.lower()
    for candidate in names_by_year.get(year, []):
        if candidate == contest_name:
            continue
        ratio = SequenceMatcher(None, needle, candidate.lower()).ratio()
        if ratio >= SUGGESTION_MIN_RATIO:
            scored_names.append((ratio, candidate))
    scored_names.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for _ratio, candidate in scored_names[:SUGGESTION_LIMIT]]


def _build_export_tsv(rows: list[ContestExistenceAuditRow]) -> str:
    output = StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(
        [
            "LINE",
            "YEAR",
            "CONTEST",
            "OCCURRENCES",
            "STATEMENT STATUS",
            "STATEMENT COUNT",
            "ANALYTICS STATUS",
            "ANALYTICS COUNT",
            "OVERALL STATUS",
            "SUGGESTIONS",
        ],
    )
    for row in rows:
        writer.writerow(
            [
                row["first_line_number"],
                row["year"],
                row["contest_name"],
                row["occurrence_count"],
                row["statement_status"],
                row["statement_count"],
                row["analytics_status"],
                row["analytics_count"],
                row["overall_status"],
                row["suggestions_label"],
            ],
        )
    return output.getvalue().rstrip("\n")


def build_contest_existence_audit_payload(
    parsed_headers: tuple[ParsedContestHeader, ...],
) -> ContestExistenceAuditPayload:
    statement_counts = _statement_counts_by_key()
    analytics_counts = _analytics_counts_by_key()
    names_by_year = _contest_names_by_year(statement_counts, analytics_counts)
    rows: list[ContestExistenceAuditRow] = []
    summary = {
        "analytics_only_total": 0,
        "both_found_total": 0,
        "missing_total": 0,
        "partial_total": 0,
        "parsed_total": len(parsed_headers),
        "statements_only_total": 0,
    }

    for header in parsed_headers:
        key = (header.year, normalize_contest_name(header.contest_name))
        statement_count = statement_counts.get(key, 0)
        analytics_count = analytics_counts.get(key, 0)
        overall_status = _status_for_counts(statement_count, analytics_count)
        statement_status = "found" if statement_count else "missing"
        analytics_status = "found" if analytics_count else "missing"
        suggestions = (
            []
            if overall_status == "both_found"
            else _suggest_contests(
                contest_name=header.contest_name,
                year=header.year,
                names_by_year=names_by_year,
            )
        )

        if overall_status == "both_found":
            summary["both_found_total"] += 1
        elif overall_status == "statements_only":
            summary["statements_only_total"] += 1
            summary["partial_total"] += 1
        elif overall_status == "analytics_only":
            summary["analytics_only_total"] += 1
            summary["partial_total"] += 1
        else:
            summary["missing_total"] += 1

        rows.append(
            {
                "analytics_count": analytics_count,
                "analytics_status": analytics_status,
                "contest_name": header.contest_name,
                "first_line_number": header.first_line_number,
                "occurrence_count": header.occurrence_count,
                "overall_status": overall_status,
                "statement_count": statement_count,
                "statement_status": statement_status,
                "suggestions": suggestions,
                "suggestions_label": ", ".join(suggestions),
                "year": header.year,
            },
        )

    return {
        "export_tsv": _build_export_tsv(rows),
        "row_count": len(rows),
        "rows": rows,
        "summary": summary,
    }
