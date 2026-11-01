"""Authenticated reuse, mathematical transformation and repair records."""

# ruff: noqa: EM101, TRY003, PLR0913
import hashlib
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from .evaluation import RUBRIC
from .evaluation import WORKSPACE
from .evaluation import EvaluationError
from .evaluation import audit
from .evaluation import case_state
from .evaluation import decision_lock
from .evaluation import digest
from .evaluation import lifecycle
from .evaluation import require
from .evaluation import verify_bundle
from .evaluation_execution import finding_identity
from .evaluation_models import EvaluationAuditEvent
from .evaluation_models import EvaluationLifecycle
from .evaluation_models import ReviewConsent

REUSE_POLICY_VERSION = "reuse-v1"


def _text(value, maximum):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _owner(user):
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        raise EvaluationError


@transaction.atomic
def record_reuse_consent(user, revision, expires_at, policy_version):
    from .models import ProblemSolution
    from .models import SolutionRevision

    _owner(user)
    decision_lock()
    original = SolutionRevision.objects.filter(pk=revision.pk, solution__author=user).first()
    if original is None:
        raise EvaluationError
    solution = ProblemSolution.objects.select_for_update().get(pk=original.solution_id)
    if solution.current_revision_id != original.pk:
        raise EvaluationError("Consent must refer to the current saved proof revision.", status=409)
    if (
        not isinstance(expires_at, datetime)
        or timezone.is_naive(expires_at)
        or expires_at <= timezone.now()
        or policy_version != REUSE_POLICY_VERSION
    ):
        raise EvaluationError("A current retention deadline and policy version are required.", status=422)
    from .reviews import ReviewError
    from .reviews import _image_manifest

    try:
        supporting_images = [item["sha256"] for item in _image_manifest(original)]
    except ReviewError as error:
        raise EvaluationError("Resolve managed proof images before granting reuse permission.", status=422) from error
    consent = ReviewConsent.objects.create(
        actor=user,
        purpose="benchmark_reuse",
        expires_at=expires_at,
        payload={
            "learner_id": user.pk,
            "source_revision_id": str(original.pk),
            "source_digest": hashlib.sha256(original.body_source.encode()).hexdigest(),
            "supporting_image_digests": supporting_images,
            "retention_policy": policy_version,
            "lawful_eligibility": "pending independent approval",
        },
    )
    audit(user, consent, "reuse_consent_recorded", {"revision_id": str(original.pk), "policy_version": policy_version})
    return consent


@transaction.atomic
def approve_reuse_eligibility(actor, consent, evidence_reference):
    require(actor, "activation", WORKSPACE)
    consent = ReviewConsent.objects.get(pk=consent.pk)
    lifecycle(consent, lock=True)
    if (
        consent.actor_id == actor.pk
        or consent.purpose != "benchmark_reuse"
        or not _text(evidence_reference, 500)
        or consent.expires_at <= timezone.now()
        or consent.payload.get("retention_policy") != REUSE_POLICY_VERSION
    ):
        raise EvaluationError("Independent eligibility evidence is required.", status=422)
    return audit(actor, consent, "reuse_eligibility_approved", {"evidence_reference": evidence_reference})


@transaction.atomic
def withdraw_reuse_consent(user, consent):
    _owner(user)
    decision_lock()
    consent = ReviewConsent.objects.get(pk=consent.pk)
    if consent.actor_id != user.pk or consent.purpose != "benchmark_reuse":
        raise EvaluationError
    previous = EvaluationLifecycle.objects.select_for_update().filter(target_id=consent.pk).first()
    if previous and not previous.eligible and previous.reason == "withdrawal":
        return
    state = previous if previous is not None else lifecycle(consent, lock=True)
    state.eligible = False
    state.generation += 1
    state.reason = "withdrawal"
    state.save()
    audit(user, consent, "reuse_consent_withdrawn")
    from .evaluation import _invalidate
    from .evaluation_models import EvaluationCase

    for case in EvaluationCase.objects.filter(provenance__consent_reference=str(consent.pk)):
        # The authenticated owner of the exact consent authorizes only its dependent content erasure.
        _invalidate(user, case, "withdrawal", purge=True)
    # A reference can accidentally include private text; erasure keeps its hash and actor/time only.
    for event in EvaluationAuditEvent.objects.filter(target_id=consent.pk, kind="reuse_eligibility_approved"):
        EvaluationAuditEvent._base_manager.filter(pk=event.pk).update(  # noqa: SLF001 - explicit owner withdrawal
            metadata={"withdrawn": True, "historical_digest": digest(event.metadata)},
        )


