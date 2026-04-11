from __future__ import annotations

from decimal import Decimal
from http import HTTPStatus

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingFormulaItem
from inspinia.rankings.models import RankingSnapshot
from inspinia.rankings.models import School
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentSelectionStatus
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _make_formula(*, name: str, season_year: int, division: str) -> RankingFormula:
    return RankingFormula.objects.create(
        name=name,
        season_year=season_year,
        division=division,
        purpose=RankingFormula.Purpose.SELECTION,
        missing_score_policy=RankingFormula.MissingScorePolicy.ZERO,
        is_active=True,
        version=1,
    )


def _attach_assessment(formula: RankingFormula, *, code: str, sort_order: int = 1) -> Assessment:
    assessment = Assessment.objects.create(
        code=code,
        display_name=code,
        season_year=formula.season_year,
        category=Assessment.Category.CONTEST,
        division_scope=formula.division,
        result_type=Assessment.ResultType.SCORE,
        sort_order=sort_order,
    )
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=assessment,
        weight=Decimal("1.0000"),
        sort_order=sort_order,
    )
    return assessment


def _snapshot(
    *,
    formula: RankingFormula,
    student: Student,
    rank: int,
    total_score: str,
    assessment: Assessment,
) -> RankingSnapshot:
    return RankingSnapshot.objects.create(
        ranking_formula=formula,
        student=student,
        season_year=formula.season_year,
        division=formula.division,
        total_score=Decimal(total_score),
        rank_overall=rank,
        rank_within_division=rank,
        score_breakdown_json={
            assessment.code: {
                "assessment_id": assessment.id,
                "assessment_code": assessment.code,
                "normalized_score": total_score,
            },
        },
        formula_version_label="v1",
        formula_version_hash="hash",
    )


def test_ranking_table_requires_login(client):
    response = client.get(reverse("rankings:ranking_table"))
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == f"{reverse(settings.LOGIN_URL)}?next={reverse('rankings:ranking_table')}"


def test_ranking_table_filters_by_school_and_division(client):
    user = UserFactory()
    client.force_login(user)

    school_a = School.objects.create(name="SMK A")
    school_b = School.objects.create(name="SMK B")
    senior_formula = _make_formula(name="Senior Formula", season_year=2026, division="senior")
    junior_formula = _make_formula(name="Junior Formula", season_year=2026, division="junior")
    senior_assessment = _attach_assessment(senior_formula, code="S1", sort_order=1)
    junior_assessment = _attach_assessment(junior_formula, code="J1", sort_order=1)

    senior_student = Student.objects.create(full_name="Alice Tan", school=school_a, state="Selangor")
    junior_student = Student.objects.create(full_name="Brian Lim", school=school_b, state="Penang")

    _snapshot(
        formula=senior_formula,
        student=senior_student,
        rank=1,
        total_score="95.0000",
        assessment=senior_assessment,
    )
    _snapshot(
        formula=junior_formula,
        student=junior_student,
        rank=1,
        total_score="88.0000",
        assessment=junior_assessment,
    )

    response = client.get(
        reverse("rankings:ranking_table"),
        {
            "division": "senior",
            "school": "SMK A",
        },
    )

    assert response.status_code == HTTPStatus.OK
    rows = response.context["ranking_rows"]
    assert len(rows) == 1
    assert rows[0]["student_name"] == "Alice Tan"
    assert rows[0]["school_name"] == "SMK A"


@override_settings(DEBUG=False)
def test_import_center_forbidden_for_non_admin(client):
    user = UserFactory(role=User.Role.NORMAL)
    client.force_login(user)

    response = client.get(reverse("rankings:import_center"))

    assert response.status_code == HTTPStatus.FORBIDDEN


@override_settings(DEBUG=False)
def test_import_center_renders_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    response = client.get(reverse("rankings:import_center"))

    assert response.status_code == HTTPStatus.OK
    assert "Import center" in response.content.decode()


def test_ranking_export_masks_nric_for_non_admin(client):
    user = UserFactory(role=User.Role.NORMAL)
    client.force_login(user)

    formula = _make_formula(name="Export Formula", season_year=2026, division="senior")
    assessment = _attach_assessment(formula, code="R1", sort_order=1)
    school = School.objects.create(name="SMK Export")
    student = Student.objects.create(
        full_name="Masked Student",
        school=school,
        full_nric="900101-01-1234",
        masked_nric="********1234",
    )
    _snapshot(
        formula=formula,
        student=student,
        rank=1,
        total_score="91.5000",
        assessment=assessment,
    )

    response = client.get(reverse("rankings:ranking_export_csv"))

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode()
    assert "900101-01-1234" not in content
    assert "1234" in content


def test_ranking_export_includes_full_nric_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    formula = _make_formula(name="Admin Export Formula", season_year=2026, division="senior")
    assessment = _attach_assessment(formula, code="R1", sort_order=1)
    student = Student.objects.create(
        full_name="Admin Student",
        full_nric="900101-01-8888",
        masked_nric="********8888",
    )
    _snapshot(
        formula=formula,
        student=student,
        rank=1,
        total_score="93.2500",
        assessment=assessment,
    )

    response = client.get(reverse("rankings:ranking_export_csv"))

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode()
    assert "900101-01-8888" in content


def test_students_assessments_formulas_and_dashboard_routes_render(client):
    user = UserFactory()
    client.force_login(user)

    formula = _make_formula(name="Routes Formula", season_year=2026, division="senior")
    assessment = _attach_assessment(formula, code="R1", sort_order=1)
    student = Student.objects.create(full_name="Route Student")
    _snapshot(
        formula=formula,
        student=student,
        rank=1,
        total_score="90.0000",
        assessment=assessment,
    )
    StudentSelectionStatus.objects.create(
        student=student,
        season_year=2026,
        division="senior",
        status=StudentSelectionStatus.Status.TEAM,
    )

    route_names = [
        "rankings:students_list",
        "rankings:student_detail",
        "rankings:assessments_list",
        "rankings:formulas_list",
        "rankings:dashboard",
    ]

    for route_name in route_names:
        if route_name == "rankings:student_detail":
            response = client.get(reverse(route_name, args=[student.id]))
        else:
            response = client.get(reverse(route_name))
        assert response.status_code == HTTPStatus.OK
