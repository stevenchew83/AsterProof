from decimal import Decimal

import pytest

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingFormulaItem
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.ranking_compute import compute_rank_rows
from inspinia.rankings.services.ranking_compute import compute_rankings

pytestmark = pytest.mark.django_db


def _make_assessment(code: str, *, max_score: str = "100.00", sort_order: int = 0) -> Assessment:
    return Assessment.objects.create(
        code=code,
        display_name=code,
        season_year=2026,
        category=Assessment.Category.CONTEST,
        division_scope="",
        result_type=Assessment.ResultType.SCORE,
        max_score=max_score,
        sort_order=sort_order,
    )


def _make_formula(*, missing_score_policy: str) -> RankingFormula:
    return RankingFormula.objects.create(
        name=f"Overall {missing_score_policy}",
        season_year=2026,
        division="",
        purpose=RankingFormula.Purpose.OVERALL,
        missing_score_policy=missing_score_policy,
    )


def _row_for(rows: list[dict], student: Student) -> dict:
    return next(row for row in rows if row["student_id"] == student.id)


def test_compute_rankings_uses_zero_policy_for_missing_optional_results():
    formula = _make_formula(missing_score_policy=RankingFormula.MissingScorePolicy.ZERO)
    round_one = _make_assessment("R1", sort_order=1)
    round_two = _make_assessment("R2", sort_order=2)
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=round_one,
        weight=Decimal("2.0000"),
        sort_order=1,
    )
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=round_two,
        weight=Decimal("1.0000"),
        sort_order=2,
    )
    student = Student.objects.create(full_name="Alice Tan")
    StudentResult.objects.create(student=student, assessment=round_one, raw_score=Decimal("80.00"))

    rows = compute_rankings(formula, Student.objects.filter(id=student.id))

    row = _row_for(rows, student)
    assert row["total_score"] == Decimal("53.3333")
    assert row["breakdown"]["R2"]["contribution"] == Decimal("0.0000")


def test_compute_rankings_rescales_when_skip_and_rescale_policy_is_used():
    formula = _make_formula(missing_score_policy=RankingFormula.MissingScorePolicy.SKIP_AND_RESCALE)
    round_one = _make_assessment("R1", sort_order=1)
    round_two = _make_assessment("R2", sort_order=2)
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=round_one,
        weight=Decimal("2.0000"),
        sort_order=1,
    )
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=round_two,
        weight=Decimal("1.0000"),
        sort_order=2,
    )
    student = Student.objects.create(full_name="Alice Tan")
    StudentResult.objects.create(student=student, assessment=round_one, raw_score=Decimal("80.00"))

    rows = compute_rankings(formula, Student.objects.filter(id=student.id))

    row = _row_for(rows, student)
    assert row["total_score"] == Decimal("80.0000")
    assert row["breakdown"]["R2"]["counted_in_denominator"] is False


def test_compute_rankings_keeps_required_missing_assessment_in_breakdown_with_zero_penalty():
    formula = _make_formula(missing_score_policy=RankingFormula.MissingScorePolicy.SKIP_AND_RESCALE)
    round_one = _make_assessment("R1", sort_order=1)
    round_two = _make_assessment("R2", sort_order=2)
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=round_one,
        weight=Decimal("2.0000"),
        sort_order=1,
    )
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=round_two,
        weight=Decimal("1.0000"),
        is_required=True,
        sort_order=2,
    )
    student = Student.objects.create(full_name="Alice Tan")
    StudentResult.objects.create(student=student, assessment=round_one, raw_score=Decimal("80.00"))

    rows = compute_rankings(formula, Student.objects.filter(id=student.id))

    row = _row_for(rows, student)
    assert row["total_score"] == Decimal("53.3333")
    assert row["breakdown"]["R2"]["is_required"] is True
    assert row["breakdown"]["R2"]["is_missing"] is True
    assert row["breakdown"]["R2"]["contribution"] == Decimal("0.0000")


