from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import ProgrammingError
from django.db import transaction
from django.db.utils import OperationalError
from django.utils import timezone

from inspinia.backoffice.models import AbusePolicy
from inspinia.backoffice.models import ContentRevision
from inspinia.backoffice.models import FeatureFlagConfig
from inspinia.backoffice.models import ModerationAction
from inspinia.backoffice.models import ModerationLog
from inspinia.backoffice.models import PrivacyDefaultsConfig
from inspinia.backoffice.models import RatingConfig
from inspinia.backoffice.models import RatingRun
from inspinia.backoffice.models import RatingRunEntry
from inspinia.backoffice.models import RatingRunStatus
from inspinia.backoffice.models import Report
from inspinia.backoffice.models import ReportStatus


def get_effective_feature_flags() -> dict[str, bool]:
    flags = dict(getattr(settings, "FEATURE_FLAGS", {}))
    if not apps.is_installed("inspinia.backoffice"):
        return flags
    try:
        cfg = FeatureFlagConfig.load()
    except (OperationalError, ProgrammingError):
        return flags

    flags.update(
        {
            "contests": cfg.contests,
            "ratings": cfg.ratings,
            "contests_rating": cfg.contests and cfg.ratings,
            "feedback_hub": cfg.problem_submissions,
            "profiles_analytics": cfg.public_dashboards,
            "catalog": True,
            "progress_notes": True,
            "community": True,
            "organization": True,
            "advanced_analytics": cfg.advanced_analytics,
        },
    )
    return flags


def get_rating_config() -> RatingConfig:
    return RatingConfig.load()


def get_privacy_defaults() -> PrivacyDefaultsConfig:
    return PrivacyDefaultsConfig.load()


def validate_abuse_policy(user, text: str) -> str | None:  # noqa: ANN001
    if not text:
        return None
    try:
        policy = AbusePolicy.load()
    except (OperationalError, ProgrammingError):
        return None

    links = re.findall(r"https?://", text, flags=re.IGNORECASE)
    if len(links) > policy.max_external_links_per_post:
        return "Too many external links in one post."

    bad_words = [w.strip().lower() for w in re.split(r"[,\n]+", policy.bad_word_list) if w.strip()]
    text_lower = text.lower()
    for word in bad_words:
        if word and word in text_lower:
            return "Content includes blocked terms."

    if not getattr(user, "is_authenticated", False):
        return None

    from inspinia.community.models import Comment
    from inspinia.community.models import PublicSolution

    now = timezone.now()
    minute_ago = now - timedelta(minutes=1)
    hour_ago = now - timedelta(hours=1)

    posts_minute = (
        Comment.objects.filter(author=user, created_at__gte=minute_ago).count()
        + PublicSolution.objects.filter(author=user, created_at__gte=minute_ago).count()
    )
    posts_hour = (
        Comment.objects.filter(author=user, created_at__gte=hour_ago).count()
        + PublicSolution.objects.filter(author=user, created_at__gte=hour_ago).count()
    )

    if posts_minute >= policy.comment_limit_per_minute:
        return "Posting limit exceeded for this minute."
    if posts_hour >= policy.comment_limit_per_hour:
        return "Posting limit exceeded for this hour."
    return None


def _target_content_type(target):  # noqa: ANN001
    return ContentType.objects.get_for_model(target.__class__)


def create_moderation_log(
    *,
    actor,
    action: str,
    reason: str = "",
    report: Report | None = None,
    target=None,
    target_user=None,
    metadata: dict[str, Any] | None = None,
):
    content_type = None
    object_id = None
    if target is not None:
        content_type = _target_content_type(target)
        object_id = target.pk
    return ModerationLog.objects.create(
        actor=actor,
        action=action,
        reason=reason,
        report=report,
        target_user=target_user,
        content_type=content_type,
        object_id=object_id,
        metadata=metadata or {},
    )


def _has_field(obj, field_name: str) -> bool:  # noqa: ANN001
    return any(field.name == field_name for field in obj._meta.get_fields())


@transaction.atomic
def hide_target(*, actor, target, reason: str = "", report: Report | None = None):
    if _has_field(target, "is_hidden"):
        target.is_hidden = True
        target.save(update_fields=["is_hidden"])
    elif _has_field(target, "status") and target.__class__.__name__ == "Problem":
        target.status = "hidden"
        target.save(update_fields=["status"])
    elif _has_field(target, "is_profile_hidden"):
        target.is_profile_hidden = True
        target.save(update_fields=["is_profile_hidden"])
    create_moderation_log(actor=actor, action=ModerationAction.HIDE, reason=reason, report=report, target=target)


@transaction.atomic
def unhide_target(*, actor, target, reason: str = "", report: Report | None = None):
    if _has_field(target, "is_hidden"):
        target.is_hidden = False
        target.save(update_fields=["is_hidden"])
    elif _has_field(target, "status") and target.__class__.__name__ == "Problem":
        target.status = "active"
        target.save(update_fields=["status"])
    elif _has_field(target, "is_profile_hidden"):
        target.is_profile_hidden = False
        target.save(update_fields=["is_profile_hidden"])
    create_moderation_log(actor=actor, action=ModerationAction.UNHIDE, reason=reason, report=report, target=target)


