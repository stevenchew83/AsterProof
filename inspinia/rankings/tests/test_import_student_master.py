from __future__ import annotations

import csv
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from inspinia.rankings.imports.student_master_import import apply_student_master_import
from inspinia.rankings.imports.student_master_import import preview_student_master_import
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import ImportRowIssue
from inspinia.rankings.models import Student
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_PREVIEW_MATCH_COUNT = 3
EXPECTED_PREVIEW_CREATE_COUNT = 1
EXPECTED_PREVIEW_AMBIGUOUS_COUNT = 1
EXPECTED_PREVIEW_ERROR_COUNT = 1
EXPECTED_ISSUE_COUNT = 2
EXPECTED_ISSUE_ROW_NUMBERS = [6, 7]
EXPECTED_APPLY_CREATED = 1
EXPECTED_APPLY_UPDATED = 1
EXPECTED_APPLY_SKIPPED = 2


def _csv_upload(filename: str, headers: list[str], rows: list[dict[str, object | None]]) -> SimpleUploadedFile:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return SimpleUploadedFile(filename, buffer.getvalue().encode("utf-8"), content_type="text/csv")


def _xlsx_upload(filename: str, headers: list[str], rows: list[dict[str, object | None]]) -> SimpleUploadedFile:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header) for header in headers])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(
        filename,
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _build_batch(upload: SimpleUploadedFile) -> ImportBatch:
    return ImportBatch.objects.create(
        import_type=ImportBatch.ImportType.STUDENT_MASTER,
        uploaded_file=upload,
        original_filename=upload.name,
    )


def test_preview_student_master_import_buckets_matches_creates_ambiguous_and_errors_from_csv():
    actor = UserFactory(role=User.Role.ADMIN)
    Student.objects.create(
        full_name="Alice Tan",
        birth_year=2010,
        external_code="ST-001",
    )
    Student.objects.create(
        full_name="Bob Lim",
        birth_year=2011,
        full_nric="900101-10-1234",
    )
    Student.objects.create(full_name="Carmen Ong", birth_year=2012)
    Student.objects.create(full_name="Cara Ong", birth_year=2013)
    Student.objects.create(full_name="Cara  Ong", birth_year=2013)

    upload = _csv_upload(
        "student-master.csv",
        ["full_name", "external_code", "full_nric", "birth_year", "state", "notes"],
        [
            {
                "full_name": "Alice Tan Updated",
                "external_code": "ST-001",
                "full_nric": "",
                "birth_year": 2010,
                "state": "Selangor",
                "notes": "external match",
            },
            {
                "full_name": "Bob Lim Updated",
                "external_code": "",
                "full_nric": "900101-10-1234",
                "birth_year": 2011,
                "state": "Penang",
                "notes": "full nric match",
            },
            {
                "full_name": "Carmen Ong",
                "external_code": "",
                "full_nric": "",
                "birth_year": 2012,
                "state": "",
                "notes": "name birth match",
            },
            {
                "full_name": "Dana Lee",
                "external_code": "",
                "full_nric": "",
                "birth_year": 2014,
                "state": "Johor",
                "notes": "new student",
            },
            {
                "full_name": "Cara Ong",
                "external_code": "",
                "full_nric": "",
                "birth_year": 2013,
                "state": "",
                "notes": "ambiguous",
            },
            {
                "full_name": "Error Row",
                "external_code": "",
                "full_nric": "",
                "birth_year": "not-a-year",
                "state": "",
                "notes": "error",
            },
        ],
    )
    batch = _build_batch(upload)

    preview = preview_student_master_import(import_batch=batch, actor=actor)

    assert preview.match_count == EXPECTED_PREVIEW_MATCH_COUNT
    assert preview.create_count == EXPECTED_PREVIEW_CREATE_COUNT
    assert preview.ambiguous_count == EXPECTED_PREVIEW_AMBIGUOUS_COUNT
    assert preview.error_count == EXPECTED_PREVIEW_ERROR_COUNT
    assert preview.matched_by_external_code == 1
    assert preview.matched_by_full_nric == 1
    assert preview.matched_by_name_birth_year == 1
    assert [
        (row.bucket, row.match_strategy)
        for row in preview.rows
    ] == [
        ("matched", "external_code"),
        ("matched", "full_nric"),
        ("matched", "normalized_name_birth_year"),
        ("create", ""),
        ("ambiguous", "normalized_name_birth_year"),
        ("error", ""),
    ]

    issues = list(ImportRowIssue.objects.filter(import_batch=batch).order_by("row_number", "id"))
    assert len(issues) == EXPECTED_ISSUE_COUNT
    assert [issue.issue_code for issue in issues] == [
        "AMBIGUOUS_NAME_BIRTH_YEAR",
        "INVALID_BIRTH_YEAR",
    ]
    assert [issue.row_number for issue in issues] == EXPECTED_ISSUE_ROW_NUMBERS
    assert batch.status == ImportBatch.Status.PREVIEWED
    assert batch.summary_json["match_count"] == EXPECTED_PREVIEW_MATCH_COUNT
    assert batch.summary_json["create_count"] == EXPECTED_PREVIEW_CREATE_COUNT
    assert batch.summary_json["ambiguous_count"] == EXPECTED_PREVIEW_AMBIGUOUS_COUNT
    assert batch.summary_json["error_count"] == EXPECTED_PREVIEW_ERROR_COUNT


def test_preview_student_master_import_does_not_use_full_nric_matching_for_non_privileged_actor_from_xlsx():
    actor = UserFactory()
    Student.objects.create(
        full_name="Evan Tan",
        birth_year=2015,
        full_nric="900202-11-1234",
    )

    upload = _xlsx_upload(
        "student-master.xlsx",
        ["full_name", "external_code", "full_nric", "birth_year", "state", "notes"],
        [
            {
                "full_name": "Evan Tan Variant",
                "external_code": "",
                "full_nric": "900202-11-1234",
                "birth_year": 2015,
                "state": "Perak",
                "notes": "should not match on nric",
            },
        ],
    )
    batch = _build_batch(upload)

    preview = preview_student_master_import(import_batch=batch, actor=actor)

    assert preview.match_count == 0
    assert preview.create_count == 1
    assert preview.rows[0].bucket == "create"
    assert preview.rows[0].match_strategy == ""
    assert ImportRowIssue.objects.filter(import_batch=batch).count() == 0


def test_apply_student_master_import_upserts_students_and_updates_batch_summary_from_xlsx():
    actor = UserFactory(role=User.Role.ADMIN)
    existing = Student.objects.create(
        full_name="Alice Tan",
        birth_year=2010,
        external_code="ST-001",
        state="Selangor",
    )
    Student.objects.create(full_name="Twin User", birth_year=2016)
    Student.objects.create(full_name="Twin  User", birth_year=2016)

    upload = _xlsx_upload(
        "student-master.xlsx",
        ["full_name", "external_code", "full_nric", "birth_year", "state", "notes"],
        [
            {
                "full_name": "Alice Tan Updated",
                "external_code": "ST-001",
                "full_nric": "900101-01-0001",
                "birth_year": 2010,
                "state": "Kuala Lumpur",
                "notes": "updated",
            },
            {
                "full_name": "New Student",
                "external_code": "ST-NEW",
                "full_nric": "",
                "birth_year": 2014,
                "state": "Johor",
                "notes": "created",
            },
            {
                "full_name": "Twin User",
                "external_code": "",
                "full_nric": "",
                "birth_year": 2016,
                "state": "",
                "notes": "ambiguous",
            },
            {
                "full_name": "Error Row",
                "external_code": "",
                "full_nric": "",
                "birth_year": "oops",
                "state": "",
                "notes": "error",
            },
        ],
    )
    batch = _build_batch(upload)

    preview = preview_student_master_import(import_batch=batch, actor=actor)
    result = apply_student_master_import(preview=preview, import_batch=batch, actor=actor)

    existing.refresh_from_db()
    assert existing.full_name == "Alice Tan Updated"
    assert existing.external_code == "ST-001"
    assert existing.full_nric == "900101-01-0001"
    assert existing.state == "Kuala Lumpur"
    assert Student.objects.filter(external_code="ST-NEW").count() == 1
    assert result.created == EXPECTED_APPLY_CREATED
    assert result.updated == EXPECTED_APPLY_UPDATED
    assert result.skipped == EXPECTED_APPLY_SKIPPED
    assert batch.status == ImportBatch.Status.PARTIAL
    assert batch.summary_json["created"] == EXPECTED_APPLY_CREATED
    assert batch.summary_json["updated"] == EXPECTED_APPLY_UPDATED
    assert batch.summary_json["skipped"] == EXPECTED_APPLY_SKIPPED
    assert batch.summary_json["ambiguous_count"] == EXPECTED_PREVIEW_AMBIGUOUS_COUNT
    assert batch.summary_json["error_count"] == EXPECTED_PREVIEW_ERROR_COUNT
    assert ImportRowIssue.objects.filter(import_batch=batch).count() == EXPECTED_ISSUE_COUNT
