"""Version-bound admin requests with durable claims and independent spending limits."""

import json
from datetime import UTC
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from inspinia.solutions.review_provider import ProviderError
from inspinia.users.roles import user_has_admin_role

from .community_forms import CONTENT_FIELDS
from .community_models import CommunityProblem
from .community_models import StatementAIReview
from .community_models import StatementReviewPolicy
from .statement_review_provider import MAX_OUTPUT_TOKENS
from .statement_review_provider import REPORT_SCHEMA
from .statement_review_provider import SYSTEM_PROMPT
from .statement_review_provider import generate_statement_review
from .statement_similarity import check_statement_similarity
from .statement_similarity import digest

MAX_INPUT_BYTES = 70000
LEASE_SECONDS = 150
DAILY_REQUEST_LIMIT = 20
REPORT_TEXT_LIMIT = 6000
REPORT_ITEM_LIMIT = 2000
MAX_REPORT_ITEMS = 8


class StatementReviewError(ValueError):
    pass


def snapshot_digest(snapshot):
    return digest(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))


def policy_ready(policy):
    now = timezone.now()
    return bool(
        getattr(settings, "PROBLEM_STATEMENT_AI_REVIEW_ENABLED", False)
        and getattr(settings, "OPENAI_API_KEY", "")
        and policy
        and policy.enabled
        and policy.model.strip()
        and policy.pricing_verified_at
        and now - timedelta(days=30) <= policy.pricing_verified_at <= now
        and min(
            policy.request_budget_micros,
            policy.daily_budget_micros,
            policy.monthly_budget_micros,
            policy.input_price_micros_per_million,
            policy.output_price_micros_per_million,
        )
        > 0
        and 1 <= policy.daily_request_limit <= DAILY_REQUEST_LIMIT,
    )


def token_cost(input_tokens, output_tokens, pricing):
    numerator = input_tokens * pricing["input_price"] + output_tokens * pricing["output_price"]
    return (numerator + 999999) // 1000000


@transaction.atomic
def enqueue_statement_review(user, problem_id, version, *, acknowledged=False):
    if not user_has_admin_role(user):
        message = "Only admins can request a statement review."
        raise StatementReviewError(message)
    if not acknowledged:
        message = (
            "Confirm that the statement, details, private outline, and library candidates will be sent to OpenAI."
        )
        raise StatementReviewError(message)
    policy = StatementReviewPolicy.objects.select_for_update().filter(pk=1).first()
    if not policy_ready(policy):
        message = "Statement AI review is not configured with an enabled, funded policy and current pricing."
        raise StatementReviewError(message)
    problem = CommunityProblem.objects.select_for_update().get(pk=problem_id)
    if problem.version != version or problem.status != CommunityProblem.Status.PENDING:
        message = "Review the current pending version of this problem."
        raise StatementReviewError(message)
    existing = StatementAIReview.objects.filter(problem=problem, version=version).first()
    if existing:
        return existing
    similarity = check_statement_similarity(problem.statement_latex)
    if not similarity["available"]:
        raise StatementReviewError(similarity["message"])
    snapshot = {field: getattr(problem, field) for field in CONTENT_FIELDS}
    snapshot["library_candidates"] = similarity["matches"]
    snapshot["similarity_limitations"] = similarity["message"]
    payload = json.dumps(snapshot, ensure_ascii=False)
    if len(payload.encode()) > MAX_INPUT_BYTES:
        message = "The review input is too large. Shorten the statement or supporting details."
        raise StatementReviewError(message)
    pricing = {
        "input_price": policy.input_price_micros_per_million,
        "output_price": policy.output_price_micros_per_million,
    }
    # UTF-8 bytes bound text token counts conservatively, including prompt/schema overhead.
    input_bound = len(payload.encode()) + len(SYSTEM_PROMPT.encode()) + len(json.dumps(REPORT_SCHEMA).encode()) + 2000
    reserve = token_cost(input_bound, MAX_OUTPUT_TOKENS, pricing)
    now = timezone.now().astimezone(UTC)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    jobs = StatementAIReview.objects.all()
    daily = jobs.filter(created_at__gte=day)
    daily_used = daily.aggregate(total=Sum("accounted_micros"))["total"] or 0
    monthly_used = jobs.filter(created_at__gte=month).aggregate(total=Sum("accounted_micros"))["total"] or 0
    if (
        reserve > policy.request_budget_micros
        or daily_used + reserve > policy.daily_budget_micros
        or monthly_used + reserve > policy.monthly_budget_micros
        or daily.count() >= policy.daily_request_limit
    ):
        message = "This request exceeds the configured statement review allowance."
        raise StatementReviewError(message)
    return StatementAIReview.objects.create(
        problem=problem,
        version=version,
        requested_by=user,
        input_snapshot=snapshot,
        input_digest=snapshot_digest(snapshot),
        model=policy.model,
        pricing_snapshot=pricing,
        reserved_micros=reserve,
        accounted_micros=reserve,
    )


