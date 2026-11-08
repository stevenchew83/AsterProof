"""Achievement presentation never promotes imported claims into verified evidence."""

# ruff: noqa: PLR2004 - Explicit fixture counts and values are acceptance criteria.
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.urls import reverse

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ResultClaim
from inspinia.rankings.models import ResultProfile
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.corrections import StaleCorrection
from inspinia.rankings.services.corrections import apply_proposal
from inspinia.rankings.services.corrections import create_proposal
from inspinia.rankings.services.corrections import reverse_proposal
from inspinia.rankings.services.corrections import transition_proposal
from inspinia.rankings.services.student_detail import build_student_detail
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return UserFactory(role=User.Role.ADMIN)


@pytest.fixture
def result():
    student = Student.objects.create(full_name="Synthetic Student", birth_year=2012)
    assessment = Assessment.objects.create(code="APMOPS", display_name="APMOPS", season_year=2024)
    return StudentResult.objects.create(student=student, assessment=assessment, medal="Gold", raw_score=35)


def profile_page(result, query=""):
    return build_student_detail(
        result.student, QueryDict(query), reverse("rankings:student_detail", args=[result.student_id]),
    )


def review(actor, result, kind, values, evidence="Identified synthetic certificate and result checked."):
    proposal = create_proposal(
        actor=actor,
        reason="Review synthetic result",
        evidence=evidence,
        operations=[{"kind": kind, "target_id": result.pk, "values": values}],
        submit=True,
    )
    apply_proposal(proposal_id=proposal.pk, actor=actor)
    return proposal


def award_values(**changes):
    return {
        "claim_type": "award",
        "claim_label": "Gold",
        "award_kind": "medal",
        "verification_status": "verified",
        "source_type": "organizer",
        "source_label": "Synthetic organizer certificate",
        "active": True,
        **changes,
    }


def test_default_achievements_separates_scores_context_and_categories(result):
    for code, values in [
        ("SCORE", {"raw_score": 17, "band": "Junior"}),
        ("PARTICIPATION", {"status_text": "Participation", "band": "Primary"}),
        ("ACHIEVEMENT_CONTEXT_2026", {"status_text": "Source Context; Verification Mixed"}),
        ("SELECTION_2026_08", {"status_text": "SQUAD"}),
    ]:
        assessment = Assessment.objects.create(code=code, display_name=code, season_year=2026)
        StudentResult.objects.create(student=result.student, assessment=assessment, **values)
    context = profile_page(result)
    assert context["kind"] == "achievements"
    assert [row["id"] for row in context["page_obj"]] == [result.pk]
    assert context["summary"]["count"] == 5
    assert context["summary"]["achievements"] == 1
    assert context["timeline_count"] == 1
    assert profile_page(result, "type=sources")["page_obj"].paginator.count == 1
    assert profile_page(result, "type=all")["page_obj"].paginator.count == 5
    assert profile_page(result, "type=scores")["page_obj"].paginator.count == 3
    assert profile_page(result, "type=outcomes")["kind"] == "achievements"
    assert profile_page(result, "type=groups&year=2024")["timeline_count"] == 0


def test_source_prose_and_links_cannot_verify_a_claim(result):
    result.remarks = "Evidence: verified in earlier research; organizer results confirmed."
    result.source_url = "https://example.com/results"
    result.save()
    row = profile_page(result)["results"][0]
    assert row["evidence_status"] == "unreviewed"
    assert row["outcomes"] == [{"label": "Gold", "tone": "neutral"}]
    assert not profile_page(result)["highlights"]


def test_review_preview_is_read_only_and_moderator_cannot_apply(result, admin):
    moderator = UserFactory(role=User.Role.MODERATOR)
    proposal = create_proposal(
        actor=moderator,
        reason="Classify result",
        evidence="Source record",
        operations=[
            {
                "kind": "profile",
                "target_id": result.pk,
                "values": {
                    "record_type": "achievement",
                    "discipline": "mathematics",
                    "scope": "regional",
                    "scope_detail": "Kedah-Perlis",
                    "participation": "individual",
                    "active": True,
                },
            },
        ],
        submit=True,
    )
    assert not ResultProfile.objects.exists()
    with pytest.raises(PermissionDenied):
        apply_proposal(proposal_id=proposal.pk, actor=moderator)
    apply_proposal(proposal_id=proposal.pk, actor=admin)
    proposal.refresh_from_db()
    assert proposal.receipt.actor == admin
    row = profile_page(result)["results"][0]
    assert row["classification_reviewed"]
    assert row["scope_detail"] == "Kedah-Perlis"
    assert profile_page(result, "discipline=mathematics")["page_obj"].paginator.count == 1
    assert profile_page(result, "discipline=computing")["page_obj"].paginator.count == 0


