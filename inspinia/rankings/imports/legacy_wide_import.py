# ruff: noqa: INP001
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from dataclasses import field
from decimal import Decimal
from decimal import InvalidOperation
from typing import Any

import pandas as pd
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import ImportRowIssue
from inspinia.rankings.models import School
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.models import StudentSelectionStatus
from inspinia.rankings.models import normalize_name
from inspinia.rankings.models import normalize_whitespace

STUDENT_COLUMN_TOKENS = {
    "active",
    "birthyear",
    "dateofbirth",
    "dob",
    "externalcode",
    "fullname",
    "fullnric",
    "gender",
    "legacycode",
    "maskednric",
    "name",
    "notes",
    "school",
    "schoolname",
    "state",
    "student",
    "studentname",
}

STATUS_COLUMN_TOKENS = {
    "squad",
    "team",
    "watchlist",
}

STATUS_VALUE_ALIASES = {
    "team": "team",
    "team member": "team",
    "team members": "team",
    "squad": "squad",
    "watchlist": "watchlist",
    "watch list": "watchlist",
}

AMBIGUOUS_COLUMN_RE = re.compile(r"^(status|selection)(\b|[_\s:-])", flags=re.IGNORECASE)


@dataclass(slots=True)
class LegacyWideColumnClassification:
    student_columns: list[str] = field(default_factory=list)
    assessment_columns: list[str] = field(default_factory=list)
    status_columns: list[str] = field(default_factory=list)
    ambiguous_columns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LegacyWideCellIssue:
    row_number: int
    column: str
    issue_code: str
    message: str
    raw_value: Any


@dataclass(slots=True)
class LegacyWidePreviewRow:
    row_number: int
    student_values: dict[str, Any] = field(default_factory=dict)
    assessment_values: dict[str, Any] = field(default_factory=dict)
    status_values: dict[str, Any] = field(default_factory=dict)
    ambiguous_values: dict[str, Any] = field(default_factory=dict)
    issues: list[LegacyWideCellIssue] = field(default_factory=list)


@dataclass(slots=True)
class LegacyWidePreviewResult:
    classification: LegacyWideColumnClassification
    rows: list[LegacyWidePreviewRow] = field(default_factory=list)
    issues: list[LegacyWideCellIssue] = field(default_factory=list)


@dataclass(slots=True)
class LegacyWideImportResult:
    created_students: int = 0
    updated_students: int = 0
    created_assessments: int = 0
    created_results: int = 0
    created_statuses: int = 0
    issues: int = 0
    rows: int = 0


def classify_legacy_wide_columns(
    columns: list[str] | tuple[str, ...] | pd.Index | list[object],
) -> LegacyWideColumnClassification:
    classification = LegacyWideColumnClassification()
    for column in columns:
        column_name = normalize_whitespace(str(column))
        token = _compact_token(column_name)
        if token in STUDENT_COLUMN_TOKENS:
            classification.student_columns.append(column_name)
            continue
        if token in STATUS_COLUMN_TOKENS:
            classification.status_columns.append(column_name)
            continue
        if _is_ambiguous_column(column_name, token):
            classification.ambiguous_columns.append(column_name)
            continue
        classification.assessment_columns.append(column_name)
    return classification


