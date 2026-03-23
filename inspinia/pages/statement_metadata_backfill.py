from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from typing import BinaryIO

import pandas as pd
from django.db import models
from django.db import transaction

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.problem_import import dataframe_to_safe_excel_bytes
from inspinia.pages.problem_import import sync_problem_topic_techniques
from inspinia.pages.statement_analytics_sync import sync_statement_analytics_from_linked_problem

STATEMENT_METADATA_EXPORT_COLUMNS = [
    "STATEMENT UUID",
    "PROBLEM UUID",
    "CONTEST YEAR",
    "CONTEST NAME",
    "CONTEST PROBLEM",
    "DAY LABEL",
    "PROBLEM NUMBER",
    "PROBLEM CODE",
    "STATEMENT LATEX",
    "TOPIC",
    "MOHS",
    "Confidence",
    "IMO slot guess",
    "Topic tags",
]
STATEMENT_METADATA_IDENTIFIER_COLUMNS = ("STATEMENT UUID", "PROBLEM UUID")
STATEMENT_METADATA_EDITABLE_COLUMNS = (
    "TOPIC",
    "MOHS",
    "Confidence",
    "IMO slot guess",
    "Topic tags",
)
STATEMENT_METADATA_STATEMENT_IDENTITY_COLUMNS = (
    "CONTEST YEAR",
    "CONTEST NAME",
    "DAY LABEL",
    "PROBLEM NUMBER",
    "PROBLEM CODE",
    "STATEMENT LATEX",
)


class StatementMetadataBackfillValidationError(ValueError):
    """Raised when a statement metadata workbook cannot be validated."""


@dataclass
class StatementMetadataBackfillImportResult:
    created_count: int = 0
    linked_count: int = 0
    processed_count: int = 0
    skipped_count: int = 0
    technique_count: int = 0
    updated_count: int = 0


@dataclass(frozen=True)
class PreparedStatementMetadataRow:
    confidence: str | None
    existing_record: ProblemSolveRecord | None
    imo_slot_guess: str | None
    mohs: int | None
    raw_topic_tags: str | None
    row_number: int
    statement: ContestProblemStatement
    topic: str | None


@dataclass(frozen=True)
class RawStatementMetadataRow:
    confidence: str | None
    imo_slot_guess: str | None
    mohs: int | None
    problem_uuid: uuid.UUID | None
    raw_cells: dict[str, object]
    raw_topic_tags: str | None
    row_number: int
    statement_uuid: uuid.UUID | None
    topic: str | None


def _statement_label(statement: ContestProblemStatement) -> str:
    day_label = statement.day_label or "Unlabeled"
    return f"{statement.contest_year_problem} · {day_label}"


