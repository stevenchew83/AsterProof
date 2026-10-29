# ruff: noqa: PLR2004
"""Queue safety, lecture opt-in and reviewed Gmail bounce correlation."""

from datetime import time
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from inspinia.users.models import User
from inspinia.website import automation
from inspinia.website import bounces
from inspinia.website import campaigns
from inspinia.website.models import LibraryArea
from inspinia.website.models import LibraryConcept
from inspinia.website.models import LibraryLecture
from inspinia.website.models import NewsletterAutomation
from inspinia.website.models import NewsletterBounceReport
from inspinia.website.models import NewsletterCampaign
from inspinia.website.models import NewsletterDelivery
from inspinia.website.models import NewsletterLectureNotice
from inspinia.website.models import NewsletterSendingHold
from inspinia.website.models import NewsletterSubscriber

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_queue(settings, mailoutbox):
    settings.NEWSLETTER_BACKGROUND_ENABLED = True
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def editor():
    return User.objects.create(email="queue-admin@example.com", role=User.Role.ADMIN)


@pytest.fixture
def admin_request(editor):
    value = RequestFactory().get("/manage/newsletter/")
    value.user = editor
    return value


@pytest.fixture
def intro(admin_request):
    draft = NewsletterCampaign.objects.create(
        subject="New mathematical ideas",
        body_markdown="A new idea awaits.",
        created_by=admin_request.user,
    )
    campaigns.send_test(admin_request, draft.pk, draft.version)
    mail.outbox.clear()
    return draft


def subscribe(email="reader@example.com"):
    return NewsletterSubscriber.objects.create(
        email=email,
        status="confirmed",
        requested_at=timezone.now(),
        confirmed_at=timezone.now(),
    )


def dsn(delivery, *, action="failed", code="5.1.1", recipient=None, message_id=None):
    return f"""From: Mail Delivery Subsystem <mailer-daemon@example.invalid>
Message-ID: <report-{delivery.pk}-{action}-{code}@example.invalid>
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="report"

--report
Content-Type: text/plain

Private diagnostic text must never be stored or displayed.
--report
Content-Type: message/delivery-status

Reporting-MTA: dns; example.invalid

Final-Recipient: rfc822; {recipient or delivery.recipient_email}
Action: {action}
Status: {code}
Diagnostic-Code: smtp; 550 private diagnostic

--report
Content-Type: text/rfc822-headers

Message-ID: {message_id or f"<newsletter-{delivery.pk}@asterproof.com>"}
Subject: PRIVATE ORIGINAL BODY

--report--
""".encode()


def sent(intro):
    subscribe()
    campaigns.start_campaign(intro.pk, intro.created_by, intro.version)
    return campaigns.send_next(None, intro.pk)


def test_background_worker_sends_after_start_without_browser(admin_request, intro):
    subscribe()
    campaigns.start_campaign(intro.pk, admin_request.user, intro.version)
    assert not mail.outbox
    result = automation.process_queue()
    assert result == {"state": "finished", "processed": 1}
    assert len(mail.outbox) == 1
    assert automation.process_queue()["processed"] == 0
    assert len(mail.outbox) == 1


def test_worker_lease_blocks_second_worker_and_old_owner_cannot_clear_new_owner():
    token = automation.acquire_lease()
    assert token
    assert automation.acquire_lease() is None
    assert automation.process_queue()["state"] == "busy"
    NewsletterAutomation.objects.filter(pk=1).update(lease_until=timezone.now() - timedelta(seconds=1))
    newer = automation.acquire_lease()
    assert newer != token
    assert not automation.renew_lease(token)
    automation._release_lease(token, "worker_failed")  # noqa: SLF001
    assert NewsletterAutomation.objects.get().lease_token == newer


def test_worker_recovers_stale_claim_without_resending(admin_request, intro):
    subscribe()
    campaigns.start_campaign(intro.pk, admin_request.user, intro.version)
    delivery = intro.deliveries.get(kind="campaign")
    delivery.status, delivery.attempted_at = "sending", timezone.now() - timedelta(minutes=6)
    delivery.save()
    automation.process_queue()
    delivery.refresh_from_db()
    intro.refresh_from_db()
    assert delivery.status == "unknown"
    assert intro.status == "paused"
    assert not mail.outbox


