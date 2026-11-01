"""Owner-only benchmark-reuse decisions; these routes never copy or review proofs."""

import json
import uuid
from http import HTTPStatus

from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .evaluation import EvaluationError
from .evaluation_assistance import record_reuse_consent
from .evaluation_assistance import withdraw_reuse_consent
from .evaluation_models import ReviewConsent
from .models import SolutionRevision

MAX_REQUEST_BYTES = 16_000


def _json(payload, status=HTTPStatus.OK):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


def _error(message, code, status):
    return _json({"error": message, "code": code}, status=status)


def _signed_in(request):
    return request.user.is_authenticated and request.user.is_active


def _request_too_large(request):
    # CSRF may already have consumed a multipart form stream; only JSON needs its raw body.
    try:
        size = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        return True
    if size < 0 or size > MAX_REQUEST_BYTES:
        return True
    return request.content_type == "application/json" and len(request.body) > MAX_REQUEST_BYTES


def _consent_input(request):
    data = json.loads(request.body) if request.content_type == "application/json" else request.POST
    if not isinstance(data, dict) or not isinstance(data.get("expires_at"), str):
        raise TypeError
    return data, uuid.UUID(str(data.get("revision_id"))), parse_datetime(data["expires_at"])


@never_cache
@require_POST
def solution_reuse_consent_create_view(request, problem_uuid):
    if not _signed_in(request):
        return _error("Sign in to manage benchmark reuse.", "authentication_required", HTTPStatus.UNAUTHORIZED)
    if _request_too_large(request):
        return _error("The request is too large.", "request_too_large", HTTPStatus.UNPROCESSABLE_ENTITY)
    try:
        data, revision_id, expires_at = _consent_input(request)
        revision = (
            SolutionRevision.objects.select_related("solution")
            .filter(pk=revision_id, solution__author=request.user, solution__problem__problem_uuid=problem_uuid)
            .first()
        )
        if revision is None:
            return _error("This proof revision was not found.", "not_found", HTTPStatus.NOT_FOUND)
        consent = record_reuse_consent(request.user, revision, expires_at, data.get("policy_version"))
    except EvaluationError as error:
        return _error(str(error), error.code, error.status)
    except (ValueError, TypeError, UnicodeError):
        return _error("Submit a valid consent request.", "invalid_request", HTTPStatus.UNPROCESSABLE_ENTITY)
    return _json(
        {
            "id": str(consent.pk),
            "revision_id": consent.payload["source_revision_id"],
            "source_digest": consent.payload["source_digest"],
            "expires_at": consent.expires_at.isoformat(),
            "policy_version": consent.payload["retention_policy"],
            "eligibility": "pending_independent_approval",
            "copied_to_benchmark": False,
        },
        status=HTTPStatus.CREATED,
    )


@never_cache
@require_POST
def solution_reuse_consent_withdraw_view(request, consent_id):
    if not _signed_in(request):
        return _error("Sign in to manage benchmark reuse.", "authentication_required", HTTPStatus.UNAUTHORIZED)
    if _request_too_large(request):
        return _error("The request is too large.", "request_too_large", HTTPStatus.UNPROCESSABLE_ENTITY)
    consent = ReviewConsent.objects.filter(pk=consent_id, actor=request.user, purpose="benchmark_reuse").first()
    if consent is None:
        return _error("This reuse consent was not found.", "not_found", HTTPStatus.NOT_FOUND)
    try:
        withdraw_reuse_consent(request.user, consent)
    except EvaluationError as error:
        return _error(str(error), error.code, error.status)
    return _json({"id": str(consent.pk), "status": "withdrawn"})
