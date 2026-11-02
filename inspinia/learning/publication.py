"""Exact-version review and one common publication pointer for every reading channel."""

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from inspinia.learning.drafts import checkpoint_draft
from inspinia.learning.models import ContentAsset
from inspinia.learning.models import ContentDocument
from inspinia.learning.models import ContentDraft
from inspinia.learning.models import ContentPublication
from inspinia.learning.models import ContentRevision
from inspinia.learning.models import ContributionProposal
from inspinia.learning.models import ContributorPermission
from inspinia.learning.permissions import module_enabled
from inspinia.learning.permissions import require_draft_owner
from inspinia.learning.permissions import require_publisher
from inspinia.learning.revisions import LearningConflict
from inspinia.learning.revisions import LearningError
from inspinia.learning.revisions import LearningUnavailable
from inspinia.learning.revisions import create_revision
from inspinia.learning.revisions import digest
from inspinia.learning.revisions import operation_receipt
from inspinia.learning.revisions import record_action
from inspinia.learning.revisions import revision_payload
from inspinia.learning.rights import grant_permission
from inspinia.learning.rights import permission_evidence
from inspinia.pages.catalogue_models import CatalogueState
from inspinia.users.roles import user_can_access_app_features

REVIEW_SALT = "asterproof.learning-review.v1"
FEEDBACK_LIMIT = 8000


def visible_publications(*, user=None, public=False):
    query = ContentPublication.objects.select_related(
        "document",
        "revision",
        "document__canonical_area",
        "document__canonical_concept",
    )
    if not module_enabled():
        return query.none()
    if public:
        return query.filter(public_visible=True, revision__isnull=False)
    if not user_can_access_app_features(user) or not getattr(user, "is_active", False):
        return query.none()
    return query.filter(training_visible=True, revision__isnull=False)


def _lock_catalogue():
    list(CatalogueState.objects.select_for_update().order_by("pk").values_list("pk", flat=True))


def _impact(document):
    from inspinia.training.pathways import publication_impact

    return publication_impact(document)


def snapshot(proposal):
    revision = proposal.revision
    if digest(revision_payload(revision)) != revision.source_digest:
        message = "The saved source integrity check failed."
        raise LearningConflict(message)
    publication = ContentPublication.objects.get(document=proposal.document)
    concepts = list(revision.concept_links.order_by("concept_id").values("concept_id", "role", "concept__redirect_id"))
    expected_concepts = sorted((e["id"], e["role"]) for e in revision.metadata.get("concepts", []))
    if expected_concepts != sorted((e["concept_id"], e["role"]) for e in concepts):
        message = "Saved concept references changed after the checkpoint."
        raise LearningConflict(message)
    assets = list(
        revision.asset_links.order_by("asset_id").values(
            "asset_id",
            "alt_text",
            "caption",
            "credit",
            "asset__sha256",
            "asset__state",
            "asset__byte_size",
            "asset__document_id",
        ),
    )
    if any(e["asset__state"] != ContentAsset.State.ACTIVE for e in assets):
        message = "A referenced image is no longer available."
        raise LearningConflict(message)
    for entry in assets:
        entry["asset_id"], entry["asset__document_id"] = str(entry["asset_id"]), str(entry["asset__document_id"])
    expected_assets = sorted(
        (e["id"], e["alt"], e.get("caption", ""), e.get("credit", "")) for e in revision.metadata.get("assets", [])
    )
    if expected_assets != sorted((e["asset_id"], e["alt_text"], e["caption"], e["credit"]) for e in assets):
        message = "Saved image references changed after the checkpoint."
        raise LearningConflict(message)
    source_state = list(CatalogueState.objects.order_by("pk").values_list("source_revision", flat=True))
    return {
        "proposal": str(proposal.pk),
        "revision": str(revision.pk),
        "source": revision.source_digest,
        "publication_version": publication.version,
        "concepts": concepts,
        "assets": assets,
        "rights": permission_evidence(revision),
        "catalogue": source_state,
        "pathways": _impact(proposal.document),
    }


