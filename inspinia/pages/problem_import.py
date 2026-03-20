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

DEFAULT_PREVIEW_MAX_ROWS = 100


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


def build_preview_payload(df: pd.DataFrame, *, max_rows: int = DEFAULT_PREVIEW_MAX_ROWS) -> dict[str, Any]:
    """
    Build a JSON-serializable payload for DataTables: column names + row dicts (string cells).
    """
    total = len(df)
    head = df.head(max_rows)
    columns = [str(c) for c in head.columns.tolist()]
    rows: list[dict[str, str]] = []
    for _, row in head.iterrows():
        record: dict[str, str] = {}
        for col in columns:
            val = row.get(col)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                record[col] = ""
            else:
                record[col] = str(val).strip() if isinstance(val, str) else str(val)
        rows.append(record)

    return {
        "columns": columns,
        "rows": rows,
        "total_row_count": int(total),
        "preview_row_count": len(rows),
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

    with transaction.atomic():
        for _, row in df.iterrows():
            year = _cell_int(row.get("YEAR"))
            if year is None:
                continue

            contest, problem = _resolve_contest_problem(row, year)
            if not contest or not problem:
                result.warnings.append(f"Skipped row: missing contest/problem for year={year}.")
                continue

            topic = _cell_str(row.get("TOPIC")) or ""
            mohs = _cell_int(row.get("MOHS"))
            if mohs is None:
                result.warnings.append(
                    f"Skipped row: invalid MOHS for {year} {contest} {problem}.",
                )
                continue

            record, _created = ProblemSolveRecord.objects.update_or_create(
                year=year,
                contest=contest,
                problem=problem,
                defaults={
                    "topic": topic,
                    "mohs": mohs,
                    "contest_year_problem": _cell_str(row.get("CONTEST PROBLEM")),
                    "solve_date": _cell_date(row.get("SOLVE DATE")),
                    "confidence": _cell_str(row.get("Confidence")),
                    "imo_slot_guess": _cell_str(row.get("IMO slot guess")),
                    "topic_tags": _cell_str(row.get("Topic tags")),
                    "rationale": _cell_str(row.get("Rationale")),
                    "pitfalls": _cell_str(row.get("Pitfalls")),
                },
            )
            result.n_records += 1

            parsed = parse_topic_tags_cell(row.get("Topic tags"))
            if not parsed:
                continue

            if replace_tags:
                ProblemTopicTechnique.objects.filter(record=record).delete()

            for item in parsed:
                technique = (item.get("technique") or "").strip()
                if not technique:
                    continue
                domain_list = domains_dedup_preserve_order(item.get("domains") or [])

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
