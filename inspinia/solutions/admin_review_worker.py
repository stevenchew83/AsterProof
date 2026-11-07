"""Process one claimed draft or notification per invocation, without automatic retries."""

import logging
from datetime import timedelta
from time import monotonic

from allauth.account.adapter import get_adapter
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from inspinia.pages.study_help_access import lock_study_help
from inspinia.users.roles import user_has_admin_role

from . import forum
from .admin_review_models import AdminSolutionReview
from .admin_review_models import SelfSolutionReviewUsage
from .admin_review_provider import MAX_RESPONSE_CHARS
from .admin_review_provider import ReviewProviderError
from .admin_review_provider import request_review
from .admin_review_provider import scored_result
from .admin_reviews import REVIEWABLE_STATES
from .admin_reviews import approved_user
from .admin_reviews import problem_label
from .admin_reviews import read_credential
from .admin_reviews import review_settings
from .admin_reviews import self_review_restricted

logger = logging.getLogger(__name__)
Status = AdminSolutionReview.Status
Notice = AdminSolutionReview.Notification
CLAIM_AGE = timedelta(minutes=15)
QUEUE_AGE = timedelta(days=1)
PREVIEW_INTERVAL = 1.5


def _review_jobs():
    return AdminSolutionReview.objects.select_related(
        "target__solution__problem", "target__solution__current_revision", "requested_by", "solver", "self_request",
    )


def _claim(query, field, states, time_field, now):
    waiting, working = states
    for pk in query.values_list("pk", flat=True)[:10]:
        if AdminSolutionReview.objects.filter(pk=pk, **{field: waiting}).update(**{
            field: working, time_field: now,
        }):
            return _review_jobs().filter(pk=pk).first()
    return None


@transaction.atomic
def _finish(review, status, **values):
    completed_self_request = status == Status.COMPLETED and getattr(review, "self_request", None)
    if completed_self_request:
        lock_study_help()
        current = _review_jobs().filter(pk=review.pk, status=Status.RUNNING).first()
        if current is None or not _eligible(current, review_settings()):
            status = Status.FAILED
            values.pop("score")
            values["error"] = "The proof or review eligibility changed before the draft was saved."
    if status != Status.COMPLETED:
        values["feedback"] = ""
    updated = AdminSolutionReview.objects.filter(pk=review.pk, status=Status.RUNNING).update(status=status, **values)
    if updated and status == Status.COMPLETED and completed_self_request:
        SelfSolutionReviewUsage.objects.filter(review=review).update(succeeded=True)
    return status


def _preview_writer(review):
    last_update = 0.0

    def write(preview):
        nonlocal last_update
        now = monotonic()
        if not preview or now - last_update < PREVIEW_INTERVAL:
            return
        safe_text = preview.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")
        AdminSolutionReview.objects.filter(pk=review.pk, status=Status.RUNNING).update(feedback=safe_text)
        last_update = now

    return write


def _eligible(review, config):
    solution = review.target.solution
    requester = review.requested_by
    if not approved_user(requester):
        return False
    request = getattr(review, "self_request", None)
    if request:
        permitted = (
            settings.SELF_SOLUTION_REVIEW_ENABLED
            and request.user_id == requester.pk == solution.author_id
            and not self_review_restricted(requester, solution.problem.problem_uuid, review.target.statement_id_value)
        )
    else:
        permitted = user_has_admin_role(requester)
    return (
        config and config.key_version == review.key_version
        and permitted
        and review.solver_id == solution.author_id
        and solution.status in REVIEWABLE_STATES
        and review.problem_label == problem_label(solution)
        and review.target.key == forum.current_target_data(solution)["key"]
    )


@sensitive_variables("key")
def _generate(review):
    config = review_settings()
    key = read_credential(config)
    if not key or not _eligible(review, config):
        return _finish(
            review, Status.FAILED, error="The proof, requester permissions, or OpenAI key is no longer current.",
        )
    try:
        response = request_review(review, key, on_preview=_preview_writer(review))
        raw = response.output_text or ""
    except ReviewProviderError as error:
        return _finish(review, Status.UNKNOWN if error.uncertain else Status.FAILED, error=str(error))
    except Exception:  # noqa: BLE001 - provider exceptions can contain credentials or submitted text
        logger.warning("Admin AI review %s: unexpected provider outcome", review.pk)
        return _finish(review, Status.UNKNOWN, error="The provider outcome could not be confirmed.")
    fields = {
        "response_text": raw[:MAX_RESPONSE_CHARS].replace("\x00", "").encode("utf-8", "replace").decode("utf-8"),
        "provider_response_id": (response.id or "")[:200],
    }
    result = scored_result(raw) if response.status == "completed" and len(raw) <= MAX_RESPONSE_CHARS else None
    if result is None:
        return _finish(review, Status.FAILED, error="OpenAI did not return usable seven-point feedback.", **fields)
    return _finish(review, Status.COMPLETED, score=result[0], feedback=result[1], **fields)


def _notify(review):
    author = review.solver
    if not author.is_active or not author.email or author.pk != review.target.solution.author_id:
        state = Notice.FAILED
    else:
        url = (
            settings.PUBLIC_SITE_ORIGIN.rstrip("/")
            + reverse("solutions:solution_detail", args=[review.target.solution_id])
            + f"?ai_review={review.pk}#ai-review-{review.pk}"
        )
        try:
            message = get_adapter().render_mail(
                "account/email/solution_review", author.email,
                {"review_url": url},
            )
            state = Notice.SENT if message.send() == 1 else Notice.FAILED
        except Exception:  # noqa: BLE001 - mail errors may contain addresses or credentials
            logger.warning("Admin AI review %s: email outcome unknown", review.pk)
            state = Notice.UNKNOWN
    AdminSolutionReview.objects.filter(pk=review.pk, notification=Notice.SENDING).update(notification=state)
    return state


def process_next():
    now = timezone.now()
    jobs = AdminSolutionReview.objects
    jobs.filter(notification=Notice.SENDING, notification_started_at__lt=now - CLAIM_AGE).update(
        notification=Notice.UNKNOWN,
    )
    jobs.filter(status=Status.RUNNING, started_at__lt=now - CLAIM_AGE).update(
        status=Status.UNKNOWN, feedback="", error="The worker stopped before confirming the provider outcome.",
    )
    jobs.filter(status=Status.QUEUED, created_at__lt=now - QUEUE_AGE).update(
        status=Status.FAILED, error="This review expired before a worker picked it up.",
    )
    pending = jobs.filter(notification=Notice.PENDING, published_at__isnull=False).order_by("published_at", "pk")
    notice = _claim(pending, "notification", (Notice.PENDING, Notice.SENDING), "notification_started_at", now)
    if notice:
        return {"review": str(notice.pk), "notification": _notify(notice)}
    if not settings.ADMIN_SOLUTION_REVIEW_ENABLED:
        return {"status": "disabled"}
    queued = jobs.filter(status=Status.QUEUED).order_by("created_at", "pk")
    review = _claim(queued, "status", (Status.QUEUED, Status.RUNNING), "started_at", now)
    return {"review": str(review.pk), "status": _generate(review)} if review else {"status": "idle"}
