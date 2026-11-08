"""Authenticated offline preregistration, with no execution or activation authority."""

# ruff: noqa: EM101, TRY003, SLF001
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from . import evaluation as ev
from .evaluation_models import EvaluationAuditEvent
from .evaluation_models import EvaluationDatasetSnapshot
from .evaluation_models import EvaluationRun
from .evaluation_models import ReviewerProfile
from .evaluation_scoring import REQUIRED_THRESHOLDS
from .evaluation_scoring import _protocol

KIND = "protocol_frozen"
SPEC_FIELDS = {
    "partition", "thresholds", "min_cases", "max_runs", "sampling_plan", "analysis_plan",
    "population", "languages", "levels", "custodian_ids", "aggregate_recipient_ids",
}
THRESHOLD_FIELDS = {*REQUIRED_THRESHOLDS, "minimum_agreement", "min_families"}
MAX_DESCRIPTION_LENGTH = 8000
MAX_LANGUAGE_LENGTH = 100
MAX_RECIPIENTS = 100


def registrations(snapshot, profile=None):
    """Internal query: callers must authorize the snapshot before delivering results."""
    query = EvaluationAuditEvent.objects.filter(target_id=snapshot.pk, kind=KIND)
    if profile is not None:
        query = query.filter(metadata__body__profile_id=str(profile.pk))
    return query.order_by("created_at", "pk")


def visible_registrations(actor, snapshot):
    ev.require(actor, "custodian", snapshot)
    ids = [
        event.pk for event in registrations(snapshot)
        if str(actor.pk) in event.metadata["body"]["spec"]["custodian_ids"]
    ]
    return registrations(snapshot).filter(pk__in=ids)


def _spec(spec, actor, snapshot):  # noqa: C901 - explicit schema validation
    if not isinstance(spec, dict) or set(spec) != SPEC_FIELDS:
        raise ev.EvaluationError("Supply exactly the documented protocol fields.", status=422)
    thresholds = spec["thresholds"]
    if not isinstance(thresholds, dict) or set(thresholds) != THRESHOLD_FIELDS:
        raise ev.EvaluationError("Every readiness threshold must be explicitly set.", status=422)
    try:
        checked = _protocol(thresholds)
    except ValueError as error:
        raise ev.EvaluationError(str(error), status=422) from error
    if any(value is None for value in checked.values()):
        raise ev.EvaluationError("Unset readiness thresholds cannot be preregistered.", status=422)
    for field in ("min_cases", "max_runs"):
        if type(spec[field]) is not int or spec[field] < 1:
            raise ev.EvaluationError("Case and repetition limits must be positive integers.", status=422)
    for field in ("sampling_plan", "analysis_plan", "population", "levels"):
        if not isinstance(spec[field], str) or not spec[field].strip() or len(spec[field]) > MAX_DESCRIPTION_LENGTH:
            raise ev.EvaluationError("Describe population, levels, sampling and analysis explicitly.", status=422)
    languages = spec["languages"]
    if (
        not isinstance(languages, list) or not languages
        or any(not isinstance(item, str) or not item.strip() or len(item) > MAX_LANGUAGE_LENGTH for item in languages)
        or len(set(languages)) != len(languages)
    ):
        raise ev.EvaluationError("Declare the intended languages without duplicates.", status=422)
    if not isinstance(spec["partition"], str) or spec["partition"] not in ev.PARTITIONS:
        raise ev.EvaluationError("Select a known dataset partition.", status=422)
    _recipients(spec, actor, snapshot)
    return checked


