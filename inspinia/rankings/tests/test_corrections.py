from decimal import Decimal
from http import HTTPStatus

import pytest
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.urls import reverse

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import AssessmentAnalysisMetadata
from inspinia.rankings.models import AssessmentCategoryScale
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import OutcomeAlias
from inspinia.rankings.models import RankingCorrectionReceipt
from inspinia.rankings.models import RankingImportConflict
from inspinia.rankings.models import ResultSchoolAttribution
from inspinia.rankings.models import School
from inspinia.rankings.models import SchoolAlias
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentIdentityReview
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.corrections import StaleCorrection
from inspinia.rankings.services.corrections import apply_proposal
from inspinia.rankings.services.corrections import create_proposal
from inspinia.rankings.services.corrections import resolve_import_conflict
from inspinia.rankings.services.corrections import reverse_proposal
from inspinia.rankings.services.corrections import transition_proposal
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

ORIGINAL_BIRTH_YEAR = 2012
EXPECTED_PAIR_SIZE = 2

pytestmark = pytest.mark.django_db


@pytest.fixture
def data():
    admin = UserFactory(role=User.Role.ADMIN)
    moderator = UserFactory(role=User.Role.MODERATOR)
    school = School.objects.create(name="Synthetic School")
    student = Student.objects.create(
        full_name="Synthetic Student",
        birth_year=2012,
        full_nric="PRIVATE-NRIC",
        notes="PRIVATE-NOTE",
    )
    other = Student.objects.create(full_name="Synthetic Student", birth_year=2017)
    assessment = Assessment.objects.create(
        code="TEST_2026",
        display_name="Synthetic Test",
        category="test",
        season_year=2026,
    )
    result = StudentResult.objects.create(
        student=student,
        assessment=assessment,
        raw_score=Decimal("10"),
        band="PIONEER",
        remarks="PRIVATE-NOTE",
    )
    return admin, moderator, school, student, other, assessment, result


def propose(actor, kind, target, values, **kwargs):
    return create_proposal(
        actor=actor,
        reason="Verified source correction",
        evidence="Synthetic source",
        submit=True,
        operations=[{"kind": kind, "target_id": target.pk, "values": values}],
        **kwargs,
    )


def test_moderator_proposes_admin_applies_once_and_receipt_is_complete(data):
    admin, moderator, _, _, _, _, result = data
    proposal = propose(moderator, "result", result, {"raw_score": "0.00"})
    with pytest.raises(PermissionDenied):
        apply_proposal(proposal_id=proposal.pk, actor=moderator)
    result.refresh_from_db()
    assert result.raw_score == Decimal(10)
    apply_proposal(proposal_id=proposal.pk, actor=admin)
    apply_proposal(proposal_id=proposal.pk, actor=admin)
    result.refresh_from_db()
    assert result.raw_score == 0
    receipt = RankingCorrectionReceipt.objects.get(correction=proposal)
    assert receipt.actor == admin
    assert receipt.changes[0]["before"]["values"]["raw_score"] == "10.00"
    assert receipt.changes[0]["after"]["values"]["raw_score"] == "0.00"
    assert RankingCorrectionReceipt.objects.count() == 1
    assert "PRIVATE" not in str(receipt.changes)


def test_stale_preview_and_receipt_failure_never_partially_apply(data, monkeypatch):
    admin, moderator, _, student, _, _, result = data
    proposal = create_proposal(
        actor=moderator,
        reason="Two supported edits",
        evidence="Source",
        submit=True,
        operations=[
            {"kind": "student", "target_id": student.pk, "values": {"birth_year": 2013}},
            {"kind": "result", "target_id": result.pk, "values": {"raw_score": "20"}},
        ],
    )
    result.medal = "GOLD"
    result.save()
    with pytest.raises(StaleCorrection):
        apply_proposal(proposal_id=proposal.pk, actor=admin)
    student.refresh_from_db()
    assert student.birth_year == ORIGINAL_BIRTH_YEAR
    fresh = propose(moderator, "result", result, {"raw_score": "20"})

    def fail(**kwargs):
        msg = "receipt unavailable"
        raise RuntimeError(msg)

    monkeypatch.setattr(RankingCorrectionReceipt.objects, "create", fail)
    with pytest.raises(RuntimeError, match="receipt unavailable"):
        apply_proposal(proposal_id=fresh.pk, actor=admin)
    result.refresh_from_db()
    assert result.raw_score == Decimal(10)
    fresh.refresh_from_db()
    assert fresh.status == "submitted"


