from __future__ import annotations

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingFormulaItem
from inspinia.rankings.models import RankingSnapshot
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult

pytestmark = pytest.mark.django_db


def _make_assessment(code: str, *, season_year: int = 2026, sort_order: int = 0) -> Assessment:
    return Assessment.objects.create(
        code=code,
        display_name=code,
        season_year=season_year,
        category=Assessment.Category.CONTEST,
        division_scope="",
        result_type=Assessment.ResultType.SCORE,
        sort_order=sort_order,
    )


def _make_formula(
    name: str,
    *,
    season_year: int = 2026,
    division: str = "",
    is_active: bool = True,
    version: int = 1,
) -> RankingFormula:
    return RankingFormula.objects.create(
        name=name,
        season_year=season_year,
        division=division,
        purpose=RankingFormula.Purpose.OVERALL,
        missing_score_policy=RankingFormula.MissingScorePolicy.ZERO,
        is_active=is_active,
        version=version,
    )


def _attach_assessment(formula: RankingFormula, assessment: Assessment, *, sort_order: int = 1) -> None:
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=assessment,
        weight=Decimal("1.0000"),
        sort_order=sort_order,
    )


def test_recompute_rankings_command_recomputes_single_formula():
    formula = _make_formula("Senior Overall", division="senior")
    assessment = _make_assessment("R1", sort_order=1)
    _attach_assessment(formula, assessment)
    alice = Student.objects.create(full_name="Alice Tan", active=True)
    Student.objects.create(full_name="Inactive Student", active=False)
    StudentResult.objects.create(student=alice, assessment=assessment, raw_score=Decimal("88.00"))

    stdout = StringIO()
    call_command("recompute_rankings", "--formula", str(formula.id), stdout=stdout)

    snapshots = list(RankingSnapshot.objects.filter(ranking_formula=formula).order_by("rank_overall"))
    assert [snapshot.student_id for snapshot in snapshots] == [alice.id]
    assert snapshots[0].season_year == formula.season_year
    assert snapshots[0].division == "senior"
    assert snapshots[0].total_score == Decimal("88.0000")
    assert snapshots[0].rank_overall == 1
    assert snapshots[0].rank_within_division == 1
    assert snapshots[0].formula_version_label == "v1"
    assert snapshots[0].formula_version_hash
    assert snapshots[0].score_breakdown_json["R1"]["normalized_score"] == "88.0000"
    assert "Recomputed 1 formula(s), stored 1 snapshot(s)." in stdout.getvalue()


def test_recompute_rankings_command_filters_active_formulas_by_season_and_division():
    senior_formula = _make_formula("Senior Overall", season_year=2026, division="senior", is_active=True)
    junior_formula = _make_formula("Junior Overall", season_year=2026, division="junior", is_active=True)
    inactive_formula = _make_formula("Senior Old", season_year=2026, division="senior", is_active=False, version=2)
    next_year_formula = _make_formula("Senior Future", season_year=2027, division="senior", is_active=True)
    senior_assessment = _make_assessment("S1", season_year=2026, sort_order=1)
    junior_assessment = _make_assessment("J1", season_year=2026, sort_order=2)
    future_assessment = _make_assessment("F1", season_year=2027, sort_order=3)
    _attach_assessment(senior_formula, senior_assessment, sort_order=1)
    _attach_assessment(junior_formula, junior_assessment, sort_order=1)
    _attach_assessment(inactive_formula, senior_assessment, sort_order=1)
    _attach_assessment(next_year_formula, future_assessment, sort_order=1)
    student = Student.objects.create(full_name="Alice Tan", active=True)
    StudentResult.objects.create(student=student, assessment=senior_assessment, raw_score=Decimal("91.00"))
    StudentResult.objects.create(student=student, assessment=junior_assessment, raw_score=Decimal("77.00"))
    StudentResult.objects.create(student=student, assessment=future_assessment, raw_score=Decimal("99.00"))

    stdout = StringIO()
    call_command(
        "recompute_rankings",
        "--season",
        "2026",
        "--division",
        "senior",
        stdout=stdout,
    )

    assert RankingSnapshot.objects.filter(ranking_formula=senior_formula).count() == 1
    assert RankingSnapshot.objects.filter(ranking_formula=junior_formula).count() == 0
    assert RankingSnapshot.objects.filter(ranking_formula=inactive_formula).count() == 0
    assert RankingSnapshot.objects.filter(ranking_formula=next_year_formula).count() == 0
    assert "Recomputed 1 formula(s), stored 1 snapshot(s)." in stdout.getvalue()
