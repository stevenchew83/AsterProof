# ruff: noqa: PLR2004
import re
import time
from http import HTTPStatus
from smtplib import SMTPException
from unittest.mock import patch

import pytest
from django.core import mail
from django.core import signing
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from inspinia.users.models import User
from inspinia.website import newsletter
from inspinia.website.models import NewsletterSubscriber

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolate_rate_limits():
    cache.clear()
    yield
    cache.clear()


def subscribe(client, email="reader@example.com", **kwargs):
    return client.post(reverse("website:newsletter_subscribe"), {"email": email, "consent": "on"}, **kwargs)


def links(subscriber):
    return (
        reverse("website:newsletter_confirm", kwargs={"token": newsletter.confirmation_token(subscriber)}),
        reverse("website:newsletter_unsubscribe", kwargs={"token": newsletter.unsubscribe_token(subscriber)}),
    )


def test_subscription_requires_consent_and_sends_branded_confirmation_only(client):
    response = client.post(reverse("website:newsletter_subscribe"), {"email": "reader@example.com"})
    assert response.status_code == HTTPStatus.OK
    assert response.context["newsletter_form"].errors["consent"]
    assert not NewsletterSubscriber.objects.exists()
    assert not mail.outbox

    response = subscribe(client, " Reader@Example.COM ")
    assert response.status_code == HTTPStatus.FOUND
    subscriber = NewsletterSubscriber.objects.get(email="reader@example.com")
    assert subscriber.status == NewsletterSubscriber.Status.PENDING
    assert not User.objects.exists()
    message = mail.outbox[-1]
    assert message.to == ["reader@example.com"]
    confirm_url, unsubscribe_url = links(subscriber)
    assert "https://asterproof.com" + confirm_url in message.body
    assert "https://asterproof.com" + unsubscribe_url in message.body
    assert "48 hours" in message.body
    assert 'src="cid:asterproof-logo"' in message.alternatives[0][0]
    assert "Confirm subscription" in message.alternatives[0][0]
    assert message.attachments[0]["Content-ID"] == "<asterproof-logo>"


def test_confirmation_get_is_safe_post_confirms_and_can_be_repeated(client):
    subscribe(client)
    subscriber = NewsletterSubscriber.objects.get()
    confirm_url, _ = links(subscriber)
    response = client.get(confirm_url)
    subscriber.refresh_from_db()
    assert subscriber.status == NewsletterSubscriber.Status.PENDING
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Referrer-Policy"] == "same-origin"
    assert response["Cache-Control"] == "private, no-store"

    assert "You're on the list" in client.post(confirm_url).content.decode()
    subscriber.refresh_from_db()
    assert subscriber.status == NewsletterSubscriber.Status.CONFIRMED
    assert subscriber.confirmed_at
    assert "You're on the list" in client.post(confirm_url).content.decode()


def test_unsubscribe_requires_post_invalidates_confirmation_and_resubscribe_requires_new_confirmation(client):
    subscribe(client)
    subscriber = NewsletterSubscriber.objects.get()
    old_confirm, unsubscribe_url = links(subscriber)
    client.post(old_confirm)
    client.get(unsubscribe_url)
    subscriber.refresh_from_db()
    assert subscriber.status == NewsletterSubscriber.Status.CONFIRMED

    response = client.post(unsubscribe_url)
    assert "been unsubscribed" in response.content.decode()
    subscriber.refresh_from_db()
    assert subscriber.status == NewsletterSubscriber.Status.UNSUBSCRIBED
    assert subscriber.unsubscribed_at
    assert not client.post(old_confirm).context["valid_link"]

    cache.clear()
    subscribe(client)
    subscriber.refresh_from_db()
    assert subscriber.status == NewsletterSubscriber.Status.PENDING
    new_confirm, _ = links(subscriber)
    assert new_confirm != old_confirm
    client.post(new_confirm)
    subscriber.refresh_from_db()
    assert subscriber.status == NewsletterSubscriber.Status.CONFIRMED
    assert subscriber.unsubscribed_at is None


def test_subscribed_address_receives_generic_response_without_more_mail(client):
    subscribe(client)
    subscriber = NewsletterSubscriber.objects.get()
    client.post(links(subscriber)[0])
    cache.clear()
    response = subscribe(client)
    assert response.url.endswith("?sent=1")
    assert len(mail.outbox) == 1


