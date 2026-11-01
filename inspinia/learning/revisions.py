"""Validation and immutable checkpoints for mathematical teaching documents."""

import hashlib
import json
import re
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import Max

from inspinia.learning.models import ContentAction
from inspinia.learning.models import ContentAsset
from inspinia.learning.models import ContentAssetGrant
from inspinia.learning.models import ContentDraft
from inspinia.learning.models import ContentPublication
from inspinia.learning.models import ContentRevision
from inspinia.learning.models import RevisionAsset
from inspinia.learning.models import RevisionConcept
from inspinia.pages.catalogue_models import CatalogueConcept

SOURCE_LIMIT = 64_000

TITLE_LIMIT = 180
SUMMARY_LIMIT = 320
METADATA_TEXT_LIMIT = 2000
READING_MINUTES_LIMIT = 1440
CONCEPT_LIMIT = 100
IMAGE_LIMIT = 20
IMAGE_TEXT_LIMIT = 500
CAPTION_LIMIT = 1000
METADATA_LIMIT = 16_000
METADATA_DEPTH_LIMIT = 12
ASSET_TOKEN = re.compile(r"asset:([0-9a-fA-F-]{36})(?![0-9a-fA-F-])")
METADATA_FIELDS = {
    "concepts",
    "assets",
    "audience",
    "level",
    "estimated_minutes",
    "prerequisites",
    "objectives",
    "attribution",
    "source_url",
    "template",
    "foundations_competency",
    "content_pack",
    "pack_id",
    "pack_version",
    "original_author",
    "source_problem_uuids",
}


class LearningError(ValueError):
    pass


class LearningConflict(LearningError):  # noqa: N818 - Public domain exception contract.
    pass


class LearningUnavailable(LearningError):  # noqa: N818 - Public domain exception contract.
    pass


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(),
    ).hexdigest()


def canonical_concept_id(value):
    seen = set()
    current = str(value)
    while current not in seen:
        seen.add(current)
        row = CatalogueConcept.objects.filter(pk=current).values("id", "redirect_id").first()
        if row is None:
            message = "A selected concept is unavailable."
            raise LearningError(message)
        if not row["redirect_id"]:
            return row["id"]
        current = row["redirect_id"]
    message = "The concept has a redirect cycle and needs curator review."
    raise LearningError(message)


def validated_content(*, document, user, source, title, summary, metadata):  # noqa: PLR0913
    if not all(isinstance(v, str) for v in (source, title, summary)):
        message = "The title, summary and source must contain text."
        raise LearningError(message)
    from inspinia.learning.rendering import validate_learning_source

    validate_learning_source(source)
    validate_learning_source(title)
    validate_learning_source(summary)
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    if (
        len(source) > SOURCE_LIMIT
        or len(title) > TITLE_LIMIT
        or len(summary) > SUMMARY_LIMIT
        or "\x00" in source + title + summary
    ):
        message = "Keep the source within 64,000 characters, title within 180 and summary within 320."
        raise LearningError(message)
    cleaned = _validated_metadata(metadata)
    _validate_metadata_mathematics(cleaned)
    cleaned["concepts"] = _validated_concepts(cleaned.get("concepts", []), document)
    cleaned["assets"] = _validated_assets(cleaned.get("assets", []), document, user, source)
    return source, title.strip(), summary.strip(), cleaned


def _validate_metadata_mathematics(value):
    """The TeX policy also covers mathematical text displayed outside the body."""
    from inspinia.learning.rendering import validate_learning_source

    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > METADATA_DEPTH_LIMIT:
            message = "The document metadata is too deeply nested."
            raise LearningError(message)
        if isinstance(item, str):
            validate_learning_source(item)
        elif isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)


def _validate_source_url(value):
    if value:
        try:
            URLValidator(schemes=["http", "https"])(value)
        except ValidationError as exc:
            message = "Use an HTTP or HTTPS source reference."
            raise LearningError(message) from exc


