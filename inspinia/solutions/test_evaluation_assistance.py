"""Consent is source-bound; repair and transformation claims need authenticated judgments."""

# ruff: noqa: PLR2004
import copy
import json
from datetime import timedelta
from hashlib import sha256

import pytest
from django.utils import timezone

from inspinia.solutions import evaluation as ev
from inspinia.solutions.evaluation_assistance import approve_reuse_eligibility
from inspinia.solutions.evaluation_assistance import record_repair
from inspinia.solutions.evaluation_assistance import record_reuse_consent
from inspinia.solutions.evaluation_assistance import repair_state
from inspinia.solutions.evaluation_assistance import verify_relationship
from inspinia.solutions.evaluation_assistance import withdraw_reuse_consent
from inspinia.solutions.evaluation_models import EvaluationAuditEvent
from inspinia.solutions.evaluation_models import EvaluationLifecycle
from inspinia.solutions.evaluation_models import ReviewConsent
from inspinia.solutions.models import SolutionRevision
from inspinia.solutions.reviews import process_next_review
from inspinia.solutions.reviews import review_payload
from inspinia.solutions.test_evaluation_contract import case_setup  # noqa: F401
from inspinia.solutions.test_evaluation_contract import judgment
from inspinia.solutions.test_reviews import coach  # noqa: F401
from inspinia.solutions.test_reviews import provider
from inspinia.solutions.test_reviews import request as request_review
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _learner_case(setup, learner):
    admin, curator, family, template, judges = setup
    expiry = timezone.now() + timedelta(days=10)
    consent = record_reuse_consent(learner.user, learner.revision, expiry, "reuse-v1")
    ev.grant(admin, judges[2], "activation", ev.WORKSPACE)
    approve_reuse_eligibility(judges[2], consent, "Synthetic eligibility review")
    provenance = {
        **template.provenance,
        "construction": "learner_submission",
        "consent_reference": str(consent.pk),
        "learner_id": learner.user.pk,
        "source_revision_id": str(learner.revision.pk),
        "source_digest": learner.revision.source_digest,
        "lawful_eligibility": "Reviewed",
        "withdrawal_policy": "withdraw-v1",
        "retention_until": expiry.isoformat(),
    }
    data = {**template.bundle.payload, "source": learner.revision.body_source, "provenance": provenance}
    return consent, ev.create_case(curator, family, data)


def _relationship_cases(setup, *, verified=True):
    admin, curator, family, source, judges = setup
    data = copy.deepcopy(source.bundle.payload)
    data.update(
        source="The product of a real number with itself is nonnegative.",
        provenance=copy.deepcopy(source.provenance),
    )
    target = ev.create_case(curator, family, data)
    for actor in judges:
        ev.grant(admin, actor, "reviewer", target, expertise="Algebra")
    if verified:
        for case in (source, target):
            for actor in judges[:2]:
                ev.submit_judgment(actor, case, judgment(), case.bundle.digest)
    return source, target, judges[2]


def test_learner_reuse_requires_independent_eligibility_and_exact_consent(case_setup, coach):  # noqa: F811
    admin, curator, family, template, judges = case_setup
    expiry = timezone.now() + timedelta(days=10)
    consent = record_reuse_consent(coach.user, coach.revision, expiry, "reuse-v1")
    provenance = {
        **template.provenance,
        "construction": "learner_submission",
        "consent_reference": str(consent.pk),
        "learner_id": coach.user.pk,
        "source_revision_id": str(coach.revision.pk),
        "source_digest": coach.revision.source_digest,
        "lawful_eligibility": "Reviewed",
        "withdrawal_policy": "withdraw-v1",
        "retention_until": expiry.isoformat(),
    }
    data = {**template.bundle.payload, "source": coach.revision.body_source, "provenance": provenance}
    with pytest.raises(ev.EvaluationError):
        ev.create_case(curator, family, data)
    ev.grant(admin, judges[2], "activation", ev.WORKSPACE)
    approve_reuse_eligibility(judges[2], consent, "Synthetic eligibility review")
    case = ev.create_case(curator, family, data)
    assert case.bundle.problem_uuid == coach.problem.problem_uuid
    assert case.metadata["corpus"] == "representative_learner"
    with pytest.raises(ev.EvaluationError):
        ev.create_case(curator, family, {**data, "source": "Different learner work"})
    withdraw_reuse_consent(coach.user, consent)
    assert not EvaluationLifecycle.objects.get(target_id=case.pk).eligible
    case.bundle.refresh_from_db()
    assert case.bundle.payload == {}
    assert coach.revision.body_source == data["source"]


