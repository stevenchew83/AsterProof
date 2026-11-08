"""Legacy ancestor transitions retain history and cannot race lecture distribution."""

import pytest
from django.core.exceptions import ValidationError

from inspinia.learning.drafts import create_draft
from inspinia.learning.legacy import link_legacy
from inspinia.learning.legacy import source_fingerprint
from inspinia.learning.models import LegacyContentLink
from inspinia.learning.revisions import LearningConflict
from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueSubject
from inspinia.users.tests.factories import UserFactory
from inspinia.website.models import LibraryArea
from inspinia.website.models import LibraryConcept
from inspinia.website.models import LibraryLecture
from inspinia.website.models import NewsletterCampaign
from inspinia.website.models import NewsletterLectureNotice

pytestmark = pytest.mark.django_db


@pytest.fixture
def legacy_context(settings):
    settings.LEARNING_MODULE_ENABLED = True
    settings.LEARNING_CONTRIBUTIONS_ENABLED = True
    publisher = UserFactory()
    settings.LEARNING_PUBLISHER_USER_ID = publisher.pk
    subject = CatalogueSubject.objects.create(id="legacy-domain", name="Synthetic legacy subject")
    canonical = CatalogueArea.objects.create(
        id="legacy-domain:inequalities", subject=subject, name="Inequalities", slug="inequalities",
    )
    draft = create_draft(user=publisher, area_id=canonical.pk, title="Shared note", source="Retained shared proof.")
    area = LibraryArea.objects.create(subject="algebra", title="Historical area", slug="historical", is_published=True)
    concept = LibraryConcept.objects.create(
        area=area, title="Historical concept", slug="historical", is_published=True,
    )
    lecture = LibraryLecture.objects.create(
        concept=concept, title="Historical lecture", slug="historical", is_published=True,
    )
    return publisher, draft.document, {"area": area, "concept": concept, "lecture": lecture}


@pytest.mark.parametrize("source_field", ["area", "concept", "lecture"])
@pytest.mark.parametrize("campaign_status", [NewsletterCampaign.Status.SENDING, "unknown"])
def test_every_typed_transition_blocks_active_or_unknown_descendant_campaigns(
    legacy_context, source_field, campaign_status,
):
    publisher, document, sources = legacy_context
    campaign = NewsletterCampaign.objects.create(
        subject="Synthetic existing campaign", body_markdown="Frozen historical message.", status=campaign_status,
    )
    notice = NewsletterLectureNotice.objects.create(
        lecture=sources["lecture"], title="Frozen lecture title", public_url="/library/historical/",
        status=NewsletterLectureNotice.Status.INCLUDED, campaign=campaign,
    )
    source = sources[source_field]
    with pytest.raises(LearningConflict, match="existing lecture campaigns"):
        link_legacy(
            user=publisher, document=document, source=source,
            expected_fingerprint=source_fingerprint(source),
        )
    assert not LegacyContentLink.objects.exists()
    campaign.refresh_from_db()
    notice.refresh_from_db()
    assert campaign.status == campaign_status
    assert notice.status == NewsletterLectureNotice.Status.INCLUDED


@pytest.mark.parametrize("source_field", ["area", "concept", "lecture"])
def test_completed_history_is_retained_and_pending_notices_are_excluded(legacy_context, source_field):
    publisher, document, sources = legacy_context
    pending = NewsletterLectureNotice.objects.create(
        lecture=sources["lecture"], title="Pending historical lecture", public_url="/library/historical/",
        status=NewsletterLectureNotice.Status.PENDING,
    )
    source = sources[source_field]
    link = link_legacy(
        user=publisher, document=document, source=source, expected_fingerprint=source_fingerprint(source),
    )
    pending.refresh_from_db()
    assert pending.status == NewsletterLectureNotice.Status.EXCLUDED
    assert link.announcement_excluded
    with pytest.raises(ValidationError):
        LegacyContentLink.objects.filter(pk=link.pk).delete()


def test_ancestor_mapping_does_not_rewrite_completed_included_history(legacy_context):
    publisher, document, sources = legacy_context
    campaign = NewsletterCampaign.objects.create(
        subject="Completed historical campaign", body_markdown="Frozen historical message.",
        status=NewsletterCampaign.Status.COMPLETED,
    )
    notice = NewsletterLectureNotice.objects.create(
        lecture=sources["lecture"], title="Original frozen title", public_url="/library/historical/",
        status=NewsletterLectureNotice.Status.INCLUDED, campaign=campaign,
    )
    link_legacy(
        user=publisher, document=document, source=sources["area"],
        expected_fingerprint=source_fingerprint(sources["area"]),
    )
    notice.refresh_from_db()
    campaign.refresh_from_db()
    assert notice.title == "Original frozen title"
    assert notice.status == NewsletterLectureNotice.Status.INCLUDED
    assert campaign.body_markdown == "Frozen historical message."
