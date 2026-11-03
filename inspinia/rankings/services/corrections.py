"""Typed, version-checked corrections; no ownership changes or private fields."""

import hashlib
import json
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from decimal import InvalidOperation

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db.models import Max
from django.utils import timezone

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import AssessmentAnalysisMetadata
from inspinia.rankings.models import AssessmentCategoryScale
from inspinia.rankings.models import OutcomeAlias
from inspinia.rankings.models import RankingCorrection
from inspinia.rankings.models import RankingCorrectionItem
from inspinia.rankings.models import RankingCorrectionReceipt
from inspinia.rankings.models import RankingImportConflict
from inspinia.rankings.models import ResultClaim
from inspinia.rankings.models import ResultProfile
from inspinia.rankings.models import ResultSchoolAttribution
from inspinia.rankings.models import School
from inspinia.rankings.models import SchoolAlias
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentIdentityReview
from inspinia.rankings.models import StudentResult
from inspinia.rankings.models import normalize_name
from inspinia.rankings.models import normalize_whitespace
from inspinia.rankings.services.achievement_records import result_fingerprint
from inspinia.rankings.services.import_protection import ranking_write_lock
from inspinia.users.roles import user_has_admin_role
from inspinia.users.roles import user_has_moderator_or_admin_role

FIELDS = {
    "student": ("full_name", "birth_year", "school_id"),
    "result": ("raw_score", "medal", "band", "status_text"),
    "assessment": ("display_name", "assessment_date"),
    "metadata": ("family", "definition", "definition_verified", "date_verified"),
    "scale": ("band", "max_score", "verified", "comparable_scope", "evidence"),
    "attribution": ("school_id", "verified", "evidence"),
    "school_alias": ("alias", "school_id", "active"),
    "outcome_alias": ("field", "alias", "canonical", "active"),
    "identity": ("second_student_id", "decision", "evidence", "active"),
    "profile": ("record_type", "discipline", "scope", "scope_detail", "participation", "featured", "active"),
    "claim": (
        "claim_type", "claim_label", "award_kind", "verification_status", "source_type", "source_label", "source_url",
        "evidence", "active",
    ),
}
BASE_MODELS = {"student": Student, "result": StudentResult, "assessment": Assessment}
BOOLEAN_FIELDS = {"definition_verified", "date_verified", "verified", "active", "featured"}
MAX_ITEMS = 2000
MAX_TEXT_LENGTH = 4000
MIN_BIRTH_YEAR = 1900
MAX_SCORE = Decimal("100000000")
SCORE_PRECISION = -2


class StaleCorrection(ValueError):  # noqa: N818 - Public domain exception retained for callers.
    """A reviewed target changed; no portion of the proposal was applied."""


@contextmanager
def _stale_target_errors():
    try:
        yield
    except ObjectDoesNotExist as exc:
        message = "A reviewed record is no longer available. Prepare a fresh proposal; nothing was applied."
        raise StaleCorrection(message) from exc


def _access(actor, *, admin=False):
    if not (user_has_admin_role(actor) if admin else user_has_moderator_or_admin_role(actor)):
        raise PermissionDenied


