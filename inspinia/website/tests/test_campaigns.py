# ruff: noqa: PLR2004
import re
from datetime import timedelta
from smtplib import SMTPRecipientsRefused
from smtplib import SMTPServerDisconnected
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import connection
from django.db import transaction
from django.test import Client
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from inspinia.users.models import User
from inspinia.website import campaigns
from inspinia.website.forms import NewsletterCampaignForm
from inspinia.website.models import NewsletterCampaign
from inspinia.website.models import NewsletterDelivery
from inspinia.website.models import NewsletterSubscriber
from inspinia.website.newsletter import subscriber_from_token
from inspinia.website.newsletter import unsubscribe

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_delivery(mailoutbox):
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin_user():
    return User.objects.create(email="editor@example.com", role=User.Role.ADMIN)


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


@pytest.fixture
def admin_request(admin_user):
    value = RequestFactory().get("/manage/newsletter/")
    value.user = admin_user
    return value


@pytest.fixture
def campaign(admin_user):
    return NewsletterCampaign.objects.create(
        subject="A useful geometric idea", preheader="New notes for a thoughtful afternoon.",
        body_markdown="## Look for the circle\n\nA **small insight**. [Study the idea](https://asterproof.com/library/).",
        created_by=admin_user,
    )


def add_subscriber(email="reader@example.com", status=NewsletterSubscriber.Status.CONFIRMED):
    return NewsletterSubscriber.objects.create(
        email=email, status=status, requested_at=timezone.now(),
        confirmed_at=timezone.now() if status == NewsletterSubscriber.Status.CONFIRMED else None,
    )


def prepare(campaign, admin_request):
    campaigns.send_test(admin_request, campaign.pk, campaign.version)
    campaigns.start_campaign(campaign.pk, admin_request.user, campaign.version)
    mail.outbox.clear()


def draft_data(campaign, **overrides):
    return {
        "subject": campaign.subject, "preheader": campaign.preheader,
        "body_markdown": campaign.body_markdown, "version": campaign.version, **overrides,
    }


READ_ROUTES = [
    "newsletter_dashboard", "newsletter_subscribers", "newsletter_history", "newsletter_campaign_new",
    "newsletter_campaign", "newsletter_preview", "newsletter_send", "newsletter_subscriber",
]
WRITE_ROUTES = [
    "newsletter_send_next", "newsletter_resume", "newsletter_pause", "newsletter_interrupted", "newsletter_duplicate",
]


@pytest.mark.parametrize("name", READ_ROUTES + WRITE_ROUTES)
def test_all_backend_routes_require_admin_even_in_debug(client, settings, campaign, name):
    settings.DEBUG = True
    row = add_subscriber()
    kwargs = {"pk": row.pk if name == "newsletter_subscriber" else campaign.pk}
    if name in {"newsletter_dashboard", "newsletter_subscribers", "newsletter_history", "newsletter_campaign_new"}:
        kwargs = {}
    url = reverse("website:" + name, kwargs=kwargs)
    assert client.get(url).status_code == 302
    user = User.objects.create(email="member@example.com", is_staff=True, is_approved=True)
    client.force_login(user)
    assert client.get(url).status_code == 403
    assert client.post(url).status_code == 403
    assert not mail.outbox


@pytest.mark.parametrize("name", READ_ROUTES)
def test_admin_pages_render_and_are_private(admin_client, campaign, name):
    row = add_subscriber()
    kwargs = {"pk": row.pk if name == "newsletter_subscriber" else campaign.pk}
    if name in {"newsletter_dashboard", "newsletter_subscribers", "newsletter_history", "newsletter_campaign_new"}:
        kwargs = {}
    response = admin_client.get(reverse("website:" + name, kwargs=kwargs))
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Referrer-Policy"] == "same-origin"
    assert not mail.outbox


