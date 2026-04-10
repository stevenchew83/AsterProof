import pytest
from django.db import IntegrityError
from django.db import connection

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingFormulaItem
from inspinia.rankings.models import School
from inspinia.rankings.models import Student

pytestmark = pytest.mark.django_db


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
