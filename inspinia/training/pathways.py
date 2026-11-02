"""Publisher-curated paths and explicit reading; never change solve records or points."""

import hashlib
import json
import re
import uuid

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueState
from inspinia.pages.catalogue_models import CatalogueSubject
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.training.models import Material
from inspinia.training.models import MaterialCompletion
from inspinia.training.pathway_models import LearningPath
from inspinia.training.pathway_models import LearningPathItem
from inspinia.training.pathway_models import LearningPathRevision
from inspinia.training.pathway_models import PathReading
from inspinia.users.roles import user_can_access_app_features

MAX_PATH_ITEMS = 100
MAX_HINTS = 5
MAX_READINESS_ITEMS = 20
READ_STATUSES = {"solved", "checked", "written", "published"}
PREVIEW_SALT = "training.pathway-publication-preview.v1"
PREVIEW_TTL = 3600


def _text(value, maximum, label, *, required=False):
    if not isinstance(value, str) or "\x00" in value or len(value) > maximum:
        msg = f"{label} is invalid or too long."
        raise ValidationError(msg)
    value = value.strip()
    if required and not value:
        msg = f"{label} is required."
        raise ValidationError(msg)
    return value


def _identifier(value, label):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        msg = f"{label} is not a valid identity."
        raise ValidationError(msg) from exc


def _require_reader(user):
    if (
        not getattr(settings, "LEARNING_MODULE_ENABLED", False)
        or not getattr(user, "is_active", False)
        or not user_can_access_app_features(user)
    ):
        msg = "Approved Training access is required."
        raise PermissionDenied(msg)


def _normalise_items(items):  # noqa: C901 - Validate every supported typed activity at one boundary.
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_PATH_ITEMS:
        msg = "A pathway needs between 1 and 100 activities."
        raise ValidationError(msg)
    result, keys = [], set()
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            msg = "Each activity must be an object."
            raise ValidationError(msg)
        key = _text(raw.get("key", ""), 80, "Activity key", required=True)
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", key) or key in keys:
            msg = "Activity keys must be unique stable identifiers."
            raise ValidationError(msg)
        keys.add(key)
        kind = raw.get("kind")
        if kind not in LearningPathItem.Kind.values:
            msg = "Unknown pathway activity kind."
            raise ValidationError(msg)
        row = {
            "item_key": key,
            "position": index,
            "title": _text(raw.get("title", ""), 180, "Activity title", required=True),
            "kind": kind,
            "document_id": None,
            "problem_id": None,
            "legacy_material_id": None,
            "exercise_source": "",
            "hints": [],
        }
        hints = raw.get("hints", [])
        if not isinstance(hints, list) or len(hints) > MAX_HINTS:
            msg = "Use at most five progressively disclosed hints."
            raise ValidationError(msg)
        row["hints"] = [_text(hint, 8000, "Hint", required=True) for hint in hints]
        present = sum(
            bool(raw.get(field)) for field in ("document_id", "problem_uuid", "material_id", "exercise_source")
        )
        if present != 1:
            msg = "An activity must have exactly one typed target."
            raise ValidationError(msg)
        if kind == LearningPathItem.Kind.DOCUMENT:
            row["document_id"] = _identifier(raw.get("document_id"), "Document")
        elif kind == LearningPathItem.Kind.PROBLEM:
            row["problem_id"] = _identifier(raw.get("problem_uuid"), "Problem UUID")
        elif kind == LearningPathItem.Kind.LEGACY:
            material_id = raw.get("material_id")
            if type(material_id) is not int or material_id <= 0:
                msg = "The legacy material identity is invalid."
                raise ValidationError(msg)
            row["legacy_material_id"] = material_id
        else:
            row["exercise_source"] = _text(raw.get("exercise_source", ""), 10000, "Exercise", required=True)
        result.append(row)
    return result


def _current_document_publications(document_ids, *, public=False):
    from inspinia.learning.models import ContentPublication

    query = ContentPublication.objects.filter(
        document_id__in=document_ids,
        revision__isnull=False,
        training_visible=True,
    ).select_related("revision", "document")
    if public:
        query = query.filter(public_visible=True)
    return {row.document_id: row for row in query}