def review_context(proposal):
    return signing.dumps({"digest": digest(snapshot(proposal)), "proposal": str(proposal.pk)}, salt=REVIEW_SALT)


def restoration_candidates(*, user, document):
    """A publisher sees submitted, permission-bound history, not private checkpoints."""
    require_publisher(user)
    return (
        ContentRevision.objects.filter(
            document=document,
            permission__isnull=False,
            proposals__isnull=False,
        )
        .select_related("permission")
        .distinct()
        .order_by("-sequence")
    )


@transaction.atomic
def propose_restoration(*, user, document, revision_id, expected_version, operation_id=None):
    """Re-review exact historical source with its original grant; never republish directly."""
    require_publisher(user)
    _lock_catalogue()
    document = ContentDocument.objects.select_for_update().get(pk=document.pk)
    publication = ContentPublication.objects.select_for_update().get(document=document)
    payload = {"revision": str(revision_id), "version": expected_version}
    receipt, operation_id, payload_digest = operation_receipt(
        operation_id,
        user,
        document,
        "propose_restoration",
        payload,
    )
    if receipt:
        return ContributionProposal.objects.get(pk=receipt.result["proposal_id"])
    if type(expected_version) is not int or publication.version != expected_version:
        message = "The current publication changed. Compare it with the historical revision again."
        raise LearningConflict(message)
    revision = restoration_candidates(user=user, document=document).filter(pk=revision_id).first()
    if revision is None:
        message = "Only submitted history with its original contributor permission can be restored."
        raise LearningError(message)
    permission_evidence(revision)
    proposal = ContributionProposal.objects.create(
        document=document,
        author=user,
        revision=revision,
        base_publication_version=publication.version,
        review_digest="",
    )
    proposal.review_digest = digest(snapshot(proposal))
    proposal.save(update_fields=["review_digest"])
    record_action(
        operation_id=operation_id,
        user=user,
        document=document,
        action="propose_restoration",
        payload_digest=payload_digest,
        result={"proposal_id": str(proposal.pk)},
    )
    return proposal


def _validate_review(context, proposal):
    try:
        value = signing.loads(context, salt=REVIEW_SALT, max_age=86400)
    except (signing.BadSignature, TypeError, ValueError) as exc:
        message = "This review expired. Open a fresh comparison."
        raise LearningConflict(message) from exc
    current = digest(snapshot(proposal))
    if value != {"digest": current, "proposal": str(proposal.pk)}:
        message = "The source, placement, rights or assets changed. Review the current comparison again."
        raise LearningConflict(message)
    return current