def test_schedule_waits_and_snapshots_current_consent_at_due_time(admin_request, intro):
    old = subscribe()
    due = timezone.now() + timedelta(hours=1)
    campaigns.schedule_campaign(intro.pk, admin_request.user, intro.version, due)
    automation.process_queue()
    assert not intro.deliveries.filter(kind="campaign").exists()
    old.status = "unsubscribed"
    old.save()
    subscribe("new@example.com")
    NewsletterCampaign.objects.filter(pk=intro.pk).update(scheduled_at=timezone.now() - timedelta(seconds=1))
    automation.process_queue()
    assert [message.to for message in mail.outbox] == [["new@example.com"]]


def test_cancellation_unlocks_draft_and_requires_a_new_test(admin_request, intro):
    campaigns.schedule_campaign(intro.pk, admin_request.user, intro.version, timezone.now() + timedelta(hours=1))
    restored = campaigns.cancel_schedule(intro.pk)
    assert restored.is_editable
    assert restored.version == 2
    assert not campaigns.has_current_test(restored)
    with pytest.raises(ValidationError):
        campaigns.cancel_schedule(intro.pk)


def test_manual_pause_is_not_resumed_by_worker(admin_request, intro):
    subscribe()
    campaigns.start_campaign(intro.pk, admin_request.user, intro.version)
    campaigns.set_paused(intro.pk, paused=True)
    automation.process_queue()
    assert not mail.outbox
    campaigns.set_paused(intro.pk, paused=False)
    automation.process_queue()
    assert len(mail.outbox) == 1