def preview_legacy_wide_import(
    *,
    dataframe: pd.DataFrame,
    import_batch: ImportBatch,
) -> LegacyWidePreviewResult:
    working_dataframe = dataframe.copy()
    working_dataframe.columns = [normalize_whitespace(str(column)) for column in working_dataframe.columns]
    classification = classify_legacy_wide_columns(list(working_dataframe.columns))
    preview_rows: list[LegacyWidePreviewRow] = []
    issues: list[LegacyWideCellIssue] = []

    with transaction.atomic():
        for ambiguous_column in classification.ambiguous_columns:
            issue = LegacyWideCellIssue(
                row_number=1,
                column=ambiguous_column,
                issue_code="AMBIGUOUS_COLUMN",
                message=f"Column '{ambiguous_column}' needs manual classification.",
                raw_value=None,
            )
            issues.append(issue)
            ImportRowIssue.objects.create(
                import_batch=import_batch,
                row_number=1,
                severity=ImportRowIssue.Severity.WARNING,
                issue_code=issue.issue_code,
                message=issue.message,
                raw_row_json={"column": ambiguous_column},
            )

        for row_number, raw_row in enumerate(working_dataframe.to_dict(orient="records"), start=2):
            preview_row = _build_preview_row(
                row_number=row_number,
                raw_row=raw_row,
                classification=classification,
            )
            preview_rows.append(preview_row)
            issues.extend(preview_row.issues)
            for issue in preview_row.issues:
                ImportRowIssue.objects.create(
                    import_batch=import_batch,
                    row_number=issue.row_number,
                    severity=ImportRowIssue.Severity.WARNING,
                    issue_code=issue.issue_code,
                    message=issue.message,
                    raw_row_json={"column": issue.column, "value": issue.raw_value},
                )

        import_batch.status = ImportBatch.Status.PREVIEWED
        import_batch.summary_json = {
            "classification": _classification_summary(classification),
            "issues": len(issues),
            "rows": len(preview_rows),
        }
        import_batch.save(update_fields={"status", "summary_json", "updated_at"})

    return LegacyWidePreviewResult(
        classification=classification,
        rows=preview_rows,
        issues=issues,
    )


def apply_legacy_wide_import(  # noqa: C901, PLR0912
    *,
    preview: LegacyWidePreviewResult,
    import_batch: ImportBatch,
    season_year: int,
    actor: Any | None = None,
) -> LegacyWideImportResult:
    result = LegacyWideImportResult(rows=len(preview.rows), issues=len(preview.issues))
    now = timezone.now()

    with transaction.atomic():
        for preview_row in preview.rows:
            try:
                student, created = _upsert_student(preview_row.student_values)
            except ValueError:
                result.issues += 1
                continue
            if created:
                result.created_students += 1
            else:
                result.updated_students += 1

            row_has_issue = bool(preview_row.issues)

            for column_name, raw_value in preview_row.assessment_values.items():
                cell_value = _coerce_score_value(raw_value)
                if cell_value is not None:
                    assessment, assessment_created = _get_or_create_assessment(
                        column_name=column_name,
                        season_year=season_year,
                    )
                    if assessment_created:
                        result.created_assessments += 1
                    StudentResult.objects.update_or_create(
                        student=student,
                        assessment=assessment,
                        defaults={
                            "raw_score": cell_value,
                            "imported_by": actor,
                            "imported_at": now,
                        },
                    )
                    result.created_results += 1
                    continue

                normalized_status = _normalize_status_value(raw_value)
                if normalized_status is not None:
                    StudentSelectionStatus.objects.get_or_create(
                        student=student,
                        season_year=season_year,
                        division="",
                        status=normalized_status,
                        defaults={
                            "created_by": actor,
                            "notes": f"Imported from {column_name}: {raw_value}",
                        },
                    )
                    result.created_statuses += 1
                    continue

                if not _is_blank_value(raw_value):
                    row_has_issue = True

            for column_name, raw_value in preview_row.status_values.items():
                normalized_status = _normalize_status_value(raw_value)
                if normalized_status is None:
                    if not _is_blank_value(raw_value):
                        row_has_issue = True
                    continue
                StudentSelectionStatus.objects.get_or_create(
                    student=student,
                    season_year=season_year,
                    division="",
                    status=normalized_status,
                    defaults={
                        "created_by": actor,
                        "notes": f"Imported from {column_name}: {raw_value}",
                    },
                )
                result.created_statuses += 1

            if row_has_issue:
                result.issues += 1

        import_batch.status = (
            ImportBatch.Status.PARTIAL if result.issues else ImportBatch.Status.APPLIED
        )
        import_batch.summary_json = {
            "created_students": result.created_students,
            "updated_students": result.updated_students,
            "created_assessments": result.created_assessments,
            "created_results": result.created_results,
            "created_statuses": result.created_statuses,
            "issues": result.issues,
            "rows": result.rows,
        }
        import_batch.save(update_fields={"status", "summary_json", "updated_at"})

    return result


