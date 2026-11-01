"""Adapters for the olympiad history sheet and category result lists.

Only reviewed columns enter the prepared payload. In particular, identity
numbers, free-form notes and unlabelled school columns are never retained.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from dataclasses import field
from decimal import Decimal
from decimal import InvalidOperation

from django.db import transaction
from django.utils import timezone

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import School
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.models import normalize_name
from inspinia.rankings.models import normalize_whitespace

MAX_SHEET_BYTES = 2_000_000
MAX_SHEET_ROWS = 2000
MAX_SCORE = Decimal("100000000")
SCORE_PRECISION = -2
MIN_BIRTH_YEAR = 1900
MAX_NAME_LENGTH = 255
MAX_CATEGORY_LENGTH = 32
RESULT_LIST_WIDTH = 4
SHEET_KIND = "olympiad_sheet_v1"
HISTORY_HEADERS = (
    "NAME",
    "Birthyear",
    "Age",
    "NRIC",
    "2026-08",
    "SST 2026",
    "APMO 2026",
    "TST 2026",
    "CST2026",
    "2026-03",
    "2026-02",
    "JOM 2026-01",
    "2025 ENTRANCE TEST",
    "2025",
    "2024",
    "MMOS ENTRANCE TEST",
    "SST 2025",
    "CST 2025",
    "JOM2025",
    "IMONST2 2024",
    "APMO QUALIFIER",
    "TST POINT 84 PTS",
    "MOCK IMO 2025",
    "TOTAL",
    "APMO2025",
    "IMONST2 2025",
    "x",
    "",
    "2026 KMC",
    "2026 KMC",
    "2026 KMC",
    "IMONST2025",
    "IMONST1_2025",
    "IMONST1_2024",
    "IMONST2_2024",
    "2024",
    "x",
    "x",
    "SASMO_2024",
    "KMC2025",
)
# Source positions are intentional: the supplied sheet has duplicate headers.
# index, assessment code, label, season, destination field
HISTORY_COLUMNS = (
    (4, "SELECTION_2026_08", "Selection August 2026", 2026, "status_text"),
    (5, "SST_2026", "SST 2026", 2026, "raw_score"),
    (6, "APMO_2026", "APMO 2026", 2026, "raw_score"),
    (7, "TST_2026", "TST 2026", 2026, "raw_score"),
    (8, "CST_2026", "CST 2026", 2026, "raw_score"),
    (9, "SELECTION_2026_03", "Selection March 2026", 2026, "status_text"),
    (10, "SELECTION_2026_02", "Selection February 2026", 2026, "status_text"),
    (11, "JOM_2026_01", "JOM January 2026", 2026, "raw_score"),
    (12, "ENTRANCE_GROUP_2025", "Entrance test group 2025", 2025, "status_text"),
    (13, "SELECTION_2025", "Selection 2025", 2025, "status_text"),
    (14, "SELECTION_2024_A", "2024 group (source column 15)", 2024, "status_text"),
    (16, "SST_2025", "SST 2025", 2025, "raw_score"),
    (17, "CST_2025", "CST 2025", 2025, "raw_score"),
    (18, "JOM_2025", "JOM 2025", 2025, "raw_score"),
    (19, "IMONST2_2024", "IMONST2 2024", 2024, "raw_score"),
    (22, "MOCK_IMO_2025", "Mock IMO 2025", 2025, "raw_score"),
    (24, "APMO_2025", "APMO 2025", 2025, "raw_score"),
    (25, "IMONST2_2025", "IMONST2 2025", 2025, "band"),
    (29, "KMC_2026", "KMC 2026", 2026, "band"),
    (30, "KMC_2026", "KMC 2026", 2026, "medal"),
    (31, "IMONST_GROUP_2025", "IMONST 2025 category (round unspecified)", 2025, "band"),
    (32, "IMONST1_2025", "IMONST1 2025", 2025, "medal"),
    (33, "IMONST1_2024", "IMONST1 2024", 2024, "medal"),
    (34, "IMONST2_2024", "IMONST2 2024", 2024, "medal"),
    (35, "SELECTION_2024_B", "2024 group (source column 36)", 2024, "status_text"),
    (38, "SASMO_2024", "SASMO 2024", 2024, "medal"),
    (39, "KMC_2025", "KMC 2025", 2025, "medal"),
)
HISTORY_EXCLUSIONS = (
    "Age: derived from birth year.",
    "NRIC: excluded from this import and its stored preview.",
    "MMOS ENTRANCE TEST, APMO QUALIFIER, TST POINT 84 PTS: year is unspecified; held for manual mapping.",
    "TOTAL: existing aggregate excluded to avoid treating it as another contest.",
    "Unlabelled school columns and free-form x columns: held for manual mapping.",
    "School columns associated with IMONST2 2025 and KMC 2026 are retained with those results.",
)


@dataclass
class ParsedSheet:
    label: str
    rows: list[dict] = field(default_factory=list)
    mappings: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_rows: int = 0


def _score(value: str) -> str:
    try:
        score = Decimal(value)
    except InvalidOperation as exc:
        msg = "Score must be a number."
        raise ValueError(msg) from exc
    if not score.is_finite() or score < 0 or score >= MAX_SCORE or score.as_tuple().exponent < SCORE_PRECISION:
        msg = "Score must be a nonnegative number with at most two decimal places."
        raise ValueError(msg)
    return str(score)


def _result(*, code: str, label: str, year: int, order: int) -> dict:
    return {
        "code": code,
        "label": label,
        "year": year,
        "order": order,
        "raw_score": None,
        "medal": "",
        "band": "",
        "status_text": "",
        "remarks": "",
    }


def _history_row(cells: list[str], number: int, parsed: ParsedSheet) -> dict:  # noqa: C901
    birth_year = None
    if cells[1]:
        if not cells[1].isdigit() or not MIN_BIRTH_YEAR <= int(cells[1]) <= timezone.now().year:
            msg = f"Row {number}: invalid birth year."
            raise ValueError(msg)
        birth_year = int(cells[1])
    results = {}
    for index, code, label, year, destination in HISTORY_COLUMNS:
        value = cells[index]
        if not value or value.upper() in {"#N/A", "N/A", "-"}:
            continue
        if "http://" in value.lower() or "https://" in value.lower():
            parsed.warnings.append(f"Row {number}, column {index + 1}: link omitted from group history.")
            continue
        if destination == "raw_score":
            try:
                value = _score(value)
            except ValueError as exc:
                msg = f"Row {number}, column {index + 1}: {exc}"
                raise ValueError(msg) from exc
        elif len(value) > (64 if destination == "status_text" else 32):
            msg = f"Row {number}, column {index + 1}: value is too long."
            raise ValueError(msg)
        result = results.setdefault(code, _result(code=code, label=label, year=year, order=index))
        result[destination] = value
    for code, school_index in (("IMONST2_2025", 26), ("KMC_2026", 28)):
        if code in results and cells[school_index]:
            results[code]["remarks"] = f"School in source result: {cells[school_index][:255]}"
    return {"name": cells[0], "birth_year": birth_year, "school": "", "results": list(results.values())}


def _result_list_row(cells: list[str], number: int, year: int) -> dict:
    if not cells[3] or len(cells[3]) > MAX_CATEGORY_LENGTH or len(cells[1]) > MAX_NAME_LENGTH:
        msg = f"Row {number}: provide a category (at most 32 characters) and a school (at most 255 characters)."
        raise ValueError(msg)
    result = _result(code=f"IMONST2_{year}", label=f"IMONST2 {year}", year=year, order=0)
    try:
        result.update(raw_score=_score(cells[2]), band=cells[3].upper())
    except ValueError as exc:
        msg = f"Row {number}: {exc}"
        raise ValueError(msg) from exc
    if cells[1]:
        result["remarks"] = f"School in source result: {cells[1]}"
    return {"name": cells[0], "birth_year": None, "school": cells[1], "results": [result]}


def parse_olympiad_sheet(text: str) -> ParsedSheet:  # noqa: C901, PLR0912
    if len(text.encode("utf-8")) > MAX_SHEET_BYTES:
        msg = "The sheet must be no larger than 2 MB."
        raise ValueError(msg)
    text = text.lstrip("\ufeff")
    delimiter = "\t" if "\t" in text.partition("\n")[0] else ","
    try:
        table = list(csv.reader(io.StringIO(text), delimiter=delimiter, strict=True))
    except csv.Error as exc:
        msg = "The sheet is not valid tab-separated text or CSV."
        raise ValueError(msg) from exc
    if not table or len(table) > MAX_SHEET_ROWS + 1:
        msg = f"Provide a header and at most {MAX_SHEET_ROWS} source rows."
        raise ValueError(msg)
    header = [normalize_whitespace(cell) for cell in table[0]]
    is_history = tuple(header) == HISTORY_HEADERS
    year_match = re.fullmatch(r"Total IMONST2 (20\d{2})", header[2]) if len(header) == RESULT_LIST_WIDTH else None
    is_results = bool(year_match and header[:2] == ["FULL NAME", "SCHOOL NAME"])
    if not is_history and not is_results:
        msg = "Use the original 40-column history header or the four-column IMONST2 result-list header."
        raise ValueError(msg)
    parsed = ParsedSheet(label="Olympiad student history" if is_history else header[2])
    if is_history:
        parsed.mappings = [
            f"Column {i + 1}: {HISTORY_HEADERS[i]} → {label} / {dest}" for i, _, label, _, dest in HISTORY_COLUMNS
        ]
        parsed.exclusions = list(HISTORY_EXCLUSIONS)
    else:
        parsed.mappings = [
            "Full name → student",
            "School → student school when empty",
            "Total → raw score",
            "Level/Grade/category → category",
        ]
    seen = set()
    for number, raw_cells in enumerate(table[1:], start=2):
        cells = [normalize_whitespace(cell) for cell in raw_cells]
        if not any(cells) or (is_results and cells[:2] == header[:2]):
            parsed.skipped_rows += 1
            continue
        if len(cells) != len(header) or not cells[0] or len(cells[0]) > MAX_NAME_LENGTH:
            msg = f"Row {number}: expected {len(header)} columns and a student name of at most 255 characters."
            raise ValueError(msg)
        name_key = normalize_name(cells[0])
        if name_key in seen:
            msg = f"Row {number}: duplicate student name; resolve this identity before importing."
            raise ValueError(msg)
        seen.add(name_key)
        if is_history:
            row = _history_row(cells, number, parsed)
        else:
            row = _result_list_row(cells, number, int(year_match.group(1)))
        row["source_row"] = number
        parsed.rows.append(row)
    if not parsed.rows:
        msg = "The sheet contains no student rows."
        raise ValueError(msg)
    return parsed


def _resolve_student(row: dict, *, lock: bool = False) -> tuple[Student | None, str]:
    matches = Student.objects.select_related("school").filter(normalized_name=normalize_name(row["name"]))
    if lock:
        matches = matches.select_for_update(of=("self",))
    birth_year = row["birth_year"]
    if birth_year is not None:
        exact = list(matches.filter(birth_year=birth_year)[:2])
        if len(exact) == 1:
            return exact[0], "Name and birth year"
        matches = matches.filter(birth_year__isnull=True) if not exact else matches
    candidates = list(matches[:2])
    if len(candidates) > 1:
        msg = f"Row {row['source_row']}: multiple students match; resolve the identity before importing."
        raise ValueError(msg)
    if candidates:
        return candidates[0], "Name only — review identity"
    return None, "New student"


def _result_key(result: dict) -> str:
    return f"{result['year']}:{result['code']}"


def _existing_results(student: Student | None, *, lock: bool = False) -> dict:
    if student is None:
        return {}
    results = student.results.select_related("assessment")
    if lock:
        results = results.select_for_update(of=("self",))
    return {
        f"{result.assessment.season_year}:{result.assessment.code}": {
            "raw_score": str(result.raw_score) if result.raw_score is not None else None,
            "medal": result.medal, "band": result.band, "status_text": result.status_text,
            "remarks": result.remarks, "updated_at": result.updated_at.isoformat(),
        }
        for result in results
    }


def prepare_sheet_preview(parsed: ParsedSheet) -> dict:
    rows = []
    for row in parsed.rows:
        student, match = _resolve_student(row)
        existing = _existing_results(student)
        results = [{**result, "previous": existing.get(_result_key(result))} for result in row["results"]]
        rows.append(
            {
                **row,
                "results": results,
                "student_id": student.pk if student else None,
                "match": match,
                "existing_school": student.school.name if student and student.school_id else "",
            },
        )
    return {
        "kind": SHEET_KIND,
        "label": parsed.label,
        "rows": rows,
        "mappings": parsed.mappings,
        "exclusions": parsed.exclusions,
        "warnings": parsed.warnings,
        "skipped_rows": parsed.skipped_rows,
        "student_count": len(rows),
        "new_students": sum(row["student_id"] is None for row in rows),
        "result_count": sum(len(row["results"]) for row in rows),
        "name_only_matches": sum(row["match"].startswith("Name only") for row in rows),
    }


@transaction.atomic
def apply_sheet_preview(*, batch_id: int, actor) -> ImportBatch:
    # Serialize applies across owners, including creation of identities with no
    # existing Student row to lock. Every apply has a committed preview batch.
    ImportBatch.objects.select_for_update().order_by("pk").values_list("pk", flat=True).first()
    batch = ImportBatch.objects.select_for_update().get(pk=batch_id, created_by=actor)
    summary = batch.summary_json
    if batch.status != ImportBatch.Status.PREVIEWED or summary.get("kind") != SHEET_KIND:
        msg = "This preview has already been applied or is not an olympiad sheet preview."
        raise ValueError(msg)
    assessments = {}
    for row in summary["rows"]:
        student, _match = _resolve_student(row, lock=True)
        if (student.pk if student else None) != row["student_id"]:
            msg = "Student matches changed since preview. Upload the sheet again to review the current matches."
            raise ValueError(msg)
        existing = _existing_results(student, lock=True)
        if any(existing.get(_result_key(result)) != result["previous"] for result in row["results"]):
            msg = "Results changed since preview. Upload the sheet again to review the current values."
            raise ValueError(msg)
        student = _save_student(student, row)
        for result in row["results"]:
            key = (result["code"], result["year"])
            if key not in assessments:
                assessments[key], _created = Assessment.objects.get_or_create(
                    code=key[0],
                    season_year=key[1],
                    defaults={
                        "display_name": result["label"],
                        "category": Assessment.Category.OTHER,
                        "result_type": Assessment.ResultType.MIXED,
                        "sort_order": result["order"],
                        "is_ranked_by_default": False,
                    },
                )
            _save_result(student=student, assessment=assessments[key], result=result, batch=batch, actor=actor)
    batch.status = ImportBatch.Status.APPLIED
    batch.summary_json = {key: value for key, value in summary.items() if key != "rows"}
    batch.save(update_fields={"status", "summary_json", "updated_at"})
    return batch


def _save_student(student: Student | None, row: dict) -> Student:
    fields = set()
    if student is None:
        student = Student(full_name=row["name"])
    if student.birth_year is None and row["birth_year"] is not None:
        student.birth_year = row["birth_year"]
        fields.add("birth_year")
    if student.school_id is None and row["school"]:
        student.school, _created = School.objects.get_or_create(
            normalized_name=normalize_name(row["school"]),
            defaults={"name": row["school"]},
        )
        fields.add("school")
    if student.pk is None:
        student.save()
    elif fields:
        student.save(update_fields=fields | {"updated_at"})
    return student


def _save_result(*, student: Student, assessment: Assessment, result: dict, batch: ImportBatch, actor) -> None:
    # Merge complementary score/medal/category lists without erasing existing data.
    defaults = {
        key: result[key]
        for key in ("raw_score", "medal", "band", "status_text", "remarks")
        if result[key] not in (None, "")
    }
    defaults.update(imported_by=actor, imported_at=timezone.now(), source_file_name=batch.original_filename)
    StudentResult.objects.update_or_create(student=student, assessment=assessment, defaults=defaults)
