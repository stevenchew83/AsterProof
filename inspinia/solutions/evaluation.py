"""Offline mathematical evidence services; no provider or network imports."""

# ruff: noqa: EM101, EM102, TRY003, PLR0913, PLR0912, C901, PLR2004, TRY301, SLF001
import hashlib
import json
import uuid
from datetime import datetime
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image

from inspinia.users.roles import user_can_curate_training
from inspinia.users.roles import user_has_admin_role

from .evaluation_models import CoachJudgment
from .evaluation_models import EvaluationAssignment
from .evaluation_models import EvaluationAuditEvent
from .evaluation_models import EvaluationCase
from .evaluation_models import EvaluationDatasetSnapshot
from .evaluation_models import EvaluationFindingJudgment
from .evaluation_models import EvaluationLifecycle
from .evaluation_models import EvaluationProblemFamily
from .evaluation_models import EvaluationRun
from .evaluation_models import ReadinessEvidence
from .evaluation_models import ReviewBundleAsset
from .evaluation_models import ReviewConsent
from .evaluation_models import ReviewerProfile
from .evaluation_models import ReviewInputBundle

WORKSPACE = uuid.UUID("00000000-0000-0000-0000-000000000001")
ROLES = {"curator", "reviewer", "adjudicator", "finding_evaluator", "custodian", "developer", "activation"}
ORIGINS = {"deterministic_fixture", "manual_import", "unverified_external"}
PARTITIONS = {"development", "validation", "final_test"}
RUBRIC = {
    "assessment": {"no_issues_found", "gap_found", "incomplete", "unable_to_assess"},
    "input_sufficiency": {"present", "partial", "missing_essential_context", "unreadable", "unresolved"},
    "problem_integrity": {"no_known_defect", "suspected_defect", "confirmed_defect", "unresolved"},
    "logical_validity": {"valid", "invalid", "uncertain"},
    "proof_completeness": {"complete", "incomplete", "undetermined"},
    "justification": {"sufficient", "compressed_acceptable", "missing_substantial", "undetermined"},
    "method": {"conventional", "alternative", "advanced", "unresolved"},
    "task_compliance": {"met", "unmet", "undetermined"},
}


class EvaluationError(ValueError):
    def __init__(
        self,
        message="Evidence is unavailable or permission is missing.",
        *,
        code="evidence_denied",
        status=403,
    ):
        super().__init__(message)
        self.code, self.status = code, status


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(),
    ).hexdigest()


def audit(actor, target, kind, metadata=None):
    return EvaluationAuditEvent.objects.create(
        actor=actor,
        target_id=getattr(target, "pk", target),
        kind=kind,
        metadata=metadata or {},
    )


def lifecycle(target, *, lock=False):
    key = getattr(target, "pk", target)
    query = EvaluationLifecycle.objects.select_for_update() if lock else EvaluationLifecycle.objects
    state = query.filter(target_id=key).first()
    if state is None:
        state = EvaluationLifecycle.objects.create(target_id=key)
    if not state.eligible:
        raise EvaluationError("This evidence is no longer eligible.", code="evidence_invalidated", status=409)
    return state


def scope_ids(target):
    ids = {getattr(target, "pk", target)}
    if isinstance(target, EvaluationCase):
        ids.add(target.family_id)
    return ids


def assignments(user):
    if not getattr(user, "is_authenticated", False) or not user.is_active or not user_can_curate_training(user):
        return EvaluationAssignment.objects.none()
    return EvaluationAssignment.objects.filter(actor=user, active=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()),
    )


def allowed(user, role, target):
    return assignments(user).filter(role=role, scope_id__in=scope_ids(target)).exists()


def blinded_case_ids(user):
    scopes = EvaluationAssignment.objects.filter(actor=user, role="developer").values_list("scope_id", flat=True)
    families = {
        row["family_id"]
        for snapshot in EvaluationDatasetSnapshot.objects.filter(pk__in=scopes)
        for row in snapshot.manifest["cases"]
    }
    return {str(pk) for pk in EvaluationCase.objects.filter(family_id__in=families).values_list("pk", flat=True)}


def require(user, role, target):
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        raise EvaluationError
    if connection.in_atomic_block:
        decision_lock()
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
    query = assignments(user).filter(role=role, scope_id__in=scope_ids(target))
    if connection.in_atomic_block:
        query = query.select_for_update()
    if not query.exists():
        raise EvaluationError
    lifecycle(target)


def decision_lock():
    """Serialize low-volume trust decisions, including cross-record invalidation."""
    EvaluationLifecycle.objects.get_or_create(target_id=WORKSPACE)
    EvaluationLifecycle.objects.select_for_update().get(target_id=WORKSPACE)