def test_allowance_pause_resumes_only_queued_recipients(admin_request, intro, settings):
    subscribe()
    subscribe("second@example.com")
    campaigns.start_campaign(intro.pk, admin_request.user, intro.version)
    settings.NEWSLETTER_DAILY_EMAIL_LIMIT = 1
    cache.clear()
    automation.process_queue()
    intro.refresh_from_db()
    assert intro.status == "paused"
    assert intro.pause_reason == "allowance"
    assert len(mail.outbox) == 1
    cache.clear()
    NewsletterCampaign.objects.filter(pk=intro.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
    automation.process_queue()
    assert len(mail.outbox) == 2
    assert {message.to[0] for message in mail.outbox} == {"reader@example.com", "second@example.com"}


@pytest.fixture
def concept():
    area = LibraryArea.objects.create(title="Circles", subject="geometry", is_published=True)
    return LibraryConcept.objects.create(area=area, title="Angles", is_published=True)


def enable(intro):
    automation.configure_lectures(enabled=True, template=intro, digest_time=time(9))
    NewsletterAutomation.objects.filter(pk=1).update(next_digest_at=timezone.now() - timedelta(seconds=1))


def test_lecture_digest_excludes_existing_lectures_and_announces_new_once(intro, concept):
    subscribe()
    existing = LibraryLecture.objects.create(concept=concept, title="Existing lesson", is_published=True)
    enable(intro)
    fresh = LibraryLecture.objects.create(concept=concept, title="A new [idea]", is_published=True)
    automation.process_queue()
    assert existing.newsletter_notice.status == "baseline"
    assert fresh.newsletter_notice.status == "included"
    assert len(mail.outbox) == 1
    assert fresh.get_absolute_url() in mail.outbox[0].body
    assert existing.get_absolute_url() not in mail.outbox[0].body
    automation.process_queue()
    assert len(mail.outbox) == 1


def test_hidden_hierarchy_not_announced_and_intro_change_requires_reapproval(intro, concept):
    subscribe()
    enable(intro)
    concept.is_published = False
    concept.save()
    LibraryLecture.objects.create(concept=concept, title="Hidden lesson", is_published=True)
    automation.process_queue()
    assert not NewsletterLectureNotice.objects.exists()
    NewsletterCampaign.objects.filter(pk=intro.pk).update(version=2)
    automation.process_queue()
    policy = NewsletterAutomation.objects.get()
    assert not policy.lecture_enabled
    assert policy.lecture_error == "lecture_template_changed"
    automation.process_queue()
    policy.refresh_from_db()
    assert policy.lecture_error == "lecture_template_changed"
    assert not mail.outbox


def test_unpublishing_after_digest_queue_skips_delivery(intro, concept):
    subscribe()
    enable(intro)
    lecture = LibraryLecture.objects.create(concept=concept, title="Soon hidden", is_published=True)
    with patch("inspinia.website.automation.campaigns.send_next", side_effect=RuntimeError):
        assert automation.process_queue()["state"] == "failed"
    lecture.is_published = False
    lecture.save()
    automation.process_queue()
    assert not mail.outbox
    assert NewsletterDelivery.objects.get(kind="campaign").status == "skipped"


def test_bounce_review_is_read_only_apply_is_idempotent_and_preserves_consent(intro, editor):
    delivery = sent(intro)
    original = NewsletterSubscriber.objects.get()
    before = (original.status, original.confirmed_at, original.confirmation_nonce)
    review = bounces.preview_report(dsn(delivery))
    assert review["will_hold"]
    assert not NewsletterBounceReport.objects.exists()
    report, created = bounces.apply_report(review["token"], editor)
    assert created
    assert bounces.apply_report(review["token"], editor) == (report, False)
    original.refresh_from_db()
    delivery.refresh_from_db()
    assert (original.status, original.confirmed_at, original.confirmation_nonce) == before
    assert delivery.status == "accepted"
    assert delivery.delivery_result == "bounced"
    assert NewsletterSendingHold.objects.count() == 1
    assert not campaigns.confirmed_subscribers().exists()
    assert "private" not in str(list(NewsletterBounceReport.objects.values())).lower()


@pytest.mark.parametrize(("action", "code"), [("delayed", "4.2.2"), ("failed", "5.7.1"), ("failed", "4.4.7")])
def test_delay_and_policy_failure_do_not_place_address_holds(intro, editor, action, code):
    delivery = sent(intro)
    review = bounces.preview_report(dsn(delivery, action=action, code=code))
    assert not review["will_hold"]
    bounces.apply_report(review["token"], editor)
    assert not NewsletterSendingHold.objects.exists()


@pytest.mark.parametrize(("action", "code"), [("delivered", "2.0.0"), ("delayed", "5.1.1"), ("failed", "invalid")])
def test_unsupported_or_success_reports_are_not_imported(intro, action, code):
    delivery = sent(intro)
    with pytest.raises(ValidationError):
        bounces.preview_report(dsn(delivery, action=action, code=code))


def test_mismatched_recipient_or_message_id_rejected_and_token_cannot_be_forged(intro, editor):
    delivery = sent(intro)
    with pytest.raises(ValidationError):
        bounces.preview_report(dsn(delivery, recipient="someone-else@example.com"))
    with pytest.raises(ValidationError):
        bounces.preview_report(dsn(delivery, message_id="<unrelated@example.com>"))
    token = bounces.preview_report(dsn(delivery))["token"]
    with pytest.raises(ValidationError):
        bounces.apply_report(token + "changed", editor)


def test_sending_hold_is_rechecked_for_already_queued_recipient_and_can_be_cleared(intro, editor, admin_request):
    delivery = sent(intro)
    bounces.apply_report(bounces.preview_report(dsn(delivery))["token"], editor)
    hold = NewsletterSendingHold.objects.get()
    bounces.clear_hold(hold.pk, editor, "Administrator verified the address correction.")
    assert campaigns.confirmed_subscribers().exists()
    hold.refresh_from_db()
    assert hold.cleared_by == editor
    assert hold.clear_reason
    second = NewsletterCampaign.objects.create(subject="Second", body_markdown="Hello", created_by=editor)
    campaigns.send_test(admin_request, second.pk, 1)
    campaigns.start_campaign(second.pk, editor, 1)
    NewsletterSendingHold.objects.create(email=delivery.recipient_email, report=NewsletterBounceReport.objects.get())
    mail.outbox.clear()
    automation.process_queue()
    assert not mail.outbox
    assert second.deliveries.get(kind="campaign").status == "skipped"


def test_new_routes_require_admin_and_status_get_never_sends(client, editor, intro):
    for name in ("newsletter_automation", "newsletter_bounces", "newsletter_status"):
        kwargs = {"pk": intro.pk} if name == "newsletter_status" else {}
        url = reverse("website:" + name, kwargs=kwargs)
        assert client.get(url).status_code == 302
        client.force_login(editor)
        response = client.get(url)
        assert response.status_code == 200
        assert response["Cache-Control"] == "private, no-store"
        client.logout()
    assert not mail.outbox


def test_bounce_upload_review_and_apply_require_explicit_confirmation(client, editor, intro):
    delivery = sent(intro)
    client.force_login(editor)
    url = reverse("website:newsletter_bounces")
    response = client.post(url, {"report": SimpleUploadedFile("failure.eml", dsn(delivery))})
    assert response.status_code == 200
    assert response.context["review"]["will_hold"]
    assert b"Private diagnostic" not in response.content
    assert not NewsletterBounceReport.objects.exists()
    token = response.context["review"]["token"]
    client.post(url, {"action": "apply", "token": token})
    assert not NewsletterBounceReport.objects.exists()
    assert client.post(url, {"action": "apply", "token": token, "confirm": "on"}).status_code == 302
    assert NewsletterBounceReport.objects.count() == 1


def test_bounded_management_command_uses_test_mail_and_master_switch(intro, settings):
    subscribe()
    campaigns.start_campaign(intro.pk, intro.created_by, 1)
    output = StringIO()
    call_command("process_newsletters", max_messages=1, seconds=1, stdout=output)
    assert '"processed": 1' in output.getvalue()
    assert len(mail.outbox) == 1
    settings.NEWSLETTER_BACKGROUND_ENABLED = False
    with pytest.raises(ValidationError):
        automation.process_queue()


def test_disabled_lectures_pause_generated_queue_and_do_not_resume_it_on_reenable(intro, concept):
    subscribe()
    enable(intro)
    LibraryLecture.objects.create(concept=concept, title="New lecture", is_published=True)
    with patch("inspinia.website.automation.campaigns.send_next", side_effect=RuntimeError):
        automation.process_queue()
    digest = NewsletterCampaign.objects.get(lecture_template=intro)
    automation.configure_lectures(enabled=False, template=None, digest_time=time(9))
    automation.process_queue()
    digest.refresh_from_db()
    assert digest.status == "paused"
    assert digest.pause_reason == "automation_disabled"
    enable(intro)
    automation.process_queue()
    digest.refresh_from_db()
    assert digest.status == "paused"
    assert not mail.outbox


def test_latest_bounced_or_delayed_test_cannot_approve_a_schedule_or_automation(intro, editor):
    delivery = intro.deliveries.get(kind="test")
    review = bounces.preview_report(dsn(delivery, action="delayed", code="4.2.2"))
    bounces.apply_report(review["token"], editor)
    assert not campaigns.has_current_test(intro)
    with pytest.raises(ValidationError, match="test"):
        campaigns.schedule_campaign(intro.pk, editor, 1, timezone.now() + timedelta(hours=1))
    with pytest.raises(ValidationError, match="test"):
        enable(intro)


def test_expired_or_oversized_report_does_not_change_history(intro, editor):
    delivery = sent(intro)
    token = bounces.preview_report(dsn(delivery))["token"]
    with (
        patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 901),
        pytest.raises(ValidationError, match="expired"),
    ):
        bounces.apply_report(token, editor)
    with pytest.raises(ValidationError, match="1 MB"):
        bounces.preview_report(b"x" * (bounces.MAX_BYTES + 1))
    assert not NewsletterBounceReport.objects.exists()


