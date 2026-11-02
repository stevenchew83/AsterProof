"""Shared-content mappings never opt into legacy discovery or queued delivery."""

from datetime import time
from datetime import timedelta

import pytest
from django.core import mail
from django.core.cache import cache
from django.utils import timezone

from inspinia.learning.models import ContentDocument
from inspinia.learning.models import LegacyContentLink
from inspinia.users.tests.factories import UserFactory
from inspinia.website import automation
from inspinia.website import campaigns
from inspinia.website.models import LibraryArea
from inspinia.website.models import LibraryConcept
from inspinia.website.models import LibraryLecture
from inspinia.website.models import NewsletterAutomation
from inspinia.website.models import NewsletterCampaign
from inspinia.website.models import NewsletterDelivery
from inspinia.website.models import NewsletterLectureNotice
from inspinia.website.models import NewsletterSubscriber

pytestmark = pytest.mark.django_db


@pytest.fixture
def enabled_digest(settings, mailoutbox):
    settings.NEWSLETTER_BACKGROUND_ENABLED = True
    cache.clear()
    editor = UserFactory()
    intro = NewsletterCampaign.objects.create(
        subject="Reviewed legacy digest", body_markdown="An existing introduction.", created_by=editor,
    )
    # Synthetic local evidence; these tests never hand an email to an adapter.
    NewsletterDelivery.objects.create(
        campaign=intro,
        kind="test",
        campaign_version=intro.version,
        status="accepted",
        recipient_email=editor.email,
        subject=intro.subject,
    )
    NewsletterSubscriber.objects.create(
        email="synthetic-reader@example.invalid",
        status="confirmed",
        requested_at=timezone.now(),
        confirmed_at=timezone.now(),
    )
    automation.configure_lectures(enabled=True, template=intro, digest_time=time(9))
    NewsletterAutomation.objects.filter(pk=1).update(next_digest_at=timezone.now() - timedelta(seconds=1))
    yield intro
    assert not mail.outbox
    cache.clear()


def lecture_hierarchy(prefix):
    area = LibraryArea.objects.create(title=prefix + " area", subject="algebra", is_published=True)
    concept = LibraryConcept.objects.create(title=prefix + " concept", area=area, is_published=True)
    lecture = LibraryLecture.objects.create(title=prefix + " lecture", concept=concept, is_published=True)
    return {"area": area, "concept": concept, "lecture": lecture}


def map_source(rows, kind, *, cutover=False, excluded=True):
    return LegacyContentLink.objects.create(
        document=ContentDocument.objects.create(),
        **{kind: rows[kind]},
        source_fingerprint="a" * 64,
        is_cutover=cutover,
        announcement_excluded=excluded,
    )


def due():
    NewsletterAutomation.objects.filter(pk=1).update(next_digest_at=timezone.now() - timedelta(seconds=1))


@pytest.mark.parametrize("module_enabled", [True, False])
@pytest.mark.parametrize("kind", ["lecture", "concept", "area"])
@pytest.mark.parametrize("cutover", [False, True])
def test_mapped_sources_create_no_notice_or_campaign_but_unrelated_legacy_remains_eligible(
    enabled_digest,
    settings,
    module_enabled,
    kind,
    cutover,
):
    settings.LEARNING_MODULE_ENABLED = module_enabled
    mapped = lecture_hierarchy("Mapped")
    map_source(mapped, kind, cutover=cutover)
    assert not automation.public_lectures().filter(pk=mapped["lecture"].pk).exists()
    campaigns_before = NewsletterCampaign.objects.count()
    assert automation.process_queue(maximum=0) == {"state": "finished", "processed": 0}
    assert not NewsletterLectureNotice.objects.exists()
    assert NewsletterCampaign.objects.count() == campaigns_before
    assert not NewsletterDelivery.objects.filter(kind="campaign").exists()
    unrelated = lecture_hierarchy("Unrelated")
    due()
    automation.process_queue(maximum=0)
    notice = NewsletterLectureNotice.objects.get()
    assert notice.lecture_id == unrelated["lecture"].pk
    assert notice.status == "included"
    assert NewsletterCampaign.objects.count() == campaigns_before + 1
    assert not NewsletterLectureNotice.objects.filter(lecture=mapped["lecture"]).exists()
    enabled_digest.refresh_from_db()
    assert enabled_digest.body_markdown == "An existing introduction."
    assert enabled_digest.status == "draft"


@pytest.mark.parametrize("module_enabled", [True, False])
@pytest.mark.parametrize("kind", ["lecture", "concept", "area"])
def test_existing_pending_notice_is_excluded_before_digest_due(enabled_digest, settings, module_enabled, kind):
    settings.LEARNING_MODULE_ENABLED = module_enabled
    rows = lecture_hierarchy("Pending")
    NewsletterAutomation.objects.filter(pk=1).update(next_digest_at=timezone.now() + timedelta(hours=1))
    automation.process_queue(maximum=0)
    notice = NewsletterLectureNotice.objects.get(lecture=rows["lecture"])
    assert notice.status == "pending"
    map_source(rows, kind)
    before = NewsletterCampaign.objects.count()
    automation.process_queue(maximum=0)
    notice.refresh_from_db()
    assert notice.status == "excluded"
    assert notice.campaign_id is None
    assert NewsletterCampaign.objects.count() == before
    assert NewsletterAutomation.objects.get(pk=1).lecture_enabled


@pytest.mark.parametrize("module_enabled", [True, False])
@pytest.mark.parametrize("kind", ["lecture", "concept", "area"])
def test_queued_digest_rechecks_mapping_without_sending_or_rewriting_history(
    enabled_digest,
    settings,
    module_enabled,
    kind,
):
    settings.LEARNING_MODULE_ENABLED = module_enabled
    rows = lecture_hierarchy("Queued")
    automation.process_queue(maximum=0)
    notice = NewsletterLectureNotice.objects.get(lecture=rows["lecture"])
    campaign = notice.campaign
    original_body = campaign.body_markdown
    map_source(rows, kind, cutover=True)
    assert not campaigns._content_still_public(campaign)  # noqa: SLF001 - Delivery preflight boundary.
    result = campaigns.send_next(None, campaign.pk)
    assert result.status == "skipped"
    notice.refresh_from_db()
    campaign.refresh_from_db()
    assert notice.status == "included"
    assert notice.campaign_id == campaign.pk
    assert campaign.body_markdown == original_body
    assert not mail.outbox


def test_absent_learning_schema_preserves_legacy_discovery(enabled_digest, monkeypatch):
    from inspinia.website import learning

    rows = lecture_hierarchy("Before schema")
    monkeypatch.setattr(learning, "schema_ready", lambda: False)
    assert automation.public_lectures().filter(pk=rows["lecture"].pk).exists()
    automation.process_queue(maximum=0)
    assert NewsletterLectureNotice.objects.get(lecture=rows["lecture"]).status == "included"


def test_cutover_is_excluded_even_if_an_old_mapping_lacks_announcement_flag(enabled_digest):
    rows = lecture_hierarchy("Cutover")
    map_source(rows, "lecture", cutover=True, excluded=False)
    automation.process_queue(maximum=0)
    assert not NewsletterLectureNotice.objects.exists()