def _validate_references(items, *, public, lock=True):
    from inspinia.learning.models import ContentDocument

    document_ids = {row["document_id"] for row in items if row["document_id"]}
    # Stable document parents are locked before path/placement rows, including new links.
    documents = ContentDocument.objects.filter(pk__in=document_ids).order_by("pk")
    locked = list(documents.select_for_update() if lock else documents)
    if len(locked) != len(document_ids):
        msg = "A pathway document is unavailable."
        raise ValidationError(msg)
    if len(_current_document_publications(document_ids, public=public)) != len(document_ids):
        msg = "Every linked document needs a current publication in the selected channel."
        raise ValidationError(msg)
    problems = {row["problem_id"] for row in items if row["problem_id"]}
    if ProblemSolveRecord.objects.filter(problem_uuid__in=problems, is_active=True).count() != len(problems):
        msg = "A canonical practice problem is unavailable."
        raise ValidationError(msg)
    legacy = {row["legacy_material_id"] for row in items if row["legacy_material_id"]}
    if Material.objects.filter(
        pk__in=legacy,
        is_published=True,
        subtopic__is_published=True,
        subtopic__topic__is_published=True,
    ).count() != len(legacy):
        msg = "A legacy material is unavailable."
        raise ValidationError(msg)
    if public and legacy:
        msg = "Private legacy materials cannot be released through a public pathway."
        raise ValidationError(msg)


def _review_digest(source, path):
    from inspinia.pages.prerequisite_models import PrerequisiteGraphState

    ids = {row["document_id"] for row in source["items"] if row["document_id"]}
    publications = _current_document_publications(ids, public=source["public"])
    graph = (
        PrerequisiteGraphState.objects.filter(pk=1)
        .values("version", "is_valid", "validated_catalogue_revision")
        .first()
    )
    context = {
        "payload": source,
        "path": [str(path.pk), str(path.current_revision_id), path.version] if path else None,
        "catalogue": CatalogueState.objects.filter(pk=1).values_list("source_revision", flat=True).first(),
        "prerequisites": graph,
        "documents": [
            [str(key), str(value.revision_id), value.version, value.training_visible, value.public_visible]
            for key, value in sorted(publications.items(), key=lambda pair: str(pair[0]))
        ],
    }
    return hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode()).hexdigest()


def _source_digest(source):
    return hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()


def _preview_payload(context, user, source):
    try:
        payload = signing.loads(context, salt=PREVIEW_SALT, max_age=PREVIEW_TTL)
        operation_id = uuid.UUID(payload["operation"])
    except (signing.BadSignature, TypeError, ValueError, KeyError, AttributeError) as exc:
        msg = "Preview this exact pathway before publishing."
        raise ValidationError(msg) from exc
    if payload.get("actor") != str(user.pk) or payload.get("source") != _source_digest(source):
        msg = "This preview belongs to another account or pathway payload."
        raise ValidationError(msg)
    return payload, operation_id