def test_award_score_and_rank_have_independent_evidence(result, admin):
    review(admin, result, "claim", award_values())
    review(
        admin,
        result,
        "claim",
        {
            "claim_type": "ranking",
            "claim_label": "Malaysia #1",
            "verification_status": "pending",
            "source_type": "family",
            "active": True,
        },
    )
    context = profile_page(result)
    row = context["results"][0]
    claims = {claim["kind"]: claim for claim in row["claims"]}
    assert claims["award"]["status"] == "verified"
    assert claims["ranking"]["status"] == "pending"
    assert claims["score"]["status"] == "unreviewed"
    assert row["outcomes"] == [{"label": "Gold", "tone": "gold"}]
    assert profile_page(result, "evidence=pending")["page_obj"].paginator.count == 1
    assert profile_page(result, "evidence=verified")["page_obj"].paginator.count == 1
    assert ResultClaim.objects.count() == 2


@pytest.mark.parametrize(
    ("changes", "evidence"),
    [
        ({"source_type": "unknown"}, "Checked"),
        ({"source_type": "family"}, "Checked"),
        ({"source_type": "research"}, "Checked"),
        ({"source_label": "", "source_url": ""}, "Checked"),
        ({}, ""),
        ({"source_url": "javascript:alert(1)"}, "Checked"),
        ({"source_url": "https://user:secret@example.com/results"}, "Checked"),
    ],
)
def test_verification_requires_identifiable_safe_evidence(result, admin, changes, evidence):
    with pytest.raises(ValidationError):
        review(admin, result, "claim", award_values(**changes), evidence=evidence)
    assert not ResultClaim.objects.exists()


def test_score_evidence_must_match_recorded_value(result, admin):
    values = award_values(claim_type="score", claim_label="200/200", award_kind="unknown")
    with pytest.raises(ValidationError, match="raw score"):
        review(admin, result, "claim", values)
    values["claim_label"] = "35.00"
    review(admin, result, "claim", values)
    row = profile_page(result)["results"][0]
    assert row["evidence_status"] == "unreviewed"
    assert next(c for c in row["claims"] if c["kind"] == "score")["status"] == "verified"
    assert not row["featured"]
    charts = profile_page(result)["charts"]
    assert next(item["count"] for item in charts["evidence"] if item["value"] == "verified") == 0
    assert profile_page(result, "evidence=achievement_verified")["match_count"] == 0
    assert profile_page(result, "evidence=achievement_unreviewed")["match_count"] == 1


def test_noop_reimport_preserves_reviews_and_changed_provenance_invalidates(result, admin):
    review(admin, result, "profile", {"record_type": "achievement", "featured": True, "active": True})
    review(admin, result, "claim", award_values())
    result.save()
    assert profile_page(result)["highlights"][0]["id"] == result.pk
    result.remarks = "Different source evidence"
    result.save()
    row = profile_page(result)["results"][0]
    assert row["classification_stale"]
    assert row["evidence_status"] == "pending"
    assert all(claim["status"] != "verified" for claim in row["claims"])
    assert not profile_page(result)["highlights"]
    # Reconfirming the same classification is a real review after source drift.
    assert profile_page(result, "evidence=achievement_pending")["match_count"] == 1
    review(admin, result, "profile", {"record_type": "achievement", "featured": True, "active": True})
    review(admin, result, "claim", award_values())
    assert profile_page(result)["highlights"][0]["id"] == result.pk


def test_result_change_after_preview_refuses_entire_review(result, admin):
    proposal = create_proposal(
        actor=admin,
        reason="Verify award",
        evidence="Certificate",
        operations=[{"kind": "claim", "target_id": result.pk, "values": award_values()}],
        submit=True,
    )
    result.raw_score = Decimal("36")
    result.save()
    with pytest.raises(StaleCorrection):
        apply_proposal(proposal_id=proposal.pk, actor=admin)
    assert not ResultClaim.objects.exists()
    assert not hasattr(proposal, "receipt")


