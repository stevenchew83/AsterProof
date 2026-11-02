"""Reviewed corrections survive every supported import path."""

import csv
import io
import json
from decimal import Decimal
from functools import partial

import pandas as pd
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from inspinia.rankings.imports.assessment_result_import import apply_assessment_result_import
from inspinia.rankings.imports.assessment_result_import import preview_assessment_result_import
from inspinia.rankings.imports.legacy_wide_import import apply_legacy_wide_import
from inspinia.rankings.imports.legacy_wide_import import preview_legacy_wide_import
from inspinia.rankings.imports.olympiad_sheet import apply_sheet_preview
from inspinia.rankings.imports.olympiad_sheet import parse_olympiad_sheet
from inspinia.rankings.imports.olympiad_sheet import prepare_sheet_preview
from inspinia.rankings.imports.student_master_import import apply_student_master_import
from inspinia.rankings.imports.student_master_import import preview_student_master_import
from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import OutcomeAlias
from inspinia.rankings.models import RankingCorrection
from inspinia.rankings.models import RankingCorrectionItem
from inspinia.rankings.models import RankingCorrectionReceipt
from inspinia.rankings.models import School
from inspinia.rankings.models import SchoolAlias
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentIdentityReview
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services import import_protection
from inspinia.rankings.services.import_protection import protected_changes
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_uploads(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}


def _actor():
    return UserFactory(role=User.Role.MODERATOR)


def _assessment(code="IMONST2_2026"):
    return Assessment.objects.create(code=code, display_name=code, season_year=2026, category="test")


def _batch(actor, kind="assessment_results"):
    return ImportBatch.objects.create(import_type=kind, original_filename="synthetic.csv", created_by=actor)


def _protect(kind, target, changes, before=None):
    correction = RankingCorrection.objects.create(
        status=RankingCorrection.Status.APPLIED,
        reason="Verified synthetic source",
        decided_at=timezone.now(),
    )
    RankingCorrectionItem.objects.create(
        correction=correction,
        kind=kind,
        target_id=target.pk,
        before={"exists": True, "version": target.updated_at.isoformat(), "values": before or {}},
        changes=changes,
    )
    RankingCorrectionReceipt.objects.create(correction=correction, changes=[])
    return correction


def _sheet(rows):
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t")
    writer.writerow(["FULL NAME", "SCHOOL NAME", "Total IMONST2 2026", "Level/Grade/category"])
    writer.writerows(rows)
    return output.getvalue()


def test_reviewed_field_protection_uses_latest_applied_value_and_numeric_equality():
    assessment = _assessment()
    student = Student.objects.create(full_name="Synthetic A")
    result = StudentResult.objects.create(student=student, assessment=assessment, raw_score=0)
    _protect("result", result, {"raw_score": "0.00"})
    assert protected_changes("result", result.pk, {"raw_score": Decimal("0")}) == []
    later = _protect("result", result, {"raw_score": "7.00"})
    pending = RankingCorrection.objects.create(status="submitted", reason="Unapplied")
    RankingCorrectionItem.objects.create(
        correction=pending,
        kind="result",
        target_id=result.pk,
        changes={"raw_score": "99"},
    )
    assert protected_changes("result", result.pk, {"raw_score": Decimal("7")}) == []
    conflict = protected_changes("result", result.pk, {"raw_score": "0"})
    assert conflict[0]["correction_id"] == later.pk
    assert conflict[0]["approved"] == "7.00"


