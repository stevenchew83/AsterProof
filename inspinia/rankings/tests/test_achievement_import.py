"""Synthetic-only acceptance tests for pasted source provenance and atomic imports."""

# ruff: noqa: PLR2004 - Explicit fixture values are acceptance criteria.
import copy
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.urls import reverse

from inspinia.rankings.achievement_forms import AchievementRowForm
from inspinia.rankings.achievement_forms import AchievementRows
from inspinia.rankings.imports.achievement_text import MAX_ROWS
from inspinia.rankings.imports.achievement_text import parse_achievement_text
from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import RankingCorrectionReceipt
from inspinia.rankings.models import ResultClaim
from inspinia.rankings.models import ResultProfile
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.achievement_import import apply_paste
from inspinia.rankings.services.achievement_import import prepare_paste
from inspinia.rankings.services.achievement_import import review_paste
from inspinia.rankings.services.corrections import apply_proposal
from inspinia.rankings.services.corrections import create_proposal
from inspinia.rankings.services.student_detail import build_student_detail
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return UserFactory(role=User.Role.ADMIN)


@pytest.fixture
def student():
    return Student.objects.create(full_name="Synthetic Paste Student", birth_year=2012)


def prepare(admin, student, text="2025 SASMO — Gold", **kwargs):
    return prepare_paste(
        student=student, actor=admin, source_text=text, source_label="Synthetic research",
        default_evidence=kwargs.get("default_evidence", "reported"),
    )


def review(admin, student, batch, rows=None):
    return review_paste(
        batch_id=batch.pk, student_id=student.pk, actor=admin,
        rows=copy.deepcopy(batch.summary_json["rows"]) if rows is None else rows,
    )


def apply(admin, student, batch):
    return apply_paste(
        batch_id=batch.pk, student_id=student.pk, actor=admin, nonce=batch.summary_json["review_nonce"],
    )


def test_parser_preserves_formal_awards_and_never_verifies_prose():
    parsed = parse_achievement_text(
        "Verified organizer results\n2025 IGO — Silver Ruler, 24 points\n"
        "2026 APMO — Honourable Mention, 18/35\n2025 VIMC — Individual Merit\n"
        "2025 NUS NOI — 200 points; Gold not established\n"
        "2026 Algorithm Contest — 5th place, 0 points",
    )["rows"]
    assert [(row["outcome"], row["score"]) for row in parsed[:3]] == [
        ("Silver Ruler", "24.00"), ("Honourable Mention", "18.00"), ("Individual Merit", None),
    ]
    assert all(row["evidence"] != "verified" for row in parsed)
    assert not parsed[1]["include"]  # Denominator needs review; no scale inferred.
    assert parsed[3]["outcome"] == ""
    assert not parsed[3]["include"]
    assert parsed[4]["ranking"] == "5th place"
    assert parsed[4]["score"] == "0.00"


def test_parser_family_sections_tables_ranges_and_repeated_highlights():
    parsed = parse_achievement_text(
        "Family record\n2024 APMOPS — Gold; Malaysia #1 unverified\n"
        "Documented computing\nYear\tCompetition\tAchievement\tScore\n"
        "2026\tMCO\tBronze\t104\n2026\tMCO\tBronze\t104\n"
        "2020\u20132025 SASMO — Gold\nTMC — Platinum Award",
    )
    assert parsed["rows"][0]["evidence"] == "family_pending"
    assert parsed["rows"][1]["evidence"] == "reported"
    assert parsed["rows"][1]["discipline"] == "computing"
    assert parsed["rows"][2]["year"] is None
    assert not parsed["rows"][2]["include"]
    assert parsed["rows"][3]["year"] is None
    assert parsed["warnings"]
    markdown = parse_achievement_text("| Year | Competition | Award |\n| --- | --- | --- |\n| 2025 | WMI | Silver |")
    assert markdown["rows"][0]["outcome"] == "Silver"


@pytest.mark.parametrize("text", ["", "周" * 70_000, "line\n" * 2001])
def test_parser_rejects_empty_or_oversized_sources(text):
    with pytest.raises(ValueError, match="bytes|lines"):
        parse_achievement_text(text)


def test_parser_caps_suggestions_without_expanding_aggregate_years():
    parsed = parse_achievement_text("\n".join(f"2025 Contest {number} — Gold" for number in range(81)))
    assert len(parsed["rows"]) == MAX_ROWS
    assert "remaining text" in parsed["warnings"][0]