def test_ambiguous_recipients_and_malformed_charset_are_validation_errors(intro):
    delivery = sent(intro)
    content = dsn(delivery)
    duplicate = content.replace(b"Action: failed", b"Final-Recipient: rfc822; other@example.com\nAction: failed")
    with pytest.raises(ValidationError, match="recipient"):
        bounces.preview_report(duplicate)
    malformed = content.replace(
        b"Content-Type: text/rfc822-headers", b"Content-Type: text/rfc822-headers; charset=not-a-real-charset",
    )
    with pytest.raises(ValidationError):
        bounces.preview_report(malformed)


def test_delay_cannot_downgrade_a_previous_bounce(intro, editor):
    delivery = sent(intro)
    bounces.apply_report(bounces.preview_report(dsn(delivery))["token"], editor)
    bounces.apply_report(bounces.preview_report(dsn(delivery, action="delayed", code="4.2.2"))["token"], editor)
    delivery.refresh_from_db()
    assert delivery.delivery_result == "bounced"
    assert NewsletterBounceReport.objects.count() == 2


def test_schedule_form_uses_malaysia_time_and_returns_validation_errors(client, editor, intro):
    client.force_login(editor)
    due = timezone.localtime(timezone.now() + timedelta(days=1)).replace(second=0, microsecond=0)
    response = client.post(
        reverse("website:newsletter_schedule", kwargs={"pk": intro.pk}),
        {
            "version": 1,
            "confirm": "on",
            "scheduled_at": due.strftime("%Y-%m-%dT%H:%M"),
        },
    )
    assert response.status_code == 302
    intro.refresh_from_db()
    assert intro.scheduled_at == due
    assert not mail.outbox


