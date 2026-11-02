"""Small private mathematical feedback intake, with no uploads or outbound messages."""

import uuid

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.utils.crypto import salted_hmac

from inspinia.learning.models import ContentIssue
from inspinia.learning.permissions import can_contribute
from inspinia.learning.permissions import require_publisher
from inspinia.learning.publication import visible_publications
from inspinia.learning.revisions import LearningError
from inspinia.learning.revisions import LearningUnavailable

ISSUE_SALT = "asterproof.learning-issue.v1"
REPORT_LIMIT = 2000


def _require_intake():
    if not getattr(settings, "LEARNING_CONTRIBUTIONS_ENABLED", False):
        message = "Contribution and report intake is currently closed."
        raise LearningUnavailable(message)


def issue_context(document, user=None):
    _require_intake()
    public = not can_contribute(user)
    publication = visible_publications(user=user, public=public).filter(document=document).first()
    if publication is None:
        message = "This teaching resource is unavailable."
        raise LearningError(message)
    return signing.dumps(
        {"document": str(document.pk), "revision": str(publication.revision_id), "submission": str(uuid.uuid4())},
        salt=ISSUE_SALT,
    )


def _limit(key, maximum, seconds):
    try:
        cache.add(key, 0, timeout=seconds)
        return cache.incr(key) <= maximum
    except (ValueError, OSError, RuntimeError):
        return False


def create_issue(  # noqa: PLR0913 - Explicit domain action and validation boundary.
    *,
    user,
    document,
    description,
    token,
    source_identity,
    kind="mathematical",
    target_key="",
    honeypot="",
):
    _require_intake()
    if (
        honeypot
        or not isinstance(description, str)
        or not description.strip()
        or len(description) > REPORT_LIMIT
        or "\x00" in description
    ):
        message = "Provide a valid report within 2,000 characters."
        raise LearningError(message)
    if kind not in ContentIssue.Kind.values or (kind != ContentIssue.Kind.MATHEMATICAL and not can_contribute(user)):
        message = "This report type requires approved workspace access."
        raise LearningError(message)
    try:
        payload = signing.loads(token, salt=ISSUE_SALT, max_age=86400)
        submission_id = uuid.UUID(payload["submission"])
        document_id, revision_id = uuid.UUID(payload["document"]), uuid.UUID(payload["revision"])
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        message = "This report form expired. Open the current resource again."
        raise LearningError(message) from exc
    if document_id != document.pk:
        message = "This report form is for another resource."
        raise LearningError(message)
    publication = (
        visible_publications(user=user, public=not can_contribute(user))
        .filter(document_id=document_id, revision_id=revision_id)
        .first()
    )
    if publication is None:
        message = "This teaching resource is unavailable."
        raise LearningError(message)
    existing = ContentIssue.objects.filter(submission_id=submission_id).first()
    if existing:
        return existing
    identity = f"user:{user.pk}" if can_contribute(user) else str(source_identity or "unknown")
    hmac = salted_hmac(ISSUE_SALT, identity).hexdigest()
    if not _limit(f"learning-issue:{hmac}", 10, 3600) or not _limit("learning-issue:global", 100, 86400):
        message = "Report intake is temporarily limited. Keep your text and try later."
        raise LearningUnavailable(message)
    issue, _created = ContentIssue.objects.get_or_create(
        submission_id=submission_id,
        defaults={
            "document": document,
            "revision_id": revision_id,
            "kind": kind,
            "target_key": str(target_key)[:180],
            "description": description.strip(),
            "reporter": user if getattr(user, "is_authenticated", False) else None,
        },
    )
    return issue


def review_issue(*, issue, user, closed=True):
    require_publisher(user)
    issue.status = "closed" if closed else "open"
    issue.save(update_fields=["status"])
    return issue


def _target_state(user, kind, target_key):
    from inspinia.learning.permissions import require_contributor
    from inspinia.learning.revisions import canonical_concept_id
    from inspinia.learning.revisions import digest
    from inspinia.pages.catalogue_models import CatalogueConcept
    from inspinia.pages.catalogue_models import CatalogueState

    require_contributor(user)
    if kind == ContentIssue.Kind.CLASSIFICATION:
        key = canonical_concept_id(target_key)
        concept = CatalogueConcept.objects.get(pk=key)
        state = {
            "key": key,
            "name": concept.name,
            "redirect": concept.redirect_id,
            "catalogue": list(CatalogueState.objects.values_list("source_revision", flat=True)),
            "areas": list(concept.memberships.order_by("area_id").values_list("area_id", flat=True)),
        }
    elif kind == ContentIssue.Kind.PATHWAY:
        from inspinia.training.pathway_models import LearningPath

        try:
            key = str(uuid.UUID(str(target_key)))
        except (TypeError, ValueError) as exc:
            message = "This pathway is unavailable."
            raise LearningError(message) from exc
        path = LearningPath.objects.filter(pk=key, training_visible=True, current_revision__isnull=False).first()
        if path is None:
            message = "This pathway is unavailable."
            raise LearningError(message)
        state = {
            "key": key,
            "revision": str(path.current_revision_id),
            "version": path.version,
            "training": path.training_visible,
            "public": path.public_visible,
        }
    else:
        message = "Choose a classification or pathway suggestion."
        raise LearningError(message)
    return key, digest(state)


def target_issue_context(*, user, kind, target_key):
    key, state = _target_state(user, kind, target_key)
    return signing.dumps(
        {"kind": kind, "target": key, "state": state, "author": str(user.pk), "submission": str(uuid.uuid4())},
        salt=ISSUE_SALT,
    )


def create_target_issue(*, user, kind, target_key, description, token, source_identity="", honeypot=""):  # noqa: PLR0913 - Explicit private suggestion intake.
    if (
        honeypot
        or not isinstance(description, str)
        or not description.strip()
        or len(description) > REPORT_LIMIT
        or "\x00" in description
    ):
        message = "Provide a valid suggestion within 2,000 characters."
        raise LearningError(message)
    key, state = _target_state(user, kind, target_key)
    try:
        payload = signing.loads(token, salt=ISSUE_SALT, max_age=86400)
        submission_id = uuid.UUID(payload["submission"])
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        message = "This suggestion form expired. Reload its current context."
        raise LearningError(message) from exc
    if {k: payload.get(k) for k in ("kind", "target", "state", "author")} != {
        "kind": kind,
        "target": key,
        "state": state,
        "author": str(user.pk),
    }:
        message = "The suggestion target changed or belongs to another account. Reload before submitting."
        raise LearningError(message)
    existing = ContentIssue.objects.filter(submission_id=submission_id).first()
    if existing:
        return existing
    hmac = salted_hmac(ISSUE_SALT, f"user:{user.pk}").hexdigest()
    if not _limit(f"learning-issue:{hmac}", 10, 3600) or not _limit("learning-issue:global", 100, 86400):
        message = "Suggestion intake is temporarily limited. Keep your text and try later."
        raise LearningUnavailable(message)
    issue, _created = ContentIssue.objects.get_or_create(
        submission_id=submission_id,
        defaults={
            "kind": kind,
            "target_key": key,
            "description": description.strip(),
            "reporter": user,
        },
    )
    return issue
