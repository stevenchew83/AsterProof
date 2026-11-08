import pytest
from django.contrib import admin as django_admin
from django.test import RequestFactory
from django.urls import reverse

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingFormulaItem
from inspinia.rankings.models import RankingSnapshot
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.corrections import apply_proposal
from inspinia.rankings.services.corrections import create_proposal
from inspinia.rankings.services.ranking_compute import compute_rank_rows
from inspinia.rankings.services.ranking_snapshot_store import store_ranking_snapshots
from inspinia.rankings.services.snapshot_freshness import snapshot_freshness
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_corrections_flag_existing_snapshots_without_recomputing_or_deleting(client):
    actor = UserFactory(role=User.Role.ADMIN)
    student = Student.objects.create(full_name="Synthetic snapshot student")
    assessment = Assessment.objects.create(code="FRESH", display_name="Synthetic", category="test", season_year=2026)
    result = StudentResult.objects.create(student=student, assessment=assessment, raw_score=10)
    formula = RankingFormula.objects.create(name="Synthetic formula", season_year=2026)
    RankingFormulaItem.objects.create(ranking_formula=formula, assessment=assessment)
    store_ranking_snapshots(formula=formula, rows=compute_rank_rows(formula, [student]))
    assert not snapshot_freshness(formula)["snapshots_stale"]
    before = list(RankingSnapshot.objects.values())
    change = create_proposal(
        actor=actor,
        reason="Supported score correction",
        evidence="Synthetic source",
        submit=True,
        operations=[{"kind": "result", "target_id": result.pk, "values": {"raw_score": "12"}}],
    )
    apply_proposal(proposal_id=change.pk, actor=actor)
    assert snapshot_freshness(formula)["snapshots_stale"]
    assert list(RankingSnapshot.objects.values()) == before
    client.force_login(actor)
    for name in ("ranking_table", "dashboard"):
        response = client.get(reverse(f"rankings:{name}"), {"formula": formula.pk})
        assert b"Computed ranking may need a refresh" in response.content
    store_ranking_snapshots(formula=formula, rows=compute_rank_rows(formula, [student]))
    assert not snapshot_freshness(formula)["snapshots_stale"]


def test_existing_admin_records_route_reviewed_fields_to_correction_workflow():
    actor = UserFactory(role=User.Role.ADMIN)
    student = Student.objects.create(full_name="Synthetic admin student")
    request = RequestFactory().get("/admin/")
    request.user = actor
    model_admin = django_admin.site._registry[Student]  # noqa: SLF001 - Registered Django admin contract.
    assert {"full_name", "birth_year", "school", "reviewed_correction"}.issubset(
        model_admin.get_readonly_fields(request, student),
    )
    assert "kind=student" in str(model_admin.reviewed_correction(student))
    assert "target=" + str(student.pk) in str(model_admin.reviewed_correction(student))