@transaction.atomic
def grant(actor, subject, role, target, *, expertise="", expires_at=None):
    decision_lock()
    subject = get_user_model().objects.select_for_update().get(pk=subject.pk)
    if not user_has_admin_role(actor) or not actor.has_perm("solutions.add_evaluationassignment"):
        raise EvaluationError
    if role not in ROLES or not subject.is_active or not user_can_curate_training(subject):
        raise EvaluationError("Appoint an approved trainer or administrator to a known capability.")
    if role in {"reviewer", "adjudicator", "finding_evaluator"} and not expertise.strip():
        raise EvaluationError("Record the appointed mathematical expertise.")
    opposite = "developer" if role == "custodian" else "custodian" if role == "developer" else None
    if opposite and EvaluationAssignment.objects.filter(actor=subject, role=opposite).exists():
        raise EvaluationError("Custody and prompt-development histories must remain separate.")
    key = getattr(target, "pk", target)
    if isinstance(target, EvaluationDatasetSnapshot) and role == "developer":
        family_ids = [row["family_id"] for row in target.manifest["cases"]]
        case_ids = [
            str(pk) for pk in EvaluationCase.objects.filter(family_id__in=family_ids).values_list("pk", flat=True)
        ]
        if EvaluationAssignment.objects.filter(actor=subject, scope_id__in=[*case_ids, *family_ids]).exists():
            raise EvaluationError("Historical case assignments prevent blinded final-test access.")
        if EvaluationAuditEvent.objects.filter(
            actor=subject,
            target_id__in=case_ids,
            kind__in=[
                "case_served",
                "asset_served",
                "judgment_submitted",
                "case_created",
                "adjudication_submitted",
                "finding_report_served",
            ],
        ).exists():
            raise EvaluationError("Prior case exposure prevents blinded final-test access.")
    if role != "developer" and EvaluationAssignment.objects.filter(actor=subject, role="developer").exists():
        if isinstance(target, (EvaluationCase, EvaluationProblemFamily)):
            raise EvaluationError("A blinded developer cannot receive case-level assignments.")
    item, _ = EvaluationAssignment.objects.update_or_create(
        actor=subject,
        role=role,
        scope_id=key,
        defaults={"appointed_by": actor, "expertise": expertise, "expires_at": expires_at, "active": True},
    )
    audit(actor, key, "appointment", {"assignment_id": str(item.pk), "role": role})
    return item


@transaction.atomic
def revoke_assignment(actor, assignment):
    decision_lock()
    if not user_has_admin_role(actor) or not actor.has_perm("solutions.change_evaluationassignment"):
        raise EvaluationError
    assignment.active = False
    assignment.save(update_fields=["active"])
    audit(actor, assignment.scope_id, "assignment_revoked", {"assignment_id": str(assignment.pk)})


def visible_families(user):
    scopes = assignments(user).values_list("scope_id", flat=True)
    return EvaluationProblemFamily.objects.filter(Q(pk__in=scopes) | Q(cases__pk__in=scopes)).distinct()


def visible_cases(user):
    scopes = assignments(user).exclude(role="developer").values_list("scope_id", flat=True)
    invalid = EvaluationLifecycle.objects.filter(eligible=False).values_list("target_id", flat=True)
    return (
        EvaluationCase.objects.filter(Q(pk__in=scopes) | Q(family_id__in=scopes))
        .exclude(pk__in=invalid)
        .exclude(pk__in=blinded_case_ids(user))
        .select_related(
            "family",
            "bundle",
            "prepared_by",
        )
        .order_by("-created_at")
    )


def visible_snapshots(user):
    scopes = assignments(user).filter(role__in=["custodian", "developer"]).values_list("scope_id", flat=True)
    return EvaluationDatasetSnapshot.objects.filter(pk__in=scopes).order_by("-created_at")


def visible_runs(user):
    return EvaluationRun.objects.filter(snapshot__in=visible_snapshots(user)).select_related("snapshot", "profile")


def visible_profiles(user):
    return ReviewerProfile.objects.all() if assignments(user).exists() else ReviewerProfile.objects.none()


@transaction.atomic
def create_family(actor, data):
    require(actor, "curator", WORKSPACE)
    if data.get("domain") not in {"ALG", "GEO", "NT", "COM"} or not str(data.get("title", "")).strip():
        raise EvaluationError("Provide a title and mathematical domain.", status=422)
    family = EvaluationProblemFamily.objects.create(
        title=data["title"][:200],
        domain=data["domain"],
        metadata={"public_familiarity": "unknown", "level": "unspecified", **data.get("metadata", {})},
        prepared_by=actor,
    )
    EvaluationLifecycle.objects.create(target_id=family.pk)
    EvaluationAssignment.objects.create(actor=actor, appointed_by=actor, role="curator", scope_id=family.pk)
    audit(actor, family, "family_created")
    return family


def _asset(data):
    raw = data["data"]
    if not isinstance(raw, bytes) or len(raw) > 3_000_000:
        raise EvaluationError("Each managed image must be at most 3 MB.", status=422)
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in {"PNG", "JPEG", "GIF", "WEBP"} or image.width * image.height > 16_000_000:
                raise EvaluationError("Unsupported image or dimensions.", status=422)
            width, height = image.size
            original_mime = Image.MIME[image.format]
            image.thumbnail((2048, 2048))
            output = BytesIO()
            image.convert("RGB").save(output, format="PNG")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise EvaluationError("Invalid managed image.", status=422) from error
    normalized = output.getvalue()
    role = data.get("role", "supporting_image")
    if role not in {"official_diagram", "supporting_image"}:
        raise EvaluationError("Unknown image role.", status=422)
    return (
        raw,
        normalized,
        {
            "role": role,
            "description": str(data.get("description", ""))[:500],
            "mime_type": "image/png",
            "original_mime_type": original_mime,
            "width": width,
            "height": height,
            "preprocessing": "rgb-png-2048-v1",
            "original_digest": hashlib.sha256(raw).hexdigest(),
            "normalized_digest": hashlib.sha256(normalized).hexdigest(),
        },
    )


