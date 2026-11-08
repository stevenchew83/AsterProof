"""Owner-only JSON interfaces for explicit, private solution coaching."""

import json

from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from .evaluation import EvaluationError
from .evaluation_execution import reveal_hint
from .review_models import SolutionReview
from .reviews import ReviewError
from .reviews import enqueue_review
from .reviews import review_payload

MAX_REQUEST_BYTES = 64_000


def _error(message, code, status):
    return JsonResponse({"error": message, "code": code}, status=status)


def _request_too_large(request):
    try:
        size = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        return True
    if size < 0 or size > MAX_REQUEST_BYTES:
        return True
    return request.content_type == "application/json" and len(request.body) > MAX_REQUEST_BYTES


@require_POST
@never_cache
def solution_review_create_view(request, problem_uuid, solution_pk=None):
    if not request.user.is_authenticated:
        return _error("Sign in to request AI review.", "authentication_required", 401)
    if _request_too_large(request):
        return _error("The review request is too large.", "request_too_large", 422)
    try:
        data = json.loads(request.body) if request.content_type == "application/json" else request.POST
        if not isinstance(data, dict):
            return _error("Submit a review request object.", "invalid_request", 422)
        acknowledged = data.get("acknowledged") in (True, "true", "1")
        statement_confirmed = data.get("statement_confirmed") in (True, "true", "1")
        review, created = enqueue_review(
            request.user,
            problem_uuid,
            data.get("revision_id"),
            data.get("idempotency_key"),
            acknowledged=acknowledged,
            statement_text=data.get("statement_text", ""),
            statement_confirmed=statement_confirmed,
            solution_pk=solution_pk,
        )
    except (ValueError, UnicodeDecodeError) as error:
        if isinstance(error, (ReviewError, EvaluationError)):
            return _error(str(error), error.code, error.status)
        return _error("Submit a valid review request.", "invalid_request", 422)
    status_args = [problem_uuid, solution_pk, review.pk] if solution_pk is not None else [problem_uuid, review.pk]
    return JsonResponse(
        {
            "id": str(review.pk),
            "status": review.status,
            "created": created,
            "revision_id": str(review.revision_id),
            "status_url": reverse("solutions:solution_review_status", args=status_args),
        },
        status=202 if created else 200,
    )


@require_GET
@never_cache
def solution_review_status_view(request, problem_uuid, review_id, solution_pk=None):
    if not request.user.is_authenticated:
        return _error("Sign in to view AI feedback.", "authentication_required", 401)
    solution_filter = {"revision__solution_id": solution_pk} if solution_pk is not None else {}
    review = (
        SolutionReview.objects.select_related("revision__solution")
        .filter(
            pk=review_id,
            author=request.user,
            revision__solution__author=request.user,
            revision__solution__problem__problem_uuid=problem_uuid,
            **solution_filter,
        )
        .first()
    )
    if review is None:
        return _error("This review was not found.", "not_found", 404)
    try:
        hint_level = int(request.GET.get("hint_level", 0))
    except (TypeError, ValueError):
        return _error("Use a hint level from 0 to 2.", "invalid_hint_level", 422)
    if hint_level not in range(3):
        return _error("Use a hint level from 0 to 2.", "invalid_hint_level", 422)
    try:
        return JsonResponse(review_payload(review))
    except EvaluationError as error:
        return _error(str(error), error.code, error.status)


@require_POST
@never_cache
def solution_review_reveal_view(request, problem_uuid, review_id, finding_id):
    if not request.user.is_authenticated:
        return _error("Sign in to reveal feedback.", "authentication_required", 401)
    review = (
        SolutionReview.objects.select_related("revision__solution")
        .filter(
            pk=review_id,
            author=request.user,
            revision__solution__author=request.user,
            revision__solution__problem__problem_uuid=problem_uuid,
        )
        .first()
    )
    if review is None:
        return _error("This review was not found.", "not_found", 404)
    if _request_too_large(request):
        return _error("The request is too large.", "request_too_large", 422)
    try:
        data = json.loads(request.body) if request.content_type == "application/json" else request.POST
        level = data.get("level")
        if isinstance(level, str) and level in {"1", "2"}:
            level = int(level)
        reveal_hint(request.user, review, finding_id, level)
        return JsonResponse(review_payload(review))
    except EvaluationError as error:
        return _error(str(error), error.code, error.status)
    except (ValueError, TypeError, AttributeError):
        return _error("Submit an available hint level.", "invalid_hint_level", 422)
