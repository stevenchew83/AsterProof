import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import connection

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingFormulaItem
from inspinia.rankings.models import RankingSnapshot
from inspinia.rankings.models import School
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.models import StudentSelectionStatus

pytestmark = pytest.mark.django_db


def _single_column_index_count(table_name: str, column_name: str) -> int:
    constraints = connection.introspection.get_constraints(connection.cursor(), table_name)
    return sum(
        1
        for details in constraints.values()
        if details["index"]
        and not details["primary_key"]
        and tuple(details["columns"]) == (column_name,)
    )


def test_school_normalizes_name_and_enforces_unique_normalized_name():
    school = School.objects.create(name="  SMK   Seri Indah  ")

    assert school.normalized_name == "smk seri indah"

    with pytest.raises(IntegrityError):
        School.objects.create(name="smk seri indah")


def test_student_external_code_is_unique_when_present():
    student = Student.objects.create(full_name="Alice Tan", external_code="  AST-001  ")

    assert student.external_code == "AST-001"

    with pytest.raises(IntegrityError):
        Student.objects.create(full_name="Bob Lim", external_code="AST-001")


def test_student_external_code_allows_multiple_blank_values():
    first_student = Student.objects.create(full_name="Alice Tan", external_code="")
    second_student = Student.objects.create(full_name="Bob Lim", external_code="   ")

    assert first_student.external_code == ""
    assert second_student.external_code == ""


def test_ranking_formula_missing_score_policy_allows_skip_and_rescale():
    formula = RankingFormula(
        name="National Overall",
        season_year=2026,
        division="",
        purpose=RankingFormula.Purpose.OVERALL,
        missing_score_policy="skip_and_rescale",
    )

    formula.full_clean()
    formula.save()

    assert formula.missing_score_policy == "skip_and_rescale"


def test_assessment_save_canonicalizes_legacy_category_and_result_type_tokens():
    assessment = Assessment.objects.create(
        code=" R1 ",
        display_name=" Round 1 ",
        season_year=2026,
        category="  EXAM  ",
        division_scope="  senior  ",
        result_type="  Rank  ",
    )

    assert assessment.category == "test"
    assert assessment.result_type == "status"


def test_ranking_formula_save_canonicalizes_legacy_missing_score_policy_tokens():
    formula = RankingFormula.objects.create(
        name="National Overall",
        season_year=2026,
        division="",
        purpose=RankingFormula.Purpose.OVERALL,
        missing_score_policy="  skip  ",
    )

    assert formula.missing_score_policy == "skip_and_rescale"


def test_ranking_formula_item_normalization_method_allows_percent_of_max():
    assessment = Assessment.objects.create(
        code="R1",
        display_name="Round 1",
        season_year=2026,
        category="contest",
        division_scope="",
        result_type="score",
    )
    formula = RankingFormula.objects.create(
        name="National Overall",
        season_year=2026,
        division="",
        purpose=RankingFormula.Purpose.OVERALL,
    )
    item = RankingFormulaItem(
        ranking_formula=formula,
        assessment=assessment,
        normalization_method="percent_of_max",
    )

    item.full_clean()
    item.save()

    assert item.normalization_method == "percent_of_max"


def test_ranking_formula_item_save_canonicalizes_legacy_normalization_method_tokens():
    assessment = Assessment.objects.create(
        code="R2",
        display_name="Round 2",
        season_year=2026,
        category="contest",
        division_scope="",
        result_type="score",
    )
    formula = RankingFormula.objects.create(
        name="National Overall",
        season_year=2026,
        division="",
        purpose=RankingFormula.Purpose.OVERALL,
    )

    item = RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=assessment,
        normalization_method="  z_score  ",
    )

    assert item.normalization_method == "zscore"


def test_ranking_formula_scope_is_unique_per_version():
    RankingFormula.objects.create(
        name="National Overall",
        season_year=2026,
        division="senior",
        purpose=RankingFormula.Purpose.OVERALL,
        version=1,
    )

    with pytest.raises(IntegrityError):
        RankingFormula.objects.create(
            name="National Overall Copy",
            season_year=2026,
            division="senior",
            purpose=RankingFormula.Purpose.OVERALL,
            version=1,
        )