def pathway_preview(*, user, data=None, **parameters):  # noqa: C901, PLR0912, PLR0915 - Explicit review boundary.
    """Sign one exact payload plus current linked-document and graph context."""
    from inspinia.learning.permissions import require_publisher

    require_publisher(user)
    if not getattr(settings, "LEARNING_MODULE_ENABLED", False):
        msg = "Training 2.0 is not enabled."
        raise PermissionDenied(msg)
    if data is not None:
        if not isinstance(data, dict) or parameters:
            msg = "Provide one pathway payload."
            raise ValidationError(msg)
        parameters = data
    allowed = {
        "slug",
        "title",
        "items",
        "expected_version",
        "summary",
        "audience",
        "readiness",
        "subject_id",
        "area_id",
        "is_foundations",
        "public",
    }
    if set(parameters) - allowed:
        msg = "Unknown pathway fields."
        raise ValidationError(msg)
    slug = _text(parameters.get("slug", ""), 120, "Pathway slug", required=True)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
        msg = "The pathway slug must be a stable identifier."
        raise ValidationError(msg)
    path = LearningPath.objects.filter(slug=slug).first()
    version = parameters.get("expected_version", 0)
    if type(version) is not int or version != (path.version if path else 0):
        msg = "The pathway changed. Reload its current version."
        raise ValidationError(msg)
    public = parameters.get("public", False)
    if type(public) is not bool:
        msg = "Choose a valid publication channel."
        raise ValidationError(msg)
    subject_id, area_id = parameters.get("subject_id"), parameters.get("area_id")
    subject = CatalogueSubject.objects.filter(pk=subject_id).first() if subject_id else None
    area = CatalogueArea.objects.select_related("subject").filter(pk=area_id).first() if area_id else None
    if (subject_id and subject is None) or (area_id and area is None):
        msg = "The pathway catalogue scope is unavailable."
        raise ValidationError(msg)
    if area and subject and area.subject_id != subject.pk:
        msg = "The area belongs to another subject."
        raise ValidationError(msg)
    if area:
        subject = area.subject
    foundations = parameters.get("is_foundations", False)
    if type(foundations) is not bool:
        msg = "Choose a valid Foundations scope."
        raise ValidationError(msg)
    foundations = foundations or slug == "foundations"
    if foundations and (subject or area):
        msg = "Foundations is cross-topic."
        raise ValidationError(msg)
    readiness = parameters.get("readiness", [])
    if not isinstance(readiness, list) or len(readiness) > MAX_READINESS_ITEMS:
        msg = "Readiness needs a bounded advisory list."
        raise ValidationError(msg)
    rows = _normalise_items(parameters.get("items"))
    _validate_references(rows, public=public, lock=False)
    source = {
        "slug": slug,
        "title": _text(parameters.get("title", ""), 180, "Title", required=True),
        "summary": _text(parameters.get("summary", ""), 500, "Summary"),
        "audience": _text(parameters.get("audience", ""), 500, "Audience"),
        "readiness": [_text(value, 500, "Readiness", required=True) for value in readiness],
        "subject": subject.pk if subject else None,
        "area": area.pk if area else None,
        "foundations": foundations,
        "public": public,
        "items": rows,
    }
    token = signing.dumps(
        {
            "actor": str(user.pk),
            "digest": _review_digest(source, path),
            "source": _source_digest(source),
            "operation": str(uuid.uuid4()),
        },
        salt=PREVIEW_SALT,
    )
    return {"context": token, "snapshot": source, "items": rows, "expected_version": version}