def test_year_heading_keeps_family_provenance_and_list_numbers_are_not_rankings():
    rows = parse_achievement_text(
        "Family record (2023\u20132025)\n2024\nMathematics Contest — Gold\n"
        "2025 MMI — Gold; entry #101, candidate #12345",
    )["rows"]
    events = [row for row in rows if row["outcome"]]
    assert len(events) == 2
    assert all(row["evidence"] == "family" for row in events)
    assert events[1]["ranking"] == ""


def test_selection_in_competition_name_does_not_turn_medal_or_score_into_squad_membership():
    rows = parse_achievement_text(
        "2023 International Mathematical Olympiad National Selection Test — Gold\n"
        "2024 International Mathematical Olympiad National Selection Test — 35 points",
    )["rows"]
    assert [row["record_type"] for row in rows] == ["achievement", "performance"]


def test_explicit_unknown_year_overrides_heading_without_negating_award():
    rows = parse_achievement_text(
        "2025\nTMC — Platinum Award (year not established)\n"
        "Year\tCompetition\tAward\nYear unspecified\tWMI\tSilver\n\tKangaroo\tGold",
    )["rows"]
    assert [row["year"] for row in rows] == [None, None, None]
    assert [row["outcome"] for row in rows] == ["Platinum Award", "Silver", "Gold"]
    assert not any(row["include"] for row in rows)


def test_prepare_has_no_business_writes_and_preserves_exact_original(admin, student):
    original = "  2025 SASMO — Gold\r\n\r\n周天佑 <script>private context</script>  \n"
    batch = prepare(admin, student, original)
    assert batch.summary_json["source_text"] == original
    assert StudentResult.objects.count() == Assessment.objects.count() == ResultProfile.objects.count() == 0
    assert RankingCorrectionReceipt.objects.count() == 0
    batch = apply(admin, student, review(admin, student, batch))
    context = StudentResult.objects.get(pk=batch.summary_json["receipt"]["context_result_id"])
    assert context.remarks == original
    assert context.profile.record_type == "context"
    assert context.assessment.is_ranked_by_default is False
    claim = ResultClaim.objects.get(claim_type="award")
    assert claim.verification_status == "reported"
    assert claim.source_type == "research"
    assert RankingCorrectionReceipt.objects.count() == 1
    page = build_student_detail(student, QueryDict(), reverse("rankings:student_detail", args=[student.pk]))
    assert page["summary"]["achievements"] == 1
    assert page["summary"]["count"] == 2


def test_family_pending_conflicting_and_separate_score_ranking_claims(admin, student):
    batch = prepare(admin, student, "2024 APMOPS — Gold; Malaysia #1 unverified", default_evidence="family")
    batch = apply(admin, student, review(admin, student, batch))
    claims = ResultClaim.objects.all()
    assert claims.count() == 2
    assert set(claims.values_list("source_type", "verification_status")) == {("family", "pending")}
    assert set(claims.values_list("claim_type", flat=True)) == {"award", "ranking"}
    second = prepare(admin, student, "2026 MCO — Bronze, 0 points; conflicting source")
    apply(admin, student, review(admin, student, second))
    assert ResultClaim.objects.get(claim_type="score").claim_label == "0.00"
    assert ResultClaim.objects.get(claim_type="score").verification_status == "conflicting"
    page = build_student_detail(student, QueryDict(), reverse("rankings:student_detail", args=[student.pk]))
    award_labels = [claim["status_label"] for row in page["results"] for claim in row["claims"]]
    assert "Family record — Pending verification" in award_labels


def test_cannot_forge_verified_or_remove_family_provenance(admin, student):
    batch = prepare(admin, student, default_evidence="family")
    for status in ("verified", "reported", "pending"):
        rows = copy.deepcopy(batch.summary_json["rows"])
        rows[0]["evidence"] = status
        with pytest.raises(ValueError, match="Row 1"):
            review(admin, student, batch, rows)
    assert not ResultClaim.objects.exists()


def test_existing_verified_result_is_linked_without_changing_results_or_reviews(admin, student):
    assessment = Assessment.objects.create(code="SASMO2025", display_name="SASMO 2025", season_year=2025)
    result = StudentResult.objects.create(student=student, assessment=assessment, medal="Silver")
    proposal = create_proposal(
        actor=admin, reason="Synthetic verified evidence", evidence="Checked synthetic certificate", submit=True,
        operations=[{"kind": "claim", "target_id": result.pk, "values": {
            "claim_type": "award", "claim_label": "Silver", "verification_status": "verified",
            "source_type": "organizer", "source_label": "Synthetic organizer",
        }}],
    )
    apply_proposal(proposal_id=proposal.pk, actor=admin)
    before_result = StudentResult.objects.filter(pk=result.pk).values().get()
    before_claim = ResultClaim.objects.values().get()
    batch = prepare(admin, student)
    assert batch.summary_json["rows"][0]["existing_result"] == str(result.pk)
    applied = apply(admin, student, review(admin, student, batch))
    assert applied.summary_json["receipt"]["linked_result_ids"] == [result.pk]
    assert applied.summary_json["receipt"]["created_result_ids"] == []
    assert StudentResult.objects.filter(pk=result.pk).values().get() == before_result
    assert ResultClaim.objects.values().get() == before_claim
    assert StudentResult.objects.count() == 2


