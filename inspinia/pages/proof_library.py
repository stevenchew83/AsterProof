"""Explicit, revision-bound publication of community mathematics; never private work."""

import hashlib
import io
import json
import re
import uuid

from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.urls import reverse
from django.utils import timezone

from inspinia.users.roles import user_has_admin_role

from .community_models import CommunityProblem
from .proof_models import CommunityAttempt
from .proof_models import CommunityProblemRevision
from .proof_models import CommunitySolution
from .proof_models import CommunitySolutionAsset
from .proof_models import CommunitySolutionRevision
from .proof_models import ModerationEvent
from .proof_models import ProblemPublication

PUBLIC_FIELDS = (
    "title",
    "statement_latex",
    "topic",
    "mohs",
    "topic_tags",
    "source_kind",
    "source_details",
    "source_url",
    "contest_name",
    "contest_year",
    "problem_code",
    "public_hint",
)
PREVIEW_AGE = 1800
MAX_BODY = 32000
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_ATTEMPT_BYTES = 12 * 1024 * 1024
MAX_ASSETS = 20
MAX_IMAGE_PIXELS = 4_000_000
IMAGE_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\]\s*)?\{([^{}]*)\}")
MANAGED_IMAGE_RE = re.compile(r"solution_body_images/[0-9a-f]{32}\.(?:png|jpg|jpeg|webp)")
STATEMENT_DECISIONS = ("statement_approved", "statement_changes_requested", "statement_declined")


def content_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def public_snapshot(problem):
    result = {name: getattr(problem, name) for name in PUBLIC_FIELDS}
    result["topic_label"] = problem.get_topic_display()
    return result


def ensure_statement_revision(problem):
    """Call only from an explicit write, with the problem locked by the caller."""
    snapshot = public_snapshot(problem)
    digest = content_digest(snapshot)
    revision, _ = CommunityProblemRevision.objects.get_or_create(
        problem=problem,
        number=problem.version,
        defaults={"snapshot": snapshot, "content_digest": digest},
    )
    if revision.content_digest != digest:
        msg = "The statement changed without a new version. Resubmit it before publishing."
        raise ValidationError(msg)
    return revision


def active_publications():
    latest = (
        ModerationEvent.objects.filter(
            statement_revision_id=OuterRef("statement_revision_id"),
            solution__isnull=True,
            action__in=STATEMENT_DECISIONS,
        )
        .order_by("-created_at", "-id")
        .values("action")[:1]
    )
    return (
        ProblemPublication.objects.select_related("statement_revision", "problem")
        .annotate(
            publication_decision=Subquery(latest),
        )
        .filter(
            visibility__in=[ProblemPublication.Visibility.UNLISTED, ProblemPublication.Visibility.PUBLIC],
            consented_at__isnull=False,
            is_held=False,
            statement_revision__isnull=False,
            statement_revision__problem_id=F("problem_id"),
            publication_decision="statement_approved",
        )
        .filter(Q(problem__embargo_until__isnull=True) | Q(problem__embargo_until__lte=timezone.now()))
    )


def statement_approved(revision):
    latest = revision.moderation_events.filter(solution__isnull=True, action__in=STATEMENT_DECISIONS).last()
    return bool(latest and latest.action == "statement_approved")


def public_solutions(publication):
    return CommunitySolution.objects.filter(
        problem_id=publication.problem_id,
        status=CommunitySolution.Status.APPROVED,
        is_held=False,
        current_revision__isnull=False,
        current_revision__solution_id=F("id"),
        current_revision__statement_revision__problem_id=F("problem_id"),
    ).select_related("current_revision", "current_revision__statement_revision")


def public_url(publication):
    return reverse("pages:proof_public_problem", args=[publication.token])


def rate_limit(user, action, limit=100):
    key = f"community-proof:{action}:{user.pk}:{timezone.now().strftime('%Y%m%d%H')}"
    if cache.add(key, 1, timeout=3600):
        return
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=3600)
        count = 1
    if count > limit:
        msg = "Too many requests. Please try again later."
        raise ValidationError(msg)


def _check_version(actual, expected):
    if actual != expected:
        msg = "This content changed in another tab. Reload and review the current version."
        raise ValidationError(msg)


def _verify_preview(token, value, salt):
    try:
        signed = signing.loads(token, salt=salt, max_age=PREVIEW_AGE)
    except signing.BadSignature as error:
        msg = "Preview this saved version again before publishing."
        raise ValidationError(msg) from error
    if signed != value:
        msg = "The reviewed content or visibility changed. Preview it again before publishing."
        raise ValidationError(msg)