def _build_preview_row(
    *,
    row_number: int,
    raw_row: dict[str, Any],
    classification: LegacyWideColumnClassification,
) -> LegacyWidePreviewRow:
    preview_row = LegacyWidePreviewRow(row_number=row_number)

    for column_name in classification.student_columns:
        preview_row.student_values[column_name] = raw_row.get(column_name)

    for column_name in classification.assessment_columns:
        raw_value = raw_row.get(column_name)
        preview_row.assessment_values[column_name] = raw_value
        if _is_blank_value(raw_value):
            continue
        if _coerce_score_value(raw_value) is None and _normalize_status_value(raw_value) is None:
            preview_row.issues.append(
                LegacyWideCellIssue(
                    row_number=row_number,
                    column=column_name,
                    issue_code="UNRECOGNIZED_ASSESSMENT_VALUE",
                    message=(
                        f"Row {row_number}, column '{column_name}' has an unrecognized value "
                        f"{raw_value!r}."
                    ),
                    raw_value=raw_value,
                ),
            )

    for column_name in classification.status_columns:
        raw_value = raw_row.get(column_name)
        preview_row.status_values[column_name] = raw_value
        if _is_blank_value(raw_value):
            continue
        if _normalize_status_value(raw_value) is None:
            preview_row.issues.append(
                LegacyWideCellIssue(
                    row_number=row_number,
                    column=column_name,
                    issue_code="UNRECOGNIZED_STATUS_VALUE",
                    message=(
                        f"Row {row_number}, column '{column_name}' has an unrecognized value "
                        f"{raw_value!r}."
                    ),
                    raw_value=raw_value,
                ),
            )

    for column_name in classification.ambiguous_columns:
        preview_row.ambiguous_values[column_name] = raw_row.get(column_name)

    if _student_payload_empty(preview_row.student_values):
        preview_row.issues.append(
            LegacyWideCellIssue(
                row_number=row_number,
                column="full_name",
                issue_code="MISSING_STUDENT_NAME",
                message=f"Row {row_number} is missing a student name.",
                raw_value=None,
            ),
        )

    return preview_row


def _classification_summary(
    classification: LegacyWideColumnClassification,
) -> dict[str, list[str]]:
    return {
        "student_columns": classification.student_columns,
        "assessment_columns": classification.assessment_columns,
        "status_columns": classification.status_columns,
        "ambiguous_columns": classification.ambiguous_columns,
    }


def _is_ambiguous_column(column_name: str, compact_token: str) -> bool:
    if compact_token in STUDENT_COLUMN_TOKENS or compact_token in STATUS_COLUMN_TOKENS:
        return False
    return bool(AMBIGUOUS_COLUMN_RE.match(column_name))


def _compact_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_whitespace(value).casefold())