@pytest.mark.parametrize(
    "values",
    [
        {"student_id": 123},
        {"remarks": "private"},
        {"normalized_score": "10"},
        {"raw_score": "NaN"},
        {"raw_score": "-1"},
        {"raw_score": "1.234"},
    ],
)
def test_forbidden_fields_and_invalid_scores_rejected(data, values):
    _, moderator, _, _, _, _, result = data
    with pytest.raises(ValidationError):
        propose(moderator, "result", result, values)


def test_draft_submit_withdraw_reject_inverse_and_private_fields(data):
    admin, moderator, _, student, _, _, _ = data
    proposal = create_proposal(
        actor=moderator,
        reason="Supported name",
        evidence="Source",
        operations=[{"kind": "student", "target_id": student.pk, "values": {"full_name": "Revised Student"}}],
    )
    with pytest.raises(PermissionDenied):
        transition_proposal(proposal_id=proposal.pk, actor=admin, action="submit")
    transition_proposal(proposal_id=proposal.pk, actor=moderator, action="submit")
    apply_proposal(proposal_id=proposal.pk, actor=admin)
    inverse = reverse_proposal(proposal_id=proposal.pk, actor=moderator, reason="Source revision withdrawn")
    transition_proposal(proposal_id=inverse.pk, actor=moderator, action="submit")
    apply_proposal(proposal_id=inverse.pk, actor=admin)
    student.refresh_from_db()
    assert student.full_name == "Synthetic Student"
    assert student.full_nric == "PRIVATE-NRIC"
    assert student.notes == "PRIVATE-NOTE"
    another = propose(moderator, "student", student, {"birth_year": 2014})
    with pytest.raises(PermissionDenied):
        transition_proposal(proposal_id=another.pk, actor=moderator, action="reject", reason="No evidence")
    transition_proposal(proposal_id=another.pk, actor=admin, action="reject", reason="No evidence")
    another.refresh_from_db()
    assert another.status == "rejected"


def test_verified_scale_attribution_identity_and_aliases_are_audited(data):
    admin, moderator, school, student, other, assessment, result = data
    scale = propose(
        moderator,
        "scale",
        assessment,
        {
            "band": "PIONEER",
            "max_score": "40",
            "verified": True,
            "comparable_scope": "Test level A",
            "evidence": "Paper",
        },
    )
    apply_proposal(proposal_id=scale.pk, actor=admin)
    assert AssessmentCategoryScale.objects.get().max_score == Decimal(40)
    attribution = propose(
        moderator,
        "attribution",
        result,
        {"school_id": school.pk, "verified": True, "evidence": "Result sheet"},
    )
    apply_proposal(proposal_id=attribution.pk, actor=admin)
    assert ResultSchoolAttribution.objects.get().school == school
    identity = propose(
        moderator,
        "identity",
        other,
        {
            "second_student_id": student.pk,
            "decision": "confirmed_separate",
            "evidence": "Confirmed by owner",
            "active": True,
        },
    )
    apply_proposal(proposal_id=identity.pk, actor=admin)
    decision = StudentIdentityReview.objects.get()
    assert decision.first_student_id < decision.second_student_id
    assert Student.objects.count() == EXPECTED_PAIR_SIZE
    result.refresh_from_db()
    assert result.student == student
    alias = propose(
        moderator,
        "school_alias",
        school,
        {"alias": "Alternate Synthetic School", "school_id": school.pk, "active": True},
    )
    apply_proposal(proposal_id=alias.pk, actor=admin)
    assert SchoolAlias.objects.get().school == school
    inverse = reverse_proposal(proposal_id=attribution.pk, actor=moderator, reason="Verification withdrawn")
    transition_proposal(proposal_id=inverse.pk, actor=moderator, action="submit")
    apply_proposal(proposal_id=inverse.pk, actor=admin)
    assert not ResultSchoolAttribution.objects.get().verified