def test_subscriber_search_filter_and_admin_opt_out(admin_client):
    row = add_subscriber()
    add_subscriber("waiting@example.com", NewsletterSubscriber.Status.PENDING)
    response = admin_client.get(reverse("website:newsletter_subscribers"), {"status": "pending", "q": "waiting"})
    assert [item.email for item in response.context["page"]] == ["waiting@example.com"]
    response = admin_client.post(reverse("website:newsletter_subscriber", kwargs={"pk": row.pk}))
    assert response.status_code == 302
    row.refresh_from_db()
    assert row.status == NewsletterSubscriber.Status.UNSUBSCRIBED
    assert row.unsubscribed_at
    assert not mail.outbox


def test_drafts_optimistic_locking_and_immutable_started_content(admin_user, campaign, admin_request):
    stale = NewsletterCampaignForm(draft_data(campaign, subject="Stale editor"), instance=campaign)
    current = NewsletterCampaignForm(draft_data(campaign, subject="First saved version"), instance=campaign)
    assert current.is_valid()
    saved = campaigns.save_draft(current, admin_user)
    assert saved.version == 2
    assert stale.is_valid()
    with pytest.raises(ValidationError, match="changed"):
        campaigns.save_draft(stale, admin_user)
    add_subscriber()
    prepare(saved, admin_request)
    locked = NewsletterCampaignForm(draft_data(saved, subject="Change after sending"), instance=saved)
    assert locked.is_valid()
    with pytest.raises(ValidationError, match="changed"):
        campaigns.save_draft(locked, admin_user)


@pytest.mark.parametrize("subject", ["Hello\nBcc: victim@example.com", "Hello\rBcc: victim@example.com"])
def test_header_injection_is_rejected(campaign, subject):
    form = NewsletterCampaignForm(draft_data(campaign, subject=subject), instance=campaign)
    assert not form.is_valid()
    assert "subject" in form.errors


def test_editor_saves_tests_own_address_and_requires_new_test_after_edit(admin_client, campaign):
    url = campaign.get_absolute_url()
    response = admin_client.post(url, draft_data(campaign, action="test", recipient_email="outsider@example.com"))
    assert response.status_code == 302
    message = mail.outbox[-1]
    assert message.to == ["editor@example.com"]
    assert "[Test]" in message.subject
    assert 'src="cid:asterproof-logo"' in message.alternatives[0][0]
    assert message.attachments[0]["Content-ID"] == "<asterproof-logo>"
    assert "List-Unsubscribe" not in message.extra_headers
    campaign.refresh_from_db()
    assert campaigns.has_current_test(campaign)
    response = admin_client.post(url, draft_data(campaign, subject="Edited newsletter", action="save"))
    assert response.status_code == 302
    campaign.refresh_from_db()
    assert campaign.version == 2
    assert not campaigns.has_current_test(campaign)
    assert campaign.deliveries.get().subject == "A useful geometric idea"
    history = admin_client.get(reverse("website:newsletter_history"), {"q": "A useful geometric idea"})
    assert history.context["page"].paginator.count == 1


def test_sanitized_preview_embeds_logo_and_has_no_active_content(admin_client, campaign):
    campaign.body_markdown = "<script>alert(1)</script>\n\n[Unsafe](javascript:alert(1))\n\n**Safe**"
    campaign.save()
    response = admin_client.get(reverse("website:newsletter_preview", kwargs={"pk": campaign.pk}))
    html = response.content.decode()
    assert "data:image/png;base64," in html
    assert "<strong>Safe</strong>" in html
    assert "<script" not in html
    assert "javascript:" not in html
    assert "sandbox" in response["Content-Security-Policy"]
    assert "default-src 'none'" in response["Content-Security-Policy"]
    assert response["X-Frame-Options"] == "SAMEORIGIN"


def test_plain_text_and_subject_preserve_punctuation(campaign, admin_request):
    campaign.subject = "Steven's areas & concepts"
    campaign.body_markdown = "Let's explore A & B. https://asterproof.com/library/?a=1&b=2"
    campaign.save()
    campaigns.send_test(admin_request, campaign.pk, 1)
    message = mail.outbox[-1]
    assert "Steven's areas & concepts" in message.subject
    assert campaign.body_markdown in message.body
    assert "&amp;" not in message.body
    assert "&amp;" in message.alternatives[0][0]


