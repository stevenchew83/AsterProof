import uuid

import pytest
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction

from inspinia.learning.drafts import archive_draft
from inspinia.learning.drafts import checkpoint_draft
from inspinia.learning.drafts import create_draft
from inspinia.learning.drafts import editor_context
from inspinia.learning.drafts import rebase_draft
from inspinia.learning.drafts import save_draft
from inspinia.learning.models import ContentAction
from inspinia.learning.models import ContentDocument
from inspinia.learning.models import ContentDraft
from inspinia.learning.models import ContentRevision
from inspinia.learning.models import ContributionProposal
from inspinia.learning.permissions import can_contribute
from inspinia.learning.permissions import is_publisher
from inspinia.learning.publication import propose_restoration
from inspinia.learning.publication import publish_proposal
from inspinia.learning.publication import restoration_candidates
from inspinia.learning.publication import review_context
from inspinia.learning.publication import review_proposal
from inspinia.learning.publication import submit_draft
from inspinia.learning.publication import visible_publications
from inspinia.learning.publication import withdraw_document
from inspinia.learning.revisions import LearningConflict
from inspinia.learning.revisions import LearningError
from inspinia.learning.revisions import LearningUnavailable
from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueSubject
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def context(settings):
    settings.LEARNING_MODULE_ENABLED = True
    settings.LEARNING_CONTRIBUTIONS_ENABLED = True
    settings.LEARNING_PUBLICATION_ENABLED = True
    settings.LEARNING_AGREEMENT_APPROVED = True
    settings.LEARNING_AGREEMENT_VERSION = "synthetic-rights-v1"
    author = UserFactory()
    publisher = UserFactory()
    settings.LEARNING_PUBLISHER_USER_ID = publisher.pk
    subject = CatalogueSubject.objects.create(id="domain-test", name="Domain test")
    area = CatalogueArea.objects.create(
        id="Domain test:inequalities",
        slug="inequalities",
        name="Test inequalities",
        subject=subject,
    )
    concept = CatalogueConcept.objects.create(id="domain-amgm", name="Domain AM-GM")
    return author, publisher, area, concept


def draft_for(context, **kwargs):
    author, _publisher, area, concept = context
    return create_draft(
        user=author,
        area_id=area.pk,
        title="AM-GM",
        source="For $a,b>0$, $a+b\\geq2\\sqrt{ab}$.",
        metadata={"concepts": [{"id": concept.pk, "role": "primary"}]},
        **kwargs,
    )


@pytest.mark.parametrize("field", ["title", "summary", "metadata"])
def test_unsafe_tex_is_rejected_in_all_displayed_document_text(context, field):
    author, _publisher, area, _concept = context
    values = {"title": "A safe title", "summary": "", "metadata": {}}
    values[field] = {"objectives": [r"$\require{html}$"]} if field == "metadata" else r"$\require{html}$"
    with pytest.raises(ValidationError):
        create_draft(user=author, area_id=area.pk, source="A safe explanation.", **values)


def test_metadata_is_bounded_json_without_nonfinite_values(context):
    author, _publisher, area, _concept = context
    deeply_nested = []
    for _ in range(30):
        deeply_nested = [deeply_nested]
    for invalid in (float("nan"), deeply_nested):
        with pytest.raises(LearningError):
            create_draft(
                user=author, area_id=area.pk, title="Metadata check", source="A safe explanation.",
                metadata={"content_pack": {"invalid": invalid}},
            )


def submitted(context, draft=None, **kwargs):
    author, _publisher, _area, _concept = context
    return submit_draft(
        draft=draft or draft_for(context),
        user=author,
        agreement_version="synthetic-rights-v1",
        rights_confirmed=True,
        declaration={"editorial_changes_allowed": True},
        **kwargs,
    )


def published(context, *, public=True):
    proposal = submitted(context)
    publisher = context[1]
    proposal = review_proposal(proposal=proposal, user=publisher, action="approve", context=review_context(proposal))
    return publish_proposal(
        proposal=proposal,
        user=publisher,
        context=review_context(proposal),
        expected_version=0,
        public=public,
    )


