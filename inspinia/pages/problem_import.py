"""Shared logic for importing problem analytics from Excel."""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any
from typing import BinaryIO

import pandas as pd
from django.db import transaction
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.utils.dataframe import dataframe_to_rows

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.statement_analytics_sync import sync_statement_analytics_from_linked_problem
from inspinia.pages.topic_tags_parse import domains_dedup_preserve_order
from inspinia.pages.topic_tags_parse import merge_domain_lists
from inspinia.pages.topic_tags_parse import parse_contest_problem_string
from inspinia.pages.topic_tags_parse import parse_topic_tags_cell

if TYPE_CHECKING:
    from pathlib import Path

REQUIRED_COLUMNS = frozenset(
    {"YEAR", "TOPIC", "MOHS", "CONTEST", "PROBLEM", "CONTEST PROBLEM", "Topic tags"},
)

DEFAULT_PREVIEW_MAX_PROBLEMS = 500
DEFAULT_PREVIEW_MAX_TECHNIQUES = 5000
EXPORT_COLUMNS = [
    "PROBLEM UUID",
    "YEAR",
    "TOPIC",
    "MOHS",
    "CONTEST",
    "PROBLEM",
    "CONTEST PROBLEM",
    "Topic tags",
    "Confidence",
    "IMO slot guess",
    "Rationale",
    "Pitfalls",
]
STATEMENT_EXPORT_COLUMNS = [
    "PROBLEM UUID",
    "LINKED PROBLEM UUID",
    "CONTEST YEAR",
    "CONTEST NAME",
    "CONTEST PROBLEM",
    "DAY LABEL",
    "PROBLEM NUMBER",
    "PROBLEM CODE",
    "STATEMENT LATEX",
]
PROBLEM_NUMBER_RE = re.compile(r"^\s*P?(?P<number>\d+)\s*$", flags=re.IGNORECASE)
STATEMENT_PROBLEM_CODE_RE = re.compile(r"^\s*(?:(?P<prefix>[A-Za-z]{1,4})\s*)?(?P<number>\d+)\s*$")


@dataclass
class PreparedImportRow:
    """One sheet row resolved the same way as DB import (before writing)."""

    problem_uuid: uuid.UUID | None
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


def _problem_number_from_code(problem_code: str) -> int | None:
    match = PROBLEM_NUMBER_RE.fullmatch(problem_code)
    if not match:
        return None
    return int(match.group("number"))


def _statement_problem_code_from_problem(problem_code: str) -> str | None:
    match = STATEMENT_PROBLEM_CODE_RE.fullmatch(problem_code)
    if not match:
        return None
    prefix = (match.group("prefix") or "P").upper()
    return f"{prefix}{int(match.group('number'))}"


def _find_statement_entry(*, year: int, contest: str, problem: str) -> ContestProblemStatement | None:
    statement_problem_code = _statement_problem_code_from_problem(problem)
    if statement_problem_code is None:
        return None
    matches = ContestProblemStatement.objects.filter(
        contest_year=year,
        contest_name=contest,
        problem_code=statement_problem_code,
    )
    if matches.count() != 1:
        return None
    return matches.first()