def test_campaign_requires_current_test_and_confirmed_audience(campaign, admin_request):
    with pytest.raises(ValidationError, match="test email"):
        campaigns.start_campaign(campaign.pk, admin_request.user, 1)
    campaigns.send_test(admin_request, campaign.pk, 1)
    with pytest.raises(ValidationError, match="no confirmed"):
        campaigns.start_campaign(campaign.pk, admin_request.user, 1)
    add_subscriber()
    with pytest.raises(ValidationError, match="no longer"):
        campaigns.start_campaign(campaign.pk, admin_request.user, 2)


def test_only_confirmed_subscribers_are_snapshotted_and_start_cannot_repeat(campaign, admin_request):
    yes = add_subscriber()
    add_subscriber("pending@example.com", NewsletterSubscriber.Status.PENDING)
    add_subscriber("unsubscribed@example.com", NewsletterSubscriber.Status.UNSUBSCRIBED)
    missing_consent = add_subscriber("bad-consent@example.com")
    missing_consent.confirmed_at = None
    missing_consent.save()
    prepare(campaign, admin_request)
    deliveries = campaign.deliveries.filter(kind=NewsletterDelivery.Kind.CAMPAIGN)
    assert list(deliveries.values_list("subscriber_id", flat=True)) == [yes.pk]
    assert deliveries.get().consent_confirmed_at == yes.confirmed_at
    with pytest.raises(ValidationError):
        campaigns.start_campaign(campaign.pk, admin_request.user, 1)
    assert deliveries.count() == 1


def test_latest_test_must_succeed_even_when_an_earlier_test_was_accepted(campaign, admin_request):
    add_subscriber()
    campaigns.send_test(admin_request, campaign.pk, 1)
    assert campaigns.has_current_test(campaign)
    failure = SMTPRecipientsRefused({"editor@example.com": (550, b"rejected")})
    with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=failure):
        campaigns.send_test(admin_request, campaign.pk, 1)
    assert not campaigns.has_current_test(campaign)
    with pytest.raises(ValidationError, match="test email"):
        campaigns.start_campaign(campaign.pk, admin_request.user, 1)
    assert not campaign.deliveries.filter(kind=NewsletterDelivery.Kind.CAMPAIGN).exists()


def test_single_recipient_messages_have_valid_individual_unsubscribe_links(campaign, admin_request):
    one, two = add_subscriber(), add_subscriber("second@example.com")
    prepare(campaign, admin_request)
    campaigns.send_next(admin_request, campaign.pk)
    campaigns.send_next(admin_request, campaign.pk)
    assert len(mail.outbox) == 2
    links = set()
    for message in mail.outbox:
        assert len(message.to) == 1
        assert not message.bcc
        link = re.search(r"https://asterproof.com/newsletter/unsubscribe/([^\s<]+?)/", message.body).group(1)
        row = subscriber_from_token(link, unsubscribe=True)
        assert row.email == message.to[0]
        assert message.extra_headers["List-Unsubscribe"] == f"<https://asterproof.com/newsletter/unsubscribe/{link}/>"
        assert f'"https://asterproof.com/newsletter/unsubscribe/{link}/"' in message.alternatives[0][0]
        links.add(link)
    assert len(links) == 2
    assert {message.to[0] for message in mail.outbox} == {one.email, two.email}
    campaign.refresh_from_db()
    assert campaign.status == NewsletterCampaign.Status.COMPLETED
    assert campaign.completed_at
    with pytest.raises(ValidationError):
        campaigns.send_next(admin_request, campaign.pk)
    assert len(mail.outbox) == 2


@pytest.mark.parametrize("change", ["unsubscribe", "delete", "reconfirm"])
def test_consent_changes_after_queue_skip_without_sending(campaign, admin_request, change):
    row = add_subscriber()
    prepare(campaign, admin_request)
    if change == "unsubscribe":
        unsubscribe(row)
    elif change == "delete":
        row.delete()
    else:
        row.confirmed_at = timezone.now() + timedelta(seconds=1)
        row.save()
    delivery = campaigns.send_next(admin_request, campaign.pk)
    assert delivery.status == NewsletterDelivery.Status.SKIPPED
    assert not mail.outbox


