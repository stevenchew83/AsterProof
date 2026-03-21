from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from typing import BinaryIO

import pandas as pd
from django.db import transaction

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.problem_import import sync_problem_topic_techniques

STATEMENT_METADATA_EXPORT_COLUMNS = [
    "PROBLEM UUID",
    "CONTEST YEAR",
    "CONTEST NAME",
    "CONTEST PROBLEM",
    "DAY LABEL",
    "PROBLEM NUMBER",
    "PROBLEM CODE",
    "TOPIC",
    "MOHS",
    "Confidence",
    "IMO slot guess",
    "Topic tags",
]
STATEMENT_METADATA_REQUIRED_COLUMNS = frozenset({"PROBLEM UUID", "TOPIC", "MOHS"})
STATEMENT_METADATA_EDITABLE_COLUMNS = (
    "TOPIC",
    "MOHS",
    "Confidence",
    "IMO slot guess",
    "Topic tags",
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
    mohs: int
    raw_topic_tags: str | None
    row_number: int
    statement: ContestProblemStatement
    topic: str


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


def _metadata_row_has_values(raw_row: dict[str, object]) -> bool:
    return any(_cell_str(raw_row.get(column)) for column in STATEMENT_METADATA_EDITABLE_COLUMNS)


def _parse_problem_uuid(raw_value: object, *, row_number: int) -> uuid.UUID:
    value = _cell_str(raw_value)
    if not value:
        msg = f'Row {row_number}: "PROBLEM UUID" is required.'
        raise StatementMetadataBackfillValidationError(msg)
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        msg = f'Row {row_number}: "PROBLEM UUID" must be a valid UUID.'
        raise StatementMetadataBackfillValidationError(msg) from exc


def _statement_problem_key(statement: ContestProblemStatement) -> tuple[int, str, str]:
    return (
        int(statement.contest_year),
        statement.contest_name,
        (statement.problem_code or "").strip().upper(),
    )


def _record_problem_key(record: ProblemSolveRecord) -> tuple[int, str, str]:
    return (
        int(record.year),
        record.contest,
        (record.problem or "").strip().upper(),
    )


def _build_statement_problem_lookup(
    statements: list[ContestProblemStatement],
) -> tuple[dict[uuid.UUID, ProblemSolveRecord], dict[tuple[int, str, str], ProblemSolveRecord]]:
    statement_problem_uuids = [statement.problem_uuid for statement in statements]
    statement_problem_keys = {_statement_problem_key(statement) for statement in statements}
    matching_records = list(
        ProblemSolveRecord.objects.filter(
            year__in=sorted({key[0] for key in statement_problem_keys}),
            contest__in=sorted({key[1] for key in statement_problem_keys}),
        ).order_by("contest", "-year", "problem"),
    )
    records_by_uuid = {
        record.problem_uuid: record
        for record in matching_records
        if record.problem_uuid in statement_problem_uuids
    }
    records_by_key = {
        _record_problem_key(record): record
        for record in matching_records
        if _record_problem_key(record) in statement_problem_keys
    }
    return records_by_uuid, records_by_key


def _resolved_problem_for_statement(
    statement: ContestProblemStatement,
    *,
    records_by_key: dict[tuple[int, str, str], ProblemSolveRecord],
    records_by_uuid: dict[uuid.UUID, ProblemSolveRecord],
) -> ProblemSolveRecord | None:
    if statement.linked_problem_id is not None and statement.linked_problem is not None:
        return statement.linked_problem

    record_by_uuid = records_by_uuid.get(statement.problem_uuid)
    if record_by_uuid is not None:
        return record_by_uuid

    return records_by_key.get(_statement_problem_key(statement))


def build_statement_metadata_export_dataframe(
    statements: list[ContestProblemStatement],
) -> pd.DataFrame:
    records_by_uuid, records_by_key = _build_statement_problem_lookup(statements)
    rows = []
    for statement in statements:
        record = _resolved_problem_for_statement(
            statement,
            records_by_key=records_by_key,
            records_by_uuid=records_by_uuid,
        )
        rows.append(
            {
                "PROBLEM UUID": str(statement.problem_uuid),
                "CONTEST YEAR": statement.contest_year,
                "CONTEST NAME": statement.contest_name,
                "CONTEST PROBLEM": statement.contest_year_problem,
                "DAY LABEL": statement.day_label,
                "PROBLEM NUMBER": statement.problem_number,
                "PROBLEM CODE": statement.problem_code,
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
    buffer = io.BytesIO()
    export_df.to_excel(buffer, index=False)
    return buffer.getvalue()


def _normalize_and_validate_statement_metadata_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe.columns = [str(column).strip() for column in dataframe.columns]
    missing_columns = STATEMENT_METADATA_REQUIRED_COLUMNS.difference(dataframe.columns)
    if missing_columns:
        msg = f"Missing required column(s): {', '.join(sorted(missing_columns))}."
        raise StatementMetadataBackfillValidationError(msg)
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


def statement_metadata_dataframe_from_rows(rows: list[dict[str, object]]) -> pd.DataFrame:
    dataframe = pd.DataFrame(rows)
    return _normalize_and_validate_statement_metadata_dataframe(dataframe)


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
        msg = "The workbook does not contain any filled metadata rows."
        raise StatementMetadataBackfillValidationError(msg)

    prepared_by_uuid: dict[uuid.UUID, PreparedStatementMetadataRow] = {}
    requested_uuids: list[uuid.UUID] = []
    for row_number, raw_row in enumerate(relevant_rows, start=2):
        problem_uuid = _parse_problem_uuid(raw_row.get("PROBLEM UUID"), row_number=row_number)
        if problem_uuid in prepared_by_uuid:
            msg = f'Row {row_number}: duplicate "PROBLEM UUID" values are not allowed in one workbook.'
            raise StatementMetadataBackfillValidationError(msg)
        topic = _cell_str(raw_row.get("TOPIC"))
        if not topic:
            msg = f'Row {row_number}: "TOPIC" is required once a metadata row is filled.'
            raise StatementMetadataBackfillValidationError(msg)

        mohs = _cell_int(raw_row.get("MOHS"))
        if mohs is None or mohs <= 0:
            msg = f'Row {row_number}: "MOHS" must be a positive integer.'
            raise StatementMetadataBackfillValidationError(msg)

        requested_uuids.append(problem_uuid)
        prepared_by_uuid[problem_uuid] = PreparedStatementMetadataRow(
            confidence=_cell_str(raw_row.get("Confidence")),
            existing_record=None,
            imo_slot_guess=_cell_str(raw_row.get("IMO slot guess")),
            mohs=mohs,
            raw_topic_tags=_cell_str(raw_row.get("Topic tags")),
            row_number=row_number,
            statement=None,  # type: ignore[arg-type]
            topic=topic,
        )

    statements = list(
        ContestProblemStatement.objects.select_related("linked_problem").filter(
            problem_uuid__in=requested_uuids,
        ),
    )
    statements_by_uuid = {statement.problem_uuid: statement for statement in statements}
    if len(statements_by_uuid) != len(set(requested_uuids)):
        missing_uuid = next(
            str(problem_uuid)
            for problem_uuid in requested_uuids
            if problem_uuid not in statements_by_uuid
        )
        msg = f'Statement row "{missing_uuid}" was not found.'
        raise StatementMetadataBackfillValidationError(msg)

    row_numbers_by_problem_key: dict[tuple[int, str, str], list[int]] = {}
    for problem_uuid in requested_uuids:
        statement = statements_by_uuid[problem_uuid]
        statement_problem_key = _statement_problem_key(statement)
        row_numbers_by_problem_key.setdefault(statement_problem_key, []).append(
            prepared_by_uuid[problem_uuid].row_number,
        )
    duplicate_problem_keys = [
        (problem_key, row_numbers)
        for problem_key, row_numbers in row_numbers_by_problem_key.items()
        if len(row_numbers) > 1
    ]
    if duplicate_problem_keys:
        contest_year_problem = (
            f"{duplicate_problem_keys[0][0][1]} {duplicate_problem_keys[0][0][0]} {duplicate_problem_keys[0][0][2]}"
        )
        row_number_text = ", ".join(str(row_number) for row_number in duplicate_problem_keys[0][1])
        msg = (
            f"Rows {row_number_text} resolve to the same tracked problem key "
            f'"{contest_year_problem}". The current schema allows only one statement row '
            "per problem record, so split or rename those statement rows first."
        )
        raise StatementMetadataBackfillValidationError(msg)

    records_by_uuid, records_by_key = _build_statement_problem_lookup(statements)
    prepared_rows: list[PreparedStatementMetadataRow] = []
    for problem_uuid in requested_uuids:
        base_row = prepared_by_uuid[problem_uuid]
        statement = statements_by_uuid[problem_uuid]
        existing_record = _resolved_problem_for_statement(
            statement,
            records_by_key=records_by_key,
            records_by_uuid=records_by_uuid,
        )
        if (
            existing_record is not None
            and existing_record.problem_uuid == statement.problem_uuid
            and _record_problem_key(existing_record) != _statement_problem_key(statement)
        ):
            msg = (
                f'Row {base_row.row_number}: linked problem "{existing_record.problem_uuid}" '
                "does not match the statement contest/problem key."
            )
            raise StatementMetadataBackfillValidationError(msg)

        prepared_rows.append(
            PreparedStatementMetadataRow(
                confidence=base_row.confidence,
                existing_record=existing_record,
                imo_slot_guess=base_row.imo_slot_guess,
                mohs=base_row.mohs,
                raw_topic_tags=base_row.raw_topic_tags,
                row_number=base_row.row_number,
                statement=statement,
                topic=base_row.topic,
            ),
        )

    return prepared_rows, skipped_count


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
        statement_problem_key = _statement_problem_key(statement)
        record = prepared_row.existing_record
        record_created = False

        if record is None:
            record = ProblemSolveRecord.objects.filter(
                year=statement.contest_year,
                contest=statement.contest_name,
                problem=statement.problem_code,
            ).first()

        if record is None:
            record = ProblemSolveRecord(
                problem_uuid=statement.problem_uuid,
                year=statement.contest_year,
                topic=prepared_row.topic,
                mohs=prepared_row.mohs,
                contest=statement.contest_name,
                problem=statement.problem_code,
                contest_year_problem=statement.contest_year_problem,
                confidence=prepared_row.confidence,
                imo_slot_guess=prepared_row.imo_slot_guess,
                topic_tags=prepared_row.raw_topic_tags,
            )
            record.save()
            record_created = True
            result.created_count += 1
        else:
            update_fields: set[str] = set()
            field_values = {
                "topic": prepared_row.topic,
                "mohs": prepared_row.mohs,
                "contest_year_problem": statement.contest_year_problem,
                "confidence": prepared_row.confidence,
                "imo_slot_guess": prepared_row.imo_slot_guess,
                "topic_tags": prepared_row.raw_topic_tags,
            }
            for field_name, next_value in field_values.items():
                if getattr(record, field_name) != next_value:
                    setattr(record, field_name, next_value)
                    update_fields.add(field_name)
            if update_fields:
                record.save(update_fields=update_fields)
            result.updated_count += 1

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
        result.linked_count += 1
        result.processed_count += 1

        if record_created:
            continue

    return result
