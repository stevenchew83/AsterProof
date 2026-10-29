"""Durable, single-recipient newsletter dispatch; no implicit retries."""

from __future__ import annotations

import base64
import re
from datetime import timedelta
from smtplib import SMTPAuthenticationError
from smtplib import SMTPDataError
from smtplib import SMTPHeloError
from smtplib import SMTPRecipientsRefused
from smtplib import SMTPSenderRefused

from allauth.account.adapter import get_adapter
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from inspinia.training.markdown import render_markdown

from .models import NewsletterCampaign
from .models import NewsletterDelivery
from .models import NewsletterSendingHold
from .models import NewsletterSubscriber
from .newsletter import _consume_limit
from .newsletter import unsubscribe_token

CONTENT_FIELDS = ("subject", "preheader", "body_markdown")
EMAIL_STYLES = {
    "p": "margin:0 0 14px;",
    "h1": "margin:20px 0 12px;font-family:Georgia,serif;font-size:25px;font-weight:400;color:#192d3d;",
    "h2": "margin:20px 0 12px;font-family:Georgia,serif;font-size:22px;font-weight:400;color:#192d3d;",
    "h3": "margin:18px 0 10px;font-size:17px;color:#192d3d;",
    "a": "color:#08796f;text-decoration:underline;",
    "blockquote": "margin:16px 0;padding:0 0 0 16px;border-left:2px solid #149e92;",
    "table": "width:100%;border-collapse:collapse;margin:16px 0;font-size:12px;",
    "th": "text-align:left;padding:7px;border-bottom:1px solid #dedfdb;color:#192d3d;",
    "td": "padding:7px;border-bottom:1px solid #e8e9e5;",
    "pre": "padding:12px;background:#faf9f6;white-space:pre-wrap;font-size:12px;",
}


def _email_body(source):
    cleaned = str(render_markdown(source))
    styled = re.sub(
        r"<(p|h1|h2|h3|a|blockquote|table|th|td|pre)(?=[\s>])",
        lambda match: "<" + match[1] + ' style="' + EMAIL_STYLES[match[1]] + '"', cleaned,
    )
    return mark_safe(styled)  # noqa: S308 - sanitized Markdown plus fixed inline styles


def confirmed_subscribers():
    return NewsletterSubscriber.objects.filter(
        status=NewsletterSubscriber.Status.CONFIRMED, confirmed_at__isnull=False,
    ).alias(normalized_email=Lower("email")).exclude(
        normalized_email__in=NewsletterSendingHold.objects.filter(cleared_at__isnull=True).values("email"),
    )


def save_draft(form, actor):
    with transaction.atomic():
        if form.instance.created_at is not None:
            campaign = NewsletterCampaign.objects.select_for_update().get(pk=form.instance.pk)
            if not campaign.is_editable or campaign.version != form.cleaned_data["version"]:
                message = "This draft has changed. Reload it before saving."
                raise ValidationError(message)
            if any(getattr(campaign, name) != form.cleaned_data[name] for name in CONTENT_FIELDS):
                campaign.version += 1
        else:
            campaign = NewsletterCampaign(created_by=actor)
        for name in CONTENT_FIELDS:
            setattr(campaign, name, form.cleaned_data[name])
        campaign.save()
    return campaign


def has_current_test(campaign):
    latest = campaign.deliveries.filter(
        kind=NewsletterDelivery.Kind.TEST, campaign_version=campaign.version,
    ).order_by("-created_at", "-pk").first()
    return bool(
        latest and latest.status == NewsletterDelivery.Status.ACCEPTED
        and latest.delivery_result == NewsletterDelivery.Result.UNCONFIRMED,
    )


def email_context(campaign, subscriber=None, *, test=False):
    return {
        "campaign": campaign,
        "rendered_body": _email_body(campaign.body_markdown),
        "is_test": test,
        "unsubscribe_url": (
            settings.PUBLIC_SITE_ORIGIN.rstrip("/")
            + reverse("website:newsletter_unsubscribe", kwargs={"token": unsubscribe_token(subscriber)})
            if subscriber else ""
        ),
    }


