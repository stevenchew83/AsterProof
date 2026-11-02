"""Author-owned autosaves and immutable checkpoints; GET never creates drafts."""

import uuid

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction

from inspinia.learning.models import ContentDocument
from inspinia.learning.models import ContentDraft
from inspinia.learning.models import ContentPublication
from inspinia.learning.models import ContributionProposal
from inspinia.learning.permissions import is_publisher
from inspinia.learning.permissions import require_contributor
from inspinia.learning.permissions import require_draft_owner
from inspinia.learning.revisions import LearningConflict
from inspinia.learning.revisions import LearningError
from inspinia.learning.revisions import canonical_concept_id
from inspinia.learning.revisions import create_revision
from inspinia.learning.revisions import digest
from inspinia.learning.revisions import operation_receipt
from inspinia.learning.revisions import record_action
from inspinia.learning.revisions import validated_content
from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueState

CONTEXT_SALT = "asterproof.learning-editor.v1"
CONTEXT_TTL = 7 * 24 * 60 * 60
DRAFT_LIMIT = 25


def editor_context(draft, user):
    require_draft_owner(draft, user)
    return signing.dumps(
        {
            "draft": str(draft.pk),
            "document": str(draft.document_id),
            "author": str(user.pk),
            "version": draft.edit_version,
        },
        salt=CONTEXT_SALT,
    )


def validate_context(context, draft, user, base_version):
    try:
        value = signing.loads(context, salt=CONTEXT_SALT, max_age=CONTEXT_TTL)
    except (signing.BadSignature, TypeError, ValueError) as exc:
        message = "This editor session expired. Reload while keeping your writing."
        raise LearningConflict(message) from exc
    expected = {
        "draft": str(draft.pk),
        "document": str(draft.document_id),
        "author": str(user.pk),
        "version": base_version,
    }
    if value != expected or type(base_version) is not int:
        message = "This editor context belongs to another version or account."
        raise LearningConflict(message)


@transaction.atomic
def create_draft(  # noqa: C901, PLR0913 - Explicit domain action and validation boundary.
    *,
    user,
    kind="lecture",
    area_id=None,
    concept_id=None,
    document=None,
    title="",
    source="",
    summary="",
    metadata=None,
):
    require_contributor(user)
    list(CatalogueState.objects.select_for_update().values_list("pk", flat=True))
    if document is None:
        if kind not in ContentDocument.Kind.values:
            message = "Choose a valid teaching document type."
            raise LearningError(message)
        area = CatalogueArea.objects.select_for_update().filter(pk=area_id).first() if area_id else None
        concept = (
            CatalogueConcept.objects.select_for_update().filter(pk=canonical_concept_id(concept_id)).first()
            if concept_id
            else None
        )
        if (area_id and area is None) or (concept_id and concept is None):
            message = "Choose an existing canonical area or concept."
            raise LearningError(message)
        if kind == "overview" and (not area or concept):
            message = "An area overview needs exactly one canonical area."
            raise LearningError(message)
        if kind == "concept" and (not concept or area):
            message = "A concept explanation needs exactly one canonical concept."
            raise LearningError(message)
        if kind in {"lecture", "technique"} and not (area or concept):
            message = "Associate this teaching document with an existing area or concept."
            raise LearningError(message)
        if kind == "standalone" and (area or concept):
            message = "Standalone editorial resources cannot claim a canonical landing."
            raise LearningError(message)
        canonical_filter = {"kind": kind, "canonical_area": area, "canonical_concept": concept}
        document = (
            ContentDocument.objects.filter(**canonical_filter).first() if kind in {"overview", "concept"} else None
        )
        if document is None:
            document = ContentDocument.objects.create(**canonical_filter, creator=user)
        ContentPublication.objects.get_or_create(document=document)
    else:
        document = ContentDocument.objects.select_for_update().get(pk=document.pk)
    document = ContentDocument.objects.select_for_update().get(pk=document.pk)
    publication = ContentPublication.objects.get(document=document)
    draft = ContentDraft.objects.filter(document=document, author=user).first()
    if draft:
        return draft
    get_user_model().objects.select_for_update().get(pk=user.pk)
    if ContentDraft.objects.filter(author=user, is_archived=False).count() >= DRAFT_LIMIT:
        message = "Keep at most 25 active drafts. Archive finished work before starting another."
        raise LearningError(message)
    base = publication.revision if publication.training_visible or is_publisher(user) else None
    values = {
        "title": base.title if base else title,
        "summary": base.summary if base else summary,
        "body_source": base.body_source if base else source,
        "metadata": base.metadata if base else metadata or {},
    }
    checked = validated_content(
        document=document,
        user=user,
        source=values["body_source"],
        title=values["title"],
        summary=values["summary"],
        metadata=values["metadata"],
    )
    return ContentDraft.objects.create(
        document=document,
        author=user,
        base_revision=base,
        base_publication_version=publication.version,
        title=checked[1],
        summary=checked[2],
        body_source=checked[0],
        metadata=checked[3],
    )


