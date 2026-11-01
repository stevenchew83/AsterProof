from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from inspinia.rankings.forms import OlympiadSheetImportForm
from inspinia.rankings.imports.olympiad_sheet import HISTORY_HEADERS
from inspinia.rankings.imports.olympiad_sheet import MAX_SHEET_ROWS
from inspinia.rankings.imports.olympiad_sheet import apply_sheet_preview
from inspinia.rankings.imports.olympiad_sheet import parse_olympiad_sheet
from inspinia.rankings.imports.olympiad_sheet import prepare_sheet_preview
from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import School
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

RESULT_HEADER = ["FULL NAME", "SCHOOL NAME", "Total IMONST2 2026", "Level/Grade/category"]


def _tsv(header, rows):
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t")
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue()


def _history_text():
    row = [""] * len(HISTORY_HEADERS)
    values = {
        0: "Synthetic Student", 1: "2012", 2: "14", 3: "120101-01-1234",
        4: "SQUAD", 5: "0", 14: "JUNIOR", 15: "42", 19: "12", 20: "35",
        21: "60", 23: "999", 25: "JUNIOR", 26: "Source School 2025",
        27: "Unlabelled School", 28: "Source School 2026", 29: "CADET", 30: "GOLD",
        32: "BRONZE 2025", 34: "SILVER", 35: "TEAM", 36: "Private family note",
        37: "https://private.example.test/student", 39: "#N/A",
    }
    for index, value in values.items():
        row[index] = value
    return _tsv(HISTORY_HEADERS, [row])


def _preview_batch(actor, text):
    return ImportBatch.objects.create(
        created_by=actor, import_type=ImportBatch.ImportType.LEGACY_WIDE_TABLE,
        original_filename="synthetic.txt", status=ImportBatch.Status.PREVIEWED,
        summary_json=prepare_sheet_preview(parse_olympiad_sheet(text)),
    )


def test_history_adapter_keeps_complementary_results_and_excludes_private_columns():
    parsed = parse_olympiad_sheet(_history_text())
    row = parsed.rows[0]
    results = {result["code"]: result for result in row["results"]}
    assert results["SST_2026"]["raw_score"] == "0"
    assert results["IMONST2_2024"]["raw_score"] == "12"
    assert results["IMONST2_2024"]["medal"] == "SILVER"
    assert results["KMC_2026"]["band"] == "CADET"
    assert results["KMC_2026"]["medal"] == "GOLD"
    assert "Source School 2026" in results["KMC_2026"]["remarks"]
    assert results["SELECTION_2024_A"]["status_text"] == "JUNIOR"
    assert results["SELECTION_2024_B"]["status_text"] == "TEAM"
    assert "KMC_2025" not in results
    payload = json.dumps(prepare_sheet_preview(parsed))
    for excluded in ("120101-01-1234", "Private family note", "Unlabelled School", "https://private.example.test"):
        assert excluded not in payload
    assert not Student.objects.exists()
    assert not Assessment.objects.exists()


def test_result_list_skips_separators_and_repeated_headers_and_retains_zero():
    text = _tsv(RESULT_HEADER, [
        ["First Student", "School A", "36", "PIONEER"], ["", "", "", ""],
        [*RESULT_HEADER[:3], ""], ["Second Student", "School B", "0", "BEGINNER"],
    ])
    parsed = parse_olympiad_sheet(text)
    assert parsed.skipped_rows == 2  # noqa: PLR2004
    assert len(parsed.rows) == 2  # noqa: PLR2004
    assert parsed.rows[1]["results"][0]["raw_score"] == "0"
    assert parsed.rows[1]["results"][0]["band"] == "BEGINNER"


@pytest.mark.parametrize("score", ["NaN", "Infinity", "-1", "1.234", "not a number", "100000000"])
def test_invalid_scores_are_rejected(score):
    with pytest.raises(ValueError, match="Score must"):
        parse_olympiad_sheet(_tsv(RESULT_HEADER, [["Student A", "School A", score, "PIONEER"]]))