@transaction.atomic
def create_bundle(actor, data, assets=()):
    if len(assets) > 4:
        raise EvaluationError("At most four managed images are supported.", status=422)
    if not all(isinstance(data.get(key), str) and data[key].strip() for key in ("statement", "source", "language")):
        raise EvaluationError("Statement, proof source and language are required.", status=422)
    if len(data["source"]) > 100_000 or len(data["statement"]) > 50_000:
        raise EvaluationError("Mathematical input is too long.", status=422)
    if data.get("completeness", "unresolved") not in RUBRIC["input_sufficiency"]:
        raise EvaluationError("Unknown input-completeness state.", status=422)
    if data.get("problem_integrity", "unresolved") not in RUBRIC["problem_integrity"]:
        raise EvaluationError("Unknown problem-integrity state.", status=422)
    prepared = [_asset(item) for item in assets]
    payload = {
        "schema_version": 1,
        "statement": data["statement"],
        "source": data["source"],
        "source_digest": hashlib.sha256(data["source"].encode()).hexdigest(),
        "language": data["language"],
        "statement_version": data.get("statement_version"),
        "revision_id": data.get("revision_id"),
        "conditions": data.get("conditions", {}),
        "conventions": data.get("conventions", []),
        "rubric_version": "math-v1",
        "modality": "typed_latex_managed_diagrams",
        "completeness": data.get("completeness", "unresolved"),
        "problem_integrity": data.get("problem_integrity", "unresolved"),
        "limitations": data.get("limitations", []),
        "assets": [item[2] for item in prepared],
    }
    bundle = ReviewInputBundle.objects.create(
        owner=actor,
        problem_uuid=uuid.UUID(str(data["problem_uuid"])) if data.get("problem_uuid") else None,
        payload=payload,
        digest=digest(payload),
    )
    for original, normalized, manifest in prepared:
        ReviewBundleAsset.objects.create(bundle=bundle, original=original, normalized=normalized, manifest=manifest)
    EvaluationLifecycle.objects.create(target_id=bundle.pk)
    audit(actor, bundle, "bundle_frozen")
    return bundle


def verify_bundle(bundle):
    lifecycle(bundle)
    if digest(bundle.payload) != bundle.digest:
        raise EvaluationError("Frozen input digest mismatch.", status=409)
    assets = list(bundle.assets.order_by("created_at", "id"))
    if len(assets) != len(bundle.payload["assets"]):
        raise EvaluationError("Frozen input assets are missing.", status=409)
    for item, manifest in zip(assets, bundle.payload["assets"], strict=True):
        if (
            item.manifest != manifest
            or hashlib.sha256(bytes(item.original)).hexdigest() != manifest["original_digest"]
            or (hashlib.sha256(bytes(item.normalized)).hexdigest() != manifest["normalized_digest"])
        ):
            raise EvaluationError("Frozen input asset digest mismatch.", status=409)


def _provenance(value):
    if not isinstance(value, dict) or not all(
        value.get(key)
        for key in (
            "source",
            "rights",
            "permitted_uses",
            "construction",
            "retention_until",
        )
    ):
        raise EvaluationError("Source rights, permitted uses, construction and retention are required.", status=422)
    try:
        expires = datetime.fromisoformat(value["retention_until"])
        if timezone.is_naive(expires) or expires <= timezone.now():
            raise ValueError
    except (ValueError, TypeError) as error:
        raise EvaluationError("Provide a future timezone-aware retention deadline.", status=422) from error
    if "benchmark" not in value["permitted_uses"]:
        raise EvaluationError("Benchmark reuse must be expressly permitted.", status=422)
    if not isinstance(value["permitted_uses"], list) or value["construction"] not in {
        "learner_submission",
        "coach_original",
        "public_source",
        "controlled_mutation",
        "synthetic",
    }:
        raise EvaluationError("Declare the permitted uses and construction method.", status=422)
    if value["construction"] == "learner_submission" and not all(
        value.get(k)
        for k in (
            "consent_reference",
            "lawful_eligibility",
            "withdrawal_policy",
        )
    ):
        raise EvaluationError("Learner reuse eligibility and consent are unresolved.", status=422)
    if value["construction"] == "learner_submission":
        try:
            consent = ReviewConsent.objects.get(
                pk=value["consent_reference"],
                purpose="benchmark_reuse",
                expires_at__gt=timezone.now(),
            )
            lifecycle(consent)
        except (ReviewConsent.DoesNotExist, ValueError, ValidationError) as error:
            raise EvaluationError(
                "Benchmark reuse requires a current authenticated consent record.",
                status=422,
            ) from error
        if not consent.payload.get("lawful_eligibility") or not consent.payload.get("retention_policy"):
            raise EvaluationError("Learner reuse eligibility is unresolved.", status=422)
        expected = {key: value.get(key) for key in ("learner_id", "source_revision_id", "source_digest")}
        if not all(expected.values()) or str(consent.actor_id) != str(expected["learner_id"]):
            raise EvaluationError("Consent must identify the learner and exact source revision.", status=422)
        if any(str(consent.payload.get(key)) != str(expected[key]) for key in expected):
            raise EvaluationError("The consent does not permit this source revision.", status=422)
        if expires > consent.expires_at:
            raise EvaluationError("Retention cannot outlast the learner reuse permission.", status=422)
        if not EvaluationAuditEvent.objects.filter(target_id=consent.pk, kind="reuse_eligibility_approved").exists():
            raise EvaluationError("Independent learner-reuse eligibility approval is required.", status=422)


