from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from inspinia.rankings.imports.legacy_wide_import import apply_legacy_wide_import
from inspinia.rankings.imports.legacy_wide_import import classify_legacy_wide_columns
from inspinia.rankings.imports.legacy_wide_import import preview_legacy_wide_import
from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import ImportRowIssue
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.models import StudentSelectionStatus
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_TEAM_AND_SQUAD_STATUS_COUNT = 2


def _make_import_batch(*, created_by: User | None = None) -> ImportBatch:
    return ImportBatch.objects.create(
        import_type=ImportBatch.ImportType.LEGACY_WIDE_TABLE,
        uploaded_file=SimpleUploadedFile(
            "legacy-wide.xlsx",
            b"legacy wide",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        original_filename="legacy-wide.xlsx",
        created_by=created_by,
    )


def test_classify_legacy_wide_columns_and_preview_ambiguous_columns_create_warnings():
    classification = classify_legacy_wide_columns(
        ["full_name", "birth_year", "external_code", "TEAM", "R1", "status_notes"],
    )

    assert classification.student_columns == ["full_name", "birth_year", "external_code"]
    assert classification.status_columns == ["TEAM"]
    assert classification.assessment_columns == ["R1"]
    assert classification.ambiguous_columns == ["status_notes"]

    batch = _make_import_batch()
    dataframe = pd.DataFrame(
        [
            {
                "full_name": "Alice Tan",
                "birth_year": 2008,
                "external_code": "AST-001",
                "TEAM": "TEAM",
                "R1": "88",
                "status_notes": "check me",
            },
        ],
    )

    preview = preview_legacy_wide_import(dataframe=dataframe, import_batch=batch)

    batch.refresh_from_db()
    assert preview.classification.ambiguous_columns == ["status_notes"]
    assert batch.status == ImportBatch.Status.PREVIEWED
    issue = ImportRowIssue.objects.get(import_batch=batch, issue_code="AMBIGUOUS_COLUMN")
    assert issue.row_number == 1
    assert issue.severity == ImportRowIssue.Severity.WARNING
    assert issue.raw_row_json == {"column": "status_notes"}


def test_apply_legacy_wide_import_routes_team_and_squad_labels_to_selection_status():
    admin_user = UserFactory(role=User.Role.ADMIN)
    batch = _make_import_batch(created_by=admin_user)
    dataframe = pd.DataFrame(
        [
            {
                "full_name": "Alice Tan",
                "birth_year": 2008,
                "external_code": "AST-001",
                "TEAM": "TEAM",
                "SQUAD": "SQUAD",
                "R1": "88",
            },
        ],
    )

    preview = preview_legacy_wide_import(dataframe=dataframe, import_batch=batch)
    result = apply_legacy_wide_import(
        preview=preview,
        import_batch=batch,
        season_year=2026,
        actor=admin_user,
    )

    batch.refresh_from_db()
    student = Student.objects.get(full_name="Alice Tan")
    assessment = Assessment.objects.get(code="R1", season_year=2026)

    assert result.created_students == 1
    assert result.created_assessments == 1
    assert result.created_results == 1
    assert result.created_statuses == EXPECTED_TEAM_AND_SQUAD_STATUS_COUNT
    assert batch.status == ImportBatch.Status.APPLIED
    assert batch.summary_json == {
        "created_students": 1,
        "updated_students": 0,
        "created_assessments": 1,
        "created_results": 1,
        "created_statuses": 2,
        "issues": 0,
        "rows": 1,
    }

    assert StudentResult.objects.filter(
        student=student,
        assessment=assessment,
        raw_score=Decimal("88.00"),
    ).exists()
    assert set(
        StudentSelectionStatus.objects.filter(student=student).values_list("status", flat=True),
    ) == {"team", "squad"}
    assert StudentSelectionStatus.objects.filter(student=student, status="team").exists()
    assert StudentSelectionStatus.objects.filter(student=student, status="squad").exists()
    assert StudentResult.objects.filter(student=student, assessment=assessment).count() == 1
    assert StudentResult.objects.filter(student=student, assessment=assessment).first().status_text == ""