def scalar(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _target(kind, target_id, values):  # noqa: PLR0911 - Each typed target has a distinct lookup key.
    if kind in BASE_MODELS:
        return BASE_MODELS[kind].objects.get(pk=target_id)
    if kind == "metadata":
        Assessment.objects.get(pk=target_id)
        return AssessmentAnalysisMetadata.objects.filter(assessment_id=target_id).first()
    if kind == "scale":
        Assessment.objects.get(pk=target_id)
        return AssessmentCategoryScale.objects.filter(assessment_id=target_id, band=values.get("band", "")).first()
    if kind == "attribution":
        StudentResult.objects.get(pk=target_id)
        return ResultSchoolAttribution.objects.filter(result_id=target_id).first()
    if kind in {"profile", "claim"}:
        StudentResult.objects.get(pk=target_id)
        if kind == "profile":
            return ResultProfile.objects.filter(result_id=target_id).first()
        return ResultClaim.objects.filter(result_id=target_id, claim_type=values.get("claim_type", "award")).first()
    if kind == "school_alias":
        School.objects.get(pk=target_id)
        return SchoolAlias.objects.filter(normalized_name=normalize_name(values.get("alias", ""))).first()
    if kind == "outcome_alias":
        Assessment.objects.get(pk=target_id)
        return OutcomeAlias.objects.filter(
            assessment_id=target_id,
            field=values.get("field"),
            normalized_alias=normalize_name(values.get("alias", "")),
        ).first()
    if kind == "identity":
        Student.objects.get(pk=target_id)
        return StudentIdentityReview.objects.filter(
            first_student_id=target_id,
            second_student_id=values.get("second_student_id"),
        ).first()
    msg = "Unknown correction type."
    raise ValidationError(msg)


def snapshot(kind, target_id, values):
    obj = _target(kind, target_id, values)
    state = {
        "exists": obj is not None,
        "version": obj.updated_at.isoformat() if obj else None,
        "values": {name: scalar(getattr(obj, name)) for name in FIELDS[kind]} if obj else {},
    }
    if kind in {"metadata", "scale", "outcome_alias"}:
        assessment = Assessment.objects.get(pk=target_id)
        state["dependency"] = {
            "assessment_version": assessment.updated_at.isoformat(),
            "assessment_date": scalar(assessment.assessment_date),
        }
        if kind == "outcome_alias":
            state["dependency"]["cohort"] = _alias_population(target_id, values, obj)
    elif kind in {"attribution", "profile", "claim"}:
        result = StudentResult.objects.select_related("assessment").get(pk=target_id)
        state["dependency"] = {"result_version": result.updated_at.isoformat()}
        if kind in {"profile", "claim"}:
            state["dependency"]["result_fingerprint"] = result_fingerprint(result)
            state["reviewed_fingerprint"] = obj.result_fingerprint if obj else None
    elif kind == "school_alias":
        state["dependency"] = {"school_version": School.objects.get(pk=target_id).updated_at.isoformat()}
    elif kind == "identity":
        state["dependency"] = list(
            Student.objects.filter(pk__in=[target_id, values.get("second_student_id")])
            .order_by("pk")
            .values_list("pk", "updated_at"),
        )
        state["dependency"] = [[pk, stamp.isoformat()] for pk, stamp in state["dependency"]]
    return state


def _alias_population(assessment_id, values, existing):
    field = values.get("field")
    if field not in OutcomeAlias.Field.values:
        msg = "Choose a category, medal or status field."
        raise ValidationError(msg)
    labels = {normalize_name(values.get("alias", "")), normalize_name(values.get("canonical", ""))}
    if existing:
        labels.add(normalize_name(existing.canonical))
    records = [
        [pk, label, updated.isoformat()]
        for pk, label, updated in StudentResult.objects.filter(assessment_id=assessment_id)
        .order_by("pk")
        .values_list("pk", field, "updated_at")
        if normalize_name(label) in labels
    ]
    aliases = [
        [pk, alias, canonical, updated.isoformat()]
        for pk, alias, canonical, updated in OutcomeAlias.objects.filter(
            assessment_id=assessment_id, field=field, active=True,
        )
        .order_by("pk")
        .values_list("pk", "normalized_alias", "canonical", "updated_at")
    ]
    digest = hashlib.sha256(json.dumps([records, aliases]).encode()).hexdigest()
    return {"records": len(records), "revision": digest}


def _clean_record_value(key, value):
    if value in (None, "") and key != "second_student_id":
        result = None
    elif isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit() or not 0 < int(value) < 2**63:
        message = "Choose a valid record or year."
        raise ValidationError(message)
    else:
        result = int(value)
    if key == "birth_year" and result is not None and not MIN_BIRTH_YEAR <= result <= timezone.now().year:
        message = "Birth year must be between 1900 and the current year."
        raise ValidationError(message)
    return result


def _clean_score(value):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        message = "Enter a valid score."
        raise ValidationError(message) from exc
    if not number.is_finite() or number < 0 or number >= MAX_SCORE or number.as_tuple().exponent < SCORE_PRECISION:
        message = "Scores must be nonnegative with at most two decimal places."
        raise ValidationError(message)
    return str(number)


def _clean_field_value(key, value):
    if key in BOOLEAN_FIELDS:
        if not isinstance(value, bool):
            message = "Verification and active values must be true or false."
            raise ValidationError(message)
        return value
    if key in {"school_id", "second_student_id", "birth_year"}:
        return _clean_record_value(key, value)
    if key in {"raw_score", "max_score"}:
        return _clean_score(value)
    if key == "assessment_date":
        try:
            return date.fromisoformat(str(value)).isoformat() if value else None
        except ValueError as exc:
            message = "Choose a valid assessment date."
            raise ValidationError(message) from exc
    if not isinstance(value, str):
        message = "Enter text for this field."
        raise ValidationError(message)
    cleaned = value.strip() if key in {"definition", "evidence"} else normalize_whitespace(value)
    if len(cleaned) > MAX_TEXT_LENGTH:
        message = "Correction text must be at most 4000 characters."
        raise ValidationError(message)
    return cleaned


def clean_values(kind, values):
    if kind not in FIELDS or not isinstance(values, dict) or not values or set(values) - set(FIELDS[kind]):
        message = "Only the displayed correction fields may be changed."
        raise ValidationError(message)
    cleaned = {key: _clean_field_value(key, value) for key, value in values.items()}
    if kind == "claim" and cleaned.get("claim_type") not in ResultClaim.ClaimType.values:
        message = "Choose the specific award, score or ranking claim."
        raise ValidationError(message)
    return cleaned


def current_values(kind, target_id, hints=None):
    """Safe form initials, never arbitrary model serialization."""
    hints = hints or {}
    return snapshot(kind, target_id, hints)["values"]


# The public interface carries actor, provenance, operation list, and lifecycle options.
def create_proposal(*, actor, reason, evidence, operations, submit=False, reverses=None):  # noqa: PLR0913
    _access(actor)
    reason, evidence = reason.strip(), evidence.strip()
    if (
        not reason
        or len(reason) > MAX_TEXT_LENGTH
        or len(evidence) > MAX_TEXT_LENGTH
        or not 0 < len(operations) <= MAX_ITEMS
    ):
        msg = "Provide a reason and between one and 2000 correction items."
        raise ValidationError(msg)
    with ranking_write_lock():
        prepared = []
        inverse_targets = (
            {
                _prepared_key(
                    operation["kind"],
                    int(operation["target_id"]),
                    clean_values(operation["kind"], operation["values"]),
                )
                for operation in operations
            }
            if reverses
            else set()
        )
        for operation in operations:
            kind, target_id = operation["kind"], int(operation["target_id"])
            values = clean_values(kind, operation["values"])
            if kind == "identity":
                second = values.get("second_student_id")
                if second is None or second == target_id:
                    msg = "Choose two different students."
                    raise ValidationError(msg)
                target_id, values["second_student_id"] = sorted((target_id, second))
            before = snapshot(kind, target_id, values)
            # Validate using an unsaved instance. No target is modified by a preview.
            _updated_object(kind, target_id, values, actor=actor, evidence=evidence, save=False)
            keys = (
                {"band"}
                if kind == "scale"
                else {"alias", "field"}
                if kind == "outcome_alias"
                else {"alias"}
                if kind == "school_alias"
                else {"second_student_id"}
                if kind == "identity"
                else {"claim_type"}
                if kind == "claim"
                else set()
            )
            changed = {
                key: value for key, value in values.items() if key in keys or before["values"].get(key) != value
            }
            if kind in {"profile", "claim"} and before.get("reviewed_fingerprint") != before["dependency"][
                "result_fingerprint"
            ]:
                changed = dict(values)
            if not before["exists"] or any(key not in keys for key in changed):
                prepared.append((kind, target_id, before, changed))
            prepared.extend(
                item
                for item in _dependent_items(kind, target_id, values, before, changed)
                if _prepared_key(item[0], item[1], item[3]) not in inverse_targets
            )
        prepared = _dedupe_prepared_items(prepared)
        if not prepared:
            msg = "No values changed. Edit a field before preparing a correction."
            raise ValidationError(msg)
        if len(prepared) > MAX_ITEMS:
            msg = "This correction affects more than 2000 records; narrow its scope."
            raise ValidationError(msg)
        proposal = RankingCorrection.objects.create(
            created_by=actor,
            reason=reason,
            evidence=evidence,
            reverses=reverses,
            status=RankingCorrection.Status.SUBMITTED if submit else RankingCorrection.Status.DRAFT,
        )
        RankingCorrectionItem.objects.bulk_create(
            [
                RankingCorrectionItem(correction=proposal, kind=kind, target_id=target, before=before, changes=values)
                for kind, target, before, values in prepared
            ],
        )
        return proposal


def _dependent_items(kind, target_id, values, before, changed):
    dependent = []
    if kind == "assessment" and "assessment_date" in changed:
        metadata = AssessmentAnalysisMetadata.objects.filter(assessment_id=target_id, date_verified=True).first()
        if metadata:
            patch = {"date_verified": False}
            dependent.append(("metadata", target_id, snapshot("metadata", target_id, patch), patch))
    if kind == "outcome_alias" and values.get("active", True):
        dependent.extend(_outcome_rename_items(target_id, values, before))
    return dependent


def _outcome_rename_items(assessment_id, values, before):
    field, canonical = values["field"], values["canonical"]
    previous = before["values"].get("canonical")
    renaming = before["exists"] and previous != canonical
    labels = {normalize_name(values["alias"])}
    if renaming:
        labels.add(normalize_name(previous))
    prepared = []
    records = StudentResult.objects.filter(assessment_id=assessment_id).only(
        "id",
        field,
        "updated_at",
        "raw_score",
        "medal",
        "band",
        "status_text",
    )
    for record in records:
        if normalize_name(getattr(record, field)) in labels and getattr(record, field) != canonical:
            patch = {field: canonical}
            prepared.append(("result", record.pk, snapshot("result", record.pk, patch), patch))
    if renaming:
        aliases = OutcomeAlias.objects.filter(assessment_id=assessment_id, field=field, active=True).exclude(
            normalized_alias=normalize_name(values["alias"]),
        )
        for alias in aliases:
            if normalize_name(alias.canonical) == normalize_name(previous) and alias.canonical != canonical:
                patch = {"field": field, "alias": alias.alias, "canonical": canonical}
                prepared.append(
                    ("outcome_alias", assessment_id, snapshot("outcome_alias", assessment_id, patch), patch),
                )
    return prepared


def _prepared_key(kind, target_id, values):
    selectors = {
        "scale": (values.get("band", ""),),
        "outcome_alias": (values.get("field"), normalize_name(values.get("alias", ""))),
        "school_alias": (normalize_name(values.get("alias", "")),),
        "identity": (values.get("second_student_id"),),
        "claim": (values.get("claim_type"),),
    }
    return kind, target_id, selectors.get(kind, ())


def _dedupe_prepared_items(prepared):
    combined = {}
    for kind, target, before, changes in prepared:
        key = _prepared_key(kind, target, changes)
        if key in combined:
            _, _, prior_before, prior_changes = combined[key]
            contradictory = any(prior_changes[name] != changes[name] for name in prior_changes.keys() & changes.keys())
            if prior_before != before or contradictory:
                message = "A proposal contains contradictory changes for the same target."
                raise ValidationError(message)
            prior_changes.update(changes)
        else:
            combined[key] = (kind, target, before, dict(changes))
    return list(combined.values())


def _updated_object(kind, target_id, values, *, actor, evidence, save):  # noqa: C901, PLR0912, PLR0913, PLR0915 - Typed correction validation.
    obj = _target(kind, target_id, values)
    if obj is None:
        constructors = {
            "metadata": lambda: AssessmentAnalysisMetadata(assessment_id=target_id),
            "scale": lambda: AssessmentCategoryScale(assessment_id=target_id),
            "attribution": lambda: ResultSchoolAttribution(result_id=target_id),
            "school_alias": SchoolAlias,
            "outcome_alias": lambda: OutcomeAlias(assessment_id=target_id),
            "identity": lambda: StudentIdentityReview(first_student_id=target_id),
            "profile": lambda: ResultProfile(result_id=target_id),
            "claim": lambda: ResultClaim(result_id=target_id),
        }
        obj = constructors[kind]()
    for key, raw_value in values.items():
        value = raw_value
        if key in {"raw_score", "max_score"}:
            value = Decimal(value) if value is not None else None
        if key == "assessment_date":
            value = date.fromisoformat(value) if value else None
        setattr(obj, key, value)
    if kind == "metadata":
        obj.reviewed_by = actor
        if (obj.definition_verified and (not obj.family or not obj.definition)) or (
            obj.date_verified and not obj.assessment.assessment_date
        ):
            msg = "A verified definition needs a family and definition; a verified date needs an assessment date."
            raise ValidationError(
                msg,
            )
        if (values.get("definition_verified") or values.get("date_verified")) and not evidence:
            msg = "Provide evidence before verifying assessment metadata."
            raise ValidationError(msg)
    if kind == "scale" and obj.verified:
        if not obj.max_score or not (evidence or obj.evidence):
            msg = "A verified scale needs a positive maximum and evidence."
            raise ValidationError(msg)
        maximum = StudentResult.objects.filter(assessment_id=target_id, band=obj.band).aggregate(
            value=Max("raw_score"),
        )["value"]
        if maximum is not None and maximum > obj.max_score:
            msg = "Recorded scores exceed this maximum. Review those scores before verifying the scale."
            raise ValidationError(
                msg,
            )
        obj.evidence = evidence or obj.evidence
    if kind == "result" and obj.raw_score is not None:
        scale = AssessmentCategoryScale.objects.filter(
            assessment_id=obj.assessment_id,
            band=obj.band,
            verified=True,
        ).first()
        if scale and obj.raw_score > scale.max_score:
            msg = "This score exceeds the verified maximum for the category."
            raise ValidationError(msg)
    if kind == "attribution":
        if not (evidence or obj.evidence):
            msg = "Provide evidence for the assessment school."
            raise ValidationError(msg)
        obj.evidence, obj.reviewed_by = evidence or obj.evidence, actor
        obj.reviewed_at = timezone.now()
    if kind == "school_alias":
        obj.normalized_name = normalize_name(obj.alias)
        if obj.active:
            if (
                SchoolAlias.objects.filter(active=True, normalized_name=obj.school.normalized_name)
                .exclude(pk=obj.pk)
                .exclude(school_id=obj.school_id)
                .exists()
            ):
                msg = "Choose a canonical school, not another alias."
                raise ValidationError(msg)
            if (
                SchoolAlias.objects.filter(active=True, school__normalized_name=obj.normalized_name)
                .exclude(pk=obj.pk)
                .exclude(school_id=obj.school_id)
                .exists()
            ):
                msg = "This alias would create an alias chain."
                raise ValidationError(msg)
    if kind == "outcome_alias":
        obj.normalized_alias = normalize_name(obj.alias)
        if obj.field not in OutcomeAlias.Field.values:
            msg = "Choose a category, medal or status field."
            raise ValidationError(msg)
        if len(obj.canonical) > (64 if obj.field == "status_text" else 32):
            msg = "Canonical labels are too long for this result field."
            raise ValidationError(msg)
        if (
            obj.active
            and OutcomeAlias.objects.filter(
                assessment_id=target_id,
                field=obj.field,
                active=True,
                normalized_alias=normalize_name(obj.canonical),
            )
            .exclude(pk=obj.pk)
            .exclude(normalized_alias=obj.normalized_alias)
            .exists()
        ):
            msg = "Choose a final label, not another alias."
            raise ValidationError(msg)
        if obj.active:
            others = OutcomeAlias.objects.filter(assessment_id=target_id, field=obj.field, active=True).exclude(
                pk=obj.pk,
            )
            if any(
                normalize_name(other.canonical) == obj.normalized_alias
                and normalize_name(obj.canonical) != obj.normalized_alias
                for other in others
            ):
                msg = "This change would create an outcome alias chain."
                raise ValidationError(msg)
    if kind == "identity":
        Student.objects.get(pk=obj.second_student_id)
        if not (evidence or obj.evidence):
            msg = "Provide evidence for the identity decision."
            raise ValidationError(msg)
        obj.evidence = evidence or obj.evidence
    if kind in {"profile", "claim"}:
        result = StudentResult.objects.select_related("assessment").get(pk=target_id)
        obj.result_fingerprint = result_fingerprint(result)
        obj.reviewed_by, obj.reviewed_at = actor, timezone.now()
        if kind == "claim":
            obj.evidence = evidence or obj.evidence
            if obj.claim_type == "score" and obj.active:
                if result.raw_score is None:
                    message = "This result has no recorded score to verify."
                    raise ValidationError(message)
                expected = format(Decimal(str(result.raw_score)), ".2f")
                if obj.claim_label != expected:
                    message = "The score claim must match the recorded raw score exactly (two decimal places)."
                    raise ValidationError(message)
    # Snapshot fields are deliberately unrelated to Student private identifiers.
    obj.full_clean()
    if save:
        obj.save()
    return obj


@_stale_target_errors()
def apply_proposal(*, proposal_id, actor):
    _access(actor, admin=True)
    with ranking_write_lock():
        proposal = RankingCorrection.objects.select_for_update().get(pk=proposal_id)
        if proposal.status == RankingCorrection.Status.APPLIED:
            return proposal
        if proposal.status != RankingCorrection.Status.SUBMITTED:
            msg = "Only a submitted proposal can be applied."
            raise ValidationError(msg)
        if proposal.import_conflicts.exclude(status="pending").exists():
            msg = "The originating import conflict has already been resolved. Nothing was applied."
            raise StaleCorrection(msg)
        items = list(proposal.items.all())
        _lock_targets(items)
        for item in items:
            if snapshot(item.kind, item.target_id, item.changes) != item.before:
                msg = "A record changed after this preview. Prepare a fresh proposal; nothing was applied."
                raise StaleCorrection(
                    msg,
                )
        for item in items:
            _updated_object(
                item.kind,
                item.target_id,
                item.changes,
                actor=actor,
                evidence=proposal.evidence,
                save=True,
            )
        receipt = [
            {
                "kind": item.kind,
                "target_id": item.target_id,
                "before": item.before,
                "after": snapshot(item.kind, item.target_id, item.changes),
            }
            for item in items
        ]
        RankingCorrectionReceipt.objects.create(correction=proposal, actor=actor, changes=receipt)
        proposal.status, proposal.decided_by, proposal.decided_at = (
            RankingCorrection.Status.APPLIED,
            actor,
            timezone.now(),
        )
        proposal.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
        RankingImportConflict.objects.filter(correction=proposal, status="pending").update(
            status="replaced",
            resolved_by=actor,
            resolved_at=proposal.decided_at,
        )
        return proposal


def _lock_targets(items):
    models = {
        **BASE_MODELS,
        "metadata": Assessment,
        "scale": Assessment,
        "outcome_alias": Assessment,
        "attribution": StudentResult,
        "profile": StudentResult,
        "claim": StudentResult,
        "school_alias": School,
        "identity": Student,
    }
    lock_ids = {Assessment: set(), School: set(), Student: set(), StudentResult: set()}
    for item in items:
        lock_ids[models[item.kind]].add(item.target_id)
        if item.kind == "identity":
            lock_ids[Student].add(item.changes["second_student_id"])
    for model, ids in lock_ids.items():
        list(model.objects.select_for_update().filter(pk__in=ids).order_by("pk").values_list("pk", flat=True))


def transition_proposal(*, proposal_id, actor, action, reason=""):
    _access(actor, admin=action == "reject")
    with ranking_write_lock():
        proposal = RankingCorrection.objects.select_for_update().get(pk=proposal_id)
        if proposal.status not in {"draft", "submitted"}:
            msg = "This proposal is already closed."
            raise ValidationError(msg)
        if action in {"submit", "withdraw"} and proposal.created_by_id != actor.pk:
            raise PermissionDenied
        if action == "submit" and proposal.status == "draft":
            proposal.status = "submitted"
        elif action == "withdraw":
            proposal.status = "withdrawn"
        elif action == "reject" and reason.strip():
            proposal.status, proposal.decision_reason = "rejected", reason.strip()[:4000]
            proposal.decided_by, proposal.decided_at = actor, timezone.now()
        else:
            msg = "Choose an available action and provide a reason when rejecting."
            raise ValidationError(msg)
        proposal.save()
        return proposal


@_stale_target_errors()
def reverse_proposal(*, proposal_id, actor, reason):
    _access(actor)
    original = RankingCorrection.objects.get(pk=proposal_id, status="applied")
    operations = []
    for item in original.items.all():
        if item.before["exists"]:
            values = {key: item.before["values"][key] for key in item.changes}
        else:
            values = dict(item.changes)
            if item.kind == "metadata":
                values.update(family="", definition="", definition_verified=False, date_verified=False)
            elif item.kind == "scale":
                values.update(max_score=None, verified=False, comparable_scope="", evidence="")
            elif item.kind == "attribution":
                values["verified"] = False
            elif item.kind in {"profile", "claim"}:
                values["active"] = False
            else:
                values["active"] = False
        operations.append({"kind": item.kind, "target_id": item.target_id, "values": values})
    return create_proposal(
        actor=actor,
        reason=reason,
        evidence=f"Reversal of correction #{original.pk}",
        operations=operations,
        reverses=original,
    )


def resolve_import_conflict(*, conflict_id, actor, action, school_id=None):
    _access(actor, admin=True)
    with ranking_write_lock():
        conflict = RankingImportConflict.objects.select_for_update().get(pk=conflict_id)
        if conflict.status != "pending":
            return conflict
        if action == "keep":
            if conflict.correction_id:
                RankingCorrection.objects.filter(pk=conflict.correction_id, status__in=["draft", "submitted"]).update(
                    status="withdrawn",
                    decision_reason="The approved import values were retained.",
                    decided_by=actor,
                    decided_at=timezone.now(),
                    updated_at=timezone.now(),
                )
            conflict.status, conflict.resolved_by, conflict.resolved_at = "kept", actor, timezone.now()
            conflict.save(update_fields=["status", "resolved_by", "resolved_at"])
        elif action == "replace":
            if conflict.correction_id and conflict.correction.status in {"draft", "submitted"}:
                return conflict
            operations = _replacement_operations(conflict.operations, school_id)
            proposal = create_proposal(
                actor=actor,
                reason=f"Review held row {conflict.row_number} from import #{conflict.batch_id}",
                evidence="Normalized values retained from the reviewed import preview.",
                operations=operations,
            )
            conflict.correction = proposal
            conflict.save(update_fields=["correction"])
        else:
            msg = "Choose keep or prepare replacement."
            raise ValidationError(msg)
        return conflict


def _replacement_operations(recorded_operations, school_id):
    operations = [dict(operation, values=dict(operation["values"])) for operation in recorded_operations]
    unresolved = [
        operation
        for operation in operations
        if isinstance(operation["values"].get("school_id"), str)
        and operation["values"]["school_id"].startswith("new:")
    ]
    if unresolved:
        selected = _clean_record_value("school_id", school_id)
        if selected is None or not School.objects.filter(pk=selected).exists():
            message = "Choose an existing canonical school before preparing this replacement."
            raise ValidationError(message)
        for operation in unresolved:
            operation["values"]["school_id"] = selected
    return operations