def test_family_claims_are_neutral_and_never_featured(result, admin):
    result.medal = ""
    result.status_text = "Family-reported Gold"
    result.save()
    review(admin, result, "profile", {"record_type": "achievement", "featured": True, "active": True})
    review(admin, result, "claim", award_values(verification_status="reported", source_type="family"))
    row = profile_page(result)["results"][0]
    assert row["outcomes"] == [{"label": "Gold", "tone": "neutral"}]
    assert not row["featured"]


def test_reversal_keeps_original_result_and_review_receipt(result, admin):
    original = review(admin, result, "claim", award_values())
    reversal = reverse_proposal(proposal_id=original.pk, actor=admin, reason="Withdraw unsupported review")
    transition_proposal(proposal_id=reversal.pk, actor=admin, action="submit")
    apply_proposal(proposal_id=reversal.pk, actor=admin)
    assert not ResultClaim.objects.get(result=result).active
    result.refresh_from_db()
    assert result.medal == "Gold"
    assert profile_page(result)["results"][0]["evidence_status"] == "unreviewed"
    assert original.receipt


def test_explicit_classification_overrides_fallback_without_rewriting_result(result, admin):
    review(admin, result, "profile", {"record_type": "context", "active": True})
    assert profile_page(result)["page_obj"].paginator.count == 0
    assert profile_page(result, "type=sources")["page_obj"].paginator.count == 1
    result.refresh_from_db()
    assert result.medal == "Gold"
    assert result.raw_score == 35
    with pytest.raises(ValidationError, match="Only achievement"):
        review(admin, result, "profile", {"record_type": "context", "featured": True, "active": True})


def test_year_pagination_never_splits_a_year(result):
    result.delete()
    for year, count in [(2026, 40), (2025, 30), (2024, 4)]:
        for index in range(count):
            assessment = Assessment.objects.create(code=f"Y{year}_{index}", display_name="Contest", season_year=year)
            StudentResult.objects.create(student=result.student, assessment=assessment, medal="Gold")
    first, second = profile_page(result), profile_page(result, "page=2")
    assert len(first["page_obj"]) == 70
    assert [group["year"] for group in first["year_groups"]] == [2026, 2025]
    assert first["page_obj"].end_index() == 70
    assert second["page_obj"].start_index() == 71
    assert len(second["page_obj"]) == 4
    assert second["page_obj"].paginator.count == 74
    assert first["charts"] == second["charts"]
    assert second["charts"]["total"] == 74
    assert [(year["year"], year["count"]) for year in second["charts"]["years"]] == [
        (2024, 4), (2025, 30), (2026, 40),
    ]
    filtered = profile_page(result, "year=2024")
    assert filtered["charts"]["total"] == filtered["match_count"] == 4


def test_profile_navigation_full_width_details_and_review_forms(client, result, admin):
    client.force_login(admin)
    url = reverse("rankings:student_detail", args=[result.student_id])
    html = client.get(url).content.decode()
    assert 'data-student-view="achievements" aria-current="page"' in html
    assert 'id="student-col-score"' not in html
    assert '<td colspan="4"><details class="student-record"' in html
    assert f'<details class="student-record" id="student-record-{result.pk}">' in html
    assert "<summary>Evidence &amp; context" in html
    assert "Import history &amp; original values" in html
    assert "Not reviewed" in html
    assert "import file" in html
    assert 'data-student-chart-filter="year-2024"' in html
    assert "evidence=achievement_unreviewed" in html
    assert "Score reviews are separate" in html
    score_html = client.get(url, {"type": "scores"}).content.decode()
    assert 'id="student-col-score"' in score_html
    assert '<td colspan="5"><details class="student-record"' in score_html
    for kind in ["achievements", "scores", "groups", "all", "sources"]:
        view_response = client.get(url, {"type": kind})
        view_html = view_response.content.decode()
        assert '<details id="student-profile-details"' in view_html
        assert 'class="student-year-label"' in view_html or kind in {"groups", "sources"}
        assert "data-year-toggle" not in view_html
        assert "data-record-toggle" not in view_html
        assert "data-default-open" not in view_html
        assert view_response.context["show_charts"] == (kind == "achievements")
    for kind, extra in [("profile", {}), ("claim", {"claim_type": "score"})]:
        response = client.get(reverse("rankings:correction_new"), {"kind": kind, "target": result.pk, **extra})
        assert response.status_code == 200
    assert not ResultProfile.objects.exists()
    assert not ResultClaim.objects.exists()