def test_duplicate_names_and_wrong_width_are_rejected():
    with pytest.raises(ValueError, match="duplicate student"):
        parse_olympiad_sheet(_tsv(RESULT_HEADER, [
            ["Student A", "School", "10", "PIONEER"], ["STUDENT A", "School", "9", "PIONEER"],
        ]))
    with pytest.raises(ValueError, match="expected 4 columns"):
        parse_olympiad_sheet(_tsv(RESULT_HEADER, [["Student A", "School", "10"]]))
    with pytest.raises(ValueError, match="at most 2000"):
        parse_olympiad_sheet(_tsv(RESULT_HEADER, [["", "", "", ""]] * (MAX_SHEET_ROWS + 1)))


def test_text_upload_handles_bom_and_checks_encoding_and_size():
    text = _tsv(RESULT_HEADER, [["Student A", "School", "10", "PIONEER"]])
    form = OlympiadSheetImportForm(files={"file": SimpleUploadedFile("source.txt", ("\ufeff" + text).encode())})
    assert form.is_valid(), form.errors
    assert parse_olympiad_sheet(form.cleaned_data["source_text"]).rows[0]["name"] == "Student A"
    invalid = OlympiadSheetImportForm(files={"file": SimpleUploadedFile("source.txt", b"\xff\xff")})
    assert not invalid.is_valid()
    both = OlympiadSheetImportForm({"text": text}, files={"file": SimpleUploadedFile("source.txt", text.encode())})
    assert not both.is_valid()


def test_ambiguous_name_match_requires_manual_resolution():
    Student.objects.create(full_name="Same Student", birth_year=2011)
    Student.objects.create(full_name="Same Student", birth_year=2012)
    parsed = parse_olympiad_sheet(_tsv(RESULT_HEADER, [["Same Student", "School", "10", "PIONEER"]]))
    with pytest.raises(ValueError, match="multiple students"):
        prepare_sheet_preview(parsed)


def test_apply_preserves_identity_and_existing_information_merges_results_and_is_once_only():
    actor = UserFactory(role=User.Role.MODERATOR)
    school = School.objects.create(name="Existing School")
    student = Student.objects.create(
        full_name="Synthetic Student", birth_year=2012, school=school,
        full_nric="120101-01-1234", notes="Existing notes",
    )
    assessment = Assessment.objects.create(
        code="SST_2026", display_name="Existing SST", season_year=2026,
        category=Assessment.Category.TEST,
    )
    StudentResult.objects.create(student=student, assessment=assessment, medal="Existing medal", raw_score=Decimal(4))
    batch = _preview_batch(actor, _history_text())
    assert batch.summary_json["rows"][0]["match"] == "Name and birth year"
    apply_sheet_preview(batch_id=batch.pk, actor=actor)
    student.refresh_from_db()
    result = StudentResult.objects.get(student=student, assessment=assessment)
    assert result.raw_score == 0
    assert result.medal == "Existing medal"
    assert student.school == school
    assert student.notes == "Existing notes"
    assert student.full_nric == "120101-01-1234"
    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.APPLIED
    assert "rows" not in batch.summary_json
    assert not batch.uploaded_file
    with pytest.raises(ValueError, match="already been applied"):
        apply_sheet_preview(batch_id=batch.pk, actor=actor)


def test_stale_preview_does_not_mutate_any_students():
    actor = UserFactory(role=User.Role.MODERATOR)
    batch = _preview_batch(actor, _tsv(RESULT_HEADER, [
        ["Student A", "School", "10", "PIONEER"], ["Student B", "School", "9", "PIONEER"],
    ]))
    Student.objects.create(full_name="Student B")
    with pytest.raises(ValueError, match="changed since preview"):
        apply_sheet_preview(batch_id=batch.pk, actor=actor)
    assert not Student.objects.filter(full_name="Student A").exists()
    assert not Assessment.objects.exists()
    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.PREVIEWED


