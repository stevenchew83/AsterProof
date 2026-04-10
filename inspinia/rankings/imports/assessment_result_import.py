# ruff: noqa: INP001
"""Shared logic for previewing and applying assessment result imports."""

from __future__ import annotations

import io
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import BinaryIO

import pandas as pd
from django.db import transaction
from django.utils import timezone

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import ImportRowIssue
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.models import normalize_whitespace

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pandas import Series

ASSESSMENT_RESULT_LOGICAL_COLUMNS = (
    "student_identifier",
    "raw_score",
    "medal",
    "band",
    "status_text",
    "remarks",
    "source_url",
)
DEFAULT_ASSESSMENT_RESULT_COLUMN_MAP = {
    logical_name: logical_name for logical_name in ASSESSMENT_RESULT_LOGICAL_COLUMNS
}
PREVIEW_STATUS_MATCHED = "matched"
PREVIEW_STATUS_MISSING_STUDENT = "missing_student"
PREVIEW_STATUS_INVALID = "invalid"
ISSUE_CODE_MISSING_STUDENT = "missing_student"
ISSUE_CODE_INVALID = "invalid"
SCORE_QUANTIZER = Decimal("0.01")


class AssessmentResultImportValidationError(ValueError):
    """Raised when a result workbook cannot be parsed reliably."""


@dataclass(slots=True)
class PreparedAssessmentResultRow:
    row_number: int
    status: str
    student_identifier: str
    student_id: int | None
    raw_score: Decimal | None
    medal: str
    band: str
    status_text: str
    remarks: str
    source_url: str
    issue_code: str | None = None
    issue_message: str | None = None
    raw_row_json: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AssessmentResultImportPreviewResult:
    total_rows: int = 0
    matched_count: int = 0
    missing_student_count: int = 0
    invalid_count: int = 0
    rows: list[PreparedAssessmentResultRow] = field(default_factory=list)


@dataclass(slots=True)
class AssessmentResultImportApplyResult:
    total_rows: int = 0
    matched_count: int = 0
    missing_student_count: int = 0
    invalid_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    rows: list[PreparedAssessmentResultRow] = field(default_factory=list)

    @property
    def upserted_count(self) -> int:
        return self.created_count + self.updated_count


@dataclass(slots=True)
class _StudentResolution:
    student: Student | None
    status: str
    issue_message: str | None = None


def assessment_result_dataframe_from_excel(source: Path | str | BinaryIO | bytes) -> pd.DataFrame:
    """Load an Excel workbook and normalize its column labels."""
    dataframe = _read_tabular_source(source, prefer_excel=True)
    return _normalize_dataframe_columns(dataframe)


def assessment_result_dataframe_from_csv(source: Path | str | BinaryIO | bytes) -> pd.DataFrame:
    """Load a CSV workbook and normalize its column labels."""
    dataframe = _read_tabular_source(source, prefer_excel=False)
    return _normalize_dataframe_columns(dataframe)


def assessment_result_dataframe_from_source(source: Path | str | BinaryIO | bytes | pd.DataFrame) -> pd.DataFrame:
    """Load CSV/XLSX-like tabular data into a normalized dataframe."""
    if isinstance(source, pd.DataFrame):
        return _normalize_dataframe_columns(source.copy())

    return _normalize_dataframe_columns(_read_tabular_source(source))


def preview_assessment_result_import(
    df: pd.DataFrame,
    *,
    batch: ImportBatch,
    assessment: Assessment,
    column_map: Mapping[str, str] | None = None,
    source_file_name: str | None = None,
) -> AssessmentResultImportPreviewResult:
    prepared_rows = prepare_assessment_result_rows(df, column_map=column_map)
    result = AssessmentResultImportPreviewResult(rows=prepared_rows)
    _finalize_preview(
        batch=batch,
        assessment=assessment,
        result=result,
        column_map=column_map,
        source_file_name=source_file_name,
    )
    return result