@transaction.atomic
def create_case(actor, family, data, assets=()):
    require(actor, "curator", family)
    lifecycle(family, lock=True)
    provenance = data.get("provenance", {})
    _provenance(provenance)
    if provenance["construction"] == "learner_submission":
        from .models import SolutionRevision

        original = SolutionRevision.objects.filter(
            pk=provenance["source_revision_id"],
            solution__author_id=provenance["learner_id"],
        ).first()
        if (
            original is None
            or original.body_source != data.get("source")
            or hashlib.sha256(original.body_source.encode()).hexdigest() != provenance["source_digest"]
        ):
            raise EvaluationError("Import only the exact expressly authorized learner revision.", status=422)
        data = {**data, "problem_uuid": str(original.solution.problem.problem_uuid)}
        consent = ReviewConsent.objects.get(pk=provenance["consent_reference"])
        supplied_images = sorted(
            hashlib.sha256(item["data"]).hexdigest()
            for item in assets
            if item.get("role", "supporting_image") == "supporting_image"
        )
        if supplied_images != sorted(consent.payload.get("supporting_image_digests", [])):
            raise EvaluationError("Supporting images must match the exact learner reuse permission.", status=422)
    data = {"problem_uuid": str(family.pk), **data}
    bundle = create_bundle(actor, data, assets)
    corpus = {"synthetic": "technical_fixture", "learner_submission": "representative_learner"}.get(
        provenance["construction"],
        "mathematical_challenge",
    )
    case = EvaluationCase.objects.create(
        family=family,
        bundle=bundle,
        prepared_by=actor,
        provenance=provenance,
        metadata={**data.get("metadata", {}), "corpus": corpus},
        supersedes_id=data.get("supersedes"),
    )
    if case.supersedes_id and case.supersedes.family_id != family.pk:
        raise EvaluationError("Case revisions must stay within their mathematical family.", status=422)
    EvaluationLifecycle.objects.create(target_id=case.pk)
    audit(actor, case, "case_created")
    return case


def validate_judgment(payload, source):
    if not isinstance(payload, dict) or any(payload.get(k) not in values for k, values in RUBRIC.items()):
        raise EvaluationError("Complete every mathematical rubric dimension.", status=422)
    if not isinstance(payload.get("explanation"), str) or not payload["explanation"].strip():
        raise EvaluationError("Explain the mathematical judgment.", status=422)
    defects = payload.get("defects")
    if not isinstance(defects, list) or len(defects) > 32:
        raise EvaluationError("Provide at most 32 explicit defects.", status=422)
    nodes = {}
    for defect in defects:
        try:
            key = str(uuid.UUID(defect["id"]))
            if key in nodes or defect["significance"] not in {"minor", "consequential", "fatal"}:
                raise ValueError
            if not defect["explanation"].strip() or not defect["justification"].strip():
                raise ValueError
            nodes[key] = defect
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise EvaluationError(
                "Every defect needs an identity, significance and mathematical support.",
                status=422,
            ) from error
    for key, defect in nodes.items():
        if defect.get("root_id") not in nodes or any(d not in nodes for d in defect.get("depends_on", [])):
            raise EvaluationError("Defect dependencies must reference this judgment.", status=422)
        seen = set()

        def visit(node, trail=seen):
            if node in trail:
                raise EvaluationError("Defect dependencies cannot contain cycles.", status=422)
            trail.add(node)
            for child in nodes[node].get("depends_on", []):
                visit(child)
            trail.remove(node)

        visit(key)
        for span in defect.get("spans", []):
            quote = span.get("quote", "")
            span["start"] = source.index(quote) if quote and source.count(quote) == 1 else None
            span["end"] = span["start"] + len(quote) if span["start"] is not None else None
    material = any(d["significance"] != "minor" for d in defects)
    clear = payload["assessment"] == "no_issues_found"
    if clear and (
        material
        or payload["input_sufficiency"] != "present"
        or payload["problem_integrity"] != "no_known_defect"
        or payload["logical_validity"] != "valid"
        or payload["proof_completeness"] != "complete"
        or payload["justification"] not in {"sufficient", "compressed_acceptable"}
    ):
        raise EvaluationError("The mathematical dimensions do not support a positive assessment.", status=422)
    if payload["assessment"] == "gap_found" and not material:
        raise EvaluationError("A gap finding needs a supported material defect.", status=422)
    return json.loads(json.dumps(payload))


def case_state(case):
    originals = list(case.judgments.filter(kind="independent").order_by("created_at"))
    if any(item.actor_id is None for item in originals):
        return {"status": "provisional", "judgment_count": len(originals)}
    final = case.judgments.filter(kind="adjudication").first()
    if final and final.actor_id is None:
        return {"status": "disputed", "judgment_count": len(originals)}
    if final:
        return {"status": "adjudicated", "judgment_count": len(originals), "ground_truth": final.payload}
    if len(originals) < 2:
        return {"status": "provisional", "judgment_count": len(originals)}
    a, b = originals[:2]
    # Defect UUIDs/wording may differ: independent mathematical explanations require explicit adjudication.
    if a.payload == b.payload:
        return {"status": "verified", "judgment_count": len(originals), "ground_truth": a.payload}
    return {"status": "disputed", "judgment_count": len(originals)}


@transaction.atomic
def submit_judgment(actor, case, payload, expected_digest):
    require(actor, "reviewer", case)
    lifecycle(case, lock=True)
    _provenance(case.provenance)
    verify_bundle(case.bundle)
    if case.prepared_by_id == actor.pk or expected_digest != case.bundle.digest:
        raise EvaluationError("A preparer or stale form cannot supply an independent judgment.", status=409)
    if case.judgments.filter(actor=actor, kind="independent").exists():
        raise EvaluationError("Your independent judgment is already preserved.", status=409)
    if case.judgments.filter(kind="independent").count() >= 2:
        raise EvaluationError("The independent review round is closed.", status=409)
    payload = validate_judgment(payload, case.bundle.payload["source"])
    item = CoachJudgment.objects.create(case=case, actor=actor, payload=payload, input_digest=expected_digest)
    audit(actor, case, "judgment_submitted", {"judgment_id": str(item.pk)})
    return item


