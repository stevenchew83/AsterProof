"""Shared logic for importing problem analytics from Excel."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd
from django.db import transaction

from pages.models import ProblemSolveRecord, ProblemTopicTechnique
from pages.topic_tags_parse import (
    domains_dedup_preserve_order,
    merge_domain_lists,
    parse_contest_problem_string,
    parse_topic_tags_cell,
)

REQUIRED_COLUMNS = frozenset(
    {"YEAR", "TOPIC", "MOHS", "CONTEST", "PROBLEM", "CONTEST PROBLEM", "Topic tags"},
)

DEFAULT_PREVIEW_MAX_PROBLEMS = 500
DEFAULT_PREVIEW_MAX_TECHNIQUES = 5000


@dataclass
class PreparedImportRow:
    """One sheet row resolved the same way as DB import (before writing)."""

    year: int
    contest: str
    problem: str
    defaults: dict[str, Any]
    techniques: list[tuple[str, list[str]]]  # (technique label, domain codes)


@dataclass
class ProblemImportResult:
    n_records: int = 0
    n_techniques: int = 0
    warnings: list[str] = field(default_factory=list)


class ProblemImportValidationError(ValueError):
    """Raised when the workbook is missing required columns or is otherwise invalid."""


def _cell_str(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _cell_int(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _cell_date(value: Any):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _resolve_contest_problem(row: pd.Series, year: int | None) -> tuple[str | None, str | None]:
    contest = _cell_str(row.get("CONTEST"))
    problem = _cell_str(row.get("PROBLEM"))
    if contest and problem:
        return contest, problem

    combined = _cell_str(row.get("CONTEST PROBLEM"))
    if not combined:
        return None, None

    _y2, c2, p2 = parse_contest_problem_string(combined, year_hint=year)
    if not c2 or not p2:
        return None, None
    return c2, p2


def prepare_import_rows(df: pd.DataFrame) -> tuple[list[PreparedImportRow], list[str]]:
    """
    Resolve every sheet row the same way as import (skips, warnings, parsed techniques).
    Does not touch the database.
    """
    prepared: list[PreparedImportRow] = []
    warnings: list[str] = []

    for _, row in df.iterrows():
        year = _cell_int(row.get("YEAR"))
        if year is None:
            continue

        contest, problem = _resolve_contest_problem(row, year)
        if not contest or not problem:
            warnings.append(f"Skipped row: missing contest/problem for year={year}.")
            continue

        topic = _cell_str(row.get("TOPIC")) or ""
        mohs = _cell_int(row.get("MOHS"))
        if mohs is None:
            warnings.append(f"Skipped row: invalid MOHS for {year} {contest} {problem}.")
            continue

        solve_date = _cell_date(row.get("SOLVE DATE"))
        defaults: dict[str, Any] = {
            "topic": topic,
            "mohs": mohs,
            "contest_year_problem": _cell_str(row.get("CONTEST PROBLEM")),
            "solve_date": solve_date,
            "confidence": _cell_str(row.get("Confidence")),
            "imo_slot_guess": _cell_str(row.get("IMO slot guess")),
            "topic_tags": _cell_str(row.get("Topic tags")),
            "rationale": _cell_str(row.get("Rationale")),
            "pitfalls": _cell_str(row.get("Pitfalls")),
        }

        techniques: list[tuple[str, list[str]]] = []
        for item in parse_topic_tags_cell(row.get("Topic tags")):
            technique = (item.get("technique") or "").strip()
            if not technique:
                continue
            domain_list = domains_dedup_preserve_order(item.get("domains") or [])
            techniques.append((technique, domain_list))

        prepared.append(
            PreparedImportRow(
                year=year,
                contest=contest,
                problem=problem,
                defaults=defaults,
                techniques=techniques,
            ),
        )

    return prepared, warnings


def build_parsed_preview_payload(
    df: pd.DataFrame,
    *,
    max_problems: int = DEFAULT_PREVIEW_MAX_PROBLEMS,
    max_techniques: int = DEFAULT_PREVIEW_MAX_TECHNIQUES,
) -> dict[str, Any]:
    """
    JSON-serializable payload for UI: parsed `ProblemSolveRecord`-shaped rows and
    parsed topic-technique rows (as stored), not raw Excel columns.
    """
    prepared, warnings = prepare_import_rows(df)
    total_sheet_rows = len(df)
    total_prepared = len(prepared)
    total_technique_rows = sum(len(p.techniques) for p in prepared)

    problems_json: list[dict[str, str]] = []
    techniques_json: list[dict[str, str]] = []
    technique_budget = max_techniques

    for p in prepared[:max_problems]:
        d = p.defaults
        solve_date = d.get("solve_date")
        problems_json.append(
            {
                "year": str(p.year),
                "topic": str(d.get("topic") or ""),
                "mohs": str(d.get("mohs") or ""),
                "contest": p.contest,
                "problem": p.problem,
                "contest_year_problem": d.get("contest_year_problem") or "",
                "solve_date": str(solve_date) if solve_date else "",
                "confidence": d.get("confidence") or "",
                "imo_slot_guess": d.get("imo_slot_guess") or "",
                "topic_tags_raw": d.get("topic_tags") or "",
                "rationale": d.get("rationale") or "",
                "pitfalls": d.get("pitfalls") or "",
                "parsed_technique_count": str(len(p.techniques)),
            },
        )

        for tech, domains in p.techniques:
            if technique_budget <= 0:
                break
            techniques_json.append(
                {
                    "year": str(p.year),
                    "contest": p.contest,
                    "problem": p.problem,
                    "technique": tech,
                    "domains": ", ".join(domains),
                },
            )
            technique_budget -= 1

    problems_truncated = total_prepared > len(problems_json)
    techniques_truncated = total_technique_rows > len(techniques_json)

    return {
        "problems": problems_json,
        "techniques": techniques_json,
        "warnings": warnings,
        "total_sheet_rows": total_sheet_rows,
        "total_prepared_problems": total_prepared,
        "total_parsed_techniques": total_technique_rows,
        "preview_problems_count": len(problems_json),
        "preview_techniques_count": len(techniques_json),
        "problems_truncated": problems_truncated,
        "techniques_truncated": techniques_truncated,
    }


def dataframe_from_excel(source: Path | str | BinaryIO | bytes) -> pd.DataFrame:
    """Load workbook; normalize column headers (strip)."""
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    try:
        df = pd.read_excel(source)
    except Exception as exc:  # noqa: BLE001 — surface to caller as validation
        msg = "Could not read Excel file. Is it a valid .xlsx?"
        raise ProblemImportValidationError(msg) from exc

    df.columns = [str(c).strip() for c in df.columns]
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ProblemImportValidationError(
            f"Missing required column(s): {', '.join(sorted(missing))}. "
            f"Found columns: {list(df.columns)}",
        )
    return df


def import_problem_dataframe(df: pd.DataFrame, *, replace_tags: bool) -> ProblemImportResult:
    """
    Upsert `ProblemSolveRecord` rows and parsed `ProblemTopicTechnique` entries.

    Caller must ensure `df` columns are normalized (see `dataframe_from_excel`).
    """
    result = ProblemImportResult()
    prepared, warnings = prepare_import_rows(df)
    result.warnings.extend(warnings)

    with transaction.atomic():
        for p in prepared:
            record, _created = ProblemSolveRecord.objects.update_or_create(
                year=p.year,
                contest=p.contest,
                problem=p.problem,
                defaults=p.defaults,
            )
            result.n_records += 1

            if not p.techniques:
                continue

            if replace_tags:
                ProblemTopicTechnique.objects.filter(record=record).delete()

            for technique, domain_list in p.techniques:
                if replace_tags:
                    ProblemTopicTechnique.objects.create(
                        record=record,
                        technique=technique,
                        domains=domain_list,
                    )
                    result.n_techniques += 1
                    continue

                obj, created = ProblemTopicTechnique.objects.get_or_create(
                    record=record,
                    technique=technique,
                    defaults={"domains": domain_list},
                )
                if created:
                    result.n_techniques += 1
                else:
                    merged = merge_domain_lists(obj.domains or [], domain_list)
                    if merged != (obj.domains or []):
                        obj.domains = merged
                        obj.save(update_fields=["domains"])
                        result.n_techniques += 1

    return result