def validate_report(report):
    required = set(REPORT_SCHEMA["required"])
    if not isinstance(report, dict) or set(report) != required:
        return False
    if report["assessment"] not in REPORT_SCHEMA["properties"]["assessment"]["enum"]:
        return False
    for key in ("summary", "similarity_assessment"):
        if not isinstance(report[key], str) or len(report[key]) > REPORT_TEXT_LIMIT:
            return False
    for key in ("issues", "metadata_suggestions", "limitations"):
        if not isinstance(report[key], list) or len(report[key]) > MAX_REPORT_ITEMS:
            return False
        if any(not isinstance(item, str) or len(item) > REPORT_ITEM_LIMIT for item in report[key]):
            return False
    return True


@transaction.atomic
def claim_statement_review():
    policy = StatementReviewPolicy.objects.select_for_update().filter(pk=1).first()
    if not policy_ready(policy):
        message = "Statement AI review is disabled or unconfigured."
        raise StatementReviewError(message)
    now = timezone.now()
    if policy.lease_until and policy.lease_until > now:
        return None
    StatementAIReview.objects.filter(status=StatementAIReview.Status.RUNNING).update(
        status=StatementAIReview.Status.UNKNOWN,
        error_code="worker_interrupted",
        completed_at=now,
    )
    job = (
        StatementAIReview.objects.select_for_update()
        .filter(status=StatementAIReview.Status.QUEUED)
        .order_by(
            "created_at",
        )
        .first()
    )
    if job is None:
        return None
    job.status, job.dispatched_at = StatementAIReview.Status.RUNNING, now
    job.save(update_fields=["status", "dispatched_at"])
    policy.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    policy.lease_job_id = job.pk
    policy.save(update_fields=["lease_until", "lease_job_id", "updated_at"])
    return job


def process_statement_review(provider=None):
    job = claim_statement_review()
    if job is None:
        return "idle"
    try:
        current = CommunityProblem.objects.get(pk=job.problem_id)
        if (
            current.version != job.version
            or current.status != CommunityProblem.Status.PENDING
            or not user_has_admin_role(job.requested_by)
            or job.created_at < timezone.now() - timedelta(minutes=15)
        ):
            job.status, job.error_code, job.accounted_micros = StatementAIReview.Status.EXPIRED, "stale_request", 0
        elif snapshot_digest(job.input_snapshot) != job.input_digest:
            job.status, job.error_code, job.accounted_micros = StatementAIReview.Status.FAILED, "input_changed", 0
        else:
            result = (provider or generate_statement_review)(job)
            job.provider_response_id, job.provider_request_id = result.response_id, result.request_id
            job.usage = result.usage or {}
            job.feedback = result.feedback if validate_report(result.feedback) else {}
            job.status = StatementAIReview.Status.COMPLETED if job.feedback else StatementAIReview.Status.FAILED
            job.error_code = "" if job.feedback else "invalid_report"
    except ProviderError as error:
        job.status = StatementAIReview.Status.FAILED if error.definitive else StatementAIReview.Status.UNKNOWN
        job.error_code, job.usage = error.code, error.usage or {}
        job.provider_request_id, job.provider_response_id = error.request_id, error.response_id
    except Exception:  # noqa: BLE001 - never replay a dispatched request after an unexpected failure.
        job.status, job.error_code = StatementAIReview.Status.UNKNOWN, "unexpected_worker_error"
    finally:
        usage = job.usage
        input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
        if type(input_tokens) is int and type(output_tokens) is int and min(input_tokens, output_tokens) >= 0:
            job.accounted_micros = token_cost(input_tokens, output_tokens, job.pricing_snapshot)
        job.completed_at = timezone.now()
        with transaction.atomic():
            policy = StatementReviewPolicy.objects.select_for_update().get(pk=1)
            job.save()
            if policy.lease_job_id == job.pk:
                policy.lease_until, policy.lease_job_id = None, None
            if job.accounted_micros > job.reserved_micros:
                policy.enabled = False
            policy.save(update_fields=["lease_until", "lease_job_id", "enabled", "updated_at"])
    return job.status