def test_consent_is_rechecked_after_rendering_immediately_before_smtp(campaign, admin_request):
    row = add_subscriber()
    prepare(campaign, admin_request)
    adapter = campaigns.get_adapter(admin_request)
    render = adapter.render_mail
    def changed(*args, **kwargs):
        message = render(*args, **kwargs)
        unsubscribe(row)
        return message
    with patch.object(campaigns, "get_adapter", return_value=adapter), patch.object(adapter, "render_mail", changed):
        delivery = campaigns.send_next(admin_request, campaign.pk)
    assert delivery.status == NewsletterDelivery.Status.SKIPPED
    assert not mail.outbox


@pytest.mark.parametrize(("error", "expected"), [
    (SMTPRecipientsRefused({"private@example.com": (550, b"private diagnostic")}), NewsletterDelivery.Status.FAILED),
    (SMTPServerDisconnected("private diagnostic"), NewsletterDelivery.Status.UNKNOWN),
])
def test_failure_is_recorded_without_secrets_and_pauses_remaining_mail(campaign, admin_request, error, expected):
    add_subscriber()
    add_subscriber("second@example.com")
    prepare(campaign, admin_request)
    with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=error):
        delivery = campaigns.send_next(admin_request, campaign.pk)
    assert delivery.status == expected
    assert "private" not in delivery.detail
    campaign.refresh_from_db()
    assert campaign.status == NewsletterCampaign.Status.PAUSED
    with pytest.raises(ValidationError):
        campaigns.send_next(admin_request, campaign.pk)
    campaigns.set_paused(campaign.pk, paused=False)
    campaigns.send_next(admin_request, campaign.pk)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to != [delivery.recipient_email]


def test_shared_daily_budget_pauses_durably_without_losing_queued_delivery(campaign, admin_request, settings):
    settings.NEWSLETTER_DAILY_EMAIL_LIMIT = 1
    add_subscriber()
    prepare(campaign, admin_request)  # the successful test consumes the single shared allowance
    with pytest.raises(ValidationError, match="allowance"):
        campaigns.send_next(admin_request, campaign.pk)
    campaign.refresh_from_db()
    assert campaign.status == NewsletterCampaign.Status.PAUSED
    assert campaign.deliveries.filter(kind="campaign").get().status == NewsletterDelivery.Status.QUEUED
    assert not mail.outbox


def test_unavailable_cache_cannot_send(campaign, admin_request):
    with patch("inspinia.website.newsletter.cache.incr", return_value=None), \
            pytest.raises(ValidationError, match="allowance"):
        campaigns.send_test(admin_request, campaign.pk, 1)
    assert not mail.outbox
    assert not NewsletterDelivery.objects.exists()


