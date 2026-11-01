"""Bounded newsletter queue processing and explicitly enabled lecture digests."""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import campaigns
from .models import LibraryLecture
from .models import NewsletterAutomation
from .models import NewsletterCampaign
from .models import NewsletterDelivery
from .models import NewsletterLectureNotice

LEASE_SECONDS = 120
DIGEST_LIMIT = 10
MAX_INTRO_LENGTH = 26000
MAX_MESSAGE_LENGTH = 30000
MAX_MESSAGES = 20
MAX_SECONDS = 50


def public_lectures():
    return LibraryLecture.objects.filter(
        is_published=True,
        concept__is_published=True,
        concept__area__is_published=True,
    ).select_related("concept__area")


def next_digest(when, digest_time):
    local = timezone.localtime(when, ZoneInfo(settings.TIME_ZONE))
    due = datetime.combine(local.date(), digest_time, tzinfo=local.tzinfo)
    return due if due > local else due + timedelta(days=1)


def _capture_lectures(status, *, maximum=None):
    lectures = public_lectures().filter(newsletter_notice__isnull=True).order_by("pk")
    if maximum:
        lectures = lectures[:maximum]
    # This runs under the singleton policy lock; a lecture is captured once.
    rows = [
        NewsletterLectureNotice(
            lecture=lecture,
            title=lecture.title,
            public_url=settings.PUBLIC_SITE_ORIGIN.rstrip("/") + lecture.get_absolute_url(),
            status=status,
        )
        for lecture in lectures
    ]
    NewsletterLectureNotice.objects.bulk_create(rows, batch_size=500)


def configure_lectures(*, enabled, template, digest_time):
    if enabled and not settings.NEWSLETTER_BACKGROUND_ENABLED:
        msg = "Configure background sending before enabling lecture notifications."
        raise ValidationError(msg)
    with transaction.atomic():
        NewsletterAutomation.objects.get_or_create(pk=1)
        policy = NewsletterAutomation.objects.select_for_update().get(pk=1)
        if enabled:
            template = NewsletterCampaign.objects.select_for_update().get(pk=template.pk)
            if not template.is_editable or not campaigns.has_current_test(template):
                msg = "Choose a saved draft with a successful test for its current version."
                raise ValidationError(msg)
            if len(template.body_markdown) > MAX_INTRO_LENGTH:
                msg = "Keep the digest introduction under 26,000 characters to leave room for lectures."
                raise ValidationError(msg)
        if not enabled or not policy.lecture_enabled:
            NewsletterLectureNotice.objects.filter(status=NewsletterLectureNotice.Status.PENDING).update(
                status=NewsletterLectureNotice.Status.EXCLUDED,
            )
        if not enabled:
            _pause_lecture_campaigns()
        if enabled and not policy.lecture_enabled:
            _capture_lectures(NewsletterLectureNotice.Status.BASELINE)
            policy.enabled_at = timezone.now()
        policy.lecture_enabled = enabled
        policy.lecture_template = template if enabled else None
        policy.template_version = template.version if enabled else None
        policy.digest_time = digest_time
        policy.next_digest_at = next_digest(timezone.now(), digest_time) if enabled else None
        policy.lecture_error = ""
        policy.save(
            update_fields=[
                "lecture_enabled",
                "lecture_template",
                "template_version",
                "digest_time",
                "enabled_at",
                "next_digest_at",
                "lecture_error",
            ],
        )
    return policy


def acquire_lease():
    with transaction.atomic():
        NewsletterAutomation.objects.get_or_create(pk=1)
        policy = NewsletterAutomation.objects.select_for_update().get(pk=1)
        if policy.lease_until and policy.lease_until > timezone.now():
            return None
        token = uuid.uuid4()
        policy.lease_token = token
        policy.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
        policy.worker_started_at = timezone.now()
        policy.worker_error = ""
        policy.save(update_fields=["lease_token", "lease_until", "worker_started_at", "worker_error"])
        return token


def _pause_lecture_campaigns():
    NewsletterCampaign.objects.filter(
        lecture_template_version__isnull=False,
        status=NewsletterCampaign.Status.SENDING,
    ).update(status=NewsletterCampaign.Status.PAUSED, pause_reason="automation_disabled", next_attempt_at=None)


def renew_lease(token):
    return bool(
        NewsletterAutomation.objects.filter(
            pk=1,
            lease_token=token,
            lease_until__gt=timezone.now(),
        ).update(lease_until=timezone.now() + timedelta(seconds=LEASE_SECONDS)),
    )


def _release_lease(token, error):
    updates = {"worker_error": error} if error else {}
    NewsletterAutomation.objects.filter(pk=1, lease_token=token).update(
        lease_token=None,
        lease_until=None,
        worker_finished_at=timezone.now(),
        **updates,
    )


