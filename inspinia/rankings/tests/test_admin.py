from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib import messages
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore

from inspinia.rankings.admin import RankingFormulaAdmin
from inspinia.rankings.models import Assessment
from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingFormulaItem
from inspinia.rankings.models import RankingSnapshot
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.ranking_compute import compute_rank_rows
from inspinia.rankings.services.ranking_snapshot_store import store_ranking_snapshots

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


def _make_formula(name: str, *, season_year: int = 2026, division: str = "senior") -> RankingFormula:
    return RankingFormula.objects.create(
        name=name,
        season_year=season_year,
        division=division,
        purpose=RankingFormula.Purpose.SELECTION,
        missing_score_policy=RankingFormula.MissingScorePolicy.ZERO,
    )


def _attach_assessment(formula: RankingFormula, assessment: Assessment, *, sort_order: int = 1) -> None:
    RankingFormulaItem.objects.create(
        ranking_formula=formula,
        assessment=assessment,
        weight=Decimal("1.0000"),
        sort_order=sort_order,
    )


def _build_action_request(rf, admin_user):
    request = rf.post("/admin/rankings/rankingformula/")
    request.user = admin_user
    request.session = SessionStore()
    request._messages = FallbackStorage(request)  # noqa: SLF001
    return request


def test_recompute_selected_formulas_clears_snapshots_for_empty_formula(rf, admin_user):
    formula = _make_formula("Selection Formula")
    assessment = _make_assessment("R1", sort_order=1)
    _attach_assessment(formula, assessment)
    student = Student.objects.create(full_name="Alice Tan", active=True)
    StudentResult.objects.create(student=student, assessment=assessment, raw_score=Decimal("87.00"))
    rows = compute_rank_rows(formula=formula, students=Student.objects.filter(active=True))
    store_ranking_snapshots(formula=formula, rows=rows)
    assert RankingSnapshot.objects.filter(ranking_formula=formula).count() == 1

    formula.items.all().delete()

    request = _build_action_request(rf=rf, admin_user=admin_user)
    admin_instance = RankingFormulaAdmin(RankingFormula, AdminSite())
    admin_instance.recompute_selected_formulas(request, RankingFormula.objects.filter(id=formula.id))

    assert RankingSnapshot.objects.filter(ranking_formula=formula).count() == 0
    stored_messages = list(request._messages)  # noqa: SLF001
    message_texts = [str(message) for message in stored_messages]
    assert any("cleared 1 existing snapshot(s)" in message for message in message_texts)
    assert any("Recomputed 0 formula(s), stored 0 snapshot(s)." in message for message in message_texts)

    warning_levels = [message.level for message in stored_messages]
    assert messages.WARNING in warning_levels