def test_authoring_review_and_publication_are_distinct(context):
    author, publisher, _area, _concept = context
    draft = draft_for(context)
    assert not ContentRevision.objects.exists()
    assert not visible_publications(user=author).exists()
    proposal = submitted(context, draft)
    assert proposal.status == ContributionProposal.Status.SUBMITTED
    assert proposal.revision.concept_links.count() == 1
    assert not visible_publications(public=True).exists()
    review_proposal(proposal=proposal, user=publisher, action="approve", context=review_context(proposal))
    proposal.refresh_from_db()
    assert not visible_publications(public=True).exists()
    publication = publish_proposal(
        proposal=proposal,
        user=publisher,
        context=review_context(proposal),
        expected_version=0,
        public=True,
    )
    assert publication.revision_id == proposal.revision_id
    assert visible_publications(user=author).get().revision_id == visible_publications(public=True).get().revision_id
    assert publication.announcement_disposition == "excluded"


@pytest.mark.parametrize(
    ("role", "superuser"),
    [("normal", False), ("trainer", False), ("admin", False), ("admin", True)],
)
def test_roles_do_not_grant_publisher_authority(context, role, superuser):
    user = UserFactory(role=role, is_superuser=superuser)
    assert can_contribute(user)
    assert not is_publisher(user)
    proposal = submitted(context)
    with pytest.raises(PermissionDenied):
        review_proposal(proposal=proposal, user=user, action="approve", context=review_context(proposal))


def test_missing_identity_and_switches_fail_closed(context, settings):
    author, publisher, *_rest = context
    settings.LEARNING_PUBLISHER_USER_ID = None
    assert not is_publisher(publisher)
    settings.LEARNING_CONTRIBUTIONS_ENABLED = False
    with pytest.raises(PermissionDenied):
        create_draft(user=author, kind="standalone")


def test_other_author_cannot_save_or_checkpoint(context):
    draft = draft_for(context)
    other = UserFactory()
    with pytest.raises(PermissionDenied):
        checkpoint_draft(draft=draft, user=other)
    with pytest.raises(PermissionDenied):
        editor_context(draft, other)


def test_stale_tabs_keep_saved_source_and_receipts(context):
    author = context[0]
    draft = draft_for(context)
    token = editor_context(draft, author)
    original = draft.body_source
    operation = uuid.uuid4()
    current = save_draft(
        draft=draft,
        user=author,
        title=draft.title,
        summary="",
        source=original + "\nA proof.",
        metadata=draft.metadata,
        base_version=0,
        context=token,
        operation_id=operation,
    )
    replay = save_draft(
        draft=draft,
        user=author,
        title=draft.title,
        summary="",
        source=original + "\nA proof.",
        metadata=draft.metadata,
        base_version=0,
        context=token,
        operation_id=operation,
    )
    assert replay.edit_version == current.edit_version == 1
    with pytest.raises(LearningConflict):
        save_draft(
            draft=draft,
            user=author,
            title=draft.title,
            summary="",
            source="Stale replacement",
            metadata=draft.metadata,
            base_version=0,
            context=token,
        )
    draft.refresh_from_db()
    assert draft.body_source == original + "\nA proof."
    assert not ContentRevision.objects.exists()


def test_checkpoint_is_immutable_and_does_not_publish(context):
    draft = draft_for(context)
    revision = checkpoint_draft(draft=draft, user=context[0])
    assert checkpoint_draft(draft=draft, user=context[0]).pk == revision.pk
    with pytest.raises(ValidationError):
        ContentRevision.objects.filter(pk=revision.pk).update(title="Tampered")
    revision.title = "Tampered"
    with pytest.raises(ValidationError):
        revision.save()
    assert not visible_publications(public=True).exists()


def test_permission_is_explicit_and_revision_bound(context, settings):
    draft = draft_for(context)
    with pytest.raises(LearningError):
        submit_draft(draft=draft, user=context[0], agreement_version="synthetic-rights-v1")
    assert not ContributionProposal.objects.exists()
    settings.LEARNING_AGREEMENT_APPROVED = False
    with pytest.raises(LearningUnavailable):
        submitted(context, draft)
    assert not ContentRevision.objects.exists()


def test_draft_changes_supersede_pending_review(context):
    proposal = submitted(context)
    draft = ContentDraft.objects.get(document=proposal.document, author=context[0])
    save_draft(
        draft=draft,
        user=context[0],
        title=draft.title,
        summary="",
        source=draft.body_source + "\nNew explanation.",
        metadata=draft.metadata,
        base_version=draft.edit_version,
        context=editor_context(draft, context[0]),
    )
    proposal.refresh_from_db()
    assert proposal.status == ContributionProposal.Status.SUPERSEDED
    assert "New explanation" not in proposal.revision.body_source