def _coerce_score_value(value: Any) -> Decimal | None:  # noqa: PLR0911
    if _is_blank_value(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    if isinstance(value, str):
        text = normalize_whitespace(value).replace(",", "")
        if not text:
            return None
        try:
            return Decimal(text).quantize(Decimal("0.01"))
        except InvalidOperation:
            return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _normalize_status_value(value: Any) -> str | None:  # noqa: PLR0911
    if _is_blank_value(value):
        return None
    text = normalize_whitespace(str(value)).casefold()
    if not text:
        return None
    if text in STATUS_VALUE_ALIASES:
        return STATUS_VALUE_ALIASES[text]

    compact = re.sub(r"[^a-z0-9]+", " ", text).strip()
    if compact.startswith("team"):
        return "team"
    if compact.startswith("squad"):
        return "squad"
    if compact.startswith(("watch list", "watchlist")):
        return "watchlist"
    return None


def _student_payload_empty(student_values: dict[str, Any]) -> bool:
    return _student_name_value(student_values) is None


def _upsert_student(student_values: dict[str, Any]) -> tuple[Student, bool]:  # noqa: C901
    full_name = _student_name_value(student_values)
    if full_name is None:
        msg = "Student rows require a full name."
        raise ValueError(msg)

    external_code = _student_text_value(student_values.get("external_code"))
    legacy_code = _student_text_value(student_values.get("legacy_code"))
    birth_year = _student_int_value(student_values.get("birth_year"))

    student = None
    if external_code:
        student = Student.objects.filter(external_code=external_code.upper()).first()
    if student is None and full_name and birth_year is not None:
        matches = list(
            Student.objects.filter(
                normalized_name=normalize_name(full_name),
                birth_year=birth_year,
            ).order_by("id"),
        )
        if len(matches) == 1:
            student = matches[0]
    if student is None and full_name:
        matches = list(Student.objects.filter(normalized_name=normalize_name(full_name)).order_by("id"))
        if len(matches) == 1:
            student = matches[0]

    payload = {
        "full_name": full_name,
        "birth_year": birth_year,
        "school": _resolve_school(student_values.get("school")),
        "state": _student_text_value(student_values.get("state")) or "",
        "masked_nric": _student_text_value(student_values.get("masked_nric")) or "",
        "full_nric": _student_text_value(student_values.get("full_nric")) or "",
        "external_code": external_code or "",
        "legacy_code": legacy_code or "",
        "gender": _normalize_gender_value(student_values.get("gender")),
        "active": _student_bool_value(student_values.get("active"), default=True),
        "notes": _student_text_value(student_values.get("notes")) or "",
    }

    if student is None:
        return Student.objects.create(**payload), True

    update_fields: set[str] = set()
    for field_name, field_value in payload.items():
        if field_name == "active":
            if field_value != student.active:
                student.active = field_value
                update_fields.add(field_name)
            continue
        if getattr(student, field_name) != field_value:
            setattr(student, field_name, field_value)
            update_fields.add(field_name)

    if update_fields:
        student.save(update_fields=update_fields | {"updated_at"})
    return student, False


def _resolve_school(value: Any) -> School | None:
    school_name = _student_text_value(value)
    if not school_name:
        return None
    normalized_name = normalize_name(school_name)
    school, _created = School.objects.get_or_create(
        normalized_name=normalized_name,
        defaults={"name": school_name},
    )
    return school


def _get_or_create_assessment(
    *,
    column_name: str,
    season_year: int,
) -> tuple[Assessment, bool]:
    code = _assessment_code_for_column(column_name)
    assessment = Assessment.objects.filter(code=code, season_year=season_year).first()
    if assessment is not None:
        return assessment, False

    return (
        Assessment.objects.create(
            code=code,
            display_name=normalize_whitespace(column_name),
            season_year=season_year,
            category=Assessment.Category.OTHER,
            result_type=Assessment.ResultType.SCORE,
        ),
        True,
    )


def _assessment_code_for_column(column_name: str) -> str:
    slug = slugify(normalize_whitespace(column_name), allow_unicode=False)
    if not slug:
        slug = f"ASSESSMENT-{hashlib.blake2s(column_name.encode('utf-8'), digest_size=4).hexdigest()}"
    return slug.replace("-", "_").upper()[:32]


def _student_name_value(student_values: dict[str, Any]) -> str | None:
    for key in ("full_name", "name", "student_name", "student"):
        value = _student_text_value(student_values.get(key))
        if value:
            return value
    return None


def _student_text_value(value: Any) -> str | None:
    if _is_blank_value(value):
        return None
    text = normalize_whitespace(str(value))
    return text or None


def _student_int_value(value: Any) -> int | None:
    if _is_blank_value(value):
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _student_bool_value(value: Any, *, default: bool) -> bool:
    if _is_blank_value(value):
        return default
    if isinstance(value, bool):
        return value
    text = normalize_whitespace(str(value)).casefold()
    if text in {"1", "true", "yes", "y", "active"}:
        return True
    if text in {"0", "false", "no", "n", "inactive"}:
        return False
    return default


def _normalize_gender_value(value: Any) -> str:
    if _is_blank_value(value):
        return ""
    text = normalize_whitespace(str(value)).casefold().replace("-", "_")
    valid_values = {choice.value for choice in Student.Gender}
    return text if text in valid_values else ""


def _is_blank_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return bool(isinstance(value, str) and not normalize_whitespace(value))
