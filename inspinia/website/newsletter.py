from __future__ import annotations

import logging
import uuid
from smtplib import SMTPException

from allauth.account.adapter import get_adapter
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import NewsletterSubscriber

logger = logging.getLogger(__name__)
CONFIRMATION_SALT = "asterproof.newsletter.confirm.v1"
UNSUBSCRIBE_SALT = "asterproof.newsletter.unsubscribe.v1"
CONFIRMATION_SECONDS = 48 * 60 * 60


def _consume_limit(label, value, maximum, seconds):
    key = "newsletter:" + label + ":" + salted_hmac("newsletter-rate", value).hexdigest()
    try:
        cache.add(key, 0, timeout=seconds)
        count = cache.incr(key)
    except (ValueError, OSError):
        return False
    return isinstance(count, int) and count <= maximum


def can_request_confirmation(request, email):
    # REMOTE_ADDR is deliberately used: proxy headers supplied by clients are not
    # trusted. This is conservative behind a reverse proxy and preserves the
    # global mail budget until a trusted client-IP policy is configured.
    address = request.META.get("REMOTE_ADDR", "unknown")
    limits = [
        ("ip", address, 10, 3600),
        ("email", email, 1, 60),
        ("email-day", email, 3, 86400),
        ("daily-budget", "all", settings.NEWSLETTER_DAILY_EMAIL_LIMIT, 86400),
    ]
    return all(_consume_limit(*limit) for limit in limits)


def confirmation_token(subscriber):
    return signing.dumps(
        {"id": str(subscriber.pk), "nonce": str(subscriber.confirmation_nonce)}, salt=CONFIRMATION_SALT,
    )


def unsubscribe_token(subscriber):
    return signing.dumps({"id": str(subscriber.pk)}, salt=UNSUBSCRIBE_SALT)


def subscriber_from_token(token, *, unsubscribe=False, for_update=False):
    try:
        payload = signing.loads(
            token,
            salt=UNSUBSCRIBE_SALT if unsubscribe else CONFIRMATION_SALT,
            max_age=None if unsubscribe else CONFIRMATION_SECONDS,
        )
        queryset = NewsletterSubscriber.objects.select_for_update() if for_update else NewsletterSubscriber.objects
        subscriber = queryset.get(pk=payload["id"])
        if not unsubscribe and str(subscriber.confirmation_nonce) != payload["nonce"]:
            return None
    except (signing.BadSignature, KeyError, ValueError, TypeError, ValidationError, NewsletterSubscriber.DoesNotExist):
        return None
    return subscriber


def request_subscription(request, email):
    if not can_request_confirmation(request, email):
        return
    with transaction.atomic():
        subscriber, created = NewsletterSubscriber.objects.select_for_update().get_or_create(
            email=email,
            defaults={"requested_at": timezone.now()},
        )
        if subscriber.status == NewsletterSubscriber.Status.CONFIRMED:
            return
        if not created:
            subscriber.status = NewsletterSubscriber.Status.PENDING
            subscriber.confirmation_nonce = uuid.uuid4()
            subscriber.requested_at = timezone.now()
            subscriber.save(update_fields=["status", "confirmation_nonce", "requested_at"])
        token = confirmation_token(subscriber)
    origin = settings.PUBLIC_SITE_ORIGIN.rstrip("/")
    context = {
        "confirmation_url": origin + reverse("website:newsletter_confirm", kwargs={"token": token}),
        "unsubscribe_url": origin
        + reverse("website:newsletter_unsubscribe", kwargs={"token": unsubscribe_token(subscriber)}),
        "email": email,
    }
    try:
        get_adapter(request).render_mail("website/email/newsletter_confirmation", email, context).send()
    except (SMTPException, OSError):
        # Keep errors observable without recording subscriber addresses or tokens.
        logger.warning("Newsletter confirmation delivery failed.")


def confirm_subscription(subscriber):
    if subscriber.status != NewsletterSubscriber.Status.PENDING:
        return subscriber.status == NewsletterSubscriber.Status.CONFIRMED
    subscriber.status = NewsletterSubscriber.Status.CONFIRMED
    subscriber.confirmed_at = timezone.now()
    subscriber.unsubscribed_at = None
    subscriber.save(update_fields=["status", "confirmed_at", "unsubscribed_at"])
    return True


def unsubscribe(subscriber):
    subscriber.status = NewsletterSubscriber.Status.UNSUBSCRIBED
    subscriber.unsubscribed_at = timezone.now()
    subscriber.confirmation_nonce = uuid.uuid4()
    subscriber.save(update_fields=["status", "unsubscribed_at", "confirmation_nonce"])