def test_new_writes_reject_non_admin_and_enforce_csrf(client, editor, intro):
    delivery = sent(intro)
    bounces.apply_report(bounces.preview_report(dsn(delivery))["token"], editor)
    hold = NewsletterSendingHold.objects.get()
    member = User.objects.create(email="not-an-admin@example.com", is_staff=True, is_approved=True)
    paths = [
        reverse("website:newsletter_automation"),
        reverse("website:newsletter_bounces"),
        reverse("website:newsletter_schedule", kwargs={"pk": intro.pk}),
        reverse("website:newsletter_cancel_schedule", kwargs={"pk": intro.pk}),
        reverse("website:newsletter_clear_hold", kwargs={"pk": hold.pk}),
    ]
    client.force_login(member)
    for path in paths:
        assert client.post(path).status_code == 403
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(editor)
    for path in paths:
        assert strict.post(path).status_code == 403


def test_worker_exception_keeps_generic_error_and_releases_lease(intro):
    with patch("inspinia.website.automation._prepare_lecture_digest", side_effect=RuntimeError("private details")):
        assert automation.process_queue()["state"] == "failed"
    policy = NewsletterAutomation.objects.get()
    assert policy.worker_error == "worker_failed"
    assert policy.lease_token is None
    assert "private" not in policy.worker_error


def test_renamed_pending_lecture_is_frozen_with_matching_history_and_link(intro, concept):
    subscribe()
    enable(intro)
    NewsletterAutomation.objects.filter(pk=1).update(next_digest_at=timezone.now() + timedelta(hours=1))
    lecture = LibraryLecture.objects.create(concept=concept, title="Before editing", is_published=True)
    automation.process_queue()
    lecture.title, lecture.slug = "After editing", "after-editing"
    lecture.save()
    NewsletterAutomation.objects.filter(pk=1).update(next_digest_at=timezone.now() - timedelta(seconds=1))
    automation.process_queue()
    lecture.newsletter_notice.refresh_from_db()
    assert lecture.newsletter_notice.title == "After editing"
    assert lecture.newsletter_notice.public_url.endswith(lecture.get_absolute_url())
    assert "after-editing" in mail.outbox[0].body


def test_queue_readiness_is_read_only_even_when_background_mode_is_off(intro, settings):
    settings.NEWSLETTER_BACKGROUND_ENABLED = False
    output = StringIO()
    with connection.execute_wrapper(_reject_writes):
        call_command("audit_newsletter_queue", stdout=output)
    assert '"sending_campaigns": 0' in output.getvalue()
    assert not NewsletterAutomation.objects.exists()
    assert not mail.outbox


def _reject_writes(execute, sql, params, many, context):
    if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")):
        pytest.fail("Queue readiness attempted a write")
    return execute(sql, params, many, context)