def _sync_statement_link(*, record: ProblemSolveRecord, created: bool) -> None:
    statement_entry = _find_statement_entry(
        year=record.year,
        contest=record.contest,
        problem=record.problem,
    )
    if statement_entry is None:
        return

    if created and record.problem_uuid != statement_entry.problem_uuid:
        record.problem_uuid = statement_entry.problem_uuid
        record.save(update_fields={"problem_uuid"})

    update_fields: set[str] = set()
    if statement_entry.linked_problem_id != record.id:
        statement_entry.linked_problem = record
        update_fields.add("linked_problem")
    if statement_entry.problem_uuid != record.problem_uuid:
        statement_entry.problem_uuid = record.problem_uuid
        update_fields.add("problem_uuid")

    if update_fields:
        statement_entry.save(update_fields=update_fields)
        if statement_entry.linked_problem_id is not None:
            statement_entry.refresh_from_db()
            sync_statement_analytics_from_linked_problem(statement_entry)


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

        problem_uuid: uuid.UUID | None = None
        raw_problem_uuid = _cell_str(row.get("PROBLEM UUID"))
        if raw_problem_uuid:
            try:
                problem_uuid = uuid.UUID(raw_problem_uuid)
            except ValueError:
                warnings.append(
                    f"Skipped row: invalid PROBLEM UUID for {year} {contest} {problem}.",
                )
                continue

        topic = _cell_str(row.get("TOPIC")) or ""
        mohs = _cell_int(row.get("MOHS"))
        if mohs is None:
            warnings.append(f"Skipped row: invalid MOHS for {year} {contest} {problem}.")
            continue

        defaults: dict[str, Any] = {
            "topic": topic,
            "mohs": mohs,
            "contest_year_problem": _cell_str(row.get("CONTEST PROBLEM")),
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
                problem_uuid=problem_uuid,
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
        problems_json.append(
            {
                "year": str(p.year),
                "topic": str(d.get("topic") or ""),
                "mohs": str(d.get("mohs") or ""),
                "contest": p.contest,
                "problem": p.problem,
                "contest_year_problem": d.get("contest_year_problem") or "",
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


def _topic_tags_export_value(record: ProblemSolveRecord) -> str:
    tags = sorted(
        record.topic_techniques.all(),
        key=lambda row: ("/".join(row.domains or []), row.technique),
    )
    if not tags:
        return record.topic_tags or ""

    grouped: dict[tuple[str, ...], list[str]] = {}
    for tag in tags:
        grouped.setdefault(tuple(tag.domains or []), []).append(tag.technique)

    segments: list[str] = []
    for domains, techniques in grouped.items():
        technique_label = ", ".join(techniques)
        if domains:
            segments.append(f"{'/'.join(domains)} - {technique_label}")
        else:
            segments.append(technique_label)

    return f"Topic tags: {'; '.join(segments)}"


def build_problem_export_dataframe(records: list[ProblemSolveRecord]) -> pd.DataFrame:
    rows = [
        {
            "PROBLEM UUID": str(record.problem_uuid),
            "YEAR": record.year,
            "TOPIC": record.topic,
            "MOHS": record.mohs,
            "CONTEST": record.contest,
            "PROBLEM": record.problem,
            "CONTEST PROBLEM": record.contest_year_problem or "",
            "Topic tags": _topic_tags_export_value(record),
            "Confidence": record.confidence or "",
            "IMO slot guess": record.imo_slot_guess or "",
            "Rationale": record.rationale or "",
            "Pitfalls": record.pitfalls or "",
        }
        for record in records
    ]
    return pd.DataFrame(rows, columns=EXPORT_COLUMNS)


def dataframe_to_safe_excel_bytes(dataframe: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    workbook = Workbook()
    worksheet = workbook.active

    for row_index, row in enumerate(dataframe_to_rows(dataframe, index=False, header=True), start=1):
        for column_index, value in enumerate(row, start=1):
            cell = worksheet.cell(row=row_index, column=column_index)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                cell.value = ""
                cell.data_type = "s"
                continue
            if isinstance(value, str):
                safe_value = ILLEGAL_CHARACTERS_RE.sub("", value)
                cell.value = safe_value
                cell.data_type = "s"
                continue
            cell.value = value

    workbook.save(buffer)
    return buffer.getvalue()


def build_problem_export_workbook_bytes(records: list[ProblemSolveRecord]) -> bytes:
    export_df = build_problem_export_dataframe(records)
    return dataframe_to_safe_excel_bytes(export_df)


def build_problem_statement_export_dataframe(
    statements: list[ContestProblemStatement],
) -> pd.DataFrame:
    rows = [
        {
            "PROBLEM UUID": str(statement.problem_uuid),
            "LINKED PROBLEM UUID": (
                str(statement.linked_problem.problem_uuid) if statement.linked_problem_id else ""
            ),
            "CONTEST YEAR": statement.contest_year,
            "CONTEST NAME": statement.contest_name,
            "CONTEST PROBLEM": statement.contest_year_problem,
            "DAY LABEL": statement.day_label,
            "PROBLEM NUMBER": statement.problem_number,
            "PROBLEM CODE": statement.problem_code,
            "STATEMENT LATEX": statement.statement_latex,
        }
        for statement in statements
    ]
    return pd.DataFrame(rows, columns=STATEMENT_EXPORT_COLUMNS)


def build_problem_statement_export_workbook_bytes(
    statements: list[ContestProblemStatement],
) -> bytes:
    export_df = build_problem_statement_export_dataframe(statements)
    return dataframe_to_safe_excel_bytes(export_df)


def dataframe_from_excel(source: Path | str | BinaryIO | bytes) -> pd.DataFrame:
    """Load workbook; normalize column headers (strip)."""
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    try:
        dataframe = pd.read_excel(source)
    except Exception as exc:
        msg = "Could not read Excel file. Is it a valid .xlsx?"
        raise ProblemImportValidationError(msg) from exc

    dataframe.columns = [str(column).strip() for column in dataframe.columns]
    missing = REQUIRED_COLUMNS - set(dataframe.columns)
    if missing:
        msg = (
            f"Missing required column(s): {', '.join(sorted(missing))}. "
            f"Found columns: {list(dataframe.columns)}"
        )
        raise ProblemImportValidationError(msg)
    return dataframe


def _upsert_topic_technique(
    *,
    record: ProblemSolveRecord,
    technique: str,
    domain_list: list[str],
    replace_tags: bool,
) -> int:
    if replace_tags:
        ProblemTopicTechnique.objects.create(
            record=record,
            technique=technique,
            domains=domain_list,
        )
        return 1

    matching_tags = list(
        ProblemTopicTechnique.objects.filter(
            record=record,
            technique__iexact=technique,
        ).order_by("id"),
    )
    if not matching_tags:
        ProblemTopicTechnique.objects.create(
            record=record,
            technique=technique,
            domains=domain_list,
        )
        return 1

    obj = matching_tags[0]
    duplicate_ids = [tag.pk for tag in matching_tags[1:]]
    merged_domains = obj.domains or []
    for duplicate in matching_tags[1:]:
        merged_domains = merge_domain_lists(merged_domains, duplicate.domains or [])

    if duplicate_ids:
        ProblemTopicTechnique.objects.filter(pk__in=duplicate_ids).delete()

    merged_domains = merge_domain_lists(merged_domains, domain_list)

    updated_fields: list[str] = []
    if obj.technique != technique:
        obj.technique = technique
        updated_fields.append("technique")
    if merged_domains != (obj.domains or []):
        obj.domains = merged_domains
        updated_fields.append("domains")

    if updated_fields:
        obj.save(update_fields=updated_fields)
        return 1

    return 1 if duplicate_ids else 0


def sync_problem_topic_techniques(
    *,
    record: ProblemSolveRecord,
    raw_topic_tags: str | None,
    replace_tags: bool,
) -> int:
    parsed_entries: list[tuple[str, list[str]]] = []
    for item in parse_topic_tags_cell(raw_topic_tags):
        technique = (item.get("technique") or "").strip()
        if not technique:
            continue
        parsed_entries.append(
            (
                technique,
                domains_dedup_preserve_order(item.get("domains") or []),
            ),
        )

    if replace_tags:
        ProblemTopicTechnique.objects.filter(record=record).delete()

    touched_count = 0
    for technique, domain_list in parsed_entries:
        touched_count += _upsert_topic_technique(
            record=record,
            technique=technique,
            domain_list=domain_list,
            replace_tags=replace_tags,
        )

    return touched_count


def _update_problem_record_from_prepared(
    *,
    record: ProblemSolveRecord,
    prepared_row: PreparedImportRow,
) -> None:
    field_values: dict[str, Any] = {
        "year": prepared_row.year,
        "contest": prepared_row.contest,
        "problem": prepared_row.problem,
        **prepared_row.defaults,
    }
    update_fields: set[str] = set()
    for field_name, next_value in field_values.items():
        if getattr(record, field_name) != next_value:
            setattr(record, field_name, next_value)
            update_fields.add(field_name)
    if update_fields:
        record.save(update_fields=update_fields)


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
            if p.problem_uuid is not None:
                record, created = ProblemSolveRecord.objects.update_or_create(
                    problem_uuid=p.problem_uuid,
                    defaults={
                        "year": p.year,
                        "contest": p.contest,
                        "problem": p.problem,
                        **p.defaults,
                    },
                )
            else:
                matching_records = ProblemSolveRecord.objects.filter(
                    year=p.year,
                    contest=p.contest,
                    problem=p.problem,
                ).order_by("id")
                if matching_records.count() > 1:
                    contest_problem_label = p.defaults.get("contest_year_problem") or ""
                    disambiguated_record = None
                    if contest_problem_label:
                        label_matches = matching_records.filter(
                            contest_year_problem=contest_problem_label,
                        )
                        if label_matches.count() == 1:
                            disambiguated_record = label_matches.first()
                    if disambiguated_record is None:
                        result.warnings.append(
                            "Skipped row: multiple existing problem rows match "
                            f"{p.year} {p.contest} {p.problem}. Add PROBLEM UUID to disambiguate.",
                        )
                        continue
                    record = disambiguated_record
                    created = False
                    _update_problem_record_from_prepared(record=record, prepared_row=p)
                else:
                    record, created = ProblemSolveRecord.objects.update_or_create(
                        year=p.year,
                        contest=p.contest,
                        problem=p.problem,
                        defaults=p.defaults,
                    )
            _sync_statement_link(record=record, created=created)
            result.n_records += 1

            if not p.techniques:
                if replace_tags:
                    ProblemTopicTechnique.objects.filter(record=record).delete()
                continue

            result.n_techniques += sync_problem_topic_techniques(
                record=record,
                raw_topic_tags=p.defaults.get("topic_tags"),
                replace_tags=replace_tags,
            )

    return result