@transaction.atomic
def archive_draft(*, draft, user, archived=True, base_version, operation_id=None):
    """Release an active workspace slot while retaining all source and history."""
    require_draft_owner(draft, user, allow_archived=True)
    if type(archived) is not bool or type(base_version) is not int:
        message = "Choose a valid draft state and current version."
        raise LearningError(message)
    document = ContentDocument.objects.select_for_update().get(pk=draft.document_id)
    current = ContentDraft.objects.select_for_update().get(pk=draft.pk)
    require_draft_owner(current, user, allow_archived=True)
    payload = {"draft": str(current.pk), "archived": archived, "version": base_version}
    receipt, operation_id, payload_digest = operation_receipt(
        operation_id, user, document, "archive_draft", payload,
    )
    if receipt:
        return current
    if current.edit_version != base_version:
        message = "This draft changed. Reload before changing its archive state."
        raise LearningConflict(message)
    if current.is_archived != archived:
        get_user_model().objects.select_for_update().get(pk=user.pk)
        if not archived and ContentDraft.objects.filter(author=user, is_archived=False).count() >= DRAFT_LIMIT:
            message = "Keep at most 25 active drafts. Archive another draft before reopening this one."
            raise LearningError(message)
        current.is_archived = archived
        current.edit_version += 1
        current.save_receipts = []
        current.save(update_fields=["is_archived", "edit_version", "save_receipts", "updated_at"])
    record_action(
        operation_id=operation_id, user=user, document=document, action="archive_draft",
        payload_digest=payload_digest,
        result={"draft_id": str(current.pk), "version": current.edit_version, "archived": current.is_archived},
    )
    return current


@transaction.atomic
def save_draft(*, draft, user, title, summary, source, metadata, base_version, context, operation_id=None):  # noqa: PLR0913 - Explicit domain action and validation boundary.
    require_draft_owner(draft, user)
    ContentDocument.objects.select_for_update().get(pk=draft.document_id)
    current = ContentDraft.objects.select_for_update().get(pk=draft.pk)
    require_draft_owner(current, user)
    validate_context(context, current, user, base_version)
    payload = {"title": title, "summary": summary, "source": source, "metadata": metadata, "base": base_version}
    payload_digest = digest(payload)
    try:
        operation_key = str(uuid.UUID(str(operation_id))) if operation_id else str(uuid.uuid4())
    except (TypeError, ValueError) as exc:
        message = "Invalid save identity."
        raise LearningError(message) from exc
    for receipt in current.save_receipts:
        if receipt["id"] == operation_key:
            if receipt["digest"] != payload_digest:
                message = "This save identity was reused for different writing."
                raise LearningConflict(message)
            return current
    if current.edit_version != base_version:
        message = "Another tab saved a newer version. Your submitted writing has been retained in this editor."
        raise LearningConflict(message)
    source, title, summary, metadata = validated_content(
        document=current.document,
        user=user,
        source=source,
        title=title,
        summary=summary,
        metadata=metadata,
    )
    changed = (source, title, summary, metadata) != (
        current.body_source,
        current.title,
        current.summary,
        current.metadata,
    )
    if changed:
        current.body_source, current.title, current.summary, current.metadata = source, title, summary, metadata
        current.edit_version += 1
        ContributionProposal.objects.filter(
            document=current.document,
            author=user,
            status__in=[ContributionProposal.Status.SUBMITTED, ContributionProposal.Status.APPROVED],
        ).update(status=ContributionProposal.Status.SUPERSEDED)
    current.save_receipts = [
        *current.save_receipts[-63:],
        {"id": operation_key, "digest": payload_digest, "version": current.edit_version},
    ]
    current.save()
    return current