def test_outcome_alias_preview_includes_existing_rows_and_changes_are_reversible(data):
    admin, moderator, _, _, _, assessment, result = data
    alias = propose(
        moderator,
        "outcome_alias",
        assessment,
        {"field": "band", "alias": "PIONEER", "canonical": "Pioneer", "active": True},
    )
    assert alias.items.count() == EXPECTED_PAIR_SIZE
    apply_proposal(proposal_id=alias.pk, actor=admin)
    result.refresh_from_db()
    assert result.band == "Pioneer"
    assert OutcomeAlias.objects.get().active
    inverse = reverse_proposal(proposal_id=alias.pk, actor=moderator, reason="Review reversal")
    transition_proposal(proposal_id=inverse.pk, actor=moderator, action="submit")
    apply_proposal(proposal_id=inverse.pk, actor=admin)
    result.refresh_from_db()
    assert result.band == "PIONEER"
    assert not OutcomeAlias.objects.get().active


def test_correction_views_require_role_and_admin_confirmation(data, client):
    admin, moderator, _, student, _, _, result = data
    proposal = propose(moderator, "result", result, {"raw_score": "12"})
    routes = [
        reverse("rankings:correction_queue"),
        reverse("rankings:correction_history"),
        reverse("rankings:correction_new"),
        reverse("rankings:correction_detail", args=[proposal.pk]),
    ]
    for url in routes:
        assert client.get(url).status_code == HTTPStatus.FOUND
    client.force_login(UserFactory(role=User.Role.NORMAL, is_staff=True))
    for url in routes:
        assert client.get(url).status_code == HTTPStatus.FORBIDDEN
    client.force_login(moderator)
    for url in routes:
        response = client.get(url)
        assert response.status_code == HTTPStatus.OK
        assert "no-store" in response["Cache-Control"]
        assert "PRIVATE-NRIC" not in response.content.decode()
        assert "PRIVATE-NOTE" not in response.content.decode()
    url = routes[-1]
    assert client.post(url, {"action": "apply", "confirm": "yes"}).status_code == HTTPStatus.FORBIDDEN
    client.force_login(admin)
    assert client.post(url, {"action": "apply"}).status_code == HTTPStatus.BAD_REQUEST
    assert client.post(url, {"action": "apply", "confirm": "yes"}).status_code == HTTPStatus.FOUND
    response = client.get(reverse("rankings:correction_new"), {"kind": "student", "target": student.pk})
    assert response.status_code == HTTPStatus.OK


def test_date_verification_covers_reviewed_date_and_date_edit_clears_verification(data):
    admin, moderator, _, _, _, assessment, _ = data
    from datetime import date

    assessment.assessment_date = date(2026, 3, 1)
    assessment.save()
    pending = propose(moderator, "metadata", assessment, {"date_verified": True})
    from inspinia.rankings.correction_views import _display_items

    context = _display_items(list(pending.items.all()))
    assert context[0]["dependency_context"] == "Assessment date under review: 2026-03-01"
    change = propose(admin, "assessment", assessment, {"assessment_date": "2026-03-02"})
    apply_proposal(proposal_id=change.pk, actor=admin)
    with pytest.raises(StaleCorrection):
        apply_proposal(proposal_id=pending.pk, actor=admin)
    valid = propose(moderator, "metadata", assessment, {"date_verified": True})
    apply_proposal(proposal_id=valid.pk, actor=admin)
    assert AssessmentAnalysisMetadata.objects.get(assessment=assessment).date_verified
    revised = propose(admin, "assessment", assessment, {"assessment_date": "2026-03-03"})
    assert revised.items.count() == EXPECTED_PAIR_SIZE
    apply_proposal(proposal_id=revised.pk, actor=admin)
    assert not AssessmentAnalysisMetadata.objects.get(assessment=assessment).date_verified


def test_keeping_conflict_cancels_old_replacement(data):
    admin, _, _, _, _, _, result = data
    batch = ImportBatch.objects.create(
        import_type="assessment_results",
        original_filename="synthetic.csv",
        status="partial",
    )
    conflict = RankingImportConflict.objects.create(
        batch=batch,
        row_number=2,
        operations=[{"kind": "result", "target_id": result.pk, "values": {"raw_score": "20"}}],
    )
    conflict = resolve_import_conflict(conflict_id=conflict.pk, actor=admin, action="replace")
    replacement = conflict.correction
    transition_proposal(proposal_id=replacement.pk, actor=admin, action="submit")
    resolve_import_conflict(conflict_id=conflict.pk, actor=admin, action="keep")
    with pytest.raises(ValidationError):
        apply_proposal(proposal_id=replacement.pk, actor=admin)
    result.refresh_from_db()
    assert result.raw_score == Decimal(10)
    replacement.refresh_from_db()
    assert replacement.status == "withdrawn"