def apply_assessment_result_import(  # noqa: PLR0913
    df: pd.DataFrame,
    *,
    batch: ImportBatch,
    assessment: Assessment,
    imported_by: Any | None = None,
    column_map: Mapping[str, str] | None = None,
    source_file_name: str | None = None,
) -> AssessmentResultImportApplyResult:
    prepared_rows = prepare_assessment_result_rows(df, column_map=column_map)
    result = AssessmentResultImportApplyResult(rows=prepared_rows)
    _apply_rows(
        batch=batch,
        assessment=assessment,
        imported_by=imported_by,
        result=result,
        column_map=column_map,
        source_file_name=source_file_name,
    )
    return result


def preview_assessment_results_dataframe(
    df: pd.DataFrame,
    *,
    batch: ImportBatch,
    assessment: Assessment,
    column_map: Mapping[str, str] | None = None,
    source_file_name: str | None = None,
) -> AssessmentResultImportPreviewResult:
    return preview_assessment_result_import(
        df,
        batch=batch,
        assessment=assessment,
        column_map=column_map,
        source_file_name=source_file_name,
    )


def apply_assessment_results_dataframe(  # noqa: PLR0913
    df: pd.DataFrame,
    *,
    batch: ImportBatch,
    assessment: Assessment,
    imported_by: Any | None = None,
    column_map: Mapping[str, str] | None = None,
    source_file_name: str | None = None,
) -> AssessmentResultImportApplyResult:
    return apply_assessment_result_import(
        df,
        batch=batch,
        assessment=assessment,
        imported_by=imported_by,
        column_map=column_map,
        source_file_name=source_file_name,
    )


def import_assessment_result_dataframe(  # noqa: PLR0913
    df: pd.DataFrame,
    *,
    batch: ImportBatch,
    assessment: Assessment,
    imported_by: Any | None = None,
    column_map: Mapping[str, str] | None = None,
    source_file_name: str | None = None,
) -> AssessmentResultImportApplyResult:
    return apply_assessment_result_import(
        df,
        batch=batch,
        assessment=assessment,
        imported_by=imported_by,
        column_map=column_map,
        source_file_name=source_file_name,
    )


def prepare_assessment_result_rows(
    df: pd.DataFrame,
    *,
    column_map: Mapping[str, str] | None = None,
) -> list[PreparedAssessmentResultRow]:
    normalized_df = _normalize_dataframe_columns(df.copy())
    resolved_column_map = _normalize_column_map(column_map)
    student_identifier_column = resolved_column_map["student_identifier"]
    if student_identifier_column not in normalized_df.columns:
        msg = (
            f"Missing required column: {student_identifier_column}. "
            f"Found columns: {list(normalized_df.columns)}"
        )
        raise AssessmentResultImportValidationError(msg)

    student_cache: dict[str, _StudentResolution] = {}
    prepared_rows: list[PreparedAssessmentResultRow] = []

    for row_number, (_, row) in enumerate(normalized_df.iterrows(), start=2):
        row_data = _json_safe_mapping(row.to_dict())
        student_identifier = _cell_text(_row_value(row, resolved_column_map, "student_identifier"))
        if not student_identifier:
            prepared_rows.append(
                PreparedAssessmentResultRow(
                    row_number=row_number,
                    status=PREVIEW_STATUS_MISSING_STUDENT,
                    student_identifier="",
                    student_id=None,
                    raw_score=None,
                    medal="",
                    band="",
                    status_text="",
                    remarks="",
                    source_url="",
                    issue_code=ISSUE_CODE_MISSING_STUDENT,
                    issue_message="Missing student identifier.",
                    raw_row_json=row_data,
                ),
            )
            continue

        resolution = _resolve_student(student_identifier, student_cache=student_cache)
        if resolution.student is None:
            prepared_rows.append(
                PreparedAssessmentResultRow(
                    row_number=row_number,
                    status=resolution.status,
                    student_identifier=student_identifier,
                    student_id=None,
                    raw_score=None,
                    medal="",
                    band="",
                    status_text="",
                    remarks="",
                    source_url="",
                    issue_code=ISSUE_CODE_MISSING_STUDENT
                    if resolution.status == PREVIEW_STATUS_MISSING_STUDENT
                    else ISSUE_CODE_INVALID,
                    issue_message=resolution.issue_message,
                    raw_row_json=row_data,
                ),
            )
            continue

        raw_score, raw_score_error = _parse_decimal_cell(_row_value(row, resolved_column_map, "raw_score"))
        if raw_score_error is not None:
            prepared_rows.append(
                PreparedAssessmentResultRow(
                    row_number=row_number,
                    status=PREVIEW_STATUS_INVALID,
                    student_identifier=student_identifier,
                    student_id=resolution.student.id,
                    raw_score=None,
                    medal="",
                    band="",
                    status_text="",
                    remarks="",
                    source_url="",
                    issue_code=ISSUE_CODE_INVALID,
                    issue_message=raw_score_error,
                    raw_row_json=row_data,
                ),
            )
            continue

        prepared_rows.append(
            PreparedAssessmentResultRow(
                row_number=row_number,
                status=PREVIEW_STATUS_MATCHED,
                student_identifier=student_identifier,
                student_id=resolution.student.id,
                raw_score=raw_score,
                medal=_optional_whitespace_text(_row_value(row, resolved_column_map, "medal")),
                band=_optional_whitespace_text(_row_value(row, resolved_column_map, "band")),
                status_text=_optional_whitespace_text(_row_value(row, resolved_column_map, "status_text")),
                remarks=_optional_text(_row_value(row, resolved_column_map, "remarks"), collapse_whitespace=False),
                source_url=_optional_whitespace_text(_row_value(row, resolved_column_map, "source_url")),
                raw_row_json=row_data,
            ),
        )

    return prepared_rows