@transaction.atomic
def checkpoint_draft(*, draft, user, operation_id=None, base_version=None):
    require_draft_owner(draft, user)
    document = ContentDocument.objects.select_for_update().get(pk=draft.document_id)
    current = ContentDraft.objects.select_for_update().get(pk=draft.pk)
    require_draft_owner(current, user)
    payload = {"draft": str(current.pk), "version": current.edit_version if base_version is None else base_version}
    receipt, operation_id, payload_digest = operation_receipt(operation_id, user, document, "checkpoint", payload)
    if receipt:
        return document.revisions.get(pk=receipt.result["revision_id"])
    if base_version is not None and (type(base_version) is not int or current.edit_version != base_version):
        message = "This draft changed before the checkpoint. Reload without discarding your writing."
        raise LearningConflict(message)
    if not current.title.strip() or not current.body_source.strip():
        message = "Give the note a title and substantive source before making a checkpoint."
        raise LearningError(message)
    checked = validated_content(
        document=document,
        user=user,
        source=current.body_source,
        title=current.title,
        summary=current.summary,
        metadata=current.metadata,
    )
    current.body_source, current.title, current.summary, current.metadata = checked
    from inspinia.learning.assets import validate_draft_assets

    validate_draft_assets(current, user, require_alt=True)
    revision = create_revision(current)
    record_action(
        operation_id=operation_id,
        user=user,
        document=document,
        action="checkpoint",
        payload_digest=payload_digest,
        result={"revision_id": str(revision.pk)},
    )
    return revision


@transaction.atomic
def rebase_draft(*, draft, user, base_version, publication_version, context, confirmed=False):  # noqa: PLR0913 - Explicit domain action and validation boundary.
    """A deliberate reconciliation keeps writing but binds it to the reviewed current base."""
    require_draft_owner(draft, user)
    _lock = ContentDocument.objects.select_for_update().get(pk=draft.document_id)
    current = ContentDraft.objects.select_for_update().get(pk=draft.pk)
    validate_context(context, current, user, base_version)
    if confirmed is not True or current.edit_version != base_version:
        message = "Compare the current publication and explicitly confirm reconciliation."
        raise LearningConflict(message)
    publication = ContentPublication.objects.select_for_update().get(document_id=current.document_id)
    if type(publication_version) is not int or publication.version != publication_version:
        message = "The publication changed during reconciliation. Compare it again."
        raise LearningConflict(message)
    if not publication.training_visible and not is_publisher(user):
        message = "The current teaching note is not available for reconciliation."
        raise LearningConflict(message)
    current.base_revision = publication.revision
    current.base_publication_version = publication.version
    current.edit_version += 1
    current.save_receipts = []
    current.save()
    ContributionProposal.objects.filter(
        document=current.document,
        author=user,
        status__in=[ContributionProposal.Status.SUBMITTED, ContributionProposal.Status.APPROVED],
    ).update(status=ContributionProposal.Status.SUPERSEDED)
    return current