@transaction.atomic
def adjudicate(actor, case, payload, expected_digest):
    require(actor, "adjudicator", case)
    lifecycle(case, lock=True)
    originals = list(case.judgments.filter(kind="independent"))
    if case.judgments.filter(kind="adjudication").exists():
        raise EvaluationError("The adjudication is already preserved.", status=409)
    if (
        len(originals) != 2
        or actor.pk in [j.actor_id for j in originals]
        or actor.pk == case.prepared_by_id
        or expected_digest != case.bundle.digest
        or not payload.get("reason")
    ):
        raise EvaluationError(
            "Distinct adjudication requires two preserved independent judgments and a reason.",
            status=409,
        )
    payload = validate_judgment(payload, case.bundle.payload["source"])
    payload["original_judgments"] = [str(j.pk) for j in originals]
    item = CoachJudgment.objects.create(
        case=case,
        actor=actor,
        kind="adjudication",
        payload=payload,
        input_digest=expected_digest,
    )
    audit(actor, case, "adjudication_submitted", {"judgment_id": str(item.pk)})
    return item


@transaction.atomic
def case_payload(user, case):
    decision_lock()
    if not visible_cases(user).filter(pk=case.pk).exists():
        raise EvaluationError
    list(assignments(user).filter(scope_id__in=scope_ids(case)).select_for_update().order_by("pk"))
    if not visible_cases(user).filter(pk=case.pk).exists():
        raise EvaluationError
    lifecycle(case, lock=True)
    _provenance(case.provenance)
    verify_bundle(case.bundle)
    originals = case.judgments.filter(kind="independent")
    own = originals.filter(actor=user).exists()
    round_complete = originals.count() == 2
    state = case_state(case)
    result = {
        "id": str(case.pk),
        "bundle": case.bundle.payload,
        "digest": case.bundle.digest,
        "state": {"status": state["status"], "judgment_count": state["judgment_count"]},
        "can_judge": allowed(user, "reviewer", case)
        and case.prepared_by_id != user.pk
        and not own
        and not round_complete,
        "can_adjudicate": allowed(user, "adjudicator", case) and round_complete and not own,
        "can_curate": allowed(user, "curator", case),
        "assets": [{"id": str(a.pk), **a.manifest} for a in case.bundle.assets.all()],
    }
    if round_complete and (allowed(user, "adjudicator", case) or allowed(user, "custodian", case)):
        result["judgments"] = list(case.judgments.values("id", "kind", "payload"))
    audit(user, case, "case_served", {"labels": "judgments" in result})
    return result


@transaction.atomic
def asset_payload(user, case, asset_id):
    case_payload(user, case)
    asset = case.bundle.assets.filter(pk=asset_id).first()
    if asset is None:
        raise EvaluationError
    audit(user, case, "asset_served", {"asset_id": str(asset.pk)})
    return bytes(asset.normalized), "image/png"


@transaction.atomic
def freeze_dataset(actor, name, membership, protocol):
    if not isinstance(membership, list) or not membership:
        raise EvaluationError("Select explicit case revisions and family partitions.", status=422)
    families, selected, rows, statements = {}, set(), [], {}
    for entry in sorted(membership, key=lambda e: str(e.get("case_id", ""))):
        case = EvaluationCase.objects.select_related("family", "bundle").filter(pk=entry["case_id"]).first()
        if case is None:
            raise EvaluationError
        require(actor, "custodian", case)
        lifecycle(case, lock=True)
        lifecycle(case.family, lock=True)
        _provenance(case.provenance)
        verify_bundle(case.bundle)
        partition = entry.get("partition")
        if partition not in PARTITIONS or case.pk in selected:
            raise EvaluationError("Duplicate case or unknown partition.", status=422)
        selected.add(case.pk)
        old = families.setdefault(str(case.family_id), partition)
        if old != partition:
            raise EvaluationError("Mathematical families cannot cross partitions.", status=422)
        for earlier in EvaluationDatasetSnapshot.objects.all():
            old_partition = earlier.manifest.get("families", {}).get(str(case.family_id))
            if old_partition and old_partition != partition:
                raise EvaluationError(
                    "Mathematical families cannot cross partitions, including previous frozen snapshots.",
                    status=422,
                )
        normalized = "".join(case.bundle.payload["statement"].split())
        if normalized in statements and statements[normalized] != case.family_id:
            raise EvaluationError("Resolve duplicate mathematical statements before freezing.", status=422)
        statements[normalized] = case.family_id
        state = case_state(case)
        if state["status"] not in {"verified", "adjudicated"}:
            raise EvaluationError("Every frozen label requires independent agreement or adjudication.", status=409)
        if case.metadata.get("duplicate_warning") and not case.metadata.get("duplicate_resolution"):
            raise EvaluationError("Resolve probable family duplication before freezing.", status=409)
        ground = state["ground_truth"]
        rows.append(
            {
                "id": str(case.pk),
                "family_id": str(case.family_id),
                "domain": case.family.domain,
                "partition": partition,
                "input_digest": case.bundle.digest,
                "provenance_digest": digest(case.provenance),
                "family_digest": digest(
                    {"domain": case.family.domain, "metadata": case.family.metadata, "title": case.family.title},
                ),
                "label_digest": digest(ground),
                "expected_assessment": ground["assessment"],
                "ground_truth": ground,
                "critical_error": any(d["significance"] == "fatal" for d in ground["defects"]),
                "valid_alternative": ground["assessment"] == "no_issues_found"
                and ground["logical_validity"] == "valid"
                and ground["method"] in {"alternative", "advanced"},
                "defects": ground["defects"],
                "input_complete": case.bundle.payload["completeness"] == "present",
                "generation": lifecycle(case).generation,
                "judgments": [
                    {"id": str(j.pk), "actor_id": j.actor_id, "kind": j.kind}
                    for j in case.judgments.order_by("kind", "id")
                ],
            },
        )
    manifest = {
        "schema_version": 2,
        "rubric_version": "math-v1",
        "cases": rows,
        "protocol": protocol,
        "families": families,
    }
    corpora = set(EvaluationCase.objects.filter(pk__in=selected).values_list("metadata__corpus", flat=True))
    if len(corpora) != 1:
        raise EvaluationError("Freeze technical, challenge and learner corpora separately.", status=422)
    manifest["corpus"] = next(iter(corpora))
    manifest["relationships"] = _snapshot_relationships(selected, rows)
    snapshot = EvaluationDatasetSnapshot.objects.create(
        name=name[:200],
        manifest=manifest,
        digest=digest(manifest),
        prepared_by=actor,
    )
    EvaluationLifecycle.objects.create(target_id=snapshot.pk)
    EvaluationAssignment.objects.create(actor=actor, appointed_by=actor, role="custodian", scope_id=snapshot.pk)
    audit(actor, snapshot, "dataset_frozen", {"dataset_digest": snapshot.digest})
    return snapshot