def _apply_rows(  # noqa: PLR0913
    *,
    batch: ImportBatch,
    assessment: Assessment,
    imported_by: Any | None,
    result: AssessmentResultImportApplyResult,
    column_map: Mapping[str, str] | None,
    source_file_name: str | None,
) -> None:
    resolved_source_file_name = _coerce_source_file_name(source_file_name, batch=batch)
    result.total_rows = len(result.rows)
    result.matched_count = sum(1 for row in result.rows if row.status == PREVIEW_STATUS_MATCHED)
    result.missing_student_count = sum(1 for row in result.rows if row.status == PREVIEW_STATUS_MISSING_STUDENT)
    result.invalid_count = sum(1 for row in result.rows if row.status == PREVIEW_STATUS_INVALID)

    with transaction.atomic():
        for row in result.rows:
            if row.status != PREVIEW_STATUS_MATCHED:
                continue

            _, created = StudentResult.objects.update_or_create(
                student_id=row.student_id,
                assessment=assessment,
                defaults={
                    "raw_score": row.raw_score,
                    "medal": row.medal,
                    "band": row.band,
                    "status_text": row.status_text,
                    "remarks": row.remarks,
                    "source_url": row.source_url,
                    "source_file_name": resolved_source_file_name,
                    "imported_by": imported_by,
                    "imported_at": timezone.now(),
                },
            )
            if created:
                result.created_count += 1
            else:
                result.updated_count += 1

        _save_batch_result(
            batch=batch,
            summary=_build_summary(
                stage="apply",
                assessment=assessment,
                result=result,
                column_map=column_map,
                source_file_name=resolved_source_file_name,
            ),
            status=_apply_batch_status(result),
        )


