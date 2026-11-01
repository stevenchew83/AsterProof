"""Bounded, private AI coaching with one dispatch per durable queue claim."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC
from datetime import timedelta
from io import BytesIO

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from PIL import Image

from inspinia.pages.models import ContestProblemStatement
from inspinia.solutions.models import SolutionBodyImage
from inspinia.solutions.models import SolutionRevision
from inspinia.solutions.review_models import SolutionReview
from inspinia.solutions.review_models import SolutionReviewPolicy

from .evaluation import EvaluationError

PILOT_GROUP = "solution-ai-pilot"
MAX_SOURCE = 64_000
MAX_STATEMENT = 12_000
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_OUTPUT_TOKENS = 16_000
MIN_IMAGE_TOKEN_BOUND = 16_384
MAX_FINDINGS = 8
CURRENT_REVIEW_SCHEMA = 2
USER_DAILY_LIMIT = 3
GLOBAL_DAILY_LIMIT = 20
PRICED_MODEL = "gpt-6-astra"
MODEL_CONTEXT_TOKENS = 1_050_000
LONG_CONTEXT_THRESHOLD = 272_000
MIN_INPUT_PRICE = 10_000_000
MIN_OUTPUT_PRICE = 50_000_000
REQUEST_TIMEOUT = 300
LEASE_SECONDS = 360
QUEUE_TTL = timedelta(minutes=15)
PRICE_REVIEW_TTL = timedelta(days=30)
IMAGE_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
IMAGE_PATH_RE = re.compile(r"solution_body_images/[0-9a-f]{32}\.(?:png|jpe?g|gif|webp)", re.IGNORECASE)
ASSESSMENTS = {"no_issues_found", "gap_found", "incomplete", "unable_to_assess"}
FINDING_TYPES = {"logical_gap", "invalid_step", "missing_case", "unclear_argument", "notation"}
SEVERITIES = {"minor", "major", "critical"}


ERROR_MESSAGES = {
    "review_disabled": "AI review is not available right now.",
    "pilot_only": "AI review is currently available to invited pilot users.",
    "worker_unavailable": "The review worker is unavailable. Your writing is saved.",
    "image_too_large": "Each review image must be at most 3 MB.",
    "invalid_image": "Use PNG, JPEG, GIF, or WebP review images.",
    "too_many_images": "AI review supports at most four images per solution.",
    "unowned_image": "AI review accepts only images uploaded to this solution.",
    "statement_required": "Supply and confirm the problem statement before requesting review.",
    "input_too_long": "This document is too long for AI review. Your complete solution remains saved.",
    "empty_solution": "Write and save a solution before requesting review.",
    "request_budget": "This review exceeds the configured per-request allowance.",
    "user_daily_limit": "You have reached today's review allowance.",
    "global_daily_limit": "Today's pilot review allowance has been reached.",
    "review_budget": "The pilot review budget has been reached.",
    "review_in_progress": "You already have a review in progress.",
    "authentication_required": "Sign in to request AI review.",
    "invalid_identifier": "A saved revision and request identifier are required.",
    "idempotency_conflict": "This request identifier belongs to another review.",
    "not_found": "The requested solution was not found.",
    "stale_revision": "Save and review the current solution version.",
    "acknowledgement_required": (
        "Acknowledge that your statement, proof, and referenced images will be sent to OpenAI."
    ),
    "invalid_report": "The reviewer returned an invalid report.",
    "input_changed": "The frozen review input has changed.",
    "image_missing": "A review image is no longer available.",
    "image_changed": "A review image has changed since the request.",
}


class ReviewError(ValueError):
    def __init__(self, message=None, *, code="invalid_review", status=422):
        super().__init__(message or ERROR_MESSAGES.get(code, "The review request is invalid."))
        self.code = code
        self.status = status


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _configured(policy):
    verified = policy.pricing_verified_at if policy else None
    now = timezone.now()
    current_pricing = bool(
        verified and timezone.is_aware(verified) and now - PRICE_REVIEW_TTL <= verified <= now,
    )
    return bool(
        getattr(settings, "SOLUTION_AI_REVIEW_ENABLED", False)
        and getattr(settings, "SOLUTION_AI_EXECUTION_MODE", "offline") == "fixture"
        and policy
        and policy.enabled
        and policy.daily_budget_micros > 0
        and policy.monthly_budget_micros > 0
        and policy.request_budget_micros > 0
        and current_pricing
        and 1 <= policy.user_daily_limit <= USER_DAILY_LIMIT
        and 1 <= policy.global_daily_limit <= GLOBAL_DAILY_LIMIT
        and policy.input_price_micros_per_million >= MIN_INPUT_PRICE
        and policy.output_price_micros_per_million >= MIN_OUTPUT_PRICE
        and policy.image_token_bound >= MIN_IMAGE_TOKEN_BOUND
        and policy.model == PRICED_MODEL,
    )


def review_available(user):
    if not user.is_authenticated or not getattr(settings, "SOLUTION_AI_REVIEW_ENABLED", False):
        return False
    policy = SolutionReviewPolicy.objects.filter(singleton_key=1).first()
    return _configured(policy) and user.groups.filter(name=PILOT_GROUP).exists()


def _require_policy(user):
    policy = SolutionReviewPolicy.objects.select_for_update().filter(singleton_key=1).first()
    if not _configured(policy):
        raise ReviewError(code="review_disabled", status=503)
    if not user.groups.filter(name=PILOT_GROUP).exists():
        raise ReviewError(code="pilot_only", status=403)
    now = timezone.now()
    seen = policy.worker_seen_at
    worker_active = policy.lease_until and policy.lease_until > now
    if not worker_active and (not seen or seen < now - timedelta(minutes=2)):
        raise ReviewError(code="worker_unavailable", status=503)
    return policy


def _without_comments(source):
    lines = []
    for line in source.splitlines():
        visible = line
        for index, char in enumerate(line):
            if char != "%":
                continue
            previous = index - 1
            while previous >= 0 and line[previous] == "\\":
                previous -= 1
            if (index - previous - 1) % 2 == 0:
                visible = line[:index]
                break
        lines.append(visible)
    return "\n".join(lines)


def _read_image(image):
    try:
        with image.file.open("rb") as handle:
            data = handle.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise ReviewError(code="image_too_large")
        with Image.open(BytesIO(data)) as picture:
            if picture.format not in {"PNG", "JPEG", "GIF", "WEBP"}:
                raise ReviewError(code="invalid_image")
            width, height = picture.size
            if width * height > MAX_IMAGE_PIXELS or getattr(picture, "is_animated", False):
                raise ReviewError(code="invalid_image")
            picture.verify()
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        if isinstance(error, ReviewError):
            raise
        raise ReviewError(code="invalid_image") from error
    return data, {
        "path": image.file.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": width,
        "height": height,
    }


def _image_manifest(revision):
    paths = list(dict.fromkeys(IMAGE_RE.findall(_without_comments(revision.body_source))))
    if len(paths) > MAX_IMAGES:
        raise ReviewError(code="too_many_images")
    manifest = []
    for path in paths:
        if not IMAGE_PATH_RE.fullmatch(path):
            raise ReviewError(code="unowned_image")
        image = SolutionBodyImage.objects.filter(solution_id=revision.solution_id, file=path).first()
        if image is None:
            raise ReviewError(code="unowned_image")
        _data, details = _read_image(image)
        manifest.append(details)
    return manifest


def _statement(problem_id):
    return (
        ContestProblemStatement.objects.filter(linked_problem_id=problem_id, is_active=True)
        .order_by(
            "-updated_at",
            "-id",
        )
        .first()
    )


def _snapshot(revision, statement_text, statement_confirmed):
    statement = _statement(revision.solution.problem_id)
    canonical_statement = statement if statement and (statement.statement_latex or "").strip() else None
    if canonical_statement:
        statement_text = statement.statement_latex or ""
    elif not statement_confirmed:
        raise ReviewError(code="statement_required")
    if not isinstance(statement_text, str) or not statement_text.strip():
        raise ReviewError(code="statement_required")
    if len(statement_text) > MAX_STATEMENT or len(revision.body_source) > MAX_SOURCE:
        raise ReviewError(code="input_too_long")
    if not revision.body_source.strip():
        raise ReviewError(code="empty_solution")
    diagram_source_only = bool(re.search(r"\\begin\{asy\}|\[asy\]", statement_text))
    return {
        "revision_id": str(revision.pk),
        "edit_version": revision.solution.edit_version,
        "body_source": revision.body_source,
        "source_digest": _digest(revision.body_source),
        "statement": statement_text,
        "statement_digest": _digest(statement_text),
        "statement_id": canonical_statement.pk if canonical_statement else None,
        "images": _image_manifest(revision),
        "diagram_source_only": diagram_source_only,
    }


def _reservation(policy, snapshot):
    # UTF-8 bytes conservatively bound text tokens, including prompt overhead.
    text_bytes = len(_json({key: value for key, value in snapshot.items() if key != "images"}).encode()) + 12_000
    # Vision tokenization has no application-proven per-image bound. Reserve the
    # model's entire context whenever images are present, including the long-
    # context pricing tier. Activation must explicitly fund this upper bound.
    input_tokens = MODEL_CONTEXT_TOKENS if snapshot["images"] else text_bytes
    upper = _token_cost(
        input_tokens,
        MAX_OUTPUT_TOKENS,
        {
            "input": policy.input_price_micros_per_million,
            "output": policy.output_price_micros_per_million,
        },
    )
    if upper > policy.request_budget_micros:
        raise ReviewError(code="request_budget", status=429)
    return upper


def _token_cost(input_tokens, output_tokens, pricing):
    long_context = input_tokens > pricing.get("long_context_threshold", LONG_CONTEXT_THRESHOLD)
    input_weight, output_weight = (
        (pricing.get("long_input_weight", 4), pricing.get("long_output_weight", 3)) if long_context else (2, 2)
    )
    numerator = input_tokens * pricing["input"] * input_weight + output_tokens * pricing["output"] * output_weight
    # Two in the denominator represents the 1.5x long-context output multiplier.
    return (numerator + 1_999_999) // 2_000_000


def _reserve_budget(policy, user, amount):
    from .evaluation_execution import accepted_request_counts
    from .evaluation_execution import ledger_totals

    now = timezone.now().astimezone(UTC)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    active = SolutionReview.objects.exclude(status=SolutionReview.Status.EXPIRED)
    day_jobs = active.filter(created_at__gte=day)
    user_requests, global_requests = accepted_request_counts(user, day)
    legacy = day_jobs.filter(execution__isnull=True)
    if legacy.filter(author=user).count() + user_requests >= min(policy.user_daily_limit, USER_DAILY_LIMIT):
        raise ReviewError(code="user_daily_limit", status=429)
    if legacy.count() + global_requests >= min(policy.global_daily_limit, GLOBAL_DAILY_LIMIT):
        raise ReviewError(code="global_daily_limit", status=429)
    daily = day_jobs.filter(execution__isnull=True).aggregate(total=Sum("accounted_micros"))["total"] or 0
    monthly = (
        active.filter(created_at__gte=month, execution__isnull=True).aggregate(total=Sum("accounted_micros"))["total"]
        or 0
    )
    daily += ledger_totals(day)
    monthly += ledger_totals(month)
    if daily + amount > policy.daily_budget_micros or monthly + amount > policy.monthly_budget_micros:
        raise ReviewError(code="review_budget", status=429)
    if active.filter(author=user, status__in=[SolutionReview.Status.QUEUED, SolutionReview.Status.RUNNING]).exists():
        raise ReviewError(code="review_in_progress", status=409)


def enqueue_review(  # noqa: PLR0913 - explicit immutable inputs form the public service contract
    user,
    problem_uuid,
    revision_id,
    idempotency_key,
    *,
    acknowledged=False,
    statement_text="",
    statement_confirmed=False,
):
    if not user.is_authenticated:
        raise ReviewError(code="authentication_required", status=401)
    try:
        key = uuid.UUID(str(idempotency_key))
        revision_key = uuid.UUID(str(revision_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise ReviewError(code="invalid_identifier") from error
    with transaction.atomic():
        existing = SolutionReview.objects.filter(author=user, idempotency_key=key).first()
        if existing:
            if existing.revision_id != revision_key or str(existing.revision.solution.problem.problem_uuid) != str(
                problem_uuid,
            ):
                raise ReviewError(code="idempotency_conflict", status=409)
            return existing, False
        policy = _require_policy(user)
        from .evaluation_execution import assert_assistance

        assert_assistance(user, problem_uuid)
        # The policy lock serializes competing enqueues, including duplicate
        # requests which were not visible before waiting for that lock.
        existing = SolutionReview.objects.filter(author=user, idempotency_key=key).first()
        if existing:
            if existing.revision_id != revision_key or str(existing.revision.solution.problem.problem_uuid) != str(
                problem_uuid,
            ):
                raise ReviewError(code="idempotency_conflict", status=409)
            return existing, False
        revision = (
            SolutionRevision.objects.select_related("solution__problem")
            .filter(
                pk=revision_key,
                solution__author=user,
                solution__problem__problem_uuid=problem_uuid,
            )
            .first()
        )
        if revision is None:
            raise ReviewError(code="not_found", status=404)
        if revision.solution.current_revision_id != revision.pk:
            raise ReviewError(code="stale_revision", status=409)
        if not acknowledged and not SolutionReview.objects.filter(author=user).exists():
            raise ReviewError(code="acknowledgement_required")
        snapshot = _snapshot(revision, statement_text, statement_confirmed)
        amount = _reservation(policy, snapshot)
        _reserve_budget(policy, user, amount)
        review = SolutionReview.objects.create(
            author=user,
            revision=revision,
            idempotency_key=key,
            input_snapshot=snapshot,
            input_digest=_digest(_json(snapshot)),
            model=policy.model,
            reserved_micros=amount,
            accounted_micros=amount,
            acknowledged_at=timezone.now(),
            pricing_snapshot={
                "input": policy.input_price_micros_per_million,
                "output": policy.output_price_micros_per_million,
                "image_token_bound": policy.image_token_bound,
                "long_context_threshold": LONG_CONTEXT_THRESHOLD,
                "long_input_weight": 4,
                "long_output_weight": 3,
                "currency": "USD",
            },
            schema_version=2,
        )
        from .evaluation_execution import bind_review

        bind_review(review)
    return review, True


def _text(value, maximum):
    return isinstance(value, str) and len(value) <= maximum


def _strings(value, count, length):
    return isinstance(value, list) and len(value) <= count and all(_text(item, length) for item in value)


def validate_feedback(value, source):
    keys = {"assessment", "summary", "strengths", "findings", "next_step", "limitations"}
    valid = (
        isinstance(value, dict)
        and set(value) == keys
        and isinstance(value.get("assessment"), str)
        and value["assessment"] in ASSESSMENTS
    )
    if not valid or not _text(value.get("summary"), 2000) or not _text(value.get("next_step"), 1000):
        raise ReviewError(code="invalid_report")
    if not _strings(value["strengths"], 3, 500) or not _strings(value["limitations"], 5, 500):
        raise ReviewError(code="invalid_report")
    findings = value.get("findings")
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        raise ReviewError(code="invalid_report")
    cleaned = [_validate_finding(finding, source) for finding in findings]
    if value["assessment"] == "no_issues_found" and any(row["severity"] in {"major", "critical"} for row in cleaned):
        raise ReviewError(code="invalid_report")
    return {**value, "findings": cleaned}


def _validate_finding(finding, source):
    keys = {"category", "severity", "quote", "context_before", "context_after", "explanation", "hints"}
    if not isinstance(finding, dict) or set(finding) != keys:
        raise ReviewError(code="invalid_report")
    valid = (
        isinstance(finding["category"], str)
        and finding["category"] in FINDING_TYPES
        and isinstance(finding["severity"], str)
        and finding["severity"] in SEVERITIES
    )
    valid = (
        valid
        and all(
            _text(finding[key], limit)
            for key, limit in {
                "quote": 2000,
                "context_before": 300,
                "context_after": 300,
                "explanation": 1500,
            }.items()
        )
        and _strings(finding["hints"], 2, 1000)
    )
    if not valid:
        raise ReviewError(code="invalid_report")
    quote = finding["quote"]
    locations = [match.start() for match in re.finditer(re.escape(quote), source)] if quote else []
    if len(locations) > 1:
        locations = [
            position
            for position in locations
            if source[:position].endswith(finding["context_before"])
            and source[position + len(quote) :].startswith(finding["context_after"])
        ]
    anchor = None
    if len(locations) == 1:
        position = locations[0]
        # Lines avoid Python-codepoint versus browser-UTF16 offset ambiguity.
        anchor = {
            "line": source.count("\n", 0, position) + 1,
            "end_line": source.count("\n", 0, position + len(quote)) + 1,
        }
    return {**finding, "anchor": anchor}


def review_payload(review, hint_level=0):
    from .evaluation import digest
    from .evaluation_execution import assert_assistance
    from .evaluation_execution import finding_identity
    from .evaluation_models import HintRevealEvent

    assert_assistance(review.author, review.revision.solution.problem.problem_uuid, delivery=True, review=review)
    snapshot = review.input_snapshot
    solution = review.revision.solution
    current_statement = _statement(solution.problem_id)
    if current_statement and not (current_statement.statement_latex or "").strip():
        current_statement = None
    statement_changed = bool(
        (snapshot["statement_id"] is not None and current_statement is None)
        or (current_statement and _digest(current_statement.statement_latex or "") != snapshot["statement_digest"]),
    )
    result = {
        "id": str(review.pk),
        "status": review.status,
        "revision_id": str(review.revision_id),
        "edit_version": snapshot["edit_version"],
        "current_edit_version": solution.edit_version,
        "stale": solution.current_revision_id != review.revision_id or statement_changed,
        "reviewed_source": snapshot["body_source"],
        "error_code": review.error_code,
        "created_at": review.created_at.isoformat(),
    }
    if review.status == SolutionReview.Status.COMPLETED:
        feedback = {**review.feedback, "findings": []}
        for index, finding in enumerate(review.feedback["findings"]):
            row = {key: value for key, value in finding.items() if key != "hints"}
            identity = finding_identity(review, finding, index)
            row["id"] = identity
            from .evaluation_assistance import repair_state

            row["repair_state"] = repair_state(review, identity)
            from django.urls import reverse

            row["reveal_url"] = reverse(
                "solutions:solution_review_reveal",
                args=[
                    solution.problem.problem_uuid,
                    review.pk,
                    identity,
                ],
            )
            row["hint_count"] = len(finding["hints"])
            levels = list(
                HintRevealEvent.objects.filter(
                    review=review, finding_id=identity, content_digest=digest(finding),
                ).values_list("level", flat=True),
            )
            released = max(levels, default=0)
            row["released_level"] = released
            if released:
                row["hints"] = finding["hints"][:released]
            feedback["findings"].append(row)
        result["hint_exposure_history"] = (
            "recorded" if review.schema_version >= CURRENT_REVIEW_SCHEMA else "historical_unknown"
        )
        result["feedback"] = feedback
    return result


def _expire_jobs(now):
    from .evaluation_execution import cancel_undispatched

    for expired in SolutionReview.objects.filter(status=SolutionReview.Status.QUEUED, created_at__lt=now - QUEUE_TTL):
        cancel_undispatched(expired, "queue_expired")
    SolutionReview.objects.filter(status=SolutionReview.Status.QUEUED, created_at__lt=now - QUEUE_TTL).update(
        status=SolutionReview.Status.EXPIRED,
        accounted_micros=0,
        error_code="queue_expired",
        completed_at=now,
    )
    SolutionReview.objects.filter(
        status=SolutionReview.Status.RUNNING,
        dispatched_at__lt=now - timedelta(seconds=LEASE_SECONDS),
    ).update(status=SolutionReview.Status.OUTCOME_UNKNOWN, error_code="worker_interrupted", completed_at=now)


def _claim(*, require_provider=False):
    if require_provider:
        from .evaluation_execution import require_offline_provider

        require_offline_provider()
    with transaction.atomic():
        policy = SolutionReviewPolicy.objects.select_for_update().filter(singleton_key=1).first()
        if not _configured(policy):
            raise ReviewError(code="review_disabled", status=503)
        if require_provider and not getattr(settings, "OPENAI_API_KEY", ""):
            msg = "Configure the provider before starting the review worker."
            raise ReviewError(msg, code="provider_not_configured", status=503)
        now = timezone.now()
        if policy.lease_until and policy.lease_until > now:
            return None
        _expire_jobs(now)
        token = uuid.uuid4()
        policy.worker_seen_at = now
        policy.lease_token = token
        policy.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        policy.save(update_fields=["worker_seen_at", "lease_token", "lease_until", "updated_at"])
        review = (
            SolutionReview.objects.select_for_update()
            .filter(status=SolutionReview.Status.QUEUED)
            .order_by("created_at")
            .first()
        )
        if review is None:
            policy.lease_token = None
            policy.lease_until = None
            policy.save(update_fields=["lease_token", "lease_until", "updated_at"])
            return None
        if not review.author.groups.filter(name=PILOT_GROUP).exists():
            from .evaluation_execution import cancel_undispatched

            cancel_undispatched(review, "pilot_access_removed")
            review.status = SolutionReview.Status.EXPIRED
            review.accounted_micros = 0
            review.error_code = "pilot_access_removed"
            review.completed_at = now
        else:
            review.status = SolutionReview.Status.RUNNING
            review.dispatched_at = now
        review.save()
        return review, token


def review_image_inputs(review):
    images = []
    if _digest(_json(review.input_snapshot)) != review.input_digest:
        raise ReviewError(code="input_changed")
    if review.model != PRICED_MODEL:
        raise ReviewError(code="unpriced_model")
    for manifest in review.input_snapshot["images"]:
        image = SolutionBodyImage.objects.filter(
            solution_id=review.revision.solution_id,
            file=manifest["path"],
        ).first()
        if image is None:
            raise ReviewError(code="image_missing")
        data, current = _read_image(image)
        if current != manifest:
            raise ReviewError(code="image_changed")
        with Image.open(BytesIO(data)) as picture:
            picture.thumbnail((2048, 2048))
            stream = BytesIO()
            picture.convert("RGB").save(stream, format="PNG")
            images.append(stream.getvalue())
    if hasattr(review, "execution"):
        from .evaluation import verify_bundle

        verify_bundle(review.execution.bundle)
        return [bytes(asset.normalized) for asset in review.execution.bundle.assets.order_by("created_at", "id")]
    return images


def _account_usage(review, usage):
    if not isinstance(usage, dict):
        return
    returned_model = usage.get("model")
    review.usage = {"model": returned_model[:120]} if isinstance(returned_model, str) and returned_model else {}
    for key in ("input_tokens_details", "output_tokens_details"):
        details = usage.get(key)
        if isinstance(details, dict):
            review.usage[key] = {name: value for name, value in details.items()
                                 if isinstance(name, str) and type(value) is int and value >= 0}
    input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
    if type(input_tokens) is int and type(output_tokens) is int and min(input_tokens, output_tokens) >= 0:
        pricing = review.pricing_snapshot
        review.accounted_micros = _token_cost(input_tokens, output_tokens, pricing)
        review.usage.update(input_tokens=input_tokens, output_tokens=output_tokens)
        if review.usage.get("input_tokens_details", {}).get("cached_tokens", 0):
            # Preserve the real usage; the current profile has no approved cached-rate settlement policy.
            review.usage["cost_unreconciled"] = True
            review.accounted_micros = review.reserved_micros


def _finish(review):
    """Finish the existing attempt, without recreating a deleted private job."""
    with transaction.atomic():
        from .evaluation_execution import finish_attempt

        finish_attempt(review)
        policy = SolutionReviewPolicy.objects.select_for_update().filter(singleton_key=1).first()
        changed = SolutionReview.objects.filter(
            pk=review.pk,
            dispatched_at=review.dispatched_at,
            input_digest=review.input_digest,
            status__in=[SolutionReview.Status.RUNNING, SolutionReview.Status.OUTCOME_UNKNOWN],
        ).update(
            status=review.status,
            feedback=review.feedback,
            error_code=review.error_code,
            provider_request_id=review.provider_request_id,
            provider_response_id=review.provider_response_id,
            accounted_micros=review.accounted_micros,
            usage=review.usage,
            completed_at=review.completed_at,
            updated_at=timezone.now(),
        )
        if changed and policy and review.accounted_micros > review.reserved_micros:
            # A bad pricing configuration must not authorize another dispatch.
            policy.enabled = False
            policy.save(update_fields=["enabled", "updated_at"])
        return bool(changed)


def process_next_review(provider=None):
    from .review_provider import ProviderError
    from .review_provider import generate_review

    claim = _claim(require_provider=provider is None)
    if claim is None:
        return {"state": "idle"}
    review, token = claim
    try:
        if review.status == SolutionReview.Status.EXPIRED:
            return {"state": "expired", "id": str(review.pk)}
        try:
            images = review_image_inputs(review)
            from .evaluation_execution import start_attempt

            attempt = start_attempt(review)
            review.execution_attempt_id = attempt.pk
            result = (provider or generate_review)(review, images)
            review.provider_response_id = result.response_id[:200]
            review.provider_request_id = result.request_id[:200]
            _account_usage(review, result.usage)
            feedback = validate_feedback(result.feedback, review.input_snapshot["body_source"])
            if review.input_snapshot["diagram_source_only"] or attempt.bundle.payload["completeness"] != "present":
                feedback["limitations"] = [
                    *feedback["limitations"][:4],
                    "The diagram was supplied as source text, not a rendered image.",
                ]
                if feedback["assessment"] == "no_issues_found":
                    feedback["assessment"] = "unable_to_assess"
            review.feedback = feedback
            review.status = SolutionReview.Status.COMPLETED
        except ProviderError as error:
            review.status = SolutionReview.Status.FAILED if error.definitive else SolutionReview.Status.OUTCOME_UNKNOWN
            review.error_code = error.code
            review.provider_request_id = error.request_id[:200]
            review.provider_response_id = error.response_id[:200]
            _account_usage(review, error.usage)
        except (ReviewError, EvaluationError) as error:
            review.status = SolutionReview.Status.FAILED
            review.error_code = error.code
        except Exception:  # noqa: BLE001 - unknown dispatch outcomes must remain claimed, never retried
            review.status = SolutionReview.Status.OUTCOME_UNKNOWN
            review.error_code = "worker_error"
        review.completed_at = timezone.now()
        if not _finish(review):
            return {"state": "discarded", "id": str(review.pk)}
        return {"state": review.status, "id": str(review.pk), "error_code": review.error_code}
    finally:
        SolutionReviewPolicy.objects.filter(singleton_key=1, lease_token=token).update(
            lease_token=None,
            lease_until=None,
            worker_seen_at=timezone.now(),
        )