@pytest.mark.parametrize(
    "query",
    [
        {"kind": "student", "target": "9" * 5000},
        {"kind": "identity", "second_student_id": "²", "target": "1"},
    ],
)
def test_malformed_record_identifiers_are_not_server_errors(data, client, query):
    client.force_login(data[0])
    assert client.get(reverse("rankings:correction_new"), query).status_code == HTTPStatus.NOT_FOUND


def test_correction_posts_require_csrf(data):
    from django.test import Client

    admin, moderator, _, _, _, _, result = data
    change = propose(moderator, "result", result, {"raw_score": "12"})
    protected_client = Client(enforce_csrf_checks=True)
    protected_client.force_login(admin)
    assert (
        protected_client.post(
            reverse("rankings:correction_detail", args=[change.pk]),
            {"action": "apply", "confirm": "yes"},
        ).status_code
        == HTTPStatus.FORBIDDEN
    )


def test_canonical_rename_updates_prior_values_and_other_aliases_and_reverses(data):
    admin, moderator, _, student, other, assessment, first = data
    first.band = "P"
    first.save()
    second = StudentResult.objects.create(student=other, assessment=assessment, raw_score=5, band="Pnr")
    initial = propose(
        moderator,
        "outcome_alias",
        assessment,
        {"field": "band", "alias": "P", "canonical": "Pioneer", "active": True},
    )
    apply_proposal(proposal_id=initial.pk, actor=admin)
    alternate = propose(
        moderator,
        "outcome_alias",
        assessment,
        {"field": "band", "alias": "Pnr", "canonical": "Pioneer", "active": True},
    )
    apply_proposal(proposal_id=alternate.pk, actor=admin)
    newcomer = Student.objects.create(full_name="New synthetic student")
    third = StudentResult.objects.create(student=newcomer, assessment=assessment, raw_score=0, band="P")
    before = dict(StudentResult.objects.values_list("pk", "band"))
    rename = propose(
        moderator,
        "outcome_alias",
        assessment,
        {"field": "band", "alias": "P", "canonical": "PIONEER", "active": True},
    )
    apply_proposal(proposal_id=rename.pk, actor=admin)
    assert set(StudentResult.objects.values_list("band", flat=True)) == {"PIONEER"}
    assert set(OutcomeAlias.objects.values_list("canonical", flat=True)) == {"PIONEER"}
    assert set(rename.items.filter(kind="result").values_list("target_id", flat=True)) == {
        first.pk,
        second.pk,
        third.pk,
    }
    inverse = reverse_proposal(proposal_id=rename.pk, actor=admin, reason="Restore the reviewed prior labels")
    transition_proposal(proposal_id=inverse.pk, actor=admin, action="submit")
    apply_proposal(proposal_id=inverse.pk, actor=admin)
    assert dict(StudentResult.objects.values_list("pk", "band")) == before
    assert set(OutcomeAlias.objects.values_list("canonical", flat=True)) == {"Pioneer"}
    first.refresh_from_db()
    assert first.student_id == student.pk


def test_identical_operations_deduplicate_but_contradictory_values_reject(data):
    admin, _, _, _, _, _, result = data
    operation = {"kind": "result", "target_id": result.pk, "values": {"raw_score": "12"}}
    duplicate = create_proposal(
        actor=admin,
        reason="Reviewed duplicate input",
        evidence="Fixture",
        operations=[operation, operation],
    )
    assert duplicate.items.count() == 1
    conflicting = {"kind": "result", "target_id": result.pk, "values": {"raw_score": "13"}}
    with pytest.raises(ValidationError, match="contradictory"):
        create_proposal(
            actor=admin,
            reason="Contradictory input",
            evidence="Fixture",
            operations=[operation, conflicting],
        )


def test_deleted_target_returns_stale_preview_without_applying_or_receipt(data, client):
    admin, moderator, _, _, _, _, result = data
    change = propose(moderator, "result", result, {"raw_score": "12"})
    result.delete()
    client.force_login(admin)
    response = client.post(
        reverse("rankings:correction_detail", args=[change.pk]),
        {"action": "apply", "confirm": "yes"},
    )
    assert response.status_code == HTTPStatus.CONFLICT
    assert "no longer available" in response.content.decode()
    change.refresh_from_db()
    assert change.status == "submitted"
    assert not RankingCorrectionReceipt.objects.filter(correction=change).exists()