def test_publication_requires_fresh_approval_and_cannot_silently_overwrite(context):
    proposal = submitted(context)
    with pytest.raises(LearningError):
        publish_proposal(proposal=proposal, user=context[1], context=review_context(proposal), expected_version=0)
    review_proposal(proposal=proposal, user=context[1], action="approve", context=review_context(proposal))
    proposal.refresh_from_db()
    operation = uuid.uuid4()
    token = review_context(proposal)
    first = publish_proposal(
        proposal=proposal,
        user=context[1],
        context=token,
        expected_version=0,
        public=True,
        operation_id=operation,
    )
    replay = publish_proposal(
        proposal=proposal,
        user=context[1],
        context=token,
        expected_version=0,
        public=True,
        operation_id=operation,
    )
    assert first.version == replay.version == 1
    assert ContentAction.objects.filter(action="publish").count() == 1
    with pytest.raises(LearningConflict):
        publish_proposal(proposal=proposal, user=context[1], context=token, expected_version=0, public=True)


def test_withdrawal_preserves_history_but_revokes_current_visibility(context):
    publication = published(context)
    withdraw_document(document=publication.document, user=context[1], expected_version=1, public_only=True)
    assert not visible_publications(public=True).exists()
    assert visible_publications(user=context[0]).exists()
    withdraw_document(document=publication.document, user=context[1], expected_version=2)
    assert not visible_publications(user=context[0]).exists()
    assert ContentRevision.objects.count() == 1
    # Another learner must not acquire withdrawn content merely by guessing its identity.
    other = UserFactory()
    branch = create_draft(
        user=other,
        document=publication.document,
        title="Own replacement",
        source="Private new writing",
    )
    assert branch.base_revision_id is None
    assert branch.body_source == "Private new writing"


def test_canonical_landings_require_identity_and_share_document(context):
    author, _publisher, area, _concept = context
    with pytest.raises(LearningError):
        create_draft(user=author, kind="overview")
    first = create_draft(user=author, kind="overview", area_id=area.pk)
    second = create_draft(user=UserFactory(), kind="overview", area_id=area.pk)
    assert first.document_id == second.document_id
    assert first.pk != second.pk
    with transaction.atomic(), pytest.raises(IntegrityError):
        ContentDocument.objects.create(kind="concept")


def test_reconciliation_requires_current_version_and_preserves_text(context):
    publication = published(context)
    draft = ContentDraft.objects.get(document=publication.document, author=context[0])
    original = draft.body_source
    with pytest.raises(LearningConflict):
        submitted(context, draft)
    current = rebase_draft(
        draft=draft,
        user=context[0],
        base_version=0,
        publication_version=1,
        context=editor_context(draft, context[0]),
        confirmed=True,
    )
    assert current.body_source == original
    assert current.base_publication_version == 1
    assert submitted(context, current).base_publication_version == 1


def test_changing_credit_requires_a_new_revision_permission(context):
    proposal = submitted(context)
    draft = ContentDraft.objects.get(document=proposal.document, author=context[0])
    changed = submitted(context, draft, public_credit="Chosen contributor credit")
    assert changed.revision_id != proposal.revision_id
    assert changed.revision.body_source == proposal.revision.body_source
    assert changed.revision.permission.public_credit == "Chosen contributor credit"
    assert proposal.revision.permission.public_credit == ""


def test_hidden_publication_cannot_be_rebased_into_another_authors_draft(context):
    publication = published(context)
    other = UserFactory()
    draft = create_draft(user=other, document=publication.document)
    withdraw_document(document=publication.document, user=context[1], expected_version=1)
    with pytest.raises(LearningConflict):
        rebase_draft(
            draft=draft,
            user=other,
            base_version=0,
            publication_version=2,
            context=editor_context(draft, other),
            confirmed=True,
        )
    draft.refresh_from_db()
    assert draft.base_publication_version == 1


def test_canonical_redirects_do_not_create_duplicate_landings(context):
    author, _publisher, _area, concept = context
    alias = CatalogueConcept.objects.create(id="domain-amgm-alias", name="Old caption", redirect=concept)
    first = create_draft(user=author, kind="concept", concept_id=alias.pk)
    second = create_draft(user=UserFactory(), kind="concept", concept_id=concept.pk)
    assert first.document_id == second.document_id
    assert first.document.canonical_concept_id == concept.pk


