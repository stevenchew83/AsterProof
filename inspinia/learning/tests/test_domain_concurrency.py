"""Real row-lock acceptance; SQLite deliberately cannot certify these races."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections
from django.db import connection

from inspinia.learning.drafts import create_draft
from inspinia.learning.drafts import editor_context
from inspinia.learning.drafts import save_draft
from inspinia.learning.models import ContentDraft
from inspinia.learning.models import ContentPublication
from inspinia.learning.publication import publish_proposal
from inspinia.learning.publication import review_context
from inspinia.learning.publication import review_proposal
from inspinia.learning.publication import submit_draft
from inspinia.learning.revisions import LearningConflict
from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueState
from inspinia.pages.catalogue_models import CatalogueSubject
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def concurrent_context(settings):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks are required for learning concurrency acceptance.")
    settings.LEARNING_MODULE_ENABLED = True
    settings.LEARNING_CONTRIBUTIONS_ENABLED = True
    settings.LEARNING_PUBLICATION_ENABLED = True
    settings.LEARNING_AGREEMENT_APPROVED = True
    settings.LEARNING_AGREEMENT_VERSION = "synthetic-concurrency-v1"
    author, publisher = UserFactory(), UserFactory()
    settings.LEARNING_PUBLISHER_USER_ID = publisher.pk
    subject = CatalogueSubject.objects.create(id="concurrent-learning", name="Concurrency fixture")
    area = CatalogueArea.objects.create(
        id="concurrent-learning:inequalities", subject=subject, name="Synthetic inequalities", slug="inequalities",
    )
    CatalogueState.objects.get_or_create(pk=1, defaults={"catalogue_version": "synthetic-concurrency"})
    draft = create_draft(user=author, area_id=area.pk, title="Synthetic inequality", source="Initial explanation.")
    return author, publisher, draft


def _race(first, second):
    barrier = Barrier(2, timeout=10)

    def run(action):
        close_old_connections()
        try:
            barrier.wait()
            try:
                return "saved", action()
            except LearningConflict:
                return "conflict", None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, action) for action in (first, second)]
        return [future.result(timeout=20) for future in futures]


def test_same_draft_autosaves_never_silently_replace_each_other(concurrent_context):
    author, _publisher, draft = concurrent_context
    context = editor_context(draft, author)

    def save(source):
        return save_draft(
            draft=ContentDraft.objects.get(pk=draft.pk), user=author, title=draft.title,
            source=source, summary="", metadata={}, base_version=0, context=context, operation_id=uuid.uuid4(),
        ).body_source

    results = _race(lambda: save("First author's retained writing."), lambda: save("Second tab's retained writing."))
    assert sorted(status for status, _source in results) == ["conflict", "saved"]
    draft.refresh_from_db()
    assert draft.edit_version == 1
    assert draft.body_source == next(source for status, source in results if status == "saved")
    assert not draft.document.revisions.exists()


def test_competing_approved_publications_serialize_on_document(concurrent_context):
    author, publisher, draft = concurrent_context
    second_author = UserFactory()
    other = create_draft(
        user=second_author, document=draft.document, title="Second original proof", source="Different proof.",
    )
    proposals = []
    for contributor, candidate in ((author, draft), (second_author, other)):
        proposal = submit_draft(
            draft=candidate, user=contributor, agreement_version="synthetic-concurrency-v1",
            rights_confirmed=True,
        )
        proposals.append(review_proposal(
            proposal=proposal, user=publisher, action="approve", context=review_context(proposal),
        ))
    contexts = [review_context(proposal) for proposal in proposals]

    def publish(index):
        return publish_proposal(
            proposal=proposals[index], user=publisher, context=contexts[index],
            expected_version=0, public=True, operation_id=uuid.uuid4(),
        ).revision_id

    results = _race(lambda: publish(0), lambda: publish(1))
    assert sorted(status for status, _revision in results) == ["conflict", "saved"]
    publication = ContentPublication.objects.get(document=draft.document)
    assert publication.version == 1
    assert publication.public_visible
    assert publication.training_visible
    assert publication.revision_id == next(revision for status, revision in results if status == "saved")
    assert publication.document.actions.filter(action="publish").count() == 1