def test_assessment_import_holds_full_row_and_imports_other_rows_once():
    actor = _actor()
    assessment = _assessment()
    first = Student.objects.create(full_name="Reviewed A", external_code="A")
    second = Student.objects.create(full_name="Synthetic B", external_code="B")
    record = StudentResult.objects.create(
        student=first,
        assessment=assessment,
        raw_score=5,
        band="BEGINNER",
        remarks="Original",
    )
    _protect("result", record, {"raw_score": "5"})
    batch = _batch(actor)
    frame = pd.DataFrame(
        [
            {
                "student_identifier": "A",
                "raw_score": 10,
                "band": "PIONEER",
                "remarks": "Must stay held",
                "full_nric": "PRIVATE-ID",
            },
            {"student_identifier": "B", "raw_score": 0},
        ],
    )
    applied = apply_assessment_result_import(frame, batch=batch, assessment=assessment, imported_by=actor)
    record.refresh_from_db()
    assert (record.raw_score, record.band, record.remarks) == (Decimal(5), "BEGINNER", "Original")
    assert StudentResult.objects.get(student=second, assessment=assessment).raw_score == 0
    assert (applied.held_count, applied.created_count) == (1, 1)
    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.PARTIAL
    held = batch.protected_conflicts.get()
    assert "PRIVATE-ID" not in json.dumps(held.operations)
    assert "Must stay held" not in json.dumps(held.operations)
    assert held.operations[0]["values"]["band"] == "PIONEER"
    with pytest.raises(ValueError, match="consumed"):
        apply_assessment_result_import(frame, batch=batch, assessment=assessment, imported_by=actor)
    assert batch.protected_conflicts.count() == 1


def test_olympiad_import_holds_student_school_and_all_results_of_conflicting_row():
    actor = _actor()
    assessment = _assessment()
    student = Student.objects.create(full_name="Reviewed A", birth_year=2012)
    record = StudentResult.objects.create(student=student, assessment=assessment, raw_score=5)
    _protect("result", record, {"raw_score": "5.00"})
    parsed = parse_olympiad_sheet(
        _sheet(
            [
                ["Reviewed A", "Do Not Create School", 10, "PIONEER"],
                ["Synthetic B", "School B", 0, "BEGINNER"],
            ],
        ),
    )
    preview = prepare_sheet_preview(parsed)
    assert preview["held_count"] == 1
    batch = _batch(actor, "legacy_wide_table")
    batch.status = ImportBatch.Status.PREVIEWED
    batch.summary_json = preview
    batch.save()
    apply_sheet_preview(batch_id=batch.pk, actor=actor)
    student.refresh_from_db()
    record.refresh_from_db()
    assert student.school_id is None
    assert not School.objects.filter(name="Do Not Create School").exists()
    assert record.raw_score == Decimal(5)
    assert StudentResult.objects.get(student__full_name="Synthetic B").raw_score == 0
    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.PARTIAL
    assert batch.summary_json["applied_rows"] == 1
    with pytest.raises(ValueError, match="consumed"):
        apply_sheet_preview(batch_id=batch.pk, actor=actor)


def test_student_master_holds_all_fields_when_reviewed_birth_year_conflicts():
    actor = _actor()
    student = Student.objects.create(full_name="Reviewed A", external_code="A", birth_year=2012, state="Original")
    _protect("student", student, {"birth_year": 2012}, before={"full_name": "Reviewed A", "birth_year": 2010})
    batch = _batch(actor, "student_master")
    batch.uploaded_file = SimpleUploadedFile(
        "synthetic.csv",
        (
            b"full_name,external_code,birth_year,state,full_nric,notes\n"
            b"Reviewed A,A,2010,Changed,PRIVATE-ID,PRIVATE-NOTE\n"
            b"Synthetic B,B,2014,New,,\n"
        ),
    )
    batch.save()
    preview = preview_student_master_import(import_batch=batch, actor=actor)
    applied = apply_student_master_import(preview=preview, import_batch=batch, actor=actor)
    student.refresh_from_db()
    assert (student.birth_year, student.state, student.full_nric, student.notes) == (2012, "Original", "", "")
    assert Student.objects.filter(external_code="B").exists()
    assert (applied.held_count, applied.created, applied.updated) == (1, 1, 0)
    held = batch.protected_conflicts.get()
    assert "PRIVATE" not in json.dumps(held.operations)
    assert batch.status == ImportBatch.Status.PARTIAL
    with pytest.raises(ValueError, match="consumed"):
        apply_student_master_import(preview=preview, import_batch=batch, actor=actor)