def test_classification_suggestion_needs_no_published_note_and_does_not_edit_graph(context):
    from django.core.cache import cache

    from inspinia.learning.issues import create_target_issue
    from inspinia.learning.issues import target_issue_context
    from inspinia.learning.models import ContentIssue

    cache.clear()
    author, _publisher, _area, concept = context
    token = target_issue_context(user=author, kind="classification", target_key=concept.pk)
    issue = create_target_issue(
        user=author,
        kind="classification",
        target_key=concept.pk,
        description="Please review the pedagogical classification.",
        token=token,
    )
    replay = create_target_issue(
        user=author,
        kind="classification",
        target_key=concept.pk,
        description="Please review the pedagogical classification.",
        token=token,
    )
    assert issue.pk == replay.pk
    assert issue.document_id is None
    assert issue.revision_id is None
    assert ContentIssue.objects.count() == 1
    concept.refresh_from_db()
    assert not concept.redirect_id
    assert not ContentDocument.objects.exists()


def test_historical_restoration_retains_original_permission_and_requires_new_review(context):
    author, publisher, _area, _concept = context
    publication = published(context)
    original = publication.revision
    other_author = UserFactory()
    draft = create_draft(user=other_author, document=publication.document)
    draft = save_draft(
        draft=draft,
        user=other_author,
        title="Improved explanation",
        summary="",
        source="For positive real numbers, the arithmetic mean is at least the geometric mean.",
        metadata=draft.metadata,
        base_version=draft.edit_version,
        context=editor_context(draft, other_author),
    )
    proposal = submit_draft(
        draft=draft,
        user=other_author,
        agreement_version="synthetic-rights-v1",
        rights_confirmed=True,
        declaration={"editorial_changes_allowed": True},
    )
    review_proposal(proposal=proposal, user=publisher, action="approve", context=review_context(proposal))
    publication = publish_proposal(
        proposal=proposal,
        user=publisher,
        context=review_context(proposal),
        expected_version=1,
        public=True,
    )
    operation = uuid.uuid4()
    restoration = propose_restoration(
        user=publisher,
        document=publication.document,
        revision_id=original.pk,
        expected_version=2,
        operation_id=operation,
    )
    assert restoration.status == ContributionProposal.Status.SUBMITTED
    assert restoration.revision_id == original.pk
    assert restoration.revision.permission.contributor_id == author.pk
    publication.refresh_from_db()
    assert publication.revision_id == proposal.revision_id
    replay = propose_restoration(
        user=publisher,
        document=publication.document,
        revision_id=original.pk,
        expected_version=2,
        operation_id=operation,
    )
    assert replay.pk == restoration.pk
    review_proposal(proposal=restoration, user=publisher, action="approve", context=review_context(restoration))
    restored = publish_proposal(
        proposal=restoration,
        user=publisher,
        context=review_context(restoration),
        expected_version=2,
        public=True,
    )
    assert restored.revision_id == original.pk
    assert restored.version == publication.version + 1
    assert list(ContentRevision.objects.order_by("sequence").values_list("pk", flat=True)) == [
        original.pk,
        proposal.revision_id,
    ]


def test_restoration_never_discloses_unsubmitted_checkpoints(context):
    author, publisher, _area, _concept = context
    draft = draft_for(context)
    private_revision = checkpoint_draft(draft=draft, user=author)
    assert not restoration_candidates(user=publisher, document=draft.document).exists()
    with pytest.raises(LearningError, match="Only submitted history"):
        propose_restoration(
            user=publisher,
            document=draft.document,
            revision_id=private_revision.pk,
            expected_version=0,
        )
    with pytest.raises(PermissionDenied):
        restoration_candidates(user=author, document=draft.document)


