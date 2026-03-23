from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from typing import BinaryIO

import pandas as pd
from django.db import IntegrityError
from django.db import models
from django.db import transaction

from inspinia.pages.contest_names import normalize_contest_name
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.problem_import import dataframe_to_safe_excel_bytes
from inspinia.pages.problem_import import sync_problem_topic_techniques
from inspinia.pages.statement_analytics_sync import sync_statement_analytics_from_linked_problem
from inspinia.pages.topic_tags_parse import domains_dedup_preserve_order
from inspinia.pages.topic_tags_parse import merge_domain_lists
from inspinia.pages.topic_tags_parse import parse_topic_tags_cell

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
# Export-only column: makes a row count as "filled" for import; values are not written
# (contest_year_problem is derived on save from year/name/code).
STATEMENT_METADATA_SHEET_CONTEXT_COLUMNS = ("CONTEST PROBLEM",)
STATEMENT_METADATA_ROW_VALUE_COLUMNS = (
    *STATEMENT_METADATA_EDITABLE_COLUMNS,
    *STATEMENT_METADATA_STATEMENT_IDENTITY_COLUMNS,
    *STATEMENT_METADATA_SHEET_CONTEXT_COLUMNS,
)

_STATEMENT_METADATA_HEADER_CANONICAL: dict[str, str] = {}
for _header in (
    *STATEMENT_METADATA_EXPORT_COLUMNS,
    *STATEMENT_METADATA_SHEET_CONTEXT_COLUMNS,
):
    _STATEMENT_METADATA_HEADER_CANONICAL[_header.casefold()] = _header


class StatementMetadataBackfillValidationError(ValueError):
    """Raised when a statement metadata workbook cannot be validated."""


@dataclass
class _StatementMetadataPrepareContext:
    statements_by_statement_uuid: dict[uuid.UUID, ContestProblemStatement]
    statements_by_problem_uuid: dict[uuid.UUID, ContestProblemStatement]
    sheet_columns: set[str]
    records_by_uuid: dict[uuid.UUID, ProblemSolveRecord]
    seen_statement_uuids: set[uuid.UUID]


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
        for column in STATEMENT_METADATA_ROW_VALUE_COLUMNS
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