def test_compute_rankings_normalizes_percent_of_max_scores():
    formula = _make_formula(missing_score_policy=RankingFormula.MissingScorePolicy.ZERO)
    qualifier = _make_assessment("Q1", max_score="40.00", sort_order=1)
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=qualifier,
        normalization_method=RankingFormulaItem.NormalizationMethod.PERCENT_OF_MAX,
        sort_order=1,
    )
    student = Student.objects.create(full_name="Alice Tan")
    StudentResult.objects.create(student=student, assessment=qualifier, raw_score=Decimal("30.00"))

    rows = compute_rankings(formula, Student.objects.filter(id=student.id))

    row = _row_for(rows, student)
    assert row["total_score"] == Decimal("75.0000")
    assert row["breakdown"]["Q1"]["normalized_score"] == Decimal("75.0000")


def test_compute_rankings_uses_fixed_scale_normalized_score_when_available():
    formula = _make_formula(missing_score_policy=RankingFormula.MissingScorePolicy.ZERO)
    mock_exam = _make_assessment("M1", max_score="40.00", sort_order=1)
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=mock_exam,
        normalization_method=RankingFormulaItem.NormalizationMethod.FIXED_SCALE,
        sort_order=1,
    )
    student = Student.objects.create(full_name="Alice Tan")
    StudentResult.objects.create(
        student=student,
        assessment=mock_exam,
        raw_score=Decimal("32.00"),
        normalized_score=Decimal("88.8888"),
    )

    rows = compute_rankings(formula, Student.objects.filter(id=student.id))

    row = _row_for(rows, student)
    assert row["total_score"] == Decimal("88.8888")
    assert row["breakdown"]["M1"]["normalized_score"] == Decimal("88.8888")


def test_compute_rank_rows_orders_ties_by_normalized_name_then_id():
    formula = _make_formula(missing_score_policy=RankingFormula.MissingScorePolicy.ZERO)
    assessment = _make_assessment("R1", sort_order=1)
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=assessment,
        weight=Decimal("1.0000"),
        sort_order=1,
    )
    student_b = Student.objects.create(full_name="Brian Tan")
    student_a = Student.objects.create(full_name="Alice Tan")
    StudentResult.objects.create(student=student_a, assessment=assessment, raw_score=Decimal("80.00"))
    StudentResult.objects.create(student=student_b, assessment=assessment, raw_score=Decimal("80.00"))

    rows = compute_rank_rows(formula, Student.objects.filter(id__in=[student_a.id, student_b.id]))

    assert [row.student_id for row in rows] == [student_a.id, student_b.id]


def test_compute_rankings_avoids_breakdown_key_collision_for_duplicate_assessment_codes():
    formula = _make_formula(missing_score_policy=RankingFormula.MissingScorePolicy.ZERO)
    assessment_current = _make_assessment("DUP", sort_order=1)
    assessment_other_season = Assessment.objects.create(
        code="DUP",
        display_name="DUP legacy",
        season_year=2027,
        category=Assessment.Category.CONTEST,
        division_scope="",
        result_type=Assessment.ResultType.SCORE,
        max_score=Decimal("100.00"),
        sort_order=2,
    )
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=assessment_current,
        weight=Decimal("1.0000"),
        sort_order=1,
    )
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=assessment_other_season,
        weight=Decimal("1.0000"),
        sort_order=2,
    )
    student = Student.objects.create(full_name="Alice Tan")
    StudentResult.objects.create(student=student, assessment=assessment_current, raw_score=Decimal("70.00"))
    StudentResult.objects.create(student=student, assessment=assessment_other_season, raw_score=Decimal("90.00"))

    rows = compute_rankings(formula, Student.objects.filter(id=student.id))
    row = _row_for(rows, student)

    assert row["total_score"] == Decimal("80.0000")
    assert "DUP" in row["breakdown"]
    assert any(key.startswith("DUP__") for key in row["breakdown"])