def _start_due_campaigns():
    ids = (
        NewsletterCampaign.objects.filter(
            status=NewsletterCampaign.Status.SCHEDULED,
            scheduled_at__lte=timezone.now(),
        )
        .order_by("scheduled_at", "pk")
        .values_list("pk", flat=True)[:20]
    )
    for pk in ids:
        with transaction.atomic():
            campaign = NewsletterCampaign.objects.select_for_update().get(pk=pk)
            if campaign.status != NewsletterCampaign.Status.SCHEDULED or campaign.scheduled_at > timezone.now():
                continue
            if not campaigns.has_current_test(campaign):
                campaign.status = NewsletterCampaign.Status.DRAFT
                campaign.scheduled_at = None
                campaign.save(update_fields=["status", "scheduled_at", "updated_at"])
                continue
            campaigns._snapshot_audience(campaign, campaign.started_by)  # noqa: SLF001 - queue shares the locked snapshot
    NewsletterCampaign.objects.filter(
        status=NewsletterCampaign.Status.PAUSED,
        pause_reason="allowance",
        next_attempt_at__lte=timezone.now(),
    ).update(status=NewsletterCampaign.Status.SENDING, pause_reason="", next_attempt_at=None)


def _review_stale_claims():
    ids = (
        NewsletterDelivery.objects.filter(
            status=NewsletterDelivery.Status.SENDING,
            attempted_at__lt=timezone.now() - timedelta(minutes=5),
        )
        .values_list("campaign_id", flat=True)
        .distinct()[:20]
    )
    for pk in ids:
        try:
            campaigns.mark_interrupted(pk)
        except ValidationError:
            # A live request may have completed between discovery and the lock.
            continue


def _lecture_body(template, notices):
    body = template.body_markdown + "\n\n## New in the library\n\n"
    included = []
    for notice in notices:
        title = re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", notice.title)
        entry = f"- [{title}]({notice.public_url})\n"
        if len(body) + len(entry) > MAX_MESSAGE_LENGTH:
            break
        body += entry
        included.append(notice)
    return body, included


def _prepare_lecture_digest():
    with transaction.atomic():
        policy = NewsletterAutomation.objects.select_for_update().get(pk=1)
        if not policy.lecture_enabled:
            return
        template = NewsletterCampaign.objects.select_for_update().filter(pk=policy.lecture_template_id).first()
        if (
            not template
            or not template.is_editable
            or template.version != policy.template_version
            or not campaigns.has_current_test(template)
        ):
            _pause_lecture_campaigns()
            policy.lecture_enabled = False
            policy.next_digest_at = None
            policy.lecture_error = "lecture_template_changed"
            policy.save(update_fields=["lecture_enabled", "next_digest_at", "lecture_error"])
            return
        _capture_lectures(NewsletterLectureNotice.Status.PENDING, maximum=100)
        if policy.next_digest_at and policy.next_digest_at > timezone.now():
            return
        public_ids = public_lectures().values("pk")
        NewsletterLectureNotice.objects.filter(status=NewsletterLectureNotice.Status.PENDING).exclude(
            lecture_id__in=public_ids,
        ).update(status=NewsletterLectureNotice.Status.EXCLUDED)
        notices = list(
            NewsletterLectureNotice.objects.filter(
                status=NewsletterLectureNotice.Status.PENDING,
                lecture_id__in=public_ids,
            ).select_related("lecture__concept__area")[:DIGEST_LIMIT],
        )
        if notices and campaigns.confirmed_subscribers().exists():
            for notice in notices:
                notice.title = notice.lecture.title
                notice.public_url = settings.PUBLIC_SITE_ORIGIN.rstrip("/") + notice.lecture.get_absolute_url()
            body, included = _lecture_body(template, notices)
            campaign = NewsletterCampaign.objects.create(
                subject=template.subject,
                preheader=template.preheader,
                body_markdown=body,
                created_by=template.created_by,
                lecture_template=template,
                lecture_template_version=template.version,
            )
            # Explicit policy activation approves this tested intro plus public lecture links.
            campaigns._snapshot_audience(campaign, template.created_by)  # noqa: SLF001
            NewsletterLectureNotice.objects.bulk_update(included, ["title", "public_url"])
            NewsletterLectureNotice.objects.filter(pk__in=[notice.pk for notice in included]).update(
                status=NewsletterLectureNotice.Status.INCLUDED,
                campaign=campaign,
            )
        policy.next_digest_at = next_digest(timezone.now(), policy.digest_time)
        policy.save(update_fields=["next_digest_at"])


def process_queue(*, maximum=20, seconds=50):
    if not settings.NEWSLETTER_BACKGROUND_ENABLED:
        msg = "Background newsletter sending is disabled."
        raise ValidationError(msg)
    token = acquire_lease()
    if token is None:
        return {"state": "busy", "processed": 0}
    processed, error = 0, ""
    deadline = time.monotonic() + seconds
    try:
        _review_stale_claims()
        _start_due_campaigns()
        _prepare_lecture_digest()
        while processed < maximum and time.monotonic() < deadline and renew_lease(token):
            campaign = (
                NewsletterCampaign.objects.filter(status=NewsletterCampaign.Status.SENDING)
                .exclude(
                    deliveries__status=NewsletterDelivery.Status.SENDING,
                )
                .order_by("updated_at", "pk")
                .first()
            )
            if campaign is None:
                break
            try:
                delivery = campaigns.send_next(None, campaign.pk)
            except ValidationError:
                # Rate limits and delivery-review pauses are durable campaign states.
                continue
            if delivery:
                processed += 1
            # Round-robin across campaigns without changing their frozen contents.
            NewsletterCampaign.objects.filter(pk=campaign.pk).update(updated_at=timezone.now())
    except Exception:  # noqa: BLE001 - never log addresses, tokens or provider diagnostics
        error = "worker_failed"
    finally:
        _release_lease(token, error)
    return {"state": "failed" if error else "finished", "processed": processed}