def _validated_metadata(metadata):
    if not isinstance(metadata, dict) or set(metadata) - METADATA_FIELDS:
        message = "Unsupported document metadata."
        raise LearningError(message)
    try:
        encoded = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
        size = len(encoded.encode())
    except (TypeError, ValueError, RecursionError) as exc:
        message = "Document metadata must be JSON."
        raise LearningError(message) from exc
    if size > METADATA_LIMIT:
        message = "The document metadata is too large."
        raise LearningError(message)
    cleaned = json.loads(encoded)
    for key in ("audience", "level", "attribution", "source_url", "template", "foundations_competency"):
        value = cleaned.get(key, "")
        if not isinstance(value, str) or len(value) > METADATA_TEXT_LIMIT:
            message = "The document metadata contains an invalid text field."
            raise LearningError(message)
    _validate_source_url(cleaned.get("source_url", ""))
    for key in ("objectives", "prerequisites"):
        values = cleaned.get(key, [])
        if (
            not isinstance(values, list)
            or len(values) > CONCEPT_LIMIT
            or any(not isinstance(value, str) or len(value) > METADATA_TEXT_LIMIT for value in values)
        ):
            message = "Objectives and readiness items must be bounded text lists."
            raise LearningError(message)
    minutes = cleaned.get("estimated_minutes", 10)
    if type(minutes) is not int or not 1 <= minutes <= READING_MINUTES_LIMIT:
        message = "Choose a reading time between 1 and 1,440 minutes."
        raise LearningError(message)
    return cleaned


def _validated_concepts(concepts, document):
    if not isinstance(concepts, list) or len(concepts) > CONCEPT_LIMIT:
        message = "Choose at most 100 concept associations."
        raise LearningError(message)
    normalized = []
    seen = set()
    for raw_entry in concepts:
        entry = {"id": raw_entry, "role": "supporting"} if isinstance(raw_entry, str) else raw_entry
        if not isinstance(entry, dict) or set(entry) - {"id", "role"}:
            message = "Invalid concept association."
            raise LearningError(message)
        cid = canonical_concept_id(entry.get("id", ""))
        role = entry.get("role", "supporting")
        if role not in RevisionConcept.Role.values:
            message = "Choose a primary or supporting concept role."
            raise LearningError(message)
        if cid not in seen:
            normalized.append({"id": cid, "role": role})
            seen.add(cid)
    if document.canonical_concept_id and document.canonical_concept_id not in seen:
        normalized.insert(0, {"id": canonical_concept_id(document.canonical_concept_id), "role": "primary"})
    return normalized


def _validated_assets(assets, document, user, source):  # noqa: C901 - Explicit domain action and validation boundary.
    if not isinstance(assets, list) or len(assets) > IMAGE_LIMIT:
        message = "Use at most 20 images in a document."
        raise LearningError(message)
    referenced = {str(uuid.UUID(match)) for match in ASSET_TOKEN.findall(source)}
    normalized_assets = []
    asset_ids = set()
    entries = []
    for entry in assets:
        if not isinstance(entry, dict) or set(entry) - {"id", "alt", "alt_text", "caption", "credit"}:
            message = "Invalid image reference."
            raise LearningError(message)
        try:
            aid = str(uuid.UUID(str(entry.get("id", ""))))
        except (TypeError, ValueError) as exc:
            message = "Invalid image reference."
            raise LearningError(message) from exc
        entries.append((aid, entry))
    # Different documents may reuse the same granted assets. Acquire every row
    # in the same order rather than the contributor's metadata ordering.
    locked_assets = {
        str(asset.pk): asset
        for asset in ContentAsset.objects.select_for_update()
        .filter(
            pk__in=[aid for aid, _entry in entries],
            state=ContentAsset.State.ACTIVE,
        )
        .order_by("pk")
    }
    for aid, entry in entries:
        alt = entry.get("alt", entry.get("alt_text", ""))
        caption, credit = entry.get("caption", ""), entry.get("credit", "")
        if not all(isinstance(v, str) for v in (alt, caption, credit)):
            message = "Add alternative text for each referenced image."
            raise LearningError(message)
        if len(alt) > IMAGE_TEXT_LIMIT or len(caption) > CAPTION_LIMIT or len(credit) > IMAGE_TEXT_LIMIT:
            message = "An image description is too long."
            raise LearningError(message)
        asset = locked_assets.get(aid)
        if asset is None:
            message = "A referenced image is unavailable."
            raise LearningError(message)
        same_document = asset.document_id == document.pk
        owns = asset.owner_id == user.pk
        permitted = ContentAssetGrant.objects.filter(asset=asset, document=document).exists()
        existing = (
            ContentDraft.objects.filter(
                document=document,
                author=user,
                base_revision__asset_links__asset=asset,
            ).exists()
            or ContentPublication.objects.filter(
                document=document,
                training_visible=True,
                revision__asset_links__asset=asset,
            ).exists()
        )
        if not ((same_document and (owns or existing)) or permitted):
            message = "The image is not authorised for this document."
            raise LearningError(message)
        if aid not in asset_ids:
            normalized_assets.append({"id": aid, "alt": alt.strip(), "caption": caption, "credit": credit})
            asset_ids.add(aid)
    if referenced - asset_ids:
        message = "Every image needs a managed reference and alternative text."
        raise LearningError(message)
    # Retain only used assets; stale toolbar metadata must not keep disclosing a removed image.
    return [entry for entry in normalized_assets if entry["id"] in referenced]