def _snapshot_relationships(selected, rows):
    selected_ids = {row["id"]: row["input_digest"] for row in rows}
    relationships = []
    for event in EvaluationAuditEvent.objects.filter(target_id__in=selected, kind="relationship_verified").order_by(
        "id",
    ):
        relation = event.metadata
        if relation.get("withdrawn"):
            continue
        source, target = relation["source_case_id"], relation["target_case_id"]
        if source in selected_ids and target in selected_ids:
            if relation["source_digest"] != selected_ids[source] or relation["target_digest"] != selected_ids[target]:
                raise EvaluationError("The verified mathematical transformation is stale.", status=409)
            relationships.append(
                {
                    "id": str(event.pk),
                    "coach_approved": True,
                    **{
                        key: relation.get(key)
                        for key in (
                            "source_case_id",
                            "target_case_id",
                            "kind",
                            "dimension",
                            "expected_assessment",
                        )
                    },
                },
            )
    return relationships


def snapshot_eligible(snapshot, *, lock=False):
    lifecycle(snapshot, lock=lock)
    if digest(snapshot.manifest) != snapshot.digest:
        raise EvaluationError("Dataset digest mismatch.", status=409)
    for row in snapshot.manifest["cases"]:
        case = EvaluationCase.objects.select_related("bundle", "family").get(pk=row["id"])
        state = lifecycle(case, lock=lock)
        lifecycle(case.family, lock=lock)
        _provenance(case.provenance)
        verify_bundle(case.bundle)
        if state.generation != row["generation"] or case.bundle.digest != row["input_digest"]:
            raise EvaluationError("Dataset dependencies changed.", status=409)
        if (
            digest(case.provenance) != row["provenance_digest"]
            or digest(
                {
                    "domain": case.family.domain,
                    "metadata": case.family.metadata,
                    "title": case.family.title,
                },
            )
            != row["family_digest"]
        ):
            raise EvaluationError("Frozen case provenance changed.", status=409)
        current = case_state(case)
        if (
            current["status"] not in {"verified", "adjudicated"}
            or digest(current["ground_truth"]) != row["label_digest"]
        ):
            raise EvaluationError("The frozen mathematical approval is no longer supported.", status=409)


def require_offline_origin(origin):
    if origin not in ORIGINS:
        raise EvaluationError("Only the trusted dispatcher can establish provider provenance.", status=422)


@transaction.atomic
def create_profile(actor, payload):
    require(actor, "curator", WORKSPACE)
    required = {
        "model",
        "prompt",
        "rubric",
        "output_schema",
        "preprocessing",
        "reasoning",
        "output_limit",
        "timeout",
        "retry_policy",
        "pricing",
    }
    if not isinstance(payload, dict) or not required <= payload.keys() or payload["retry_policy"] != "none":
        raise EvaluationError(
            "Freeze the complete executable reviewer configuration with retries disabled.",
            status=422,
        )
    profile, _ = ReviewerProfile.objects.get_or_create(digest=digest(payload), defaults={"payload": payload})
    audit(actor, profile, "profile_frozen")
    return profile


@transaction.atomic
def import_run(actor, snapshot, profile, reports, protocol, origin="manual_import"):
    require(actor, "custodian", snapshot)
    snapshot_eligible(snapshot, lock=True)
    require_offline_origin(origin)
    protocol = {**protocol, "partition": protocol.get("partition", "final_test")}
    from .evaluation_scoring import _protocol

    try:
        _protocol(protocol)
    except ValueError as error:
        raise EvaluationError(str(error), status=422) from error
    selected = [row for row in snapshot.manifest["cases"] if row["partition"] == protocol["partition"]]
    if protocol["partition"] not in PARTITIONS or not selected:
        raise EvaluationError("Select a nonempty frozen evaluation partition.", status=422)
    if not isinstance(reports, dict) or set(reports) != {r["id"] for r in selected}:
        raise EvaluationError("Supply every eligible case exactly once.", status=422)
    if digest(profile.payload) != profile.digest:
        raise EvaluationError("Profile digest mismatch.", status=409)
    run = EvaluationRun.objects.create(
        snapshot=snapshot,
        profile=profile,
        reports=reports,
        protocol=protocol,
        origin=origin,
        actor=actor,
        digest=digest(
            {
                "snapshot": snapshot.digest,
                "profile": profile.digest,
                "reports": reports,
                "protocol": protocol,
                "origin": origin,
            },
        ),
    )
    from .evaluation_execution import import_attempts

    import_attempts(run, selected)
    EvaluationLifecycle.objects.create(target_id=run.pk)
    audit(actor, run, "reports_imported", {"origin": origin})
    return run