def _sharing_payload(user, problem, publication, revision, data):
    return {
        "owner": str(user.pk),
        "problem": str(problem.pk),
        "problem_version": problem.version,
        "publication_version": publication.version,
        "generation": str(publication.generation),
        "revision": str(revision.pk),
        "digest": revision.content_digest,
        "visibility": data["visibility"],
        "credit": data["public_credit"],
        "embargo": problem.embargo_until.isoformat() if problem.embargo_until else None,
    }


@transaction.atomic
def share_problem(user, problem_id, data, *, action, token=""):
    problem = CommunityProblem.objects.select_for_update().get(pk=problem_id, author=user)
    publication, _ = ProblemPublication.objects.select_for_update().get_or_create(problem=problem)
    _check_version(publication.version, data["version"])
    if action == "stop" or (action == "publish" and data["visibility"] == "private"):
        publication.visibility = ProblemPublication.Visibility.PRIVATE
        publication.consented_at = None
        publication.token, publication.generation = uuid.uuid4(), uuid.uuid4()
        publication.version += 1
        publication.save()
        ModerationEvent.objects.create(problem=problem, actor=user, action="sharing_stopped")
        return publication, None, ""
    revision = ensure_statement_revision(problem)
    if data.get("statement_revision") and data["statement_revision"] != revision.pk:
        msg = "The statement changed. Reload the sharing preview."
        raise ValidationError(msg)
    value = _sharing_payload(user, problem, publication, revision, data)
    if action == "preview":
        return publication, revision, signing.dumps(value, salt="community-problem-publication-v1")
    if action != "publish":
        msg = "Choose a valid sharing action."
        raise ValidationError(msg)
    _verify_preview(token, value, "community-problem-publication-v1")
    if not data.get("consent") or not statement_approved(revision):
        msg = "This exact statement needs publication moderation and your sharing consent first."
        raise ValidationError(msg)
    if publication.is_held or (problem.embargo_until and problem.embargo_until > timezone.now()):
        msg = "Sharing is on hold or the competition embargo has not ended."
        raise ValidationError(msg)
    if publication.visibility == "private":
        publication.token, publication.generation = uuid.uuid4(), uuid.uuid4()
    publication.statement_revision = revision
    publication.visibility, publication.public_credit = data["visibility"], data["public_credit"]
    publication.consented_at = timezone.now()
    publication.version += 1
    publication.save()
    ModerationEvent.objects.create(
        problem=problem,
        statement_revision=revision,
        actor=user,
        action="publication_enabled",
        reason=f"Explicit {publication.visibility} publication",
    )
    return publication, revision, ""


def attempt_assets(attempt):
    paths = list(dict.fromkeys(path.strip() for path in IMAGE_RE.findall(attempt.body_source)))
    if len(paths) > MAX_ASSETS or any(not MANAGED_IMAGE_RE.fullmatch(path) for path in paths):
        msg = "Use only images uploaded into this private attempt."
        raise ValidationError(msg)
    assets = list(attempt.assets.filter(name__in=paths))
    if {asset.name for asset in assets} != set(paths):
        msg = "An image is missing or belongs to another private attempt."
        raise ValidationError(msg)
    if sum(len(asset.data) for asset in assets) > MAX_ATTEMPT_BYTES:
        msg = "The selected images are too large to publish."
        raise ValidationError(msg)
    return assets


def _solution_payload(user, attempt, solution, data, assets, publication):  # noqa: PLR0913
    return {
        "owner": str(user.pk),
        "attempt": str(attempt.pk),
        "attempt_version": attempt.version,
        "statement": str(attempt.statement_revision_id),
        "body": content_digest(attempt.body_source),
        "solution": str(solution.pk) if solution else None,
        "solution_version": solution.version if solution else 0,
        "publication_generation": str(publication.generation),
        "publication_token": str(publication.token),
        "publication_version": publication.version,
        "audience": publication.visibility,
        "title": data["title"],
        "summary": data["summary"],
        "credit": data["public_credit"],
        "assets": sorted((asset.name, asset.sha256) for asset in assets),
    }


def _copy_solution_assets(revision, assets):
    for asset in assets:
        if hashlib.sha256(bytes(asset.data)).hexdigest() != asset.sha256:
            msg = "An image changed. Review and upload it again."
            raise ValidationError(msg)
        CommunitySolutionAsset.objects.create(
            revision=revision,
            name=asset.name,
            content_type=asset.content_type,
            data=bytes(asset.data),
            sha256=asset.sha256,
        )