def test_a_fresh_model_instance_cannot_overwrite_an_immutable_checkpoint(context):
    draft = draft_for(context)
    revision = checkpoint_draft(draft=draft, user=context[0])
    replacement = ContentRevision(
        id=revision.pk, document=revision.document, author=context[0], sequence=revision.sequence,
        title="Substituted content", body_source="Substituted proof", source_digest="0" * 64,
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        replacement.save()
    revision.refresh_from_db()
    assert revision.body_source == draft.body_source


def test_closed_contribution_gate_also_closes_anonymous_error_intake(context, settings):
    from django.contrib.auth.models import AnonymousUser

    from inspinia.learning.issues import create_issue
    from inspinia.learning.issues import issue_context

    publication = published(context)
    token = issue_context(publication.document, AnonymousUser())
    settings.LEARNING_CONTRIBUTIONS_ENABLED = False
    with pytest.raises(LearningUnavailable, match="intake is currently closed"):
        create_issue(
            user=AnonymousUser(), document=publication.document, token=token,
            description="Synthetic report", source_identity="synthetic",
        )


def test_archiving_releases_a_slot_without_losing_source_publication_or_history(context):
    from inspinia.learning.drafts import DRAFT_LIMIT

    author, _publisher, area, _concept = context
    publication = published(context)
    original = ContentDraft.objects.get(document=publication.document, author=author)
    original_source = original.body_source
    for index in range(DRAFT_LIMIT - 1):
        create_draft(
            user=author, area_id=area.pk, title=f"Another note {index}", source="Retained private explanation.",
        )
    with pytest.raises(LearningError, match="25 active drafts"):
        create_draft(user=author, area_id=area.pk, title="Next area", source="Another substantive explanation.")
    archived = archive_draft(draft=original, user=author, base_version=original.edit_version)
    assert archived.is_archived
    assert archived.body_source == original_source
    assert archived.document.revisions.filter(pk=publication.revision_id).exists()
    publication.refresh_from_db()
    assert publication.public_visible
    following = create_draft(
        user=author, area_id=area.pk, title="Next area", source="Another substantive explanation.",
    )
    with pytest.raises(LearningError, match="before reopening"):
        archive_draft(draft=archived, user=author, archived=False, base_version=archived.edit_version)
    archived.refresh_from_db()
    assert archived.is_archived
    archive_draft(draft=following, user=author, base_version=following.edit_version)
    reopened = archive_draft(draft=archived, user=author, archived=False, base_version=archived.edit_version)
    assert not reopened.is_archived
    assert reopened.body_source == original_source
    assert ContentDraft.objects.filter(author=author, is_archived=False).count() == DRAFT_LIMIT


def test_archived_drafts_require_owner_reopen_before_edit_or_checkpoint(context):
    author, publisher, _area, _concept = context
    draft = draft_for(context)
    token = editor_context(draft, author)
    archived = archive_draft(draft=draft, user=author, base_version=draft.edit_version)
    for actor in (publisher, UserFactory()):
        with pytest.raises(PermissionDenied):
            archive_draft(
                draft=archived, user=actor, archived=False, base_version=archived.edit_version,
            )
    with pytest.raises(PermissionDenied, match="Reopen"):
        checkpoint_draft(draft=archived, user=author)
    with pytest.raises(PermissionDenied, match="Reopen"):
        save_draft(
            draft=archived, user=author, source="Should not replace retained writing.",
            title=archived.title, summary="", metadata=archived.metadata,
            base_version=archived.edit_version, context=token,
        )
    with pytest.raises(LearningConflict):
        archive_draft(draft=archived, user=author, archived=False, base_version=draft.edit_version)
    archived.refresh_from_db()
    assert archived.is_archived
    assert archived.body_source == draft.body_source


def test_checkpoint_receipt_reconciles_after_later_private_edits(context):
    author = context[0]
    draft = draft_for(context)
    operation = uuid.uuid4()
    revision = checkpoint_draft(draft=draft, user=author, operation_id=operation, base_version=0)
    changed = save_draft(
        draft=draft, user=author, title=draft.title, summary="", source="Later private explanation.",
        metadata=draft.metadata, base_version=0, context=editor_context(draft, author),
    )
    replay = checkpoint_draft(draft=changed, user=author, operation_id=operation, base_version=0)
    assert replay.pk == revision.pk
    changed.refresh_from_db()
    assert changed.body_source == "Later private explanation."
    assert changed.document.revisions.count() == 1


def test_publication_receipt_reconciles_without_repeating_storage_preflight(context, monkeypatch):
    publisher = context[1]
    proposal = submitted(context)
    review_proposal(proposal=proposal, user=publisher, action="approve", context=review_context(proposal))
    token, operation = review_context(proposal), uuid.uuid4()
    publication = publish_proposal(
        proposal=proposal, user=publisher, context=token, expected_version=0, public=True, operation_id=operation,
    )
    monkeypatch.setattr("inspinia.learning.assets.asset_files_available", lambda _revision: False)
    replay = publish_proposal(
        proposal=proposal, user=publisher, context=token, expected_version=0, public=True, operation_id=operation,
    )
    assert replay.version == publication.version
    assert replay.revision_id == publication.revision_id