@transaction.atomic
def save_pathway(  # noqa: C901, PLR0912, PLR0913, PLR0915 - Atomic publisher action.
    *,
    user,
    slug,
    title,
    items,
    expected_version=0,
    summary="",
    audience="",
    readiness=None,
    subject_id=None,
    area_id=None,
    is_foundations=False,
    public=False,
    context=None,
):
    """Explicit publisher review-and-release; importing a pack never calls this."""
    from inspinia.learning.permissions import require_publisher

    require_publisher(user)
    if not getattr(settings, "LEARNING_MODULE_ENABLED", False) or not getattr(
        settings,
        "LEARNING_PUBLICATION_ENABLED",
        False,
    ):
        msg = "Pathway publication is not enabled."
        raise PermissionDenied(msg)
    slug = _text(slug, 120, "Pathway slug", required=True)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
        msg = "The pathway slug must be a stable identifier."
        raise ValidationError(msg)
    if type(is_foundations) is not bool or type(public) is not bool:
        msg = "Choose a valid publication channel and Foundations scope."
        raise ValidationError(msg)
    is_foundations = is_foundations or slug == "foundations"
    if is_foundations and (subject_id or area_id):
        msg = "Foundations is cross-topic, not a catalogue subject."
        raise ValidationError(msg)
    subject = CatalogueSubject.objects.filter(pk=subject_id).first() if subject_id else None
    area = CatalogueArea.objects.select_related("subject").filter(pk=area_id).first() if area_id else None
    if (subject_id and subject is None) or (area_id and area is None):
        msg = "The pathway catalogue scope is unavailable."
        raise ValidationError(msg)
    if area and subject and area.subject_id != subject.pk:
        msg = "The area belongs to another subject."
        raise ValidationError(msg)
    if area:
        subject = area.subject
    readiness = [] if readiness is None else readiness
    if not isinstance(readiness, list) or len(readiness) > MAX_READINESS_ITEMS:
        msg = "Readiness needs a bounded list of advisory requirements."
        raise ValidationError(msg)
    readiness = [_text(text, 500, "Readiness", required=True) for text in readiness]
    rows = _normalise_items(items)
    # Same global catalogue-before-document order as content publication and graph edits.
    CatalogueState.objects.select_for_update().filter(pk=1).first()
    _validate_references(rows, public=public)
    path = LearningPath.objects.select_for_update().filter(slug=slug).first()
    source = {
        "slug": slug,
        "title": _text(title, 180, "Title", required=True),
        "summary": _text(summary, 500, "Summary"),
        "audience": _text(audience, 500, "Audience"),
        "readiness": readiness,
        "subject": subject.pk if subject else None,
        "area": area.pk if area else None,
        "foundations": bool(is_foundations),
        "public": bool(public),
        "items": rows,
    }
    payload, operation_id = _preview_payload(context, user, source)
    receipt = LearningPathRevision.objects.filter(operation_id=operation_id).select_related("path").first()
    if receipt:
        if (
            receipt.created_by_id != user.pk
            or receipt.source_digest != payload["source"]
            or receipt.review_context_digest != payload["digest"]
            or receipt.path.slug != slug
        ):
            msg = "This publication operation belongs to a different review."
            raise ValidationError(msg)
        return receipt.path
    if type(expected_version) is not int or expected_version < 0 or (path.version if path else 0) != expected_version:
        msg = "This pathway changed. Review its current version before publishing."
        raise ValidationError(msg)
    if payload.get("digest") != _review_digest(source, path):
        msg = "The pathway, linked notes or readiness context changed. Preview and review again."
        raise ValidationError(msg)
    digest = _source_digest(source)
    if path is None:
        path = LearningPath.objects.create(slug=slug, created_by=user)
    revision = LearningPathRevision.objects.create(
        path=path,
        sequence=path.version + 1,
        title=source["title"],
        summary=source["summary"],
        audience=source["audience"],
        readiness=readiness,
        source_digest=digest,
        created_by=user,
        operation_id=operation_id,
        review_context_digest=payload["digest"],
        snapshot=json.loads(json.dumps(source, default=str)),
    )
    LearningPathItem.objects.bulk_create([LearningPathItem(revision=revision, **row) for row in rows])
    path.current_revision = revision
    path.version += 1
    path.subject = subject
    path.area = area
    path.is_foundations = is_foundations
    path.training_visible = True
    path.public_visible = bool(public)
    path.save(
        update_fields=[
            "current_revision",
            "version",
            "subject",
            "area",
            "is_foundations",
            "training_visible",
            "public_visible",
        ],
    )
    return path


def published_pathways(*, public=False):
    query = LearningPath.objects.filter(training_visible=True, current_revision__isnull=False).select_related(
        "current_revision",
        "subject",
        "area",
    )
    if public:
        query = query.filter(public_visible=True)
    return query


def pathway_edit_payload(path):
    """Round-trip the current immutable revision into the public authoring shape."""
    if not path.current_revision_id:
        msg = "This pathway has no current revision to edit."
        raise ValidationError(msg)
    revision = path.current_revision
    items = []
    for item in revision.items.all():
        row = {"key": item.item_key, "title": item.title, "kind": item.kind, "hints": item.hints}
        if item.kind == LearningPathItem.Kind.DOCUMENT:
            row["document_id"] = str(item.document_id)
        elif item.kind == LearningPathItem.Kind.PROBLEM:
            row["problem_uuid"] = str(item.problem_id)
        elif item.kind == LearningPathItem.Kind.LEGACY:
            row["material_id"] = item.legacy_material_id
        else:
            row["exercise_source"] = item.exercise_source
        items.append(row)
    return {
        "slug": path.slug,
        "title": revision.title,
        "summary": revision.summary,
        "audience": revision.audience,
        "readiness": revision.readiness,
        "subject_id": path.subject_id,
        "area_id": path.area_id,
        "is_foundations": path.is_foundations,
        "public": path.public_visible,
        "expected_version": path.version,
        "items": items,
    }