def _metadata_cell_is_blank_for_ffill(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    return isinstance(value, str) and not value.strip()


def _ffill_like_pandas(series: pd.Series) -> pd.Series:
    last: object = pd.NA
    filled: list[object] = []
    for value in series:
        if value is pd.NA or value is None or (isinstance(value, float) and pd.isna(value)):
            filled.append(last)
        else:
            last = value
            filled.append(value)
    return pd.Series(filled, index=series.index, dtype=object)


def _row_has_problem_grid_cells(row: pd.Series) -> bool:
    """Merged contest headers apply to real problem rows, not blank template/footer rows."""
    if not _metadata_cell_is_blank_for_ffill(row.get("PROBLEM CODE")):
        return True
    if not _metadata_cell_is_blank_for_ffill(row.get("DAY LABEL")):
        return True
    value = row.get("PROBLEM NUMBER")
    if value is not None and not (isinstance(value, float) and pd.isna(value)):
        if _cell_int(value) is not None:
            return True
    return False


def _canonicalize_statement_metadata_column_names(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Map headers like 'mohs' / 'Mohs' to canonical export names so cells are read correctly."""
    rename: dict[str, str] = {}
    for column in list(dataframe.columns):
        key = str(column).strip().casefold()
        canonical = _STATEMENT_METADATA_HEADER_CANONICAL.get(key)
        if canonical is not None and column != canonical:
            rename[column] = canonical
    if rename:
        return dataframe.rename(columns=rename)
    return dataframe


def _forward_fill_statement_metadata_columns(dataframe: pd.DataFrame) -> None:
    """Excel often merges CONTEST YEAR / CONTEST NAME / CONTEST PROBLEM; only the first row has text."""
    grid_mask = dataframe.apply(_row_has_problem_grid_cells, axis=1)
    for column in ("CONTEST YEAR", "CONTEST NAME", "CONTEST PROBLEM"):
        if column not in dataframe.columns:
            continue
        raw = dataframe[column].map(
            lambda v: pd.NA if _metadata_cell_is_blank_for_ffill(v) else v,
        )
        filled = _ffill_like_pandas(raw.astype(object))
        dataframe[column] = filled.where(grid_mask, raw.astype(object))


def _normalize_and_validate_statement_metadata_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe.columns = [str(column).strip() for column in dataframe.columns]
    dataframe = _canonicalize_statement_metadata_column_names(dataframe)
    if not any(column in dataframe.columns for column in STATEMENT_METADATA_IDENTIFIER_COLUMNS):
        msg = 'Missing required column: "STATEMENT UUID" (or legacy "PROBLEM UUID").'
        raise StatementMetadataBackfillValidationError(msg)
    for column in STATEMENT_METADATA_EDITABLE_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = ""
    _forward_fill_statement_metadata_columns(dataframe)
    return dataframe


def _prospective_statement_unique_key(
    statement: ContestProblemStatement,
    patch: dict[str, object],
) -> tuple[int, str, str, str]:
    year = patch.get("contest_year", statement.contest_year)
    name = patch.get("contest_name", statement.contest_name)
    day_label = patch.get("day_label", statement.day_label)
    if day_label is None:
        day_label = ""
    problem_number = patch.get("problem_number", statement.problem_number)
    problem_code = patch.get("problem_code", statement.problem_code)
    code = (problem_code or "").strip().upper()
    if not code:
        code = f"P{problem_number}"
    return (int(year), str(name), str(day_label), code)


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


def _identity_patch_contest_year(
    statement: ContestProblemStatement,
    raw_cells: dict[str, object],
    sheet_columns: set[str],
    patch: dict[str, object],
) -> None:
    if "CONTEST YEAR" not in sheet_columns:
        return
    year = _cell_int(raw_cells.get("CONTEST YEAR"))
    if year is not None and year != statement.contest_year:
        patch["contest_year"] = year


def _identity_patch_contest_name(
    statement: ContestProblemStatement,
    raw_cells: dict[str, object],
    sheet_columns: set[str],
    patch: dict[str, object],
) -> None:
    if "CONTEST NAME" not in sheet_columns:
        return
    name = _cell_str(raw_cells.get("CONTEST NAME"))
    if name is None:
        return
    normalized = normalize_contest_name(name)
    if normalized != statement.contest_name:
        patch["contest_name"] = normalized


def _identity_patch_day_label(
    statement: ContestProblemStatement,
    raw_cells: dict[str, object],
    sheet_columns: set[str],
    patch: dict[str, object],
) -> None:
    if "DAY LABEL" not in sheet_columns:
        return
    raw = raw_cells.get("DAY LABEL")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        next_label = ""
    else:
        stripped = str(raw).strip()
        next_label = normalize_contest_name(stripped) if stripped else ""
    current = (statement.day_label or "").strip()
    if next_label != current:
        patch["day_label"] = next_label


def _identity_patch_problem_number(
    statement: ContestProblemStatement,
    raw_cells: dict[str, object],
    sheet_columns: set[str],
    patch: dict[str, object],
) -> None:
    if "PROBLEM NUMBER" not in sheet_columns:
        return
    number = _cell_int(raw_cells.get("PROBLEM NUMBER"))
    if number is not None and number > 0 and number != statement.problem_number:
        patch["problem_number"] = number


def _identity_patch_problem_code(
    statement: ContestProblemStatement,
    raw_cells: dict[str, object],
    sheet_columns: set[str],
    patch: dict[str, object],
) -> None:
    if "PROBLEM CODE" not in sheet_columns:
        return
    code = _cell_str(raw_cells.get("PROBLEM CODE"))
    if code is None:
        return
    normalized_code = code.strip().upper()
    current_code = (statement.problem_code or "").strip().upper()
    if normalized_code != current_code:
        patch["problem_code"] = normalized_code


def _identity_patch_statement_latex(
    statement: ContestProblemStatement,
    raw_cells: dict[str, object],
    sheet_columns: set[str],
    patch: dict[str, object],
) -> None:
    if "STATEMENT LATEX" not in sheet_columns:
        return
    raw = raw_cells.get("STATEMENT LATEX")
    next_latex = (
        ""
        if raw is None or (isinstance(raw, float) and pd.isna(raw))
        else str(raw)
    )
    if next_latex != (statement.statement_latex or ""):
        patch["statement_latex"] = next_latex


def _identity_patch_problem_uuid_unlinked(
    statement: ContestProblemStatement,
    raw_cells: dict[str, object],
    sheet_columns: set[str],
    patch: dict[str, object],
) -> None:
    if "PROBLEM UUID" not in sheet_columns or statement.linked_problem_id is not None:
        return
    pu = _cell_str(raw_cells.get("PROBLEM UUID"))
    if not pu:
        return
    try:
        parsed = uuid.UUID(pu)
    except ValueError:
        return
    if parsed != statement.problem_uuid:
        patch["problem_uuid"] = parsed


def _statement_identity_patch_from_row(
    statement: ContestProblemStatement,
    raw_cells: dict[str, object],
    sheet_columns: set[str],
) -> dict[str, object]:
    patch: dict[str, object] = {}
    _identity_patch_contest_year(statement, raw_cells, sheet_columns, patch)
    _identity_patch_contest_name(statement, raw_cells, sheet_columns, patch)
    _identity_patch_day_label(statement, raw_cells, sheet_columns, patch)
    _identity_patch_problem_number(statement, raw_cells, sheet_columns, patch)
    _identity_patch_problem_code(statement, raw_cells, sheet_columns, patch)
    _identity_patch_statement_latex(statement, raw_cells, sheet_columns, patch)
    _identity_patch_problem_uuid_unlinked(statement, raw_cells, sheet_columns, patch)
    return patch


def _apply_statement_identity_patch(
    statement: ContestProblemStatement,
    patch: dict[str, object],
    *,
    row_number: int,
) -> None:
    if not patch:
        return
    key = _prospective_statement_unique_key(statement, patch)
    conflict = (
        ContestProblemStatement.objects.filter(
            contest_year=key[0],
            contest_name=key[1],
            day_label=key[2],
            problem_code=key[3],
        )
        .exclude(pk=statement.pk)
        .first()
    )
    if conflict is not None:
        msg = (
            f'Row {row_number}: another statement already uses contest identity '
            f'({key[0]}, {key[1]}, day label "{key[2]}", problem code "{key[3]}"). '
            f'Existing row: "{_statement_label(conflict)}". '
            "Adjust the sheet or fix the duplicate in the database first."
        )
        raise StatementMetadataBackfillValidationError(msg)
    for field_name, value in patch.items():
        setattr(statement, field_name, value)
    try:
        statement.save()
    except IntegrityError as exc:
        err = str(exc).lower()
        if "unique" in err and "contest" in err:
            msg = (
                f'Row {row_number}: "{_statement_label(statement)}" conflicts with the unique '
                f'contest key ({key[0]}, {key[1]}, day label "{key[2]}", problem code "{key[3]}"). '
                "Another row may already use that combination."
            )
            raise StatementMetadataBackfillValidationError(msg) from exc
        raise


def _build_prepared_statement_metadata_row(
    raw_row: RawStatementMetadataRow,
    ctx: _StatementMetadataPrepareContext,
) -> PreparedStatementMetadataRow:
    statement = None
    if raw_row.statement_uuid is not None:
        statement = ctx.statements_by_statement_uuid.get(raw_row.statement_uuid)
    if statement is None and raw_row.problem_uuid is not None:
        statement = ctx.statements_by_problem_uuid.get(raw_row.problem_uuid)
    if statement is None:
        missing_uuid = raw_row.statement_uuid or raw_row.problem_uuid
        msg = f'Statement row "{missing_uuid}" was not found.'
        raise StatementMetadataBackfillValidationError(msg)
    if statement.statement_uuid in ctx.seen_statement_uuids:
        msg = (
            f"Row {raw_row.row_number}: duplicate statement rows are not allowed in one import batch."
        )
        raise StatementMetadataBackfillValidationError(msg)
    ctx.seen_statement_uuids.add(statement.statement_uuid)
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

    identity_patch = _statement_identity_patch_from_row(
        statement,
        raw_row.raw_cells,
        ctx.sheet_columns,
    )
    if identity_patch:
        _apply_statement_identity_patch(
            statement,
            identity_patch,
            row_number=raw_row.row_number,
        )
        statement.refresh_from_db()

    existing_record = _resolved_problem_for_statement(
        statement,
        records_by_uuid=ctx.records_by_uuid,
    )

    return PreparedStatementMetadataRow(
        confidence=raw_row.confidence,
        existing_record=existing_record,
        imo_slot_guess=raw_row.imo_slot_guess,
        mohs=raw_row.mohs,
        raw_topic_tags=raw_row.raw_topic_tags,
        row_number=raw_row.row_number,
        statement=statement,
        topic=raw_row.topic,
    )


def _prepare_statement_metadata_rows(
    df: pd.DataFrame,
) -> tuple[list[PreparedStatementMetadataRow], int]:
    sheet_columns = {str(column).strip() for column in df.columns}
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
    ctx = _StatementMetadataPrepareContext(
        statements_by_statement_uuid=statements_by_statement_uuid,
        statements_by_problem_uuid=statements_by_problem_uuid,
        sheet_columns=sheet_columns,
        records_by_uuid=records_by_uuid,
        seen_statement_uuids=set(),
    )
    prepared_rows = [_build_prepared_statement_metadata_row(raw_row, ctx) for raw_row in raw_rows]

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


def _upsert_statement_topic_technique(
    *,
    statement: ContestProblemStatement,
    technique: str,
    domain_list: list[str],
    replace_tags: bool,
) -> int:
    if replace_tags:
        StatementTopicTechnique.objects.create(
            statement=statement,
            technique=technique,
            domains=domain_list,
        )
        return 1

    matching_tags = list(
        StatementTopicTechnique.objects.filter(
            statement=statement,
            technique__iexact=technique,
        ).order_by("id"),
    )
    if not matching_tags:
        StatementTopicTechnique.objects.create(
            statement=statement,
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
        StatementTopicTechnique.objects.filter(pk__in=duplicate_ids).delete()

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


def sync_statement_topic_techniques(
    *,
    statement: ContestProblemStatement,
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
        StatementTopicTechnique.objects.filter(statement=statement).delete()

    touched_count = 0
    for technique, domain_list in parsed_entries:
        touched_count += _upsert_statement_topic_technique(
            statement=statement,
            technique=technique,
            domain_list=domain_list,
            replace_tags=replace_tags,
        )

    return touched_count


def _apply_prepared_row_to_statement_analytics(
    prepared_row: PreparedStatementMetadataRow,
    statement: ContestProblemStatement,
) -> None:
    """Copy sheet analytics onto the statement row (canonical CPS fields)."""
    update_fields: set[str] = set()
    if prepared_row.topic is not None and statement.topic != prepared_row.topic:
        statement.topic = prepared_row.topic
        update_fields.add("topic")
    if prepared_row.mohs is not None and statement.mohs != prepared_row.mohs:
        statement.mohs = prepared_row.mohs
        update_fields.add("mohs")
    if prepared_row.confidence is not None and statement.confidence != prepared_row.confidence:
        statement.confidence = prepared_row.confidence
        update_fields.add("confidence")
    if prepared_row.imo_slot_guess is not None and statement.imo_slot_guess != prepared_row.imo_slot_guess:
        statement.imo_slot_guess = prepared_row.imo_slot_guess
        update_fields.add("imo_slot_guess")
    if prepared_row.raw_topic_tags is not None and statement.topic_tags != prepared_row.raw_topic_tags:
        statement.topic_tags = prepared_row.raw_topic_tags
        update_fields.add("topic_tags")

    if update_fields:
        update_fields.add("updated_at")
        statement.save(update_fields=update_fields)


def _import_metadata_update_statement_analytics_only(
    prepared_row: PreparedStatementMetadataRow,
    *,
    replace_tags: bool,
    result: StatementMetadataBackfillImportResult,
) -> None:
    statement = prepared_row.statement
    _apply_prepared_row_to_statement_analytics(prepared_row, statement)

    if prepared_row.raw_topic_tags is not None:
        result.technique_count += sync_statement_topic_techniques(
            statement=statement,
            raw_topic_tags=prepared_row.raw_topic_tags,
            replace_tags=replace_tags,
        )

    result.updated_count += 1
    result.processed_count += 1


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
            msg = "Cannot create a problem row without both TOPIC and MOHS."
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


def _import_metadata_sync_statement_with_sheet_and_link(
    prepared_row: PreparedStatementMetadataRow,
    statement: ContestProblemStatement,
    record: ProblemSolveRecord,
    *,
    replace_tags: bool,
    result: StatementMetadataBackfillImportResult,
) -> None:
    """Keep ContestProblemStatement analytics aligned with the import (effective_* prefers CPS)."""
    _apply_prepared_row_to_statement_analytics(prepared_row, statement)
    _import_metadata_link_statement_and_sync(
        prepared_row,
        statement,
        record,
        replace_tags=replace_tags,
        result=result,
    )


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
        if prepared_row.existing_record is not None or (
            prepared_row.topic is not None and prepared_row.mohs is not None
        ):
            record = _import_metadata_upsert_problem_record(prepared_row, statement, result=result)
            _import_metadata_sync_statement_with_sheet_and_link(
                prepared_row,
                statement,
                record,
                replace_tags=replace_tags,
                result=result,
            )
        else:
            _import_metadata_update_statement_analytics_only(
                prepared_row,
                replace_tags=replace_tags,
                result=result,
            )

    return result