@transaction.atomic
def assess_findings(actor, run, case, payload):
    require(actor, "finding_evaluator", case)
    snapshot_eligible(run.snapshot, lock=True)
    if str(case.pk) not in run.reports:
        raise EvaluationError
    if not isinstance(payload, dict) or any(str(key).startswith("_") for key in payload):
        raise EvaluationError(
            "Reserved adjudication fields cannot be submitted as an independent assessment.",
            status=422,
        )
    originals = run.finding_judgments.filter(case=case).exclude(payload__has_key="_adjudicates")
    if originals.count() >= 2:
        raise EvaluationError("The independent finding-assessment round is closed.", status=409)
    from .evaluation_scoring import score_reports

    # Scorer validates all judgment fields before this immutable annotation is accepted.
    row = next(r for r in run.snapshot.manifest["cases"] if r["id"] == str(case.pk))
    try:
        score_reports([row], {str(case.pk): run.reports[str(case.pk)]}, {str(case.pk): payload}, run.protocol)
    except ValueError as error:
        raise EvaluationError(str(error), status=422) from error
    if EvaluationFindingJudgment.objects.filter(run=run, case=case, actor=actor).exists():
        raise EvaluationError("This finding assessment is already preserved.", status=409)
    item = EvaluationFindingJudgment.objects.create(run=run, case=case, actor=actor, payload=payload)
    audit(actor, run, "finding_judgment", {"case_id": str(case.pk), "judgment_id": str(item.pk)})
    return item


def visible_case_runs(user, case):
    if not any(allowed(user, role, case) for role in ("finding_evaluator", "custodian", "adjudicator")):
        return EvaluationRun.objects.none()
    ids = [run.pk for run in EvaluationRun.objects.all() if str(case.pk) in run.reports]
    return EvaluationRun.objects.filter(pk__in=ids)


@transaction.atomic
def finding_payload(actor, run, case):
    originals = run.finding_judgments.filter(case=case).exclude(payload__has_key="_adjudicates")
    if allowed(actor, "finding_evaluator", case):
        require(actor, "finding_evaluator", case)
    else:
        require(actor, "adjudicator", case)
        if originals.count() != 2:
            raise EvaluationError("The independent finding round is not closed.", status=409)
    snapshot_eligible(run.snapshot, lock=True)
    if str(case.pk) not in run.reports:
        raise EvaluationError
    audit(actor, case, "finding_report_served", {"run_id": str(run.pk)})
    result = {
        "report": run.reports[str(case.pk)],
        "bundle": case.bundle.payload,
        "ground_truth": case_state(case).get("ground_truth", {}),
        "assets": [{"id": str(a.pk), **a.manifest} for a in case.bundle.assets.all()],
    }
    if allowed(actor, "adjudicator", case) and originals.count() == 2:
        result["finding_judgments"] = [{"id": str(item.pk), "payload": item.payload} for item in originals]
    return result


@transaction.atomic
def run_payload(actor, run, *, aggregate_only=False):
    decision_lock()
    is_custodian = allowed(actor, "custodian", run.snapshot)
    if not is_custodian:
        require(actor, "developer", run.snapshot)
        aggregate_only = True
    snapshot_eligible(run.snapshot, lock=True)
    from .evaluation_finding_adjudication import resolve_finding_judgments

    judgments = resolve_finding_judgments(run)
    from .evaluation_scoring import score_reports

    pending = len(run.reports) - len(judgments)
    if pending:
        if aggregate_only:
            raise EvaluationError("Mathematical report annotation is incomplete.", status=409)
        metrics = None
    else:
        selected = [row for row in run.snapshot.manifest["cases"] if row["id"] in run.reports]
        metrics = score_reports(selected, run.reports, judgments, run.protocol)
        from .evaluation_scoring import evaluate_metamorphic_relationships

        relations = [
            item
            for item in run.snapshot.manifest.get("relationships", [])
            if item["source_case_id"] in run.reports and item["target_case_id"] in run.reports
        ]
        if relations:
            consistency = evaluate_metamorphic_relationships(run.reports, relations)
            metrics["metamorphic"] = consistency
            metrics["candidate_passed"] = metrics["candidate_passed"] and consistency["all_passed"]
    if aggregate_only:
        if EvaluationAuditEvent.objects.filter(target_id=run.snapshot_id, kind="aggregate_served").exists():
            raise EvaluationError("The final-test aggregate has already been delivered.", status=409)
        audit(actor, run.snapshot, "aggregate_served", {"run_id": str(run.pk), "candidate_digest": run.profile.digest})
        # Case-by-case results, identifiers and defect graphs remain with the custodian.
        aggregate = {
            key: metrics[key]
            for key in (
                "schema_version",
                "origin",
                "model_readiness",
                "candidate_passed",
                "counts",
                "metrics",
                "gates",
                "by_domain",
                "failures",
                "abstentions",
                "family_statistics",
                "limitations",
            )
        }
        safe_reasons = {
            "missing_context",
            "missing_essential_context",
            "unreadable",
            "mathematical_uncertainty",
            "problem_defect",
            "unsupported_modality",
            "other",
        }
        categories = {}
        for reason, count in aggregate["abstentions"].items():
            key = reason if reason in safe_reasons else "other"
            categories[key] = categories.get(key, 0) + count
        aggregate["abstentions"] = categories
        return {"origin": run.origin, "model_readiness": False, "metrics": aggregate, "aggregate_only": True}
    audit(actor, run, "run_served")
    return {
        "origin": run.origin,
        "model_readiness": False,
        "metrics": metrics,
        "reports": run.reports,
        "annotation_pending": pending,
        "aggregate_only": False,
    }


