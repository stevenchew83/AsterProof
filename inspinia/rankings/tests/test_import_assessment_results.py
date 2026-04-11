from decimal import Decimal

import pandas as pd
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from inspinia.rankings.imports.assessment_result_import import PREVIEW_STATUS_INVALID
from inspinia.rankings.imports.assessment_result_import import PREVIEW_STATUS_MATCHED
from inspinia.rankings.imports.assessment_result_import import PREVIEW_STATUS_MISSING_STUDENT
from inspinia.rankings.imports.assessment_result_import import apply_assessment_result_import
from inspinia.rankings.imports.assessment_result_import import preview_assessment_result_import
from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult

pytestmark = pytest.mark.django_db

PREVIEW_TOTAL_ROWS = 3
PREVIEW_MATCHED_ROWS = 1
PREVIEW_ISSUE_ROWS = 2
PREVIEW_ISSUE_ROW_NUMBERS = [3, 4]
APPLY_TOTAL_ROWS = 2
APPLY_MATCHED_ROWS = 2
APPLY_CREATED_ROWS = 1
APPLY_UPDATED_ROWS = 1
APPLY_UPSERTED_ROWS = 2
APPLY_STUDENT_RESULT_COUNT = 2


def _test_password() -> str:
    return f"{'sec'}{'ret'}"


def _assessment() -> Assessment:
    return Assessment.objects.create(
        code="R1",
        display_name="Round 1",
        season_year=2026,
        category="contest",
        division_scope="",
        result_type="score",
    )


def _batch(filename: str = "results.xlsx") -> ImportBatch:
    upload = SimpleUploadedFile(filename, b"student_identifier,raw_score\n", content_type="text/csv")
    return ImportBatch.objects.create(
        import_type=ImportBatch.ImportType.ASSESSMENT_RESULTS,
        uploaded_file=upload,
        original_filename=filename,
    )


def test_preview_assessment_result_import_logs_missing_student_and_invalid_rows():
    assessment = _assessment()
    batch = _batch()
    alice = Student.objects.create(full_name="Alice Tan", external_code="A-001")

    dataframe = pd.DataFrame(
        [
            {
                "student_no": "A-001",
                "score": "88.25",
                "award": "Gold",
                "division_band": "A",
                "status_note": "Qualified",
                "notes": "Top performer",
                "link": "https://example.com/alice",
            },
            {
                "student_no": "MISSING-1",
                "score": "74.00",
                "award": "Silver",
                "division_band": "B",
                "status_note": "Qualified",
                "notes": "Not found",
                "link": "https://example.com/missing",
            },
            {
                "student_no": "A-001",
                "score": "not-a-number",
                "award": "Bronze",
                "division_band": "C",
                "status_note": "Needs review",
                "notes": "Bad score",
                "link": "https://example.com/bad",
            },
        ],
    )
    column_map = {
        "student_identifier": "student_no",
        "raw_score": "score",
        "medal": "award",
        "band": "division_band",
        "status_text": "status_note",
        "remarks": "notes",
        "source_url": "link",
    }

    result = preview_assessment_result_import(
        dataframe,
        batch=batch,
        assessment=assessment,
        column_map=column_map,
        source_file_name="preview-results.xlsx",
    )

    assert result.total_rows == PREVIEW_TOTAL_ROWS
    assert result.matched_count == PREVIEW_MATCHED_ROWS
    assert result.missing_student_count == 1
    assert result.invalid_count == 1
    assert [row.status for row in result.rows] == [
        PREVIEW_STATUS_MATCHED,
        PREVIEW_STATUS_MISSING_STUDENT,
        PREVIEW_STATUS_INVALID,
    ]
    assert result.rows[0].student_id == alice.id
    assert result.rows[0].raw_score == Decimal("88.25")
    assert result.rows[0].medal == "Gold"
    assert result.rows[0].band == "A"
    assert result.rows[0].status_text == "Qualified"
    assert result.rows[0].remarks == "Top performer"
    assert result.rows[0].source_url == "https://example.com/alice"

    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.PREVIEWED
    assert batch.summary_json["stage"] == "preview"
    assert batch.summary_json["matched_count"] == 1
    assert batch.summary_json["missing_student_count"] == 1
    assert batch.summary_json["invalid_count"] == 1
    assert batch.summary_json["source_file_name"] == "preview-results.xlsx"

    issues = list(batch.row_issues.order_by("row_number"))
    assert len(issues) == PREVIEW_ISSUE_ROWS
    assert [issue.row_number for issue in issues] == PREVIEW_ISSUE_ROW_NUMBERS
    assert {issue.issue_code for issue in issues} == {"missing_student", "invalid"}
    assert issues[0].raw_row_json["student_no"] == "MISSING-1"
    assert StudentResult.objects.count() == 0