def test_source_edit_never_automatically_confirms_repair(case_setup, coach):  # noqa: F811
    admin, _, _, _, judges = case_setup
    review, _ = request_review(coach)
    process_next_review(provider)
    review.refresh_from_db()
    finding = review_payload(review)["feedback"]["findings"][0]
    source = "An entirely changed passage that has not been assessed."
    revised = SolutionRevision.objects.create(
        solution=coach.solution,
        sequence=2,
        body_source=source,
        source_digest=sha256(source.encode()).hexdigest(),
    )
    coach.solution.current_revision = revised
    coach.solution.save()
    review = type(review).objects.select_related("revision__solution").get(pk=review.pk)
    assert repair_state(review, finding["id"]) == "source_changed_unassessed"
    with pytest.raises(ev.EvaluationError):
        record_repair(coach.user, review, finding["id"], revised, "coach_confirmed_repaired", "Looks changed")
    ev.grant(admin, judges[0], "reviewer", coach.problem.problem_uuid, expertise="Algebra")
    record_repair(judges[0], review, finding["id"], revised, "unresolved", "The new argument is still unsupported.")
    assert repair_state(review, finding["id"]) == "unresolved"
    assert EvaluationAuditEvent.objects.filter(target_id=review.pk, kind="repair_assessed").count() == 1


def test_reuse_eligibility_cannot_be_self_approved_or_approved_without_staff_assignment(case_setup, coach):  # noqa: F811
    admin, _, _, _, judges = case_setup
    consent = record_reuse_consent(coach.user, coach.revision, timezone.now() + timedelta(days=10), "reuse-v1")
    with pytest.raises(ev.EvaluationError):
        approve_reuse_eligibility(judges[0], consent, "No staff assignment")
    coach.user.role = "trainer"
    coach.user.is_approved = True
    coach.user.save()
    ev.grant(admin, coach.user, "activation", ev.WORKSPACE)
    with pytest.raises(ev.EvaluationError, match="Independent"):
        approve_reuse_eligibility(coach.user, consent, "Self approval")
    assert not EvaluationAuditEvent.objects.filter(target_id=consent.pk, kind="reuse_eligibility_approved").exists()


def test_consent_withdrawal_is_owner_only_and_idempotent(coach):  # noqa: F811
    consent = record_reuse_consent(coach.user, coach.revision, timezone.now() + timedelta(days=10), "reuse-v1")
    with pytest.raises(ev.EvaluationError):
        withdraw_reuse_consent(UserFactory(), consent)
    withdraw_reuse_consent(coach.user, consent)
    withdraw_reuse_consent(coach.user, consent)
    assert EvaluationAuditEvent.objects.filter(target_id=consent.pk, kind="reuse_consent_withdrawn").count() == 1


def test_consent_withdrawal_purges_a_previously_invalidated_dependent_case(case_setup, coach):  # noqa: F811
    _, curator, _, _, _ = case_setup
    consent, case = _learner_case(case_setup, coach)
    ev.invalidate(curator, case, "correction")
    assert case.bundle.payload["source"]
    withdraw_reuse_consent(coach.user, consent)
    case.bundle.refresh_from_db()
    assert case.bundle.payload == {}
    assert not EvaluationLifecycle.objects.get(target_id=consent.pk).eligible


def test_owner_can_erase_dependent_content_after_staff_revoked_consent(case_setup, coach):  # noqa: F811
    consent, case = _learner_case(case_setup, coach)
    EvaluationLifecycle.objects.filter(target_id=consent.pk).update(eligible=False, reason="revocation")
    withdraw_reuse_consent(coach.user, consent)
    case.bundle.refresh_from_db()
    assert case.bundle.payload == {}
    assert EvaluationLifecycle.objects.get(target_id=consent.pk).reason == "withdrawal"


def test_expired_or_other_purpose_consent_cannot_receive_reuse_eligibility(case_setup, coach):  # noqa: F811
    admin, _, _, _, judges = case_setup
    ev.grant(admin, judges[2], "activation", ev.WORKSPACE)
    for purpose, expiry in [
        ("feedback", timezone.now() + timedelta(days=10)),
        ("benchmark_reuse", timezone.now() - timedelta(days=1)),
    ]:
        consent = ReviewConsent.objects.create(actor=coach.user, purpose=purpose, payload={}, expires_at=expiry)
        with pytest.raises(ev.EvaluationError):
            approve_reuse_eligibility(judges[2], consent, "Synthetic eligibility review")


def test_relationship_approval_is_authenticated_and_frozen_from_server_event(case_setup):  # noqa: F811
    admin, curator, family, _, _ = case_setup
    source, target, verifier = _relationship_cases(case_setup)
    event = verify_relationship(
        verifier,
        source,
        target,
        "same_dimension",
        "Both arguments are mathematically valid.",
        dimension="logical_validity",
    )
    assert event.actor_id == verifier.pk
    ev.grant(admin, curator, "custodian", family)
    snapshot = ev.freeze_dataset(
        curator,
        "Verified equivalent variants",
        [
            {"case_id": str(source.pk), "partition": "final_test"},
            {"case_id": str(target.pk), "partition": "final_test"},
        ],
        {},
    )
    assert snapshot.manifest["relationships"] == [
        {
            "id": str(event.pk),
            "coach_approved": True,
            "source_case_id": str(source.pk),
            "target_case_id": str(target.pk),
            "kind": "same_dimension",
            "dimension": "logical_validity",
            "expected_assessment": None,
        },
    ]