def test_legacy_import_preflights_entire_source_row_before_creating_schools():
    actor = _actor()
    assessment = _assessment("SST")
    student = Student.objects.create(full_name="Reviewed A", external_code="A", birth_year=2012)
    record = StudentResult.objects.create(student=student, assessment=assessment, raw_score=5)
    _protect("result", record, {"raw_score": "5"})
    batch = _batch(actor, "legacy_wide_table")
    frame = pd.DataFrame(
        [
            {
                "full_name": "Changed A",
                "external_code": "A",
                "birth_year": 2012,
                "school": "Do Not Create School",
                "SST": 10,
            },
            {"full_name": "Synthetic B", "external_code": "B", "birth_year": 2013, "school": "School B", "SST": 0},
        ],
    )
    preview = preview_legacy_wide_import(dataframe=frame, import_batch=batch)
    applied = apply_legacy_wide_import(preview=preview, import_batch=batch, season_year=2026, actor=actor)
    student.refresh_from_db()
    record.refresh_from_db()
    assert (student.full_name, student.school_id, record.raw_score) == ("Reviewed A", None, Decimal(5))
    assert not School.objects.filter(name="Do Not Create School").exists()
    assert StudentResult.objects.get(student__external_code="B", assessment=assessment).raw_score == 0
    assert (applied.held_count, applied.applied_rows) == (1, 1)
    assert batch.status == ImportBatch.Status.PARTIAL
    with pytest.raises(ValueError, match="consumed"):
        apply_legacy_wide_import(preview=preview, import_batch=batch, season_year=2026, actor=actor)


def test_corrected_former_name_is_held_instead_of_creating_duplicate_student():
    actor = _actor()
    student = Student.objects.create(full_name="Reviewed Name", birth_year=2012)
    _protect(
        "student",
        student,
        {"full_name": "Reviewed Name"},
        before={"full_name": "Former Name", "birth_year": 2012},
    )
    preview = prepare_sheet_preview(parse_olympiad_sheet(_sheet([["Former Name", "", 0, "PIONEER"]])))
    assert preview["rows"][0]["student_id"] == student.pk
    batch = _batch(actor, "legacy_wide_table")
    batch.status = "previewed"
    batch.summary_json = preview
    batch.save()
    apply_sheet_preview(batch_id=batch.pk, actor=actor)
    assert Student.objects.count() == 1
    assert not StudentResult.objects.exists()
    assert batch.protected_conflicts.count() == 1


def test_reviewed_aliases_are_applied_before_comparing_protected_values():
    actor = _actor()
    assessment = _assessment()
    school = School.objects.create(name="Canonical School")
    SchoolAlias.objects.create(alias="School Alias", normalized_name="school alias", school=school)
    OutcomeAlias.objects.create(
        assessment=assessment,
        field="band",
        alias="P",
        normalized_alias="p",
        canonical="PIONEER",
    )
    student = Student.objects.create(full_name="Synthetic A")
    record = StudentResult.objects.create(student=student, assessment=assessment, raw_score=0, band="PIONEER")
    _protect("result", record, {"band": "PIONEER", "raw_score": "0"})
    batch = _batch(actor, "legacy_wide_table")
    batch.status = "previewed"
    batch.summary_json = prepare_sheet_preview(parse_olympiad_sheet(_sheet([["Synthetic A", "School Alias", 0, "P"]])))
    batch.save()
    apply_sheet_preview(batch_id=batch.pk, actor=actor)
    student.refresh_from_db()
    record.refresh_from_db()
    assert student.school_id == school.pk
    assert record.band == "PIONEER"
    assert batch.protected_conflicts.count() == 0