def publication_impact(document):
    """Current consuming path identities for exact-version content review digests."""
    document_id = getattr(document, "pk", document)
    paths = (
        LearningPath.objects.filter(
            current_revision__items__document_id=document_id,
            current_revision__items__revision_id=F("current_revision_id"),
        )
        .distinct()
        .order_by("pk")
    )
    return [
        {
            "path_id": str(path.pk),
            "revision_id": str(path.current_revision_id),
            "version": path.version,
            "training_visible": path.training_visible,
            "public_visible": path.public_visible,
        }
        for path in paths
    ]


def _practice_status(user, problem_uuid):
    if not getattr(user, "is_authenticated", False):
        return "unattempted"
    statement = (
        ContestProblemStatement.objects.filter(problem_uuid=problem_uuid, is_active=True)
        .order_by("-updated_at", "-pk")
        .first()
    )
    completion = UserProblemCompletion.objects.filter(user=user, statement=statement).first() if statement else None
    if completion is None:
        completion = UserProblemCompletion.objects.filter(user=user, problem__problem_uuid=problem_uuid).first()
    return (completion.status or "").strip().lower() if completion else "unattempted"


def path_context(path, user=None, *, public=False):
    if not getattr(settings, "LEARNING_MODULE_ENABLED", False):
        msg = "Training 2.0 is not enabled."
        raise PermissionDenied(msg)
    if not public:
        _require_reader(user)
    if not path.training_visible or not path.current_revision_id or (public and not path.public_visible):
        msg = "This pathway is not available in this channel."
        raise PermissionDenied(msg)
    items = list(path.current_revision.items.select_related("document", "problem", "legacy_material"))
    publications = _current_document_publications(
        {item.document_id for item in items if item.document_id},
        public=public,
    )
    result = []
    for item in items:
        row = {
            "item": item,
            "key": item.item_key,
            "title": item.title,
            "kind": item.kind,
            "available": True,
            "revision": None,
            "read": False,
            "read_earlier": False,
            "practice_status": "unattempted",
            "practice_completed": False,
        }
        if item.document_id:
            publication = publications.get(item.document_id)
            row["available"] = publication is not None
            row["revision"] = publication.revision if publication else None
            if getattr(user, "is_authenticated", False):
                readings = PathReading.objects.filter(
                    user=user,
                    path_revision__path_id=path.pk,
                    item__item_key=item.item_key,
                    document_revision__document_id=item.document_id,
                )
                row["read"] = bool(
                    publication and readings.filter(document_revision_id=publication.revision_id).exists(),
                )
                row["read_earlier"] = not row["read"] and readings.exists()
        elif item.problem_id:
            row["available"] = item.problem.is_active
            row["practice_status"] = _practice_status(user, item.problem_id)
            row["practice_completed"] = row["practice_status"] in READ_STATUSES
        elif item.legacy_material_id:
            material = item.legacy_material
            row["available"] = (
                not public
                and material.is_published
                and material.subtopic.is_published
                and material.subtopic.topic.is_published
            )
            if getattr(user, "is_authenticated", False):
                row["read"] = MaterialCompletion.objects.filter(user=user, material=material).exists()
        result.append(row)
    return {"path": path, "revision": path.current_revision, "items": result, "public": public}


@transaction.atomic
def mark_read(*, user, path, item_key, revision_id):
    _require_reader(user)
    from inspinia.learning.models import ContentDocument

    item = LearningPathItem.objects.filter(revision_id=path.current_revision_id, item_key=item_key).first()
    if item is None or item.document_id is None:
        msg = "Only a current lecture activity can be marked as read."
        raise ValidationError(msg)
    ContentDocument.objects.select_for_update().get(pk=item.document_id)
    path = LearningPath.objects.select_for_update().get(pk=path.pk)
    if not path.training_visible:
        msg = "This pathway is unavailable."
        raise PermissionDenied(msg)
    if item.revision_id != path.current_revision_id:
        msg = "The pathway changed. Open its current revision."
        raise ValidationError(msg)
    publication = _current_document_publications({item.document_id}).get(item.document_id)
    if publication is None or str(publication.revision_id) != str(revision_id):
        msg = "The lecture changed. Read the current revision before marking it read."
        raise ValidationError(msg)
    reading, _ = PathReading.objects.get_or_create(
        user=user,
        path_revision=path.current_revision,
        item=item,
        document_revision=publication.revision,
    )
    return reading