def preview_html(campaign):
    html = render_to_string("website/email/campaign_message.html", email_context(campaign))
    logo = base64.b64encode((settings.APPS_DIR / "static/images/asterproof-logo-email.png").read_bytes()).decode()
    return html.replace("cid:asterproof-logo", "data:image/png;base64," + logo)


def _reserve_mail_budget():
    # Shared with subscription confirmations, preserving capacity for account mail.
    return _consume_limit("daily-budget", "all", settings.NEWSLETTER_DAILY_EMAIL_LIMIT, 86400)


def start_campaign(pk, actor, version):
    with transaction.atomic():
        campaign = NewsletterCampaign.objects.select_for_update().get(pk=pk)
        if not campaign.is_editable or campaign.version != version:
            message = "This version is no longer available to send. Reload the campaign."
            raise ValidationError(message)
        if not has_current_test(campaign):
            message = "Send a successful test email for this version before sending to subscribers."
            raise ValidationError(message)
        if not confirmed_subscribers().exists():
            message = "There are no confirmed subscribers to send to yet."
            raise ValidationError(message)
        _snapshot_audience(campaign, actor)
    return campaign


def _snapshot_audience(campaign, actor):
    """Caller holds the campaign lock; content is frozen before any SMTP claim."""
    audience = confirmed_subscribers().values("pk", "email", "confirmed_at").iterator(chunk_size=500)
    NewsletterDelivery.objects.bulk_create((
        NewsletterDelivery(
            campaign=campaign, subscriber_id=row["pk"], recipient_email=row["email"],
            subject=campaign.subject, consent_confirmed_at=row["confirmed_at"], campaign_version=campaign.version,
        ) for row in audience
    ), batch_size=500)
    campaign.status = (
        NewsletterCampaign.Status.SENDING if campaign.deliveries.filter(kind=NewsletterDelivery.Kind.CAMPAIGN).exists()
        else NewsletterCampaign.Status.COMPLETED
    )
    campaign.started_at = timezone.now()
    campaign.started_by = actor
    campaign.completed_at = campaign.started_at if campaign.status == NewsletterCampaign.Status.COMPLETED else None
    campaign.next_attempt_at = None
    campaign.pause_reason = ""
    campaign.save(update_fields=[
        "status", "started_at", "started_by", "completed_at", "next_attempt_at", "pause_reason", "updated_at",
    ])


def schedule_campaign(pk, actor, version, when):
    if not settings.NEWSLETTER_BACKGROUND_ENABLED:
        msg = "Background sending must be configured before scheduling."
        raise ValidationError(msg)
    if timezone.is_naive(when) or when <= timezone.now():
        msg = "Choose a future date and time."
        raise ValidationError(msg)
    with transaction.atomic():
        campaign = NewsletterCampaign.objects.select_for_update().get(pk=pk)
        if not campaign.is_editable or campaign.version != version or not has_current_test(campaign):
            msg = "Save and test this draft version before scheduling."
            raise ValidationError(msg)
        campaign.status = NewsletterCampaign.Status.SCHEDULED
        campaign.scheduled_at = when
        campaign.started_by = actor
        campaign.save(update_fields=["status", "scheduled_at", "started_by", "updated_at"])
    return campaign


def cancel_schedule(pk):
    with transaction.atomic():
        campaign = NewsletterCampaign.objects.select_for_update().get(pk=pk)
        if campaign.status != NewsletterCampaign.Status.SCHEDULED or campaign.started_at is not None:
            msg = "This schedule has already started or was cancelled. Reload the campaign."
            raise ValidationError(msg)
        campaign.status = NewsletterCampaign.Status.DRAFT
        campaign.scheduled_at = None
        campaign.started_by = None
        campaign.version += 1
        campaign.save(update_fields=["status", "scheduled_at", "started_by", "version", "updated_at"])
    return campaign


def _finish(delivery, status, detail):
    NewsletterDelivery.objects.filter(pk=delivery.pk, status=NewsletterDelivery.Status.SENDING).update(
        status=status, detail=detail, finished_at=timezone.now(),
    )
    delivery.status, delivery.detail = status, detail
    return delivery