@transaction.atomic
def submit_draft(  # noqa: PLR0913 - Explicit domain action and validation boundary.
    *,
    draft,
    user,
    agreement_version,
    rights_confirmed=False,
    public_credit="",
    declaration=None,
    operation_id=None,
    base_version=None,
):
    require_draft_owner(draft, user)
    if not isinstance(public_credit, str) or (declaration is not None and not isinstance(declaration, dict)):
        message = "Provide valid contributor credit and permission fields."
        raise LearningError(message)
    _lock_catalogue()
    document = ContentDocument.objects.select_for_update().get(pk=draft.document_id)
    current = ContentDraft.objects.select_for_update().get(pk=draft.pk)
    require_draft_owner(current, user)
    payload = {
        "draft": str(current.pk),
        "version": current.edit_version if base_version is None else base_version,
        "agreement": agreement_version,
        "credit": public_credit,
        "declaration": declaration,
        "confirmed": rights_confirmed,
    }
    receipt, operation_id, payload_digest = operation_receipt(operation_id, user, document, "submit", payload)
    if receipt:
        return ContributionProposal.objects.get(pk=receipt.result["proposal_id"])
    publication = ContentPublication.objects.select_for_update().get(document=document)
    if publication.version != current.base_publication_version:
        message = "A newer version was published. Compare and reconcile this draft before submission."
        raise LearningConflict(message)
    revision = checkpoint_draft(draft=current, user=user, base_version=base_version)
    existing_permission = ContributorPermission.objects.filter(revision=revision).first()
    desired_declaration = {
        "original_or_authorised": True,
        "sources": (declaration or {}).get("sources", ""),
        "editorial_changes_allowed": (declaration or {}).get("editorial_changes_allowed") is True,
    }
    if existing_permission and (
        existing_permission.agreement_version != agreement_version
        or existing_permission.public_credit != public_credit.strip()
        or existing_permission.rights_declaration != desired_declaration
    ):
        revision = create_revision(current, force=True)
    grant_permission(
        revision=revision,
        user=user,
        agreement_version=agreement_version,
        rights_confirmed=rights_confirmed,
        public_credit=public_credit,
        declaration=declaration,
    )
    existing = ContributionProposal.objects.filter(
        revision=revision,
        author=user,
        status__in=[ContributionProposal.Status.SUBMITTED, ContributionProposal.Status.APPROVED],
    ).first()
    if existing:
        record_action(
            operation_id=operation_id,
            user=user,
            document=document,
            action="submit",
            payload_digest=payload_digest,
            result={"proposal_id": str(existing.pk)},
        )
        return existing
    proposal = ContributionProposal.objects.create(
        document=document,
        author=user,
        revision=revision,
        base_publication_version=publication.version,
        review_digest="",
    )
    proposal.review_digest = digest(snapshot(proposal))
    proposal.save(update_fields=["review_digest"])
    record_action(
        operation_id=operation_id,
        user=user,
        document=document,
        action="submit",
        payload_digest=payload_digest,
        result={"proposal_id": str(proposal.pk)},
    )
    return proposal


@transaction.atomic
def review_proposal(*, proposal, user, action, feedback="", context="", operation_id=None):  # noqa: PLR0913 - Explicit domain action and validation boundary.
    require_publisher(user)
    if action not in {"approve", "changes_requested", "decline"}:
        message = "Choose an approval, revision request or decline action."
        raise LearningError(message)
    if not isinstance(feedback, str) or len(feedback) > FEEDBACK_LIMIT:
        message = "Keep review feedback within 8,000 characters."
        raise LearningError(message)
    if action != "approve" and not feedback.strip():
        message = "Explain the requested revision or decline."
        raise LearningError(message)
    _lock_catalogue()
    document = ContentDocument.objects.select_for_update().get(pk=proposal.document_id)
    proposal = (
        ContributionProposal.objects.select_for_update().select_related("revision", "document").get(pk=proposal.pk)
    )
    payload = {"proposal": str(proposal.pk), "action": action, "feedback": feedback, "context": context}
    receipt, operation_id, payload_digest = operation_receipt(operation_id, user, document, "review", payload)
    if receipt:
        return proposal
    if proposal.status != ContributionProposal.Status.SUBMITTED:
        message = "This submission is no longer awaiting review."
        raise LearningConflict(message)
    publication = ContentPublication.objects.select_for_update().get(document=document)
    if action == "approve" and publication.version != proposal.base_publication_version:
        message = "This proposal was based on an older publication. Request reconciliation first."
        raise LearningConflict(message)
    checked = _validate_review(context, proposal)
    proposal.status = {
        "approve": ContributionProposal.Status.APPROVED,
        "changes_requested": ContributionProposal.Status.CHANGES_REQUESTED,
        "decline": ContributionProposal.Status.DECLINED,
    }[action]
    proposal.feedback = feedback.strip()
    proposal.reviewed_by = user
    proposal.reviewed_at = timezone.now()
    proposal.review_digest = checked
    proposal.save()
    record_action(
        operation_id=operation_id,
        user=user,
        document=document,
        action="review",
        payload_digest=payload_digest,
        result={"proposal_id": str(proposal.pk), "status": proposal.status},
    )
    return proposal