def test_duplicate_recipient_and_inflight_claims_are_rejected_by_database(campaign):
    row = add_subscriber()
    NewsletterDelivery.objects.create(campaign=campaign, recipient_email=row.email, campaign_version=1)
    with transaction.atomic(), pytest.raises(IntegrityError):
        NewsletterDelivery.objects.create(campaign=campaign, recipient_email=row.email, campaign_version=1)
    NewsletterDelivery.objects.create(
        campaign=campaign, recipient_email="one@example.com", campaign_version=1, status="sending",
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        NewsletterDelivery.objects.create(
            campaign=campaign, recipient_email="two@example.com", campaign_version=1, status="sending",
        )


def test_interrupted_claim_is_not_retried_and_requires_age_before_review(campaign, admin_request):
    add_subscriber()
    prepare(campaign, admin_request)
    with patch.object(campaigns, "_finish", side_effect=RuntimeError("lost result write")), \
            pytest.raises(RuntimeError, match="lost result"):
        campaigns.send_next(admin_request, campaign.pk)
    assert len(mail.outbox) == 1
    with pytest.raises(ValidationError, match="in progress"):
        campaigns.send_next(admin_request, campaign.pk)
    with pytest.raises(ValidationError, match="No interrupted"):
        campaigns.mark_interrupted(campaign.pk)
    campaign.deliveries.filter(status="sending").update(attempted_at=timezone.now() - timedelta(minutes=6))
    campaigns.mark_interrupted(campaign.pk)
    assert campaign.deliveries.filter(status=NewsletterDelivery.Status.UNKNOWN).count() == 1
    campaigns.set_paused(campaign.pk, paused=False)
    campaigns.send_next(admin_request, campaign.pk)
    assert len(mail.outbox) == 1


def test_interrupted_test_can_be_reviewed_from_the_draft(admin_client, campaign, admin_request):
    with patch.object(campaigns, "_finish", side_effect=RuntimeError("lost result write")), \
            pytest.raises(RuntimeError):
        campaigns.send_test(admin_request, campaign.pk, 1)
    response = admin_client.get(campaign.get_absolute_url())
    assert response.context["inflight"]
    assert not response.context["can_review_interrupted"]
    campaign.deliveries.filter(status="sending").update(attempted_at=timezone.now() - timedelta(minutes=6))
    response = admin_client.get(campaign.get_absolute_url())
    assert response.context["can_review_interrupted"]
    response = admin_client.post(reverse("website:newsletter_interrupted", kwargs={"pk": campaign.pk}))
    assert response.status_code == 302
    assert campaign.deliveries.get().status == NewsletterDelivery.Status.UNKNOWN
    assert len(mail.outbox) == 1
    campaign.refresh_from_db()
    assert campaign.is_editable
    assert not campaigns.has_current_test(campaign)


def test_csrf_and_explicit_send_confirmation_are_required(admin_user, campaign):
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)
    for name in ["newsletter_send", *WRITE_ROUTES]:
        assert client.post(reverse("website:" + name, kwargs={"pk": campaign.pk})).status_code == 403
    response = client.get(campaign.get_absolute_url())
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode()).group(1)
    response = client.post(reverse("website:newsletter_send", kwargs={"pk": campaign.pk}), {
        "version": 1, "csrfmiddlewaretoken": token,
    })
    assert response.status_code == 200
    assert not NewsletterDelivery.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_smtp_runs_after_delivery_claim_is_committed(admin_client, campaign):
    def outside_transaction(*args, **kwargs):
        assert not connection.in_atomic_block
        delivery = NewsletterDelivery.objects.get(status="sending")
        assert delivery.attempted_at
        return 1
    with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=outside_transaction):
        response = admin_client.post(campaign.get_absolute_url(), draft_data(campaign, action="test"))
    assert response.status_code == 302
    assert NewsletterDelivery.objects.get().status == NewsletterDelivery.Status.ACCEPTED


def test_json_runner_and_copy_to_draft_preserve_history(admin_client, campaign, admin_request):
    add_subscriber()
    campaigns.send_test(admin_request, campaign.pk, 1)
    response = admin_client.post(reverse("website:newsletter_send", kwargs={"pk": campaign.pk}), {
        "version": 1, "confirm": "on",
    }, HTTP_ACCEPT="application/json")
    assert response.json()["counts"]["total"] == 1
    response = admin_client.post(response.json()["step_url"], HTTP_ACCEPT="application/json")
    assert response.json()["status"] == "completed"
    response = admin_client.post(reverse("website:newsletter_duplicate", kwargs={"pk": campaign.pk}))
    assert response.status_code == 302
    copied = NewsletterCampaign.objects.exclude(pk=campaign.pk).get()
    assert copied.status == NewsletterCampaign.Status.DRAFT
    assert copied.version == 1
    assert copied.body_markdown == campaign.body_markdown
    assert not copied.deliveries.exists()
    assert campaign.deliveries.count() == 2


@pytest.mark.django_db(transaction=True)
def test_campaign_smtp_and_acknowledgement_are_outside_request_transaction(admin_client, campaign, admin_request):
    add_subscriber()
    prepare(campaign, admin_request)
    def outside_transaction(*args, **kwargs):
        assert not connection.in_atomic_block
        delivery = NewsletterDelivery.objects.get(status="sending")
        assert delivery.kind == NewsletterDelivery.Kind.CAMPAIGN
        return 1
    with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=outside_transaction):
        response = admin_client.post(
            reverse("website:newsletter_send_next", kwargs={"pk": campaign.pk}), HTTP_ACCEPT="application/json",
        )
    assert response.json()["status"] == "completed"