def _recipients(spec, actor, snapshot):
    for field, role in (("custodian_ids", "custodian"), ("aggregate_recipient_ids", "developer")):
        ids = spec[field]
        if (
            not isinstance(ids, list) or len(ids) > MAX_RECIPIENTS or (field == "custodian_ids" and not ids)
            or any(not isinstance(item, str) or not item for item in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ev.EvaluationError("Recipients must be distinct assigned account identifiers.", status=422)
        # Compare as strings: account primary keys need not be UUIDs.
        try:
            people = {str(user.pk): user for user in get_user_model().objects.filter(pk__in=ids)}
        except (ValueError, ValidationError) as error:
            raise ev.EvaluationError("Recipients need valid assigned account identifiers.", status=422) from error
        if set(people) != set(ids) or any(not ev.allowed(user, role, snapshot) for user in people.values()):
            raise ev.EvaluationError("Every recipient needs the current scoped assignment.", status=422)
    if str(actor.pk) not in spec["custodian_ids"]:
        raise ev.EvaluationError("The registering custodian must be a named recipient.", status=422)


@transaction.atomic
def freeze_protocol(actor, snapshot, profile, spec):
    ev.require(actor, "custodian", snapshot)
    ev.snapshot_eligible(snapshot, lock=True)
    _spec(spec, actor, snapshot)
    if ev.digest(profile.payload) != profile.digest:
        raise ev.EvaluationError("Profile digest mismatch.", status=409)
    rubric = profile.payload.get("rubric")
    if (rubric.get("version") if isinstance(rubric, dict) else rubric) != snapshot.manifest["rubric_version"]:
        raise ev.EvaluationError("Candidate and dataset rubric versions must match.", status=422)
    selected = sorted(
        (row for row in snapshot.manifest["cases"] if row["partition"] == spec["partition"]),
        key=lambda row: row["id"],
    )
    families = sorted({row["family_id"] for row in selected})
    if len(selected) < spec["min_cases"] or len(families) < spec["thresholds"]["min_families"]:
        raise ev.EvaluationError("The partition does not meet the declared case/family minimums.", status=422)
    body = {
        "schema_version": 1,
        "snapshot_id": str(snapshot.pk), "snapshot_digest": snapshot.digest,
        "profile_id": str(profile.pk), "profile_digest": profile.digest,
        "rubric_version": snapshot.manifest["rubric_version"],
        "case_inputs": [{"id": row["id"], "input_digest": row["input_digest"]} for row in selected],
        "family_ids": families, "domains": sorted({row["domain"] for row in selected}),
        "eligible_cases": len(selected), "independent_families": len(families),
        "modalities": ["typed_latex", "managed_diagrams"],
        "failure_policy": "preserve_all_attempts_no_automatic_retries",
        "disclosure_policy": "named_custodians_case_detail_named_developers_one_aggregate",
        "execution_authority": "none", "financial_cap_minor_units": 0,
        "spec": spec,
    }
    fingerprint = ev.digest(body)
    previous = registrations(snapshot, profile).filter(metadata__body__spec__partition=spec["partition"]).first()
    if previous is not None:
        if previous.metadata.get("digest") == fingerprint and ev.digest(previous.metadata["body"]) == fingerprint:
            return previous
        raise ev.EvaluationError(
            "This candidate/partition is already preregistered; its rules cannot be replaced.", status=409,
        )
    existing_runs = EvaluationRun.objects.filter(snapshot=snapshot, profile=profile)
    if any(run.protocol.get("partition", "final_test") == spec["partition"] for run in existing_runs):
        raise ev.EvaluationError(
            "Reports already exist for this candidate/partition; preregistration is too late.", status=409,
        )
    if EvaluationAuditEvent.objects.filter(target_id=snapshot.pk, kind="aggregate_served").exists():
        raise ev.EvaluationError("Aggregate feedback has been disclosed; use fresh final-test evidence.", status=409)
    return ev.audit(actor, snapshot, KIND, {"body": body, "digest": fingerprint})


def _bound(event, snapshot, profile):
    body = event.metadata.get("body", {})
    stored = EvaluationAuditEvent.objects.filter(pk=event.pk, kind=KIND, target_id=snapshot.pk).first()
    if (
        stored is None or stored.metadata != event.metadata
        or event.kind != KIND or event.target_id != snapshot.pk
        or ev.digest(body) != event.metadata.get("digest")
        or body.get("snapshot_id") != str(snapshot.pk) or body.get("snapshot_digest") != snapshot.digest
        or body.get("profile_id") != str(profile.pk) or body.get("profile_digest") != profile.digest
        or ev.digest(profile.payload) != profile.digest
    ):
        raise ev.EvaluationError("Protocol binding or integrity check failed.", status=409)
    return body


def import_protocol(actor, event, snapshot, profile):
    """Called inside import_run's locked transaction; failed imports consume no slot."""
    body = _bound(event, snapshot, profile)
    if str(actor.pk) not in body["spec"]["custodian_ids"]:
        raise ev.EvaluationError
    previous = EvaluationRun.objects.filter(snapshot=snapshot, profile=profile)
    used = sum(run.protocol.get("partition", "final_test") == body["spec"]["partition"] for run in previous)
    if used >= body["spec"]["max_runs"]:
        raise ev.EvaluationError("The preregistered repetition limit has been reached.", status=409)
    return {
        **body["spec"]["thresholds"], "partition": body["spec"]["partition"],
        "preregistration": {"id": str(event.pk), "digest": event.metadata["digest"]},
    }


def check_run_recipient(actor, run, *, custodian):
    """Registration narrows recipients; it never substitutes for current assignment."""
    reference = run.protocol.get("preregistration")
    if reference is None:
        return
    event = EvaluationAuditEvent.objects.filter(pk=reference["id"], kind=KIND).first()
    if event is None or event.metadata.get("digest") != reference["digest"]:
        raise ev.EvaluationError("Run preregistration is unavailable.", status=409)
    body = _bound(event, run.snapshot, run.profile)
    field = "custodian_ids" if custodian else "aggregate_recipient_ids"
    if str(actor.pk) not in body["spec"][field]:
        raise ev.EvaluationError


@transaction.atomic
def protocol_payload(actor, event):
    snapshot = EvaluationDatasetSnapshot.objects.get(pk=event.target_id)
    ev.require(actor, "custodian", snapshot)
    ev.snapshot_eligible(snapshot, lock=True)
    profile = ReviewerProfile.objects.get(pk=event.metadata["body"]["profile_id"])
    body = _bound(event, snapshot, profile)
    if str(actor.pk) not in body["spec"]["custodian_ids"]:
        raise ev.EvaluationError
    ev.audit(actor, snapshot, "protocol_served", {"protocol_id": str(event.pk)})
    return {"id": str(event.pk), "digest": event.metadata["digest"], "body": body}