def test_receipt_failure_rolls_back_other_rows_and_batch_state(monkeypatch):
    actor = _actor()
    assessment = _assessment()
    first = Student.objects.create(full_name="Synthetic A", external_code="A")
    second = Student.objects.create(full_name="Reviewed B", external_code="B")
    record = StudentResult.objects.create(student=second, assessment=assessment, raw_score=5)
    _protect("result", record, {"raw_score": "5"})
    batch = _batch(actor)
    frame = pd.DataFrame([{"student_identifier": "A", "raw_score": 0}, {"student_identifier": "B", "raw_score": 10}])

    def fail_receipt(*args, **kwargs):
        message = "Receipt unavailable"
        raise RuntimeError(message)

    monkeypatch.setattr(import_protection.RankingImportConflict.objects, "get_or_create", fail_receipt)
    with pytest.raises(RuntimeError, match="Receipt unavailable"):
        apply_assessment_result_import(frame, batch=batch, assessment=assessment, imported_by=actor)
    assert not StudentResult.objects.filter(student=first).exists()
    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.UPLOADED
    assert not batch.protected_conflicts.exists()


@pytest.mark.parametrize("kind", ["assessment", "student", "legacy"])
@pytest.mark.parametrize("status", [ImportBatch.Status.APPLIED, ImportBatch.Status.PARTIAL])
def test_preview_cannot_rearm_a_consumed_batch(kind, status):
    actor = _actor()
    assessment = _assessment()
    student = Student.objects.create(full_name="Synthetic A", external_code="A")
    batch = _batch(actor)
    batch.status = status
    batch.summary_json = {"receipt": "Keep original receipt"}
    batch.save()
    previews = {
        "assessment": partial(
            preview_assessment_result_import,
            pd.DataFrame([{"student_identifier": "A", "raw_score": 0}]),
            batch=batch,
            assessment=assessment,
        ),
        "student": partial(preview_student_master_import, import_batch=batch, actor=actor),
        "legacy": partial(
            preview_legacy_wide_import, dataframe=pd.DataFrame([{"full_name": student.full_name}]), import_batch=batch,
        ),
    }
    with pytest.raises(ValueError, match="consumed"):
        previews[kind]()
    batch.refresh_from_db()
    assert batch.status == status
    assert batch.summary_json == {"receipt": "Keep original receipt"}


def test_reviewed_birth_year_match_cannot_be_bypassed_by_creating_a_new_student():
    actor = _actor()
    student = Student.objects.create(full_name="Reviewed A", birth_year=2012)
    _protect("student", student, {"birth_year": 2012}, before={"full_name": "Reviewed A", "birth_year": 2010})
    batch = _batch(actor, "student_master")
    batch.uploaded_file = SimpleUploadedFile("synthetic.csv", b"full_name,birth_year\nReviewed A,2010\n")
    batch.save()
    preview = preview_student_master_import(import_batch=batch, actor=actor)
    assert preview.held_count == 1
    assert preview.create_count == 0
    applied = apply_student_master_import(preview=preview, import_batch=batch, actor=actor)
    assert applied.held_count == 1
    assert Student.objects.count() == 1


def test_former_identity_cannot_hide_a_confirmed_separate_current_namesake():
    actor = _actor()
    first = Student.objects.create(full_name="Same Synthetic Name", birth_year=2012, state="First original")
    second = Student.objects.create(full_name="Same Synthetic Name", birth_year=2017, state="Second original")
    StudentIdentityReview.objects.create(
        first_student=first, second_student=second, decision="confirmed_separate", evidence="Owner confirmed",
    )
    _protect("student", first, {"birth_year": 2012},
             before={"full_name": "Same Synthetic Name", "birth_year": 2010})
    batch = _batch(actor, "student_master")
    batch.uploaded_file = SimpleUploadedFile("synthetic.csv", b"full_name,state\nSame Synthetic Name,Changed\n")
    batch.save()
    preview = preview_student_master_import(import_batch=batch, actor=actor)
    assert preview.match_count == 0
    assert preview.ambiguous_count == 1
    applied = apply_student_master_import(preview=preview, import_batch=batch, actor=actor)
    assert applied.updated == 0
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.state == "First original"
    assert second.state == "Second original"