@transaction.atomic
def invalidate(actor, target, reason, *, purge=False):
    require(actor, "curator", target)
    return _invalidate(actor, target, reason, purge=purge)


@transaction.atomic
def _invalidate(actor, target, reason, *, purge=False):
    if purge:
        state, _ = EvaluationLifecycle.objects.select_for_update().get_or_create(target_id=target.pk)
    else:
        state = lifecycle(target, lock=True)
    if reason not in {"withdrawal", "exposure", "correction", "family_overlap", "integrity_failure", "revocation"}:
        raise EvaluationError("Record a known invalidation reason.", status=422)
    state.eligible, state.reason = False, reason
    state.generation += 1
    state.save()
    audit(actor, target, reason)
    if purge and isinstance(target, EvaluationCase):
        # Explicit content erasure is the only bypass of immutable-content guards.
        ReviewBundleAsset._base_manager.filter(bundle=target.bundle).delete()
        ReviewInputBundle._base_manager.filter(pk=target.bundle_id).update(payload={}, owner=None)
        EvaluationLifecycle.objects.filter(target_id=target.bundle_id).update(eligible=False, reason=reason)
        CoachJudgment._base_manager.filter(case=target).update(payload={"withdrawn": True})
        EvaluationFindingJudgment._base_manager.filter(case=target).update(payload={"withdrawn": True})
        EvaluationCase._base_manager.filter(pk=target.pk).update(metadata={}, provenance={"withdrawn": True})
        related = EvaluationAuditEvent.objects.filter(kind="relationship_verified").filter(
            Q(target_id=target.pk) | Q(metadata__target_case_id=str(target.pk)),
        )
        for event in related:
            EvaluationAuditEvent._base_manager.filter(pk=event.pk).update(metadata={"withdrawn": True})
        for snapshot in EvaluationDatasetSnapshot.objects.all():
            if not any(row["id"] == str(target.pk) for row in snapshot.manifest["cases"]):
                continue
            manifest = json.loads(json.dumps(snapshot.manifest))
            for row in manifest["cases"]:
                if row["id"] == str(target.pk):
                    row["ground_truth"], row["defects"] = {"withdrawn": True}, []
            EvaluationDatasetSnapshot._base_manager.filter(pk=snapshot.pk).update(manifest=manifest)
            EvaluationLifecycle.objects.filter(target_id=snapshot.pk).update(eligible=False, reason=reason)
            for run in snapshot.runs.all():
                reports = dict(run.reports)
                reports.pop(str(target.pk), None)
                EvaluationRun._base_manager.filter(pk=run.pk).update(reports=reports)
                EvaluationLifecycle.objects.filter(target_id=run.pk).update(eligible=False, reason=reason)
            audit(actor, snapshot, "content_purged", {"case_id": str(target.pk), "historical_digest": snapshot.digest})


@transaction.atomic
def record_readiness(actor, gate, target, decision, payload):
    require(actor, "activation", target)
    lifecycle(target, lock=True)
    if gate not in {"E", "D", "M", "P"} or decision not in {"passed", "blocked", "provisional", "unassessed"}:
        raise EvaluationError("Unknown readiness gate or decision.", status=422)
    if gate in {"M", "P"} and decision == "passed":
        raise EvaluationError("Real-model and pedagogical readiness cannot be established offline.", status=409)
    if not payload.get("artifacts") or not payload.get("limitations"):
        raise EvaluationError("Readiness requires supporting artifacts and explicit limitations.", status=422)
    if gate == "D" and decision == "passed":
        if not isinstance(target, EvaluationDatasetSnapshot):
            raise EvaluationError("Dataset readiness requires an exact frozen snapshot.", status=422)
        snapshot_eligible(target, lock=True)
    item = ReadinessEvidence.objects.create(
        gate=gate,
        target_id=getattr(target, "pk", target),
        actor=actor,
        payload=payload,
        decision=decision,
    )
    audit(actor, target, "readiness_recorded", {"evidence_id": str(item.pk), "gate": gate, "decision": decision})
    return item


def default_membership(cases, *, seed="math-v1"):
    """Deterministic 60/20/20 allocation by family/domain, never by proof variant."""
    grouped = {}
    cases = list(cases)
    for case in cases:
        grouped.setdefault(case.family.domain, set()).add(str(case.family_id))
    partitions = {}
    names = ("development", "validation", "final_test")
    for families in grouped.values():
        ordered = sorted(families, key=lambda key: digest({"seed": seed, "family": key}))
        weights = (3, 1, 1)
        counts = [len(ordered) * weight // 5 for weight in weights]
        remainder_order = sorted(range(3), key=lambda index: (-(len(ordered) * weights[index] % 5), index))
        for index in remainder_order[: len(ordered) - sum(counts)]:
            counts[index] += 1
        cursor = 0
        for name, count in zip(names, counts, strict=True):
            for key in ordered[cursor : cursor + count]:
                partitions[key] = name
            cursor += count
    return [{"case_id": str(case.pk), "partition": partitions[str(case.family_id)]} for case in cases]