def test_inverse_of_deleted_target_is_a_useful_stale_error(data):
    admin, moderator, _, _, _, _, result = data
    change = propose(moderator, "result", result, {"raw_score": "12"})
    apply_proposal(proposal_id=change.pk, actor=admin)
    result.delete()
    with pytest.raises(StaleCorrection, match="no longer available"):
        reverse_proposal(proposal_id=change.pk, actor=admin, reason="Restore prior score")


def test_unknown_school_replacement_requires_explicit_existing_school_and_keeps_receipt(data):
    admin, _, school, student, _, _, _ = data
    batch = ImportBatch.objects.create(
        import_type="legacy_wide_table",
        original_filename="synthetic.csv",
        status="partial",
    )
    operations = [{"kind": "student", "target_id": student.pk, "values": {"school_id": "new:source school"}}]
    conflict = RankingImportConflict.objects.create(batch=batch, row_number=2, operations=operations)
    with pytest.raises(ValidationError, match="Choose an existing canonical school"):
        resolve_import_conflict(conflict_id=conflict.pk, actor=admin, action="replace")
    reviewed = resolve_import_conflict(conflict_id=conflict.pk, actor=admin, action="replace", school_id=school.pk)
    change = reviewed.correction
    assert change.items.get().changes == {"school_id": school.pk}
    transition_proposal(proposal_id=change.pk, actor=admin, action="submit")
    apply_proposal(proposal_id=change.pk, actor=admin)
    conflict.refresh_from_db()
    student.refresh_from_db()
    assert conflict.status == "replaced"
    assert conflict.operations == operations
    assert student.school_id == school.pk
    batch.refresh_from_db()
    assert batch.status == "partial"


def test_review_context_is_human_readable_private_and_uses_bulk_queries(data, django_assert_num_queries):
    from inspinia.rankings.correction_views import _display_items

    admin, _, school, student, _, assessment, result = data
    operations = [
        {"kind": "student", "target_id": student.pk, "values": {"school_id": school.pk}},
        {"kind": "result", "target_id": result.pk, "values": {"raw_score": "12"}},
        {"kind": "metadata", "target_id": assessment.pk, "values": {"family": "Synthetic family"}},
        {
            "kind": "school_alias",
            "target_id": school.pk,
            "values": {"alias": "School alternative", "school_id": school.pk},
        },
    ]
    change = create_proposal(
        actor=admin,
        reason="Reviewed contexts",
        evidence="Synthetic fixture",
        operations=operations,
    )
    items = list(change.items.all())
    with django_assert_num_queries(4):
        labels = _display_items(items)
    students = next(item for item in labels if item["kind"] == "Student")
    assert "Synthetic Student" in students["target_label"]
    assert "2012" in students["target_label"]
    school_field = next(field for field in students["fields"] if field["name"] == "School id")
    assert "Synthetic School" in school_field["after_label"]
    outcomes = next(item for item in labels if item["kind"] == "Result")
    assert "Synthetic Test" in outcomes["target_label"]
    assert "PIONEER" in outcomes["target_label"]
    assert "PRIVATE" not in str(labels)


def test_alias_preview_rejects_intervening_cohort_import(data):
    admin, moderator, _, _, other, assessment, result = data
    change = propose(
        moderator,
        "outcome_alias",
        assessment,
        {"field": "band", "alias": "PIONEER", "canonical": "Pioneer", "active": True},
    )
    added = StudentResult.objects.create(student=other, assessment=assessment, raw_score=20, band="PIONEER")
    with pytest.raises(StaleCorrection):
        apply_proposal(proposal_id=change.pk, actor=admin)
    result.refresh_from_db()
    added.refresh_from_db()
    assert result.band == added.band == "PIONEER"
    assert not OutcomeAlias.objects.exists()
    assert not RankingCorrectionReceipt.objects.filter(correction=change).exists()


def test_identity_selector_distinguishes_same_names_by_id_and_birth_year(data):
    from inspinia.rankings.correction_forms import CorrectionForm

    _, _, _, student, other, _, _ = data
    form = CorrectionForm(kind="identity", target_id=student.pk)
    labels = [label for key, label in form.fields["second_student_id"].choices if key]
    assert any(str(other.pk) in label and "2017" in label for label in labels)