def _finalize_preview(
    *,
    batch: ImportBatch,
    assessment: Assessment,
    result: AssessmentResultImportPreviewResult,
    column_map: Mapping[str, str] | None,
    source_file_name: str | None,
) -> None:
    result.total_rows = len(result.rows)
    result.matched_count = sum(1 for row in result.rows if row.status == PREVIEW_STATUS_MATCHED)
    result.missing_student_count = sum(1 for row in result.rows if row.status == PREVIEW_STATUS_MISSING_STUDENT)
    result.invalid_count = sum(1 for row in result.rows if row.status == PREVIEW_STATUS_INVALID)

    issues: list[ImportRowIssue] = []
    for row in result.rows:
        if row.status == PREVIEW_STATUS_MATCHED:
            continue
        issues.append(
            ImportRowIssue(
                import_batch=batch,
                row_number=row.row_number,
                severity="warning" if row.status == PREVIEW_STATUS_MISSING_STUDENT else "error",
                issue_code=row.issue_code or row.status,
                message=row.issue_message or "Unable to preview row.",
                raw_row_json=row.raw_row_json,
            ),
        )

    with transaction.atomic():
        batch.row_issues.all().delete()
        if issues:
            ImportRowIssue.objects.bulk_create(issues)
        _save_batch_result(
            batch=batch,
            summary=_build_summary(
                stage="preview",
                assessment=assessment,
                result=result,
                column_map=column_map,
                source_file_name=_coerce_source_file_name(source_file_name, batch=batch),
            ),
            status=ImportBatch.Status.PREVIEWED,
        )


def _save_batch_result(*, batch: ImportBatch, summary: dict[str, Any], status: str) -> None:
    batch.summary_json = summary
    batch.status = status
    batch.save(update_fields={"summary_json", "status"})


def _build_summary(
    *,
    stage: str,
    assessment: Assessment,
    result: AssessmentResultImportPreviewResult | AssessmentResultImportApplyResult,
    column_map: Mapping[str, str] | None,
    source_file_name: str,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "assessment_id": assessment.id,
        "assessment_code": assessment.code,
        "assessment_season_year": assessment.season_year,
        "total_rows": result.total_rows,
        "matched_count": result.matched_count,
        "missing_student_count": result.missing_student_count,
        "invalid_count": result.invalid_count,
        "created_count": getattr(result, "created_count", 0),
        "updated_count": getattr(result, "updated_count", 0),
        "upserted_count": getattr(result, "upserted_count", 0),
        "source_file_name": source_file_name,
        "column_map": _normalize_column_map(column_map),
    }


def _apply_batch_status(result: AssessmentResultImportApplyResult) -> str:
    if result.matched_count == 0:
        return ImportBatch.Status.FAILED
    if result.missing_student_count or result.invalid_count:
        return ImportBatch.Status.PARTIAL
    return ImportBatch.Status.APPLIED


def _coerce_source_file_name(source_file_name: str | None, *, batch: ImportBatch) -> str:
    if source_file_name is not None:
        cleaned = normalize_whitespace(source_file_name)
        if cleaned:
            return cleaned
    return normalize_whitespace(batch.original_filename)


def _normalize_column_map(column_map: Mapping[str, str] | None) -> dict[str, str]:
    normalized = dict(DEFAULT_ASSESSMENT_RESULT_COLUMN_MAP)
    if column_map is None:
        return normalized

    for logical_name in ASSESSMENT_RESULT_LOGICAL_COLUMNS:
        raw_column_name = column_map.get(logical_name)
        if raw_column_name is None:
            continue
        normalized[logical_name] = str(raw_column_name).strip()
    return normalized


def _normalize_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(column).strip() for column in df.columns]
    return df


def _read_tabular_source(source: Path | str | BinaryIO | bytes, *, prefer_excel: bool = True) -> pd.DataFrame:  # noqa: PLR0911
    if isinstance(source, bytes):
        buffer = io.BytesIO(source)
        return _read_tabular_source(buffer, prefer_excel=prefer_excel)

    if isinstance(source, (str, Path)):
        path = Path(source)
        suffix = path.suffix.lower()
        if suffix in {".csv", ".tsv"}:
            return pd.read_csv(path)
        return pd.read_excel(path)

    if prefer_excel:
        try:
            return pd.read_excel(source)
        except (ValueError, TypeError, OSError):
            _rewind_source(source)
            return pd.read_csv(source)

    try:
        return pd.read_csv(source)
    except (ValueError, TypeError, OSError):
        _rewind_source(source)
        return pd.read_excel(source)