def test_honeypot_returns_generic_response_without_storing_or_sending(client):
    response = client.post(
        reverse("website:newsletter_subscribe"),
        {
            "email": "robot@example.com",
            "consent": "on",
            "company": "A bot",
        },
    )
    assert response.url.endswith("?sent=1")
    assert not NewsletterSubscriber.objects.exists()
    assert not mail.outbox


@pytest.mark.parametrize("kind", ["confirm", "unsubscribe"])
def test_post_forms_require_csrf(kind):
    client = Client(enforce_csrf_checks=True)
    assert subscribe(client).status_code == HTTPStatus.FORBIDDEN
    # Get a legitimate browser CSRF cookie and submit the initial request.
    response = client.get(reverse("website:newsletter_subscribe"))
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode()).group(1)
    client.post(
        reverse("website:newsletter_subscribe"),
        {
            "email": "reader@example.com",
            "consent": "on",
            "csrfmiddlewaretoken": token,
        },
    )
    subscriber = NewsletterSubscriber.objects.get()
    url = links(subscriber)[0 if kind == "confirm" else 1]
    assert client.get(url).status_code == HTTPStatus.OK
    assert client.post(url).status_code == HTTPStatus.FORBIDDEN
    assert client.post(url, {"csrfmiddlewaretoken": token}, HTTP_ORIGIN="http://testserver").context["action_completed"]


def test_expired_tampered_replaced_and_malformed_tokens_fail_safely(client):
    subscribe(client)
    subscriber = NewsletterSubscriber.objects.get()
    token = newsletter.confirmation_token(subscriber)
    with patch("django.core.signing.time.time", return_value=time.time() + newsletter.CONFIRMATION_SECONDS + 1):
        assert newsletter.subscriber_from_token(token) is None
    assert newsletter.subscriber_from_token(token + "changed") is None
    malformed = signing.dumps({"id": "not-a-uuid", "nonce": "bad"}, salt=newsletter.CONFIRMATION_SALT)
    assert newsletter.subscriber_from_token(malformed) is None
    cache.clear()
    subscribe(client)
    assert newsletter.subscriber_from_token(token) is None
    assert not client.get(reverse("website:newsletter_confirm", kwargs={"token": "invalid"})).context["valid_link"]


def test_unsubscribe_link_does_not_expire(client):
    subscribe(client)
    token = newsletter.unsubscribe_token(NewsletterSubscriber.objects.get())
    with patch("django.core.signing.time.time", return_value=time.time() + 366 * 86400):
        assert newsletter.subscriber_from_token(token, unsubscribe=True)


def test_rate_limits_bound_repeated_addresses_and_global_mail(client, settings):
    settings.NEWSLETTER_DAILY_EMAIL_LIMIT = 2
    subscribe(client)
    subscribe(client)
    assert len(mail.outbox) == 1
    subscribe(client, "second@example.com")
    subscribe(client, "third@example.com")
    assert len(mail.outbox) == 2
    assert NewsletterSubscriber.objects.count() == 2


def test_per_address_daily_limit_survives_minute_spacing(client, monkeypatch):
    monotonic_time = time.time()
    monkeypatch.setattr("django.core.cache.backends.base.time.time", lambda: monotonic_time)
    for _ in range(4):
        subscribe(client)
        monotonic_time += 61
    assert len(mail.outbox) == 3


def test_client_supplied_forwarded_header_cannot_evade_ip_limit(client):
    for index in range(11):
        subscribe(client, f"reader{index}@example.com", HTTP_X_FORWARDED_FOR=f"192.0.2.{index}")
    assert len(mail.outbox) == 10


def test_unavailable_cache_fails_closed(client):
    with patch.object(newsletter.cache, "incr", return_value=None):
        assert subscribe(client).url.endswith("?sent=1")
    assert not mail.outbox
    assert not NewsletterSubscriber.objects.exists()


def test_email_delivery_failure_is_generic_and_logs_no_address(client, caplog):
    with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=SMTPException("synthetic failure")):
        response = subscribe(client)
    assert response.url.endswith("?sent=1")
    assert NewsletterSubscriber.objects.get().status == NewsletterSubscriber.Status.PENDING
    assert "Newsletter confirmation delivery failed" in caplog.text
    assert "reader@example.com" not in caplog.text


def test_confirmation_origin_is_configured_not_supplied_by_host_header(client, settings):
    settings.ALLOWED_HOSTS = ["testserver", "untrusted.example"]
    subscribe(client, HTTP_HOST="untrusted.example")
    assert "https://asterproof.com/newsletter/confirm/" in mail.outbox[-1].body
    assert "untrusted.example" not in mail.outbox[-1].body