def _still_subscribed(delivery):
    return confirmed_subscribers().filter(
        pk=delivery.subscriber_id, email=delivery.recipient_email, confirmed_at=delivery.consent_confirmed_at,
    ).exists()


def _content_still_public(campaign):
    if campaign.lecture_template_version is None:
        return True
    notices = campaign.lecture_notices.all()
    return notices.exists() and not notices.filter(
        Q(lecture__isnull=True) | Q(lecture__is_published=False)
        | Q(lecture__concept__is_published=False) | Q(lecture__concept__area__is_published=False),
    ).exists()


def _dispatch(request, campaign, delivery):
    subscriber = NewsletterSubscriber.objects.filter(pk=delivery.subscriber_id).first()
    test = delivery.kind == NewsletterDelivery.Kind.TEST
    try:
        context = email_context(campaign, subscriber, test=test)
        headers = {"Message-ID": f"<newsletter-{delivery.pk}@asterproof.com>"}
        if not test:
            headers["List-Unsubscribe"] = "<" + context["unsubscribe_url"] + ">"
        message = get_adapter(request).render_mail(
            "website/email/campaign", delivery.recipient_email, context, headers=headers,
        )
    except Exception:  # noqa: BLE001 - rendering failed before any SMTP handoff
        return _finish(delivery, NewsletterDelivery.Status.FAILED, "The email could not be prepared.")
    # Recheck after rendering, immediately before handing this address to SMTP.
    if not test and (not _still_subscribed(delivery) or not _content_still_public(campaign)):
        return _finish(
            delivery, NewsletterDelivery.Status.SKIPPED, "Subscription or lecture visibility changed before sending.",
        )
    try:
        accepted = message.send()
    except (SMTPAuthenticationError, SMTPDataError, SMTPHeloError, SMTPRecipientsRefused, SMTPSenderRefused):
        return _finish(delivery, NewsletterDelivery.Status.FAILED, "The email server rejected this attempt.")
    except Exception:  # noqa: BLE001 - an interrupted SMTP handoff must never be retried automatically
        return _finish(delivery, NewsletterDelivery.Status.UNKNOWN, "Sending was interrupted. Receipt is unconfirmed.")
    if accepted != 1:
        return _finish(delivery, NewsletterDelivery.Status.FAILED, "The email server did not accept this attempt.")
    return _finish(delivery, NewsletterDelivery.Status.ACCEPTED, "Accepted by the email server.")


def send_test(request, pk, version):
    with transaction.atomic():
        campaign = NewsletterCampaign.objects.select_for_update().get(pk=pk)
        if not campaign.is_editable or campaign.version != version:
            message = "Save the current draft before sending a test."
            raise ValidationError(message)
        if campaign.deliveries.filter(status=NewsletterDelivery.Status.SENDING).exists():
            message = "A delivery is already in progress for this draft."
            raise ValidationError(message)
        if not _consume_limit("admin-test", str(request.user.pk), 3, 60) or not _reserve_mail_budget():
            message = "The email allowance is unavailable. Please try again later."
            raise ValidationError(message)
        delivery = NewsletterDelivery.objects.create(
            campaign=campaign, campaign_version=campaign.version, kind=NewsletterDelivery.Kind.TEST,
            recipient_email=request.user.email, status=NewsletterDelivery.Status.SENDING, attempted_at=timezone.now(),
            subject=campaign.subject,
        )
    return _dispatch(request, campaign, delivery)


def _complete_if_finished(campaign):
    if not campaign.deliveries.filter(
        kind=NewsletterDelivery.Kind.CAMPAIGN,
        status__in=[NewsletterDelivery.Status.QUEUED, NewsletterDelivery.Status.SENDING],
    ).exists():
        NewsletterCampaign.objects.filter(pk=campaign.pk).exclude(
            status__in=[NewsletterCampaign.Status.DRAFT, NewsletterCampaign.Status.SCHEDULED],
        ).update(
            status=NewsletterCampaign.Status.COMPLETED, completed_at=timezone.now(),
        )