@pytest.mark.parametrize("route", ["assessment_results", "result_history", "olympiad_sheet_import"])
def test_new_pages_keep_login_and_role_boundaries(client, route):
    url = reverse(f"rankings:{route}")
    assert client.get(url).status_code == HTTPStatus.FOUND
    client.force_login(UserFactory(role=User.Role.NORMAL))
    assert client.get(url).status_code == HTTPStatus.FORBIDDEN
    assert client.post(url, {"action": "apply", "confirm": "yes"}).status_code == HTTPStatus.FORBIDDEN
    client.force_login(UserFactory(role=User.Role.MODERATOR))
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert "no-store" in response["Cache-Control"]


def _result(student_name, score, band, assessment, school=None):
    student = Student.objects.create(full_name=student_name, school=school, full_nric="120101-01-1234")
    return StudentResult.objects.create(student=student, assessment=assessment, raw_score=score, band=band)


def _assessment():
    return Assessment.objects.create(
        code="IMONST2_2026", display_name="IMONST2 2026", season_year=2026,
        category=Assessment.Category.CONTEST,
    )


def test_category_ranks_share_ties_keep_zero_and_remain_global_after_filtering(client):
    client.force_login(UserFactory(role=User.Role.MODERATOR))
    assessment = _assessment()
    _result("Pioneer A", 36, "PIONEER", assessment)
    _result("Pioneer B", 34, "PIONEER", assessment)
    _result("Pioneer C", 34, "PIONEER", assessment)
    _result("Pioneer D", 0, "PIONEER", assessment)
    _result("Beginner A", 28, "BEGINNER", assessment)
    _result("No Score", None, "PIONEER", assessment)
    response = client.get(reverse("rankings:assessment_results"))
    assert response.status_code == HTTPStatus.OK
    rows = {result.student.full_name: result for result in response.context["page_obj"]}
    assert {name: result.category_rank for name, result in rows.items()} == {
        "Pioneer A": 1, "Pioneer B": 2, "Pioneer C": 2, "Pioneer D": 4, "Beginner A": 1, "No Score": None,
    }
    assert "120101-01-1234" not in response.content.decode()
    filtered = client.get(reverse("rankings:assessment_results"), {"q": "Pioneer D"})
    assert filtered.context["page_obj"][0].category_rank == 4  # noqa: PLR2004
    assert filtered.context["page_obj"][0].raw_score == 0


def test_results_and_history_search_all_rows_before_pagination_and_escape_source_text(client):
    client.force_login(UserFactory(role=User.Role.ADMIN))
    assessment = _assessment()
    for i in range(55):
        _result(f"Student {i:03}", i, "PIONEER", assessment)
    target = _result("ZZ Target <script>alert(1)</script>", 0, "BEGINNER", assessment)
    target.remarks = "<script>source note</script>"
    target.save()
    for route in ("assessment_results", "result_history"):
        response = client.get(reverse(f"rankings:{route}"))
        assert len(response.context["page_obj"]) == 50  # noqa: PLR2004
        filtered = client.get(reverse(f"rankings:{route}"), {"q": "ZZ Target"})
        assert filtered.context["page_obj"].paginator.count == 1
        html = filtered.content.decode()
        assert "&lt;script&gt;" in html
        assert "<script>source note</script>" not in html
        assert "120101-01-1234" not in html
    student_page = client.get(reverse("rankings:student_detail", args=[target.student_id]))
    assert ">0.00</td>" in student_page.content.decode()