def publish_proposal(*, proposal, user, context, expected_version, public=False, operation_id=None):  # noqa: PLR0913 - Explicit domain action and validation boundary.
    require_publisher(user)
    if not getattr(settings, "LEARNING_PUBLICATION_ENABLED", False):
        message = "Publication is disabled until the release prerequisites are verified."
        raise LearningUnavailable(message)
    if type(public) is not bool or type(expected_version) is not int:
        message = "Choose valid publication visibility and version."
        raise LearningError(message)
    payload = {"proposal": str(proposal.pk), "context": context, "version": expected_version, "public": public}
    receipt, operation_id, payload_digest = operation_receipt(
        operation_id, user, proposal.document, "publish", payload,
    )
    if receipt:
        return ContentPublication.objects.get(document_id=proposal.document_id)
    # Storage availability is checked before any publication transaction/row locks.
    from inspinia.learning.assets import asset_files_available

    if asset_files_available(proposal.revision) is False:
        message = "A referenced image file is missing or damaged."
        raise LearningError(message)
    with transaction.atomic():
        _lock_catalogue()
        document = ContentDocument.objects.select_for_update().get(pk=proposal.document_id)
        proposal = (
            ContributionProposal.objects.select_for_update().select_related("revision", "document").get(pk=proposal.pk)
        )
        receipt, operation_id, payload_digest = operation_receipt(operation_id, user, document, "publish", payload)
        publication = ContentPublication.objects.select_for_update().get(document=document)
        if receipt:
            return publication
        list(
            ContentAsset.objects.select_for_update().filter(revision_links__revision=proposal.revision).order_by("pk"),
        )
        if publication.version != expected_version or proposal.base_publication_version != expected_version:
            message = "The publication changed. Reconcile and review a new proposal."
            raise LearningConflict(message)
        if proposal.status != ContributionProposal.Status.APPROVED:
            message = "Approve this exact submitted revision before publishing it."
            raise LearningError(message)
        checked = _validate_review(context, proposal)
        if checked != proposal.review_digest:
            message = "The approved publication context changed. Review a new submission."
            raise LearningConflict(message)
        publication.revision = proposal.revision
        publication.training_visible = True
        publication.public_visible = public
        publication.version += 1
        publication.published_by = user
        publication.published_at = timezone.now()
        publication.announcement_disposition = "excluded"
        publication.save()
        if not document.slug:
            document.slug = slugify(proposal.revision.title)[:180] or str(document.pk)
            document.save(update_fields=["slug"])
        record_action(
            operation_id=operation_id,
            user=user,
            document=document,
            action="publish",
            payload_digest=payload_digest,
            result={"publication_version": publication.version, "revision_id": str(publication.revision_id)},
        )
        return publication


@transaction.atomic
def withdraw_document(*, document, user, expected_version, public_only=False, operation_id=None):
    require_publisher(user)
    if type(public_only) is not bool:
        message = "Choose a valid withdrawal scope."
        raise LearningError(message)
    _lock_catalogue()
    document = ContentDocument.objects.select_for_update().get(pk=document.pk)
    payload = {"version": expected_version, "public_only": public_only}
    receipt, operation_id, payload_digest = operation_receipt(operation_id, user, document, "withdraw", payload)
    publication = ContentPublication.objects.select_for_update().get(document=document)
    if receipt:
        return publication
    if type(expected_version) is not int or publication.version != expected_version:
        message = "The publication changed. Review the current visibility first."
        raise LearningConflict(message)
    publication.public_visible = False
    if not public_only:
        publication.training_visible = False
    publication.version += 1
    publication.save()
    record_action(
        operation_id=operation_id,
        user=user,
        document=document,
        action="withdraw",
        payload_digest=payload_digest,
        result={"publication_version": publication.version},
    )
    return publication