def test_duplicates_cross_student_links_and_missing_suggestions_are_rejected(admin, student):
    batch = prepare(admin, student)
    rows = copy.deepcopy(batch.summary_json["rows"])
    with pytest.raises(ValueError, match="duplicate event"):
        review(admin, student, batch, rows + rows)
    other = Student.objects.create(full_name="Other Synthetic Student")
    assessment = Assessment.objects.create(code="OTHER", season_year=2025)
    other_result = StudentResult.objects.create(student=other, assessment=assessment)
    rows[0]["existing_result"] = str(other_result.pk)
    with pytest.raises(ValueError, match="Row 1"):
        review(admin, student, batch, rows)
    with pytest.raises(ValueError, match="Review all"):
        review(admin, student, batch, [])


def test_stale_record_or_evidence_stops_atomic_import(admin, student):
    prior = apply(admin, student, review(admin, student, prepare(admin, student)))
    batch = review(admin, student, prepare(admin, student, "2026 MCO — Bronze"))
    claim = ResultClaim.objects.first()
    claim.evidence = "A later review"
    claim.save()
    with pytest.raises(ValueError, match="changed after review"):
        apply(admin, student, batch)
    assert StudentResult.objects.count() == 2
    assert RankingCorrectionReceipt.objects.count() == 1
    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.PREVIEWED
    assert prior.status == ImportBatch.Status.APPLIED


def test_nonce_replay_duplicate_source_and_transaction_rollback(admin, student):
    batch = review(admin, student, prepare(admin, student))
    old_nonce = batch.summary_json["review_nonce"]
    batch = review(admin, student, batch)
    with pytest.raises(ValueError, match="superseded"):
        apply_paste(batch_id=batch.pk, student_id=student.pk, actor=admin, nonce=old_nonce)
    with (
        patch("inspinia.rankings.services.achievement_import.apply_proposal", side_effect=ValidationError("Rejected")),
        pytest.raises(ValueError, match="Rejected"),
    ):
        apply(admin, student, batch)
    assert not StudentResult.objects.exists()
    assert not Assessment.objects.exists()
    assert not RankingCorrectionReceipt.objects.exists()
    batch = apply(admin, student, batch)
    with pytest.raises(ValueError, match="consumed"):
        apply(admin, student, batch)
    assert prepare(admin, student).pk == batch.pk
    another_admin = UserFactory(role=User.Role.ADMIN)
    second = review(another_admin, student, prepare(another_admin, student))
    with pytest.raises(ValueError, match="already imported"):
        apply(another_admin, student, second)


def test_unparsed_text_can_be_explicitly_imported_as_context_only(admin, student):
    batch = prepare(admin, student, "Undated training memories.\nOriginal narrative retained.")
    assert batch.summary_json["rows"] == []
    batch = apply(admin, student, review(admin, student, batch, []))
    assert batch.summary_json["receipt"]["created_result_ids"] == []
    assert StudentResult.objects.count() == 1
    assert not ResultClaim.objects.exists()


def formset_post(rows):
    data = {"rows-TOTAL_FORMS": str(len(rows)), "rows-INITIAL_FORMS": str(len(rows))}
    for index, row in enumerate(rows):
        data.update({f"rows-{index}-{key}": value for key, value in row.items() if value is not None})
    return data


def test_formset_bounds_and_excluded_invalid_rows():
    form = AchievementRowForm({"include": "", "year": "not a year", "score": "bad"})
    assert form.is_valid()
    assert form.cleaned_data == {"include": False}
    forms = AchievementRows({"rows-TOTAL_FORMS": "81", "rows-INITIAL_FORMS": "0"}, prefix="rows")
    assert not forms.is_valid()


@pytest.mark.parametrize("role", [User.Role.NORMAL, User.Role.TRAINER, User.Role.MODERATOR])
def test_import_is_admin_only_for_views_and_services(client, student, role):
    user = UserFactory(role=role)
    client.force_login(user)
    url = reverse("rankings:achievement_text_import", args=[student.pk])
    assert client.get(url).status_code == 403
    assert client.post(url, {"action": "preview"}).status_code == 403
    with pytest.raises(PermissionDenied):
        prepare(user, student)