@transaction.atomic
def publish_solution(user, attempt_id, data, *, action, token="", solution_id=None):  # noqa: PLR0913
    reference = CommunityAttempt.objects.get(pk=attempt_id, owner=user)
    problem = CommunityProblem.objects.select_for_update().get(pk=reference.problem_id)
    publication = active_publications().select_for_update(of=("self",)).filter(problem=problem).first()
    if not publication or publication.statement_revision_id != reference.statement_revision_id:
        msg = "The problem is no longer shared at this statement version. Your draft is preserved."
        raise ValidationError(msg)
    attempt = CommunityAttempt.objects.select_for_update().get(pk=attempt_id, owner=user)
    _check_version(attempt.version, data["version"])
    if not attempt.body_source.strip() or len(attempt.body_source) > MAX_BODY:
        msg = "Save a proof of at most 32,000 characters before publishing."
        raise ValidationError(msg)
    solution = None
    if solution_id:
        solution = CommunitySolution.objects.select_for_update().get(pk=solution_id, author=user, problem=problem)
    assets = attempt_assets(attempt)
    payload = _solution_payload(user, attempt, solution, data, assets, publication)
    # JSON signing turns tuples into lists; use the same canonical representation on comparison.
    payload = json.loads(json.dumps(payload))
    if action == "preview":
        return solution, signing.dumps(payload, salt="community-proof-publication-v1")
    if action != "submit":
        msg = "Choose a valid solution publication action."
        raise ValidationError(msg)
    _verify_preview(token, payload, "community-proof-publication-v1")
    if not data.get("consent"):
        msg = "Confirm that this selected proof may be published."
        raise ValidationError(msg)
    if solution is None:
        previous = CommunitySolutionRevision.objects.filter(
            source_attempt=attempt, solution__author=user,
            solution__status__in=[CommunitySolution.Status.PENDING, CommunitySolution.Status.APPROVED],
            content_digest=content_digest(payload),
        ).select_related("solution").first()
        if previous:
            return previous.solution, ""
        solution = CommunitySolution.objects.create(problem=problem, author=user)
    latest = solution.revisions.order_by("-number").first()
    revision = CommunitySolutionRevision.objects.create(
        solution=solution,
        source_attempt=attempt,
        statement_revision=attempt.statement_revision,
        number=latest.number + 1 if latest else 1,
        title=data["title"],
        summary=data["summary"],
        body_source=attempt.body_source,
        public_credit=data["public_credit"],
        consented_at=timezone.now(),
        content_digest=content_digest(payload),
    )
    _copy_solution_assets(revision, assets)
    solution.current_revision = revision
    solution.status = CommunitySolution.Status.PENDING
    solution.version += 1
    solution.save()
    ModerationEvent.objects.create(
        problem=problem,
        solution=solution,
        solution_revision=revision,
        statement_revision=attempt.statement_revision,
        actor=user,
        action="proof_submitted",
    )
    return solution, ""


@transaction.atomic
def save_attempt(user, revision, data, *, attempt_id=None):
    # Serialize first saves from two browser tabs without using a GET to create a row.
    from django.contrib.auth import get_user_model

    get_user_model().objects.select_for_update(no_key=True).get(pk=user.pk)
    if attempt_id:
        attempt = CommunityAttempt.objects.select_for_update().get(pk=attempt_id, owner=user)
    else:
        attempt = (
            CommunityAttempt.objects.select_for_update()
            .filter(
                owner=user,
                problem_id=revision.problem_id,
                statement_revision=revision,
            )
            .first()
        )
    _check_version(attempt.version if attempt else 0, data["version"])
    if data["statement_revision"] != revision.pk:
        msg = "Use the statement version shown in your editor."
        raise ValidationError(msg)
    if attempt is None:
        attempt = CommunityAttempt(owner=user, problem_id=revision.problem_id, statement_revision=revision)
    attempt.title, attempt.body_source = data["title"], data["body_source"]
    attempt.version += 1
    attempt.save()
    return attempt


def normalize_image(upload):
    from PIL import Image
    from PIL import UnidentifiedImageError

    if not upload or upload.size > MAX_IMAGE_BYTES:
        msg = "Choose a PNG, JPEG, or WebP image of at most 2 MB."
        raise ValidationError(msg)
    try:
        with Image.open(io.BytesIO(upload.read(MAX_IMAGE_BYTES + 1))) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > MAX_IMAGE_PIXELS:
                msg = "Use a PNG, JPEG, or WebP diagram of at most four megapixels."
                raise ValidationError(msg)
            result = io.BytesIO()
            image.convert("RGBA").save(result, format="PNG")
            data = result.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        msg = "The image could not be read safely."
        raise ValidationError(msg) from error
    if len(data) > MAX_IMAGE_BYTES:
        msg = "The normalized image is too large. Resize it before uploading."
        raise ValidationError(msg)
    return data


def require_admin(user):
    from django.core.exceptions import PermissionDenied

    if not user_has_admin_role(user):
        raise PermissionDenied