def test_preview_apply_flow_requires_confirmation_is_owner_scoped_and_retains_no_raw_upload(client):
    actor = UserFactory(role=User.Role.MODERATOR)
    client.force_login(actor)
    url = reverse("rankings:olympiad_sheet_import")
    response = client.post(url, {"text": _history_text()})
    assert response.status_code == HTTPStatus.FOUND
    batch = ImportBatch.objects.get()
    assert not batch.uploaded_file
    assert "120101-01-1234" not in json.dumps(batch.summary_json)
    assert not Student.objects.exists()
    assert not Assessment.objects.exists()
    preview = client.get(response["Location"])
    assert "Synthetic Student" in preview.content.decode()
    missing_confirmation = client.post(url, {"action": "apply", "batch_id": batch.pk})
    assert missing_confirmation.status_code == HTTPStatus.OK
    assert "Confirm that you have reviewed" in missing_confirmation.content.decode()
    assert not Student.objects.exists()
    client.force_login(UserFactory(role=User.Role.ADMIN))
    assert client.get(url, {"batch": batch.pk}).status_code == HTTPStatus.NOT_FOUND
    forbidden_apply = client.post(url, {"action": "apply", "batch_id": batch.pk, "confirm": "yes"})
    assert forbidden_apply.status_code == HTTPStatus.NOT_FOUND
    client.force_login(actor)
    applied = client.post(url, {"action": "apply", "batch_id": batch.pk, "confirm": "yes"})
    assert applied.status_code == HTTPStatus.FOUND
    assert applied["Location"] == reverse("rankings:assessment_results")
    assert Student.objects.count() == 1
    assert StudentResult.objects.exists()


def test_changed_result_values_require_a_fresh_preview():
    actor = UserFactory(role=User.Role.MODERATOR)
    assessment = _assessment()
    result = _result("Student A", 10, "PIONEER", assessment)
    batch = _preview_batch(actor, _tsv(RESULT_HEADER, [["Student A", "School", "12", "PIONEER"]]))
    assert batch.summary_json["rows"][0]["results"][0]["previous"]["raw_score"] == "10.00"
    result.raw_score = 11
    result.save()
    with pytest.raises(ValueError, match="Results changed since preview"):
        apply_sheet_preview(batch_id=batch.pk, actor=actor)
    result.refresh_from_db()
    assert result.raw_score == Decimal(11)


def test_overlapping_previews_from_different_owners_do_not_create_duplicate_students():
    first_actor = UserFactory(role=User.Role.MODERATOR)
    second_actor = UserFactory(role=User.Role.ADMIN)
    source = _tsv(RESULT_HEADER, [["New Student", "School", "12", "PIONEER"]])
    first_batch = _preview_batch(first_actor, source)
    second_batch = _preview_batch(second_actor, source)
    apply_sheet_preview(batch_id=first_batch.pk, actor=first_actor)
    with pytest.raises(ValueError, match="Student matches changed since preview"):
        apply_sheet_preview(batch_id=second_batch.pk, actor=second_actor)
    assert Student.objects.filter(full_name="New Student").count() == 1
    assert StudentResult.objects.count() == 1


def test_source_school_remains_searchable_when_master_school_differs(client):
    actor = UserFactory(role=User.Role.MODERATOR)
    school = School.objects.create(name="Master School")
    Student.objects.create(full_name="Student A", school=school)
    other_school = School.objects.create(name="AAA Master School")
    Student.objects.create(full_name="Student B", school=other_school)
    batch = _preview_batch(actor, _tsv(RESULT_HEADER, [
        ["Student A", "Contest School", "12", "PIONEER"],
        ["Student B", "ZZZ Event School", "11", "PIONEER"],
    ]))
    apply_sheet_preview(batch_id=batch.pk, actor=actor)
    assert Student.objects.get(full_name="Student A").school == school
    client.force_login(actor)
    response = client.get(reverse("rankings:assessment_results"), {"school": "Contest School"})
    assert response.context["page_obj"].paginator.count == 1
    assert response.context["page_obj"][0].school_display == "Contest School"
    sorted_response = client.get(reverse("rankings:assessment_results"), {"order": "school"})
    assert [row.student.full_name for row in sorted_response.context["page_obj"]] == ["Student A", "Student B"]


@pytest.mark.parametrize("invalid_id", ["abc", "0", "-1", "9" * 100])
def test_invalid_result_and_preview_ids_return_404(client, invalid_id):
    client.force_login(UserFactory(role=User.Role.MODERATOR))
    result_page = client.get(reverse("rankings:assessment_results"), {"assessment": invalid_id})
    assert result_page.status_code == HTTPStatus.NOT_FOUND
    response = client.get(reverse("rankings:olympiad_sheet_import"), {"batch": invalid_id})
    assert response.status_code == HTTPStatus.NOT_FOUND