def send_next(request, pk):
    budget_blocked = False
    with transaction.atomic():
        campaign = NewsletterCampaign.objects.select_for_update().get(pk=pk)
        if campaign.status != NewsletterCampaign.Status.SENDING:
            message = "Resume this campaign before continuing."
            raise ValidationError(message)
        if campaign.deliveries.filter(status=NewsletterDelivery.Status.SENDING).exists():
            message = "A delivery is already in progress. Check its history before continuing."
            raise ValidationError(message)
        delivery = campaign.deliveries.filter(
            kind=NewsletterDelivery.Kind.CAMPAIGN, status=NewsletterDelivery.Status.QUEUED,
        ).order_by("created_at", "pk").first()
        if delivery is None:
            _complete_if_finished(campaign)
            return None
        if not _still_subscribed(delivery) or not _content_still_public(campaign):
            delivery.status = NewsletterDelivery.Status.SKIPPED
            delivery.detail = "Subscription or lecture visibility changed before sending."
            delivery.finished_at = timezone.now()
            delivery.save(update_fields=["status", "detail", "finished_at"])
            _complete_if_finished(campaign)
            return delivery
        minute_available = _consume_limit("campaign-minute", "all", 20, 60)
        if not minute_available or not _reserve_mail_budget():
            campaign.status = NewsletterCampaign.Status.PAUSED
            campaign.pause_reason = "allowance"
            campaign.next_attempt_at = timezone.now() + timedelta(minutes=1 if not minute_available else 60)
            campaign.save(update_fields=["status", "pause_reason", "next_attempt_at", "updated_at"])
            budget_blocked = True
        else:
            delivery.status = NewsletterDelivery.Status.SENDING
            delivery.attempted_at = timezone.now()
            delivery.save(update_fields=["status", "attempted_at"])
    if budget_blocked:
        message = "Sending paused because the email allowance is unavailable. Resume later."
        raise ValidationError(message)
    delivery = _dispatch(request, campaign, delivery)
    if delivery.status in {NewsletterDelivery.Status.FAILED, NewsletterDelivery.Status.UNKNOWN}:
        NewsletterCampaign.objects.filter(pk=pk, status=NewsletterCampaign.Status.SENDING).update(
            status=NewsletterCampaign.Status.PAUSED, pause_reason="delivery_review", next_attempt_at=None,
        )
    _complete_if_finished(campaign)
    return delivery


def set_paused(pk, *, paused):
    with transaction.atomic():
        campaign = NewsletterCampaign.objects.select_for_update().get(pk=pk)
        if campaign.status not in {NewsletterCampaign.Status.SENDING, NewsletterCampaign.Status.PAUSED}:
            message = "This campaign cannot be paused or resumed."
            raise ValidationError(message)
        campaign.status = NewsletterCampaign.Status.PAUSED if paused else NewsletterCampaign.Status.SENDING
        campaign.pause_reason = "manual" if paused else ""
        campaign.next_attempt_at = None
        campaign.save(update_fields=["status", "pause_reason", "next_attempt_at", "updated_at"])
    return campaign


def mark_interrupted(pk):
    with transaction.atomic():
        campaign = NewsletterCampaign.objects.select_for_update().get(pk=pk)
        deliveries = campaign.deliveries.filter(
            status=NewsletterDelivery.Status.SENDING, attempted_at__lt=timezone.now() - timedelta(minutes=5),
        )
        count = deliveries.update(
            status=NewsletterDelivery.Status.UNKNOWN, finished_at=timezone.now(),
            detail="Interrupted delivery marked for review. It will not be sent again.",
        )
        if not count:
            message = "No interrupted delivery is ready to review yet."
            raise ValidationError(message)
        if campaign.status == NewsletterCampaign.Status.SENDING:
            campaign.status = NewsletterCampaign.Status.PAUSED
            campaign.pause_reason = "delivery_review"
            campaign.next_attempt_at = None
            campaign.save(update_fields=["status", "pause_reason", "next_attempt_at", "updated_at"])