def test_full_web_flow_has_confirmation_escaping_and_owner_scoping(client, admin, student):
    url = reverse("rankings:achievement_text_import", args=[student.pk])
    assert client.get(url).status_code == 302
    client.force_login(admin)
    assert client.get(url).status_code == 200
    response = client.post(url, {
        "action": "preview", "source_label": "Synthetic family note", "default_evidence": "family",
        "source_text": "2025 SASMO — Gold\n<script>alert('source')</script>",
    })
    assert response.status_code == 302
    assert not StudentResult.objects.exists()
    batch = ImportBatch.objects.get()
    response = client.get(f"{url}?batch={batch.pk}")
    assert response.context["stage"] == "edit"
    assert b"&lt;script&gt;" in response.content
    assert b"<script>alert('source')" not in response.content
    data = formset_post(batch.summary_json["rows"])
    response = client.post(url, {"action": "review", "batch_id": batch.pk, **data})
    assert response.status_code == 302
    batch.refresh_from_db()
    final = client.get(response.url)
    assert final.context["stage"] == "review"
    assert b"Family record" in final.content
    assert b"Import reviewed records" in final.content
    response = client.post(url, {"action": "apply", "batch_id": batch.pk, "nonce": batch.summary_json["review_nonce"]})
    assert response.status_code == 200
    assert not StudentResult.objects.exists()
    response = client.post(url, {
        "action": "apply", "batch_id": batch.pk, "nonce": batch.summary_json["review_nonce"], "confirm": "yes",
    })
    assert response.status_code == 302
    receipt = client.get(response.url)
    assert receipt.context["stage"] == "receipt"
    assert ResultClaim.objects.get().source_type == "family"
    profile = client.get(reverse("rankings:student_detail", args=[student.pk]))
    assert b"Paste achievements" in profile.content
    client.force_login(UserFactory(role=User.Role.ADMIN))
    assert client.get(f"{url}?batch={batch.pk}").status_code == 404
    assert client.post(reverse("rankings:import_center"), {
        "action": "assessment_result_apply", "batch_id": batch.pk,
    }).status_code == 404


def test_no_automatic_new_record_when_existing_event_link_is_cleared(admin, student):
    assessment = Assessment.objects.create(code="SASMO", display_name="SASMO", season_year=2025)
    StudentResult.objects.create(student=student, assessment=assessment, medal="Gold")
    batch = prepare(admin, student)
    rows = copy.deepcopy(batch.summary_json["rows"])
    rows[0]["existing_result"] = ""
    with pytest.raises(ValueError, match="already exist"):
        review(admin, student, batch, rows)


def test_manual_row_and_ambiguous_year_require_review(admin, student):
    batch = prepare(admin, student, "2020\u20132025 SASMO — Gold")
    row = copy.deepcopy(batch.summary_json["rows"][0])
    row["include"] = True
    with pytest.raises(ValueError, match="year"):
        review(admin, student, batch, [row])
    row.update(year=2024, outcome="Silver", evidence="pending")
    manual = {
        "include": True, "year": 2023, "title": "Synthetic piano award", "outcome": "Bronze",
        "record_type": "achievement", "discipline": "music", "evidence": "family",
    }
    batch = apply(admin, student, review(admin, student, batch, [row, manual]))
    assert len(batch.summary_json["receipt"]["created_result_ids"]) == 2
    assert set(ResultClaim.objects.values_list("source_type", "verification_status")) == {
        ("research", "pending"), ("family", "reported"),
    }


def test_student_change_invalidates_confirmation_and_wrong_batch_is_not_importable(admin, student):
    batch = review(admin, student, prepare(admin, student))
    student.full_name = "Revised Synthetic Student"
    student.save()
    with pytest.raises(ValueError, match="changed after review"):
        apply(admin, student, batch)
    batch.summary_json["kind"] = "other_import"
    batch.save()
    with pytest.raises(ValueError, match="not an achievement paste"):
        apply(admin, student, batch)
    assert not StudentResult.objects.exists()


def test_import_requires_csrf_and_hides_action_from_moderators(client, admin, student):
    from django.test import Client

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin)
    url = reverse("rankings:achievement_text_import", args=[student.pk])
    assert csrf_client.post(url, {"action": "preview"}).status_code == 403
    client.force_login(UserFactory(role=User.Role.MODERATOR))
    response = client.get(reverse("rankings:student_detail", args=[student.pk]))
    assert response.status_code == 200
    assert b"Paste achievements" not in response.content