def revision_payload(revision):
    return {
        "title": revision.title,
        "summary": revision.summary,
        "source": revision.body_source,
        "metadata": revision.metadata,
        "format": revision.body_format,
    }


def create_revision(draft, *, force=False):
    payload = {
        "title": draft.title,
        "summary": draft.summary,
        "source": draft.body_source,
        "metadata": draft.metadata,
        "format": "markdown_latex_v1",
    }
    source_digest = digest(payload)
    previous = draft.document.revisions.order_by("-sequence").first()
    if (
        not force
        and previous
        and previous.author_id == draft.author_id
        and previous.source_digest == source_digest
        and previous.base_revision_id == draft.base_revision_id
    ):
        return previous
    sequence = (ContentRevision.objects.filter(document=draft.document).aggregate(n=Max("sequence"))["n"] or 0) + 1
    revision = ContentRevision.objects.create(
        document=draft.document,
        author=draft.author,
        base_revision=draft.base_revision,
        sequence=sequence,
        title=draft.title,
        summary=draft.summary,
        body_source=draft.body_source,
        metadata=draft.metadata,
        source_digest=source_digest,
    )
    RevisionConcept.objects.bulk_create(
        [
            RevisionConcept(revision=revision, concept_id=e["id"], role=e["role"])
            for e in draft.metadata.get("concepts", [])
        ],
    )
    RevisionAsset.objects.bulk_create(
        [
            RevisionAsset(
                revision=revision,
                asset_id=e["id"],
                alt_text=e["alt"],
                caption=e.get("caption", ""),
                credit=e.get("credit", ""),
            )
            for e in draft.metadata.get("assets", [])
        ],
    )
    return revision


def operation_receipt(operation_id, user, document, action, payload):
    if operation_id is None:
        return None, uuid.uuid4(), digest(payload)
    try:
        operation_id = uuid.UUID(str(operation_id))
    except (TypeError, ValueError) as exc:
        message = "Invalid operation identity."
        raise LearningError(message) from exc
    payload_digest = digest(payload)
    receipt = ContentAction.objects.filter(pk=operation_id).first()
    if receipt and (
        receipt.actor_id != user.pk
        or receipt.document_id != document.pk
        or receipt.action != action
        or receipt.payload_digest != payload_digest
    ):
        message = "This operation identity was already used for different work."
        raise LearningConflict(message)
    return receipt, operation_id, payload_digest


def record_action(*, operation_id, user, document, action, payload_digest, result):  # noqa: PLR0913 - Explicit domain action and validation boundary.
    return ContentAction.objects.create(
        operation_id=operation_id,
        actor=user,
        document=document,
        action=action,
        payload_digest=payload_digest,
        result=result,
    )