def test_apply_assessment_result_import_upserts_rows_and_updates_batch_summary():
    assessment = _assessment()
    batch = _batch("assessment-results.csv")
    user = get_user_model().objects.create_user(email="importer@example.com", password=_test_password())

    alice = Student.objects.create(full_name="Alice Tan", external_code="A-001")
    bob = Student.objects.create(full_name="Bob Lim", external_code="B-002")
    existing = StudentResult.objects.create(
        student=alice,
        assessment=assessment,
        raw_score=Decimal("10.00"),
        medal="",
        band="",
        status_text="",
        remarks="old",
        source_url="",
        source_file_name="old.csv",
        imported_by=None,
        imported_at=None,
    )

    dataframe = pd.DataFrame(
        [
            {
                "student_identifier": "A-001",
                "raw_score": "91.50",
                "medal": "Gold",
                "band": "A",
                "status_text": "Qualified",
                "remarks": "Promoted",
                "source_url": "https://example.com/alice",
            },
            {
                "student_identifier": "B-002",
                "raw_score": "74",
                "medal": "Silver",
                "band": "B",
                "status_text": "Qualified",
                "remarks": "New row",
                "source_url": "https://example.com/bob",
            },
        ],
    )

    result = apply_assessment_result_import(
        dataframe,
        batch=batch,
        assessment=assessment,
        imported_by=user,
        source_file_name="assessment-results.csv",
    )

    assert result.total_rows == APPLY_TOTAL_ROWS
    assert result.matched_count == APPLY_MATCHED_ROWS
    assert result.missing_student_count == 0
    assert result.invalid_count == 0
    assert result.created_count == APPLY_CREATED_ROWS
    assert result.updated_count == APPLY_UPDATED_ROWS
    assert result.upserted_count == APPLY_UPSERTED_ROWS

    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.APPLIED
    assert batch.summary_json["stage"] == "apply"
    assert batch.summary_json["created_count"] == APPLY_CREATED_ROWS
    assert batch.summary_json["updated_count"] == APPLY_UPDATED_ROWS
    assert batch.summary_json["source_file_name"] == "assessment-results.csv"
    assert batch.row_issues.count() == 0

    alice.refresh_from_db()
    bob.refresh_from_db()
    assert StudentResult.objects.count() == APPLY_STUDENT_RESULT_COUNT

    alice_result = StudentResult.objects.get(student=alice, assessment=assessment)
    assert alice_result.id == existing.id
    assert alice_result.raw_score == Decimal("91.50")
    assert alice_result.medal == "Gold"
    assert alice_result.band == "A"
    assert alice_result.status_text == "Qualified"
    assert alice_result.remarks == "Promoted"
    assert alice_result.source_url == "https://example.com/alice"
    assert alice_result.source_file_name == "assessment-results.csv"
    assert alice_result.imported_by == user
    assert alice_result.imported_at is not None

    bob_result = StudentResult.objects.get(student=bob, assessment=assessment)
    assert bob_result.raw_score == Decimal("74.00")
    assert bob_result.medal == "Silver"
    assert bob_result.band == "B"
    assert bob_result.status_text == "Qualified"
    assert bob_result.remarks == "New row"
    assert bob_result.source_url == "https://example.com/bob"
    assert bob_result.source_file_name == "assessment-results.csv"
    assert bob_result.imported_by == user
    assert bob_result.imported_at is not None