def _rewind_source(source: BinaryIO) -> None:
    seek = getattr(source, "seek", None)
    if callable(seek):
        with suppress(Exception):
            seek(0)


def _resolve_student(identifier: str, *, student_cache: dict[str, _StudentResolution]) -> _StudentResolution:
    cache_key = identifier.casefold()
    cached = student_cache.get(cache_key)
    if cached is not None:
        return cached

    for lookup in ("external_code", "legacy_code", "full_name"):
        matches = list(Student.objects.filter(**{f"{lookup}__iexact": identifier}).order_by("id")[:2])
        if len(matches) == 1:
            resolution = _StudentResolution(student=matches[0], status=PREVIEW_STATUS_MATCHED)
            student_cache[cache_key] = resolution
            return resolution
        if len(matches) > 1:
            resolution = _StudentResolution(
                student=None,
                status=PREVIEW_STATUS_INVALID,
                issue_message=f"Student identifier '{identifier}' is ambiguous.",
            )
            student_cache[cache_key] = resolution
            return resolution

    if identifier.isdigit():
        student = Student.objects.filter(pk=int(identifier)).first()
        if student is not None:
            resolution = _StudentResolution(student=student, status=PREVIEW_STATUS_MATCHED)
            student_cache[cache_key] = resolution
            return resolution

    resolution = _StudentResolution(
        student=None,
        status=PREVIEW_STATUS_MISSING_STUDENT,
        issue_message=f"Student identifier '{identifier}' did not match any student.",
    )
    student_cache[cache_key] = resolution
    return resolution


def _parse_decimal_cell(value: Any) -> tuple[Decimal | None, str | None]:
    text = _cell_text(value)
    if text is None:
        return (None, None)

    cleaned = text.replace(",", "")
    try:
        return (Decimal(cleaned).quantize(SCORE_QUANTIZER), None)
    except (InvalidOperation, ValueError):
        return (None, f"Invalid raw_score '{text}'.")


def _cell_text(value: Any) -> str | None:
    if _is_missing_value(value):
        return None
    text = str(value).strip()
    return text or None


def _optional_whitespace_text(value: Any) -> str:
    text = _cell_text(value)
    if text is None:
        return ""
    return normalize_whitespace(text)


def _optional_text(value: Any, *, collapse_whitespace: bool) -> str:
    text = _cell_text(value)
    if text is None:
        return ""
    if collapse_whitespace:
        return normalize_whitespace(text)
    return text


def _row_value(row: Series, column_map: Mapping[str, str], logical_name: str) -> Any:
    column_name = column_map.get(logical_name)
    if not column_name or column_name not in row.index:
        return None
    return row.get(column_name)


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return pd.isna(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _json_safe_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in mapping.items()}


def _json_safe_value(value: Any) -> Any:  # noqa: PLR0911
    if _is_missing_value(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        with suppress(Exception):
            return _json_safe_value(value.item())
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    return value


__all__ = [  # noqa: RUF022
    "ASSESSMENT_RESULT_LOGICAL_COLUMNS",
    "AssessmentResultImportApplyResult",
    "AssessmentResultImportPreviewResult",
    "AssessmentResultImportValidationError",
    "DEFAULT_ASSESSMENT_RESULT_COLUMN_MAP",
    "ISSUE_CODE_INVALID",
    "ISSUE_CODE_MISSING_STUDENT",
    "PREVIEW_STATUS_INVALID",
    "PREVIEW_STATUS_MATCHED",
    "PREVIEW_STATUS_MISSING_STUDENT",
    "PreparedAssessmentResultRow",
    "apply_assessment_result_import",
    "apply_assessment_results_dataframe",
    "assessment_result_dataframe_from_csv",
    "assessment_result_dataframe_from_excel",
    "assessment_result_dataframe_from_source",
    "import_assessment_result_dataframe",
    "prepare_assessment_result_rows",
    "preview_assessment_result_import",
    "preview_assessment_results_dataframe",
]