@transaction.atomic
def redact_target(*, actor, target, replacement_text: str, reason: str = "", report: Report | None = None):
    text_field = None
    if _has_field(target, "content"):
        text_field = "content"
    elif _has_field(target, "statement"):
        text_field = "statement"
    elif _has_field(target, "bio"):
        text_field = "bio"
    if text_field is None:
        return

    old_text = getattr(target, text_field)
    if old_text == replacement_text:
        return

    setattr(target, text_field, replacement_text)
    update_fields = [text_field]
    if _has_field(target, "is_moderator_edited"):
        target.is_moderator_edited = True
        update_fields.append("is_moderator_edited")
    target.save(update_fields=update_fields)

    log = create_moderation_log(
        actor=actor,
        action=ModerationAction.REDACT,
        reason=reason,
        report=report,
        target=target,
    )
    ContentRevision.objects.create(
        content_type=_target_content_type(target),
        object_id=target.pk,
        previous_text=old_text,
        new_text=replacement_text,
        edited_by=actor,
        moderation_log=log,
    )


@transaction.atomic
def set_user_state(*, actor, target_user, action: str, reason: str = "", mute_until=None):
    metadata: dict[str, Any] = {}
    if action == ModerationAction.WARN:
        pass
    elif action == ModerationAction.MUTE:
        target_user.mute_expires_at = mute_until
        target_user.save(update_fields=["mute_expires_at"])
        metadata["mute_until"] = mute_until.isoformat() if mute_until else None
    elif action == ModerationAction.BAN:
        target_user.is_banned = True
        target_user.is_active = False
        target_user.save(update_fields=["is_banned", "is_active"])
    elif action == ModerationAction.SHADOW_BAN:
        target_user.is_shadow_banned = True
        target_user.save(update_fields=["is_shadow_banned"])

    create_moderation_log(
        actor=actor,
        action=action,
        reason=reason,
        target_user=target_user,
        metadata=metadata,
    )


@transaction.atomic
def clear_user_state(*, actor, target_user, action: str, reason: str = ""):
    if action == ModerationAction.MUTE:
        target_user.mute_expires_at = None
        target_user.save(update_fields=["mute_expires_at"])
        cleared_action = ModerationAction.MUTE
    elif action == ModerationAction.BAN:
        target_user.is_banned = False
        target_user.is_active = True
        target_user.save(update_fields=["is_banned", "is_active"])
        cleared_action = ModerationAction.BAN
    elif action == ModerationAction.SHADOW_BAN:
        target_user.is_shadow_banned = False
        target_user.save(update_fields=["is_shadow_banned"])
        cleared_action = ModerationAction.SHADOW_BAN
    else:
        return

    create_moderation_log(
        actor=actor,
        action=cleared_action,
        reason=reason,
        target_user=target_user,
        metadata={"cleared": True},
    )


@transaction.atomic
def resolve_report(*, actor, report: Report, status: str, note: str = "", action: str = ""):
    report.status = status
    report.resolution_note = note
    report.resolved_by = actor
    report.resolved_at = timezone.now()
    report.save(update_fields=["status", "resolution_note", "resolved_by", "resolved_at", "updated_at"])
    log_action = ModerationAction.RESOLVE if status == ReportStatus.RESOLVED else ModerationAction.DISMISS
    if status == ReportStatus.ESCALATED:
        log_action = ModerationAction.ESCALATE
    create_moderation_log(actor=actor, action=log_action, reason=note or action, report=report, target=report.target)


@transaction.atomic
def apply_rating_run(*, contest, triggered_by=None):
    from inspinia.contests.services import apply_simple_elo

    cfg = get_rating_config()
    run = RatingRun.objects.create(
        contest=contest,
        triggered_by=triggered_by,
        status=RatingRunStatus.APPLIED,
        config_snapshot={
            "base_rating": cfg.base_rating,
            "k_factor": cfg.k_factor,
            "small_contest_threshold": cfg.small_contest_threshold,
            "small_contest_k_multiplier": cfg.small_contest_k_multiplier,
            "rating_floor": cfg.rating_floor,
            "rating_cap": cfg.rating_cap,
        },
    )
    snapshots = apply_simple_elo(contest_id=contest.id, config=cfg)
    for row in snapshots:
        RatingRunEntry.objects.create(
            run=run,
            user=row["user"],
            previous_rating=row["previous_rating"],
            new_rating=row["new_rating"],
            delta=row["delta"],
        )
    return run


@transaction.atomic
def rollback_rating_run(*, run: RatingRun, triggered_by=None):
    if run.is_rollback:
        return None
    rollback_run = RatingRun.objects.create(
        contest=run.contest,
        triggered_by=triggered_by,
        status=RatingRunStatus.ROLLED_BACK,
        is_rollback=True,
        parent_run=run,
        config_snapshot=run.config_snapshot,
    )
    for entry in run.entries.select_related("user"):
        user = entry.user
        current_rating = user.rating
        user.rating = entry.previous_rating
        user.save(update_fields=["rating"])
        RatingRunEntry.objects.create(
            run=rollback_run,
            user=user,
            previous_rating=current_rating,
            new_rating=entry.previous_rating,
            delta=entry.previous_rating - current_rating,
        )
    run.status = RatingRunStatus.ROLLED_BACK
    run.save(update_fields=["status"])
    return rollback_run