def test_relationship_verification_waits_until_blind_initial_judgments_are_closed(case_setup):  # noqa: F811
    source, target, verifier = _relationship_cases(case_setup, verified=False)
    with pytest.raises(ev.EvaluationError, match="Complete independent ground truth"):
        verify_relationship(verifier, source, target, "same_assessment", "Expected equal mathematical judgment.")
    assert not EvaluationAuditEvent.objects.filter(kind="relationship_verified").exists()


def test_preparer_and_unassigned_coach_cannot_approve_relationship(case_setup):  # noqa: F811
    admin, curator, _, _, _ = case_setup
    source, target, _ = _relationship_cases(case_setup)
    for case in (source, target):
        ev.grant(admin, curator, "reviewer", case, expertise="Algebra")
    for actor in (curator, UserFactory()):
        with pytest.raises(ev.EvaluationError):
            verify_relationship(actor, source, target, "same_assessment", "Both arguments are valid.")


def test_relationship_cannot_contradict_verified_ground_truth(case_setup):  # noqa: F811
    source, target, verifier = _relationship_cases(case_setup)
    with pytest.raises(ev.EvaluationError, match="conflicts"):
        verify_relationship(
            verifier,
            source,
            target,
            "different_assessment",
            "These valid proofs have different validity.",
        )
    with pytest.raises(ev.EvaluationError, match="dimension"):
        verify_relationship(verifier, source, target, "same_dimension", "Unknown rubric field.", dimension="invented")


def test_withdrawing_relationship_target_erases_private_explanation(case_setup):  # noqa: F811
    _, curator, _, _, _ = case_setup
    source, target, verifier = _relationship_cases(case_setup)
    marker = "PRIVATE_TRANSFORMATION_EXPLANATION"
    event = verify_relationship(verifier, source, target, "same_assessment", marker)
    assert event.target_id == source.pk
    ev.invalidate(curator, target, "withdrawal", purge=True)
    event.refresh_from_db()
    assert marker not in json.dumps(event.metadata)


def test_review_deletion_erases_private_repair_explanation(case_setup, coach):  # noqa: F811
    admin, _, _, _, judges = case_setup
    review, _ = request_review(coach)
    process_next_review(provider)
    review.refresh_from_db()
    finding = review_payload(review)["feedback"]["findings"][0]
    source = "A revised proof whose defect still needs work."
    revised = SolutionRevision.objects.create(
        solution=coach.solution,
        sequence=2,
        body_source=source,
        source_digest=sha256(source.encode()).hexdigest(),
    )
    ev.grant(admin, judges[0], "reviewer", coach.problem.problem_uuid, expertise="Algebra")
    marker = "PRIVATE_REPAIR_EXPLANATION"
    event = record_repair(judges[0], review, finding["id"], revised, "unresolved", marker)
    type(review).objects.filter(pk=review.pk).delete()
    event.refresh_from_db()
    assert marker not in json.dumps(event.metadata)


def test_learner_reuse_permission_binds_managed_image_bytes(case_setup, coach, settings, tmp_path):  # noqa: F811
    from inspinia.solutions.test_reviews import _image
    from inspinia.solutions.test_reviews import _revision_with_image

    settings.MEDIA_ROOT = tmp_path
    image = _image(coach)
    _revision_with_image(coach, image.file.name)
    admin, curator, family, template, judges = case_setup
    expiry = timezone.now() + timedelta(days=10)
    consent = record_reuse_consent(coach.user, coach.revision, expiry, "reuse-v1")
    ev.grant(admin, judges[2], "activation", ev.WORKSPACE)
    approve_reuse_eligibility(judges[2], consent, "Synthetic rights verification")
    data = {
        **template.bundle.payload,
        "source": coach.revision.body_source,
        "provenance": {
            **template.provenance,
            "construction": "learner_submission",
            "consent_reference": str(consent.pk),
            "learner_id": coach.user.pk,
            "source_revision_id": str(coach.revision.pk),
            "source_digest": coach.revision.source_digest,
            "lawful_eligibility": "Reviewed",
            "withdrawal_policy": "withdraw-v1",
            "retention_until": expiry.isoformat(),
        },
    }
    with pytest.raises(ev.EvaluationError, match="images must match"):
        ev.create_case(curator, family, data)
    with image.file.open("rb") as handle:
        raw = handle.read()
    with pytest.raises(ev.EvaluationError, match="images must match"):
        ev.create_case(curator, family, data, assets=[{"data": raw + b"changed", "role": "supporting_image"}])
    case = ev.create_case(curator, family, data, assets=[{"data": raw, "role": "supporting_image"}])
    assert case.bundle.assets.count() == 1
