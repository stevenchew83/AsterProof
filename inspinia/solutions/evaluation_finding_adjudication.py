"""Preserved, independently adjudicated mathematical assessments of AI findings."""

from collections import defaultdict

from django.db import transaction

from . import evaluation as ev
from .evaluation_models import EvaluationAuditEvent
from .evaluation_models import EvaluationFindingJudgment
from .evaluation_scoring import EvaluationScoringError
from .evaluation_scoring import score_reports

ORIGINAL_COUNT = 2
MAX_REASON_LENGTH = 4000


def _clean(payload):
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        message = "Finding assessments must be structured objects."
        raise ev.EvaluationError(message, status=422)
    return {key: value for key, value in payload.items() if not key.startswith("_")}


def _rows(run, case):
    rows = list(EvaluationFindingJudgment.objects.filter(run=run, case=case).order_by("created_at", "id"))
    originals = [row for row in rows if "_adjudicates" not in row.payload]
    finals = [row for row in rows if "_adjudicates" in row.payload]
    return originals, finals


def _validate_annotation(run, case, payload):
    identifier = str(case.pk)
    if identifier not in run.reports:
        raise ev.EvaluationError
    row = next((item for item in run.snapshot.manifest["cases"] if item["id"] == identifier), None)
    if row is None:
        raise ev.EvaluationError
    try:
        score_reports([row], {identifier: run.reports[identifier]}, {identifier: payload}, run.protocol)
    except EvaluationScoringError as error:
        raise ev.EvaluationError(str(error), status=422) from error


@transaction.atomic
def adjudicate_findings(actor, run, case, payload, reason):
    """Append a third human judgment without replacing either independent assessment."""
    ev.require(actor, "adjudicator", case)
    ev.snapshot_eligible(run.snapshot, lock=True)
    ev.lifecycle(run, lock=True)
    originals, finals = _rows(run, case)
    identities = {row.actor_id for row in originals}
    if finals:
        message = "The finding adjudication is already preserved."
        raise ev.EvaluationError(message, status=409)
    if (
        len(originals) != ORIGINAL_COUNT
        or None in identities
        or len(identities) != ORIGINAL_COUNT
        or actor.pk in identities
    ):
        message = "Finding adjudication requires two original assessments and a distinct third actor."
        raise ev.EvaluationError(message, status=409)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
        message = "Explain the mathematical resolution in at most 4000 characters."
        raise ev.EvaluationError(message, status=422)
    clean = _clean(payload)
    if len(clean) != len(payload):
        message = "Adjudication metadata is issued by the server."
        raise ev.EvaluationError(message, status=422)
    _validate_annotation(run, case, clean)
    references = [str(row.pk) for row in originals]
    resolved = {**clean, "_adjudicates": references, "_reason": reason}
    final = EvaluationFindingJudgment.objects.create(run=run, case=case, actor=actor, payload=resolved)
    ev.audit(
        actor,
        run,
        "finding_adjudicated",
        {
            "case_id": str(case.pk),
            "judgment_id": str(final.pk),
            "original_judgment_ids": references,
            "payload_digest": ev.digest(resolved),
        },
    )
    return final


def _verified_final(run, case_id, originals, final):
    references = final.payload.get("_adjudicates")
    reason = final.payload.get("_reason")
    identities = {row.actor_id for row in originals}
    valid = (
        len(originals) == ORIGINAL_COUNT
        and len(identities) == ORIGINAL_COUNT
        and None not in identities
        and final.actor_id is not None
        and final.actor_id not in identities
        and isinstance(references, list)
        and len(references) == ORIGINAL_COUNT
        and all(isinstance(value, str) for value in references)
        and set(references) == {str(row.pk) for row in originals}
        and isinstance(reason, str)
        and bool(reason.strip())
    )
    if not valid:
        message = "Finding adjudication does not identify two preserved independent assessments."
        raise ev.EvaluationError(message, status=409)
    receipt = EvaluationAuditEvent.objects.filter(
        actor_id=final.actor_id,
        target_id=run.pk,
        kind="finding_adjudicated",
        metadata__case_id=str(case_id),
        metadata__judgment_id=str(final.pk),
    ).first()
    if receipt is None or receipt.metadata.get("payload_digest") != ev.digest(final.payload):
        message = "Finding adjudication requires an authenticated execution record."
        raise ev.EvaluationError(message, status=409)
    return _clean(final.payload)


def resolve_finding_judgments(run):
    """Return scoring annotations; an unresolved or unauthenticated dispute fails closed.

    This is an internal resolver, not an authorization interface. Its caller must
    authorize delivery. Original and final records remain immutable, while only
    the mathematical annotation is returned to the scorer.
    """
    ev.snapshot_eligible(run.snapshot)
    ev.lifecycle(run)
    grouped = defaultdict(list)
    for row in run.finding_judgments.select_related("case").order_by("created_at", "id"):
        if str(row.case_id) not in run.reports:
            message = "Finding judgments reference a case outside this run."
            raise ev.EvaluationError(message, status=409)
        grouped[str(row.case_id)].append(row)
    result = {}
    for identifier, rows in grouped.items():
        originals = [row for row in rows if "_adjudicates" not in row.payload]
        finals = [row for row in rows if "_adjudicates" in row.payload]
        if len(originals) > ORIGINAL_COUNT or len(finals) > 1:
            message = "The finding-review round contains incompatible decisions."
            raise ev.EvaluationError(message, status=409)
        identities = {row.actor_id for row in originals}
        if None in identities or len(identities) != len(originals):
            message = "Finding assessments require preserved authenticated reviewer identities."
            raise ev.EvaluationError(message, status=409)
        if finals:
            result[identifier] = _verified_final(run, identifier, originals, finals[0])
        elif originals:
            clean = [_clean(row.payload) for row in originals]
            if any(row != clean[0] for row in clean[1:]):
                message = "Finding-judgment disagreement requires mathematical adjudication."
                raise ev.EvaluationError(message, status=409)
            result[identifier] = clean[0]
    return result