def test_school_has_name_index():
    constraints = connection.introspection.get_constraints(connection.cursor(), "rankings_school")
    indexed_columns = {
        tuple(details["columns"])
        for details in constraints.values()
        if details["index"]
    }

    assert ("name",) in indexed_columns


def test_student_result_is_unique_per_student_and_assessment():
    student = Student.objects.create(full_name="Alice Tan")
    assessment = Assessment.objects.create(
        code="R1",
        display_name="Round 1",
        season_year=2026,
        category="contest",
        division_scope="",
        result_type="score",
    )

    StudentResult.objects.create(student=student, assessment=assessment, raw_score="12.00")

    with pytest.raises(IntegrityError):
        StudentResult.objects.create(student=student, assessment=assessment, raw_score="13.00")


def test_ranking_snapshot_is_unique_per_formula_and_student():
    student = Student.objects.create(full_name="Alice Tan")
    formula = RankingFormula.objects.create(
        name="National Overall",
        season_year=2026,
        division="senior",
        purpose=RankingFormula.Purpose.OVERALL,
    )

    RankingSnapshot.objects.create(
        ranking_formula=formula,
        student=student,
        season_year=2026,
        division="senior",
        total_score="88.5000",
        last_computed_at="2026-04-10T12:00:00Z",
    )

    with pytest.raises(IntegrityError):
        RankingSnapshot.objects.create(
            ranking_formula=formula,
            student=student,
            season_year=2026,
            division="senior",
            total_score="89.0000",
            last_computed_at="2026-04-10T12:05:00Z",
        )


def test_student_selection_status_scope_key_is_unique():
    student = Student.objects.create(full_name="Alice Tan")

    StudentSelectionStatus.objects.create(
        student=student,
        season_year=2026,
        division="senior",
        status="team",
    )

    with pytest.raises(IntegrityError):
        StudentSelectionStatus.objects.create(
            student=student,
            season_year=2026,
            division="senior",
            status="team",
        )


def test_import_batch_defaults_to_uploaded_status():
    from django.core.files.uploadedfile import SimpleUploadedFile

    from inspinia.rankings.models import ImportBatch

    upload = SimpleUploadedFile("results.csv", b"student,score\nAlice,12\n", content_type="text/csv")

    batch = ImportBatch.objects.create(
        import_type=ImportBatch.ImportType.ASSESSMENT_RESULTS,
        uploaded_file=upload,
        original_filename="results.csv",
    )

    assert batch.status == ImportBatch.Status.UPLOADED


def test_ranking_snapshot_save_uses_formula_scope():
    student = Student.objects.create(full_name="Alice Tan")
    formula = RankingFormula.objects.create(
        name="National Overall",
        season_year=2026,
        division="Senior ",
        purpose=RankingFormula.Purpose.OVERALL,
    )

    snapshot = RankingSnapshot.objects.create(
        ranking_formula=formula,
        student=student,
        season_year=2030,
        division=" junior ",
        total_score="88.5000",
    )

    assert snapshot.season_year == formula.season_year
    assert snapshot.division == "Senior"


def test_student_selection_status_full_clean_rejects_invalid_status():
    student = Student.objects.create(full_name="Alice Tan")
    selection_status = StudentSelectionStatus(
        student=student,
        season_year=2026,
        division="senior",
        status="invalid-status",
    )

    with pytest.raises(ValidationError) as exc_info:
        selection_status.full_clean()

    assert "status" in exc_info.value.message_dict


def test_student_result_duplicate_single_column_indexes_are_removed():
    assert _single_column_index_count("rankings_studentresult", "student_id") == 1
    assert _single_column_index_count("rankings_studentresult", "assessment_id") == 1
    assert _single_column_index_count("rankings_studentresult", "medal") == 1
    assert _single_column_index_count("rankings_studentresult", "band") == 1
    assert _single_column_index_count("rankings_studentresult", "raw_score") == 1


def test_ranking_snapshot_duplicate_single_column_indexes_are_removed():
    assert _single_column_index_count("rankings_rankingsnapshot", "season_year") == 1
    assert _single_column_index_count("rankings_rankingsnapshot", "division") == 1
    assert _single_column_index_count("rankings_rankingsnapshot", "total_score") == 1
    assert _single_column_index_count("rankings_rankingsnapshot", "rank_overall") == 1