@transaction.atomic
def verify_relationship(actor, source, target, kind, explanation, *, dimension=None, expected_assessment=None):
    require(actor, "reviewer", source)
    require(actor, "reviewer", target)
    lifecycle(source, lock=True)
    lifecycle(target, lock=True)
    verify_bundle(source.bundle)
    verify_bundle(target.bundle)
    if source.family_id != target.family_id or source.pk == target.pk or not _text(explanation, 4000):
        raise EvaluationError("Verify a relationship between distinct variants of the same family.", status=422)
    if actor.pk in {source.prepared_by_id, target.prepared_by_id}:
        raise EvaluationError("The transformation preparer cannot independently verify it.", status=409)
    if not isinstance(kind, str) or kind not in {
        "same_assessment",
        "different_assessment",
        "same_dimension",
        "target_assessment",
    }:
        raise EvaluationError("Unknown mathematical relationship.", status=422)
    if dimension is not None and not isinstance(dimension, str):
        raise EvaluationError("Name the invariant mathematical dimension.", status=422)
    if kind == "same_dimension" and dimension not in RUBRIC:
        raise EvaluationError("Name the invariant mathematical dimension.", status=422)
    if kind == "target_assessment" and (
        not isinstance(expected_assessment, str)
        or expected_assessment not in {"no_issues_found", "gap_found", "incomplete", "unable_to_assess"}
    ):
        raise EvaluationError("Name the expected mathematical assessment.", status=422)
    states = [case_state(case) for case in (source, target)]
    if any(state["status"] not in {"verified", "adjudicated"} for state in states):
        raise EvaluationError(
            "Complete independent ground truth before reviewing transformation relationships.",
            status=409,
        )
    left, right = (state["ground_truth"] for state in states)
    checks = {
        "same_assessment": left["assessment"] == right["assessment"],
        "different_assessment": left["assessment"] != right["assessment"],
        "same_dimension": left.get(dimension) == right.get(dimension),
        "target_assessment": right["assessment"] == expected_assessment,
    }
    if not checks[kind]:
        raise EvaluationError(
            "The relationship conflicts with independently established mathematical judgments.",
            status=409,
        )
    return audit(
        actor,
        source,
        "relationship_verified",
        {
            "source_case_id": str(source.pk),
            "target_case_id": str(target.pk),
            "source_digest": source.bundle.digest,
            "target_digest": target.bundle.digest,
            "kind": kind,
            "dimension": dimension,
            "expected_assessment": expected_assessment,
            "explanation": explanation,
        },
    )


@transaction.atomic
def record_repair(actor, review, finding_id, revision, state, explanation):
    _owner(actor)
    if (
        revision.solution_id != review.revision.solution_id
        or revision.pk == review.revision_id
        or revision.sequence <= review.revision.sequence
        or not _text(explanation, 4000)
        or review.status != "completed"
    ):
        raise EvaluationError("Repair assessment needs a different revision of the same proof.", status=422)
    finding_ids = {
        finding_identity(review, finding, i) for i, finding in enumerate(review.feedback.get("findings", []))
    }
    if finding_id not in finding_ids:
        raise EvaluationError("The original finding is unavailable.", status=404)
    if state == "reevaluation_requested":
        if actor.pk != review.author_id:
            raise EvaluationError
        decision_lock()
    elif state in {"coach_confirmed_repaired", "unresolved", "replaced"}:
        require(actor, "reviewer", revision.solution.problem.problem_uuid)
        if actor.pk == review.author_id:
            raise EvaluationError("An author cannot independently confirm mathematical repair.", status=409)
    else:
        raise EvaluationError("Only a new mathematical judgment can resolve a finding.", status=422)
    return audit(
        actor,
        review.pk,
        "repair_assessed",
        {
            "finding_id": finding_id,
            "revision_id": str(revision.pk),
            "source_digest": revision.source_digest,
            "state": state,
            "explanation": explanation,
        },
    )


def repair_state(review, finding_id):
    event = (
        EvaluationAuditEvent.objects.filter(
            target_id=review.pk,
            kind="repair_assessed",
            metadata__finding_id=finding_id,
            metadata__revision_id=str(review.revision.solution.current_revision_id),
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if event:
        return event.metadata["state"]
    return (
        "source_changed_unassessed"
        if review.revision.solution.current_revision_id != review.revision_id
        else "unresolved"
    )