def _cell_str(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _cell_int(value: object) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _column_might_contribute_metadata(column: str, raw_row: dict[str, object]) -> bool:
    val = raw_row.get(column)
    if column in {"CONTEST YEAR", "PROBLEM NUMBER", "MOHS"}:
        return _cell_int(val) is not None
    if column == "STATEMENT LATEX":
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return False
        return bool(str(val).strip())
    return bool(_cell_str(val))


def _metadata_row_has_values(raw_row: dict[str, object]) -> bool:
    return any(
        _column_might_contribute_metadata(column, raw_row)
        for column in STATEMENT_METADATA_EDITABLE_COLUMNS
    )


def _parse_uuid_cell(raw_value: object, *, row_number: int, label: str) -> uuid.UUID:
    value = _cell_str(raw_value)
    if not value:
        msg = f'Row {row_number}: "{label}" is required.'
        raise StatementMetadataBackfillValidationError(msg)
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        msg = f'Row {row_number}: "{label}" must be a valid UUID.'
        raise StatementMetadataBackfillValidationError(msg) from exc


def _statement_problem_key(statement: ContestProblemStatement) -> tuple[int, str, str]:
    return (
        int(statement.contest_year),
        statement.contest_name,
        (statement.problem_code or "").strip().upper(),
    )


def _build_statement_problem_lookup(
    statements: list[ContestProblemStatement],
) -> dict[uuid.UUID, ProblemSolveRecord]:
    statement_problem_uuids = [statement.problem_uuid for statement in statements]
    matching_records = list(
        ProblemSolveRecord.objects.filter(
            problem_uuid__in=statement_problem_uuids,
        ).order_by("contest", "-year", "problem"),
    )
    return {
        record.problem_uuid: record
        for record in matching_records
        if record.problem_uuid in statement_problem_uuids
    }


def _resolved_problem_for_statement(
    statement: ContestProblemStatement,
    *,
    records_by_uuid: dict[uuid.UUID, ProblemSolveRecord],
) -> ProblemSolveRecord | None:
    if statement.linked_problem_id is not None and statement.linked_problem is not None:
        return statement.linked_problem

    record_by_uuid = records_by_uuid.get(statement.problem_uuid)
    if record_by_uuid is not None:
        return record_by_uuid

    return None


def build_statement_metadata_export_dataframe(
    statements: list[ContestProblemStatement],
) -> pd.DataFrame:
    records_by_uuid = _build_statement_problem_lookup(statements)
    rows = []
    for statement in statements:
        record = _resolved_problem_for_statement(
            statement,
            records_by_uuid=records_by_uuid,
        )
        rows.append(
            {
                "STATEMENT UUID": str(statement.statement_uuid),
                "PROBLEM UUID": str(statement.problem_uuid),
                "CONTEST YEAR": statement.contest_year,
                "CONTEST NAME": statement.contest_name,
                "CONTEST PROBLEM": statement.contest_year_problem,
                "DAY LABEL": statement.day_label,
                "PROBLEM NUMBER": statement.problem_number,
                "PROBLEM CODE": statement.problem_code,
                "STATEMENT LATEX": statement.statement_latex,
                "TOPIC": record.topic if record is not None else "",
                "MOHS": record.mohs if record is not None else "",
                "Confidence": record.confidence if record is not None else "",
                "IMO slot guess": record.imo_slot_guess if record is not None else "",
                "Topic tags": record.topic_tags if record is not None else "",
            },
        )
    return pd.DataFrame(rows, columns=STATEMENT_METADATA_EXPORT_COLUMNS)


def build_statement_metadata_export_workbook_bytes(
    statements: list[ContestProblemStatement],
) -> bytes:
    export_df = build_statement_metadata_export_dataframe(statements)
    return dataframe_to_safe_excel_bytes(export_df)


def _normalize_and_validate_statement_metadata_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe.columns = [str(column).strip() for column in dataframe.columns]
    if not any(column in dataframe.columns for column in STATEMENT_METADATA_IDENTIFIER_COLUMNS):
        msg = 'Missing required column: "STATEMENT UUID" (or legacy "PROBLEM UUID").'
        raise StatementMetadataBackfillValidationError(msg)
    for column in STATEMENT_METADATA_EDITABLE_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = ""
    for column in STATEMENT_METADATA_STATEMENT_IDENTITY_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = ""
    for column in STATEMENT_METADATA_IDENTIFIER_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = ""
    return dataframe


def statement_metadata_dataframe_from_excel(source: str | BinaryIO | bytes) -> pd.DataFrame:
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    try:
        dataframe = pd.read_excel(source)
    except Exception as exc:
        msg = "Could not read Excel file. Is it a valid .xlsx?"
        raise StatementMetadataBackfillValidationError(msg) from exc

    return _normalize_and_validate_statement_metadata_dataframe(dataframe)


def statement_metadata_dataframe_from_text(source_text: str) -> pd.DataFrame:
    text = source_text.strip()
    if not text:
        msg = "Paste at least one metadata row."
        raise StatementMetadataBackfillValidationError(msg)

    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel

    stream = io.StringIO(text, newline="")
    try:
        reader = csv.DictReader(stream, dialect=dialect)
        dataframe = pd.DataFrame(list(reader), columns=reader.fieldnames or None)
    except csv.Error as exc:
        msg = "Could not read pasted rows. Use a header row with TSV or CSV columns."
        raise StatementMetadataBackfillValidationError(msg) from exc

    if dataframe.empty and not getattr(reader, "fieldnames", None):
        msg = "Could not read pasted rows. Use a header row with TSV or CSV columns."
        raise StatementMetadataBackfillValidationError(msg)

    return _normalize_and_validate_statement_metadata_dataframe(dataframe)


def statement_metadata_dataframe_from_rows(rows: list[dict[str, object]]) -> pd.DataFrame:
    dataframe = pd.DataFrame(rows)
    return _normalize_and_validate_statement_metadata_dataframe(dataframe)


def _parse_raw_statement_metadata_sheet_rows(
    relevant_rows: list[object],
) -> list[RawStatementMetadataRow]:
    raw_rows: list[RawStatementMetadataRow] = []
    for row_number, row_series in enumerate(relevant_rows, start=2):
        cells = row_series.to_dict()
        statement_uuid_raw = _cell_str(cells.get("STATEMENT UUID"))
        problem_uuid_raw = _cell_str(cells.get("PROBLEM UUID"))
        statement_uuid = (
            _parse_uuid_cell(statement_uuid_raw, row_number=row_number, label="STATEMENT UUID")
            if statement_uuid_raw
            else None
        )
        problem_uuid = (
            _parse_uuid_cell(problem_uuid_raw, row_number=row_number, label="PROBLEM UUID")
            if problem_uuid_raw
            else None
        )
        if statement_uuid is None and problem_uuid is None:
            msg = f'Row {row_number}: "STATEMENT UUID" is required.'
            raise StatementMetadataBackfillValidationError(msg)
        topic = _cell_str(cells.get("TOPIC"))
        mohs = _cell_int(cells.get("MOHS"))
        if mohs is not None and mohs <= 0:
            msg = f'Row {row_number}: "MOHS" must be a positive integer.'
            raise StatementMetadataBackfillValidationError(msg)

        raw_rows.append(
            RawStatementMetadataRow(
                confidence=_cell_str(cells.get("Confidence")),
                imo_slot_guess=_cell_str(cells.get("IMO slot guess")),
                mohs=mohs,
                problem_uuid=problem_uuid,
                raw_cells=cells,
                raw_topic_tags=_cell_str(cells.get("Topic tags")),
                row_number=row_number,
                statement_uuid=statement_uuid,
                topic=topic,
            ),
        )
    return raw_rows


def _prepare_statement_metadata_rows(
    df: pd.DataFrame,
) -> tuple[list[PreparedStatementMetadataRow], int]:
    relevant_rows = [
        row
        for _, row in df.iterrows()
        if _metadata_row_has_values(row.to_dict())
    ]
    skipped_count = len(df) - len(relevant_rows)
    if not relevant_rows:
        msg = "The import does not contain any filled metadata rows."
        raise StatementMetadataBackfillValidationError(msg)

    raw_rows = _parse_raw_statement_metadata_sheet_rows(relevant_rows)

    requested_statement_uuids = [row.statement_uuid for row in raw_rows if row.statement_uuid is not None]
    requested_problem_uuids = [row.problem_uuid for row in raw_rows if row.problem_uuid is not None]
    statements = list(
        ContestProblemStatement.objects.select_related("linked_problem").filter(
            models.Q(statement_uuid__in=requested_statement_uuids)
            | models.Q(problem_uuid__in=requested_problem_uuids),
        ),
    )
    statements_by_statement_uuid = {statement.statement_uuid: statement for statement in statements}
    statements_by_problem_uuid = {statement.problem_uuid: statement for statement in statements}

    records_by_uuid = _build_statement_problem_lookup(statements)
    prepared_rows: list[PreparedStatementMetadataRow] = []
    seen_statement_uuids: set[uuid.UUID] = set()
    for raw_row in raw_rows:
        statement = None
        if raw_row.statement_uuid is not None:
            statement = statements_by_statement_uuid.get(raw_row.statement_uuid)
        if statement is None and raw_row.problem_uuid is not None:
            statement = statements_by_problem_uuid.get(raw_row.problem_uuid)
        if statement is None:
            missing_uuid = raw_row.statement_uuid or raw_row.problem_uuid
            msg = f'Statement row "{missing_uuid}" was not found.'
            raise StatementMetadataBackfillValidationError(msg)
        if statement.statement_uuid in seen_statement_uuids:
            msg = (
                f"Row {raw_row.row_number}: duplicate statement rows are not allowed in one import batch."
            )
            raise StatementMetadataBackfillValidationError(msg)
        seen_statement_uuids.add(statement.statement_uuid)
        if (
            statement.linked_problem_id is not None
            and statement.linked_problem is not None
            and statement.linked_problem.problem_uuid != statement.problem_uuid
        ):
            msg = (
                f'Row {raw_row.row_number}: "{_statement_label(statement)}" is linked to a '
                "problem row with a different PROBLEM UUID. Fix that UUID/link mismatch first."
            )
            raise StatementMetadataBackfillValidationError(msg)
        existing_record = _resolved_problem_for_statement(
            statement,
            records_by_uuid=records_by_uuid,
        )
        if existing_record is None and not raw_row.topic:
            msg = (
                f'Row {raw_row.row_number}: "{_statement_label(statement)}" needs "TOPIC" '
                "before a new problem row can be created."
            )
            raise StatementMetadataBackfillValidationError(msg)
        if existing_record is None and raw_row.mohs is None:
            msg = (
                f'Row {raw_row.row_number}: "{_statement_label(statement)}" needs "MOHS" '
                "before a new problem row can be created."
            )
            raise StatementMetadataBackfillValidationError(msg)

        prepared_rows.append(
            PreparedStatementMetadataRow(
                confidence=raw_row.confidence,
                existing_record=existing_record,
                imo_slot_guess=raw_row.imo_slot_guess,
                mohs=raw_row.mohs,
                raw_topic_tags=raw_row.raw_topic_tags,
                row_number=raw_row.row_number,
                statement=statement,
                topic=raw_row.topic,
            ),
        )

    return prepared_rows, skipped_count


def _import_metadata_update_existing_problem_record(
    prepared_row: PreparedStatementMetadataRow,
    statement: ContestProblemStatement,
    record: ProblemSolveRecord,
) -> None:
    update_fields: set[str] = set()
    field_values = {
        "year": statement.contest_year,
        "contest": statement.contest_name,
        "problem": statement.problem_code,
        "contest_year_problem": statement.contest_year_problem,
    }
    if prepared_row.topic is not None:
        field_values["topic"] = prepared_row.topic
    if prepared_row.mohs is not None:
        field_values["mohs"] = prepared_row.mohs
    if prepared_row.confidence is not None:
        field_values["confidence"] = prepared_row.confidence
    if prepared_row.imo_slot_guess is not None:
        field_values["imo_slot_guess"] = prepared_row.imo_slot_guess
    if prepared_row.raw_topic_tags is not None:
        field_values["topic_tags"] = prepared_row.raw_topic_tags
    for field_name, next_value in field_values.items():
        if getattr(record, field_name) != next_value:
            setattr(record, field_name, next_value)
            update_fields.add(field_name)
    if update_fields:
        record.save(update_fields=update_fields)


def _import_metadata_upsert_problem_record(
    prepared_row: PreparedStatementMetadataRow,
    statement: ContestProblemStatement,
    *,
    result: StatementMetadataBackfillImportResult,
) -> ProblemSolveRecord:
    record = prepared_row.existing_record
    if record is None:
        topic = prepared_row.topic
        mohs = prepared_row.mohs
        if topic is None or mohs is None:
            msg = (
                f'Row {prepared_row.row_number}: "{_statement_label(statement)}" needs '
                '"TOPIC" and "MOHS" before a new problem row can be created.'
            )
            raise StatementMetadataBackfillValidationError(msg)
        record = ProblemSolveRecord(
            problem_uuid=statement.problem_uuid,
            year=statement.contest_year,
            topic=topic,
            mohs=mohs,
            contest=statement.contest_name,
            problem=statement.problem_code,
            contest_year_problem=statement.contest_year_problem,
            confidence=prepared_row.confidence,
            imo_slot_guess=prepared_row.imo_slot_guess,
            topic_tags=prepared_row.raw_topic_tags,
        )
        record.save()
        result.created_count += 1
        return record

    _import_metadata_update_existing_problem_record(prepared_row, statement, record)
    result.updated_count += 1
    return record


def _import_metadata_link_statement_and_sync(
    prepared_row: PreparedStatementMetadataRow,
    statement: ContestProblemStatement,
    record: ProblemSolveRecord,
    *,
    replace_tags: bool,
    result: StatementMetadataBackfillImportResult,
) -> None:
    if prepared_row.raw_topic_tags is not None:
        result.technique_count += sync_problem_topic_techniques(
            record=record,
            raw_topic_tags=prepared_row.raw_topic_tags,
            replace_tags=replace_tags,
        )

    claimant = (
        ContestProblemStatement.objects.filter(problem_uuid=record.problem_uuid)
        .exclude(id=statement.id)
        .first()
    )
    if claimant is not None:
        msg = (
            f'Row {prepared_row.row_number}: "{_statement_label(statement)}" cannot reuse '
            f'"{record.contest_year_problem}" because that problem UUID is already claimed by '
            f'"{_statement_label(claimant)}".'
        )
        raise StatementMetadataBackfillValidationError(msg)

    if statement.linked_problem_id != record.id:
        statement.linked_problem = record
        statement.save(update_fields={"linked_problem", "updated_at"})
    statement.refresh_from_db()
    if statement.linked_problem_id is not None:
        sync_statement_analytics_from_linked_problem(statement)
    result.linked_count += 1
    result.processed_count += 1


@transaction.atomic
def import_statement_metadata_dataframe(
    df: pd.DataFrame,
    *,
    replace_tags: bool,
) -> StatementMetadataBackfillImportResult:
    prepared_rows, skipped_count = _prepare_statement_metadata_rows(df)
    result = StatementMetadataBackfillImportResult(skipped_count=skipped_count)
    for prepared_row in prepared_rows:
        statement = prepared_row.statement
        record = _import_metadata_upsert_problem_record(prepared_row, statement, result=result)
        _import_metadata_link_statement_and_sync(
            prepared_row,
            statement,
            record,
            replace_tags=replace_tags,
            result=result,
        )

    return result