def test_non_medal_awards_keep_formal_names_without_medal_coloring(result, admin):
    review(admin, result, "claim", award_values(claim_label="Silver Ruler", award_kind="distinction"))
    row = profile_page(result)["results"][0]
    assert row["outcomes"] == [{"label": "Silver Ruler", "tone": "neutral"}]
    assert row["primary_claim"]["award_kind_label"] == "Distinction / special award"


def test_database_rejects_verified_evidence_without_source_and_featured_nonachievement(result):
    from django.db import IntegrityError
    from django.db import transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        ResultClaim.objects.create(result=result, claim_type="award", claim_label="Gold",
                                   verification_status="verified", result_fingerprint="a" * 64)
    with pytest.raises(IntegrityError), transaction.atomic():
        ResultProfile.objects.create(result=result, record_type="performance", featured=True,
                                     result_fingerprint="a" * 64)


def test_real_import_preserves_claims_and_invalidates_only_changed_content(result, admin):
    import pandas as pd

    from inspinia.rankings.imports.assessment_result_import import apply_assessment_result_import
    from inspinia.rankings.models import ImportBatch

    result.source_file_name = "same.csv"
    result.save()
    review(admin, result, "claim", award_values())
    for score, expected in [(35, "verified"), (36, "pending")]:
        batch = ImportBatch.objects.create(import_type="assessment_results", original_filename="same.csv")
        imported = apply_assessment_result_import(
            pd.DataFrame([{"student_identifier": result.student.full_name, "raw_score": score, "medal": "Gold"}]),
            batch=batch, assessment=result.assessment, imported_by=admin, source_file_name="same.csv",
        )
        assert imported.upserted_count == 1
        assert profile_page(result)["results"][0]["evidence_status"] == expected
        assert ResultClaim.objects.filter(result=result).count() == 1


@pytest.mark.parametrize(("role", "expected"), [(None, 302), (User.Role.NORMAL, 403),
                                                (User.Role.MODERATOR, 200), (User.Role.ADMIN, 200)])
def test_profile_review_forms_keep_existing_role_boundary(client, result, role, expected):
    if role:
        client.force_login(UserFactory(role=role))
    for kind in ("profile", "claim"):
        response = client.get(reverse("rankings:correction_new"), {"kind": kind, "target": result.pk})
        assert response.status_code == expected
    assert not ResultProfile.objects.exists()
    assert not ResultClaim.objects.exists()


def test_targeted_review_form_does_not_render_unrelated_result_archive(client, result, admin):
    other = Student.objects.create(full_name="Unrelated archive student")
    StudentResult.objects.create(student=other, assessment=result.assessment, medal="Silver")
    client.force_login(admin)
    response = client.get(reverse("rankings:correction_new"), {"kind": "profile", "target": result.pk})
    assert list(response.context["targets"]) == [result]
    assert b"Unrelated archive student" not in response.content


def test_verified_rank_cannot_verify_or_feature_an_unreviewed_medal(result, admin):
    review(admin, result, "profile", {"record_type": "achievement", "featured": True, "active": True})
    review(admin, result, "claim", award_values(claim_type="ranking", claim_label="Malaysia #1", award_kind="unknown"))
    row = profile_page(result)["results"][0]
    assert row["primary_claim"]["kind"] == "award"
    assert row["evidence_status"] == "unreviewed"
    assert row["outcomes"] == [{"label": "Gold", "tone": "neutral"}]
    assert not profile_page(result)["highlights"]
    assert {claim["kind"]: claim["status"] for claim in row["claims"]} == {
        "ranking": "verified", "award": "unreviewed", "score": "unreviewed",
    }


def test_ranking_only_achievement_displays_the_reviewed_placing(result, admin):
    result.medal, result.raw_score = "", None
    result.save()
    review(admin, result, "profile", {"record_type": "achievement", "featured": True, "active": True})
    review(admin, result, "claim", award_values(claim_type="ranking", claim_label="5th Place", award_kind="unknown"))
    row = profile_page(result)["results"][0]
    assert row["outcomes"] == [{"label": "5th Place", "tone": "neutral"}]
    assert row["primary_claim"]["kind"] == "ranking"
    assert row["evidence_status"] == "verified"
    assert profile_page(result)["highlights"][0]["id"] == result.pk
    assert profile_page(result, "evidence=achievement_verified")["match_count"] == 1
