"""Conservative display classifications and independently reviewed result claims."""

import hashlib
import json
import re
from decimal import Decimal

from inspinia.rankings.models import ResultClaim
from inspinia.rankings.models import ResultProfile
from inspinia.rankings.profile_models import EvidenceSource
from inspinia.rankings.profile_models import EvidenceStatus

AWARD_STATUSES = frozenset(
    {
        "honourable mention",
        "honorable mention",
        "silver ruler",
        "individual merit",
        "merit",
        "distinction",
        "high distinction",
        "achievement",
        "achievement award",
        "mathematics medal winner",
        "individual champion",
        "champion",
        "national team runner-up",
        "junior secondary outstanding award",
        "overall second place",
        "class first place",
        "best mathematics subject award",
        "male model student award",
        "graduating-class representative",
        "joint school contribution",
        "platinum award",
    },
)
MEDAL = re.compile(r"(gold|silver|bronze)(?: medal| award| medalist)?")
PLACING = re.compile(r"\d+(?:st|nd|rd|th) place")
REPORTED_AWARD = re.compile(r"(?:family-reported|reported) (?:gold|silver|bronze)(?:; .*)?")


def result_fingerprint(result):
    """A no-op reimport preserves reviews; changed facts or provenance invalidate them."""
    values = {
        name: getattr(result, name)
        for name in (
            "student_id",
            "assessment_id",
            "medal",
            "band",
            "status_text",
            "remarks",
            "source_url",
            "source_file_name",
        )
    }
    values["raw_score"] = format(Decimal(str(result.raw_score)), ".2f") if result.raw_score is not None else None
    values["assessment"] = [result.assessment.code, result.assessment.season_year, result.assessment.display_name]
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def recorded_achievement(medal, status):
    """Recognize recorded outcomes without awarding a medal or verifying evidence."""
    token = " ".join(status.casefold().split())
    return bool(
        medal
        or token in AWARD_STATUSES
        or MEDAL.fullmatch(token)
        or PLACING.fullmatch(token)
        or REPORTED_AWARD.fullmatch(token),
    )


def _claim(claim, fingerprint):
    stale = claim.result_fingerprint != fingerprint
    status = EvidenceStatus.PENDING if stale else claim.verification_status
    return {
        "kind": claim.claim_type,
        "kind_label": claim.get_claim_type_display(),
        "award_kind": claim.award_kind,
        "award_kind_label": claim.get_award_kind_display(),
        "label": claim.claim_label,
        "status": status,
        "status_label": (
            "Needs review — result changed" if stale
            else "Family record" if status == EvidenceStatus.REPORTED and claim.source_type == EvidenceSource.FAMILY
            else "Reported source" if status == EvidenceStatus.REPORTED else EvidenceStatus(status).label
        ),
        "source_type": claim.source_type,
        "source_type_label": claim.get_source_type_display(),
        "source_label": claim.source_label,
        "url": claim.source_url,
        "evidence": claim.evidence,
        "reviewed_at": claim.reviewed_at,
        "stale": stale,
        "explicit": True,
    }


def _unreviewed(kind, label):
    return {
        "kind": kind,
        "kind_label": ResultClaim.ClaimType(kind).label,
        "award_kind": "unknown",
        "award_kind_label": "Not classified",
        "label": label,
        "status": EvidenceStatus.UNREVIEWED,
        "status_label": EvidenceStatus.UNREVIEWED.label,
        "source_type": EvidenceSource.UNKNOWN,
        "source_type_label": EvidenceSource.UNKNOWN.label,
        "source_label": "",
        "url": "",
        "evidence": "",
        "reviewed_at": None,
        "stale": False,
        "explicit": False,
    }


def presentation_metadata(result, *, medal, status, is_group):
    fingerprint = result_fingerprint(result)
    profile = getattr(result, "profile", None)
    profile_stale = bool(profile and profile.active and profile.result_fingerprint != fingerprint)
    reviewed = bool(profile and profile.active and not profile_stale)
    claims = [_claim(claim, fingerprint) for claim in result.claims.all() if claim.active]
    claims_by_kind = {claim["kind"]: claim for claim in claims}
    recorded_kind = "ranking" if PLACING.fullmatch(status.casefold()) and not medal else "award"
    has_recorded_achievement = recorded_achievement(medal, status)
    has_award = has_recorded_achievement or any(
        claim["kind"] in {"award", "ranking"} and not claim["stale"] for claim in claims
    )
    context = result.assessment.code.startswith("ACHIEVEMENT_CONTEXT_") or result.band.casefold() == "context record"
    fallback = (
        "context"
        if context
        else "selection"
        if is_group
        else "achievement"
        if has_award
        else "performance"
        if result.raw_score is not None or status
        else "unknown"
    )
    record_type = profile.record_type if reviewed and profile.record_type != "unknown" else fallback
    if has_recorded_achievement and recorded_kind not in claims_by_kind:
        claims.append(_unreviewed(recorded_kind, medal or status))
    if result.raw_score is not None and "score" not in claims_by_kind:
        claims.append(_unreviewed("score", format(Decimal(str(result.raw_score)), ".2f")))
    # A score claim never verifies an award, and a ranking claim never verifies a medal.
    primary_kind = "award" if any(claim["kind"] == "award" for claim in claims) else "ranking"
    if record_type == "performance":
        primary_kind = "score"
    primary = next((claim for claim in claims if claim["kind"] == primary_kind), None)
    if primary is None:
        primary = _unreviewed("award", "")
    if profile_stale:
        primary = {**primary, "status": EvidenceStatus.PENDING, "status_label": "Needs review — result changed"}
    safe_highlight = (
        record_type == "achievement"
        and reviewed
        and profile.featured
        and primary["explicit"]
        and not primary["stale"]
        and primary["status"] in {EvidenceStatus.VERIFIED, EvidenceStatus.REPORTED}
        and primary["source_type"] not in {EvidenceSource.FAMILY, EvidenceSource.UNKNOWN}
        and all(claim["status"] != EvidenceStatus.CONFLICTING for claim in claims)
    )
    return {
        "record_type": record_type,
        "record_type_label": ResultProfile.RecordType(record_type).label,
        "classification_reviewed": reviewed,
        "classification_stale": profile_stale,
        "discipline": profile.discipline if reviewed else "unknown",
        "discipline_label": profile.get_discipline_display() if reviewed and profile.discipline != "unknown" else "",
        "scope": profile.scope if reviewed else "unknown",
        "scope_label": profile.get_scope_display() if reviewed and profile.scope != "unknown" else "",
        "scope_detail": profile.scope_detail if reviewed else "",
        "participation_label": (
            profile.get_participation_display() if reviewed and profile.participation != "unknown" else ""
        ),
        "claims": claims,
        "primary_claim": primary,
        "evidence_status": primary["status"],
        "evidence_label": primary["status_label"],
        "featured": safe_highlight,
    }
