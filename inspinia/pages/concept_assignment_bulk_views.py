"""Admin-only downloads and read-only bulk checks; no assignment write endpoint."""

import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from inspinia.pages.concept_assignment_bulk import MAX_PACKET_BYTES
from inspinia.pages.concept_assignment_bulk import BulkReviewError
from inspinia.pages.concept_assignment_bulk import capture_snapshot
from inspinia.pages.concept_assignment_bulk import check_live_packet
from inspinia.pages.concept_assignment_bulk import document_bytes
from inspinia.pages.concept_assignment_views import _admin


def download(document, name, *, compressed=False):
    response = HttpResponse(
        document_bytes(document, compressed=compressed),
        content_type="application/gzip" if compressed else "application/json",
    )
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@transaction.non_atomic_requests
@login_required
@require_GET
def concept_review_snapshot_export(request):
    _admin(request)
    try:
        snapshot = capture_snapshot({key: request.GET.get(key, "") for key in ("subject", "year", "contest", "q")})
    except (BulkReviewError, ValueError, KeyError, TypeError) as exc:
        return HttpResponseBadRequest(str(exc))
    return download(snapshot, f"concept-review-snapshot-{snapshot['sha256'][:16]}.json.gz", compressed=True)


@transaction.non_atomic_requests
@login_required
@require_POST
def concept_review_bulk_check(request):
    _admin(request)
    uploaded = request.FILES.get("packet")
    if uploaded is None or uploaded.size > MAX_PACKET_BYTES:
        return HttpResponseBadRequest("Upload one JSON review packet, at most 8 MiB.")
    try:
        content = uploaded.read(MAX_PACKET_BYTES + 1)
        if len(content) > MAX_PACKET_BYTES:
            return HttpResponseBadRequest("Review packet exceeds 8 MiB.")
        report = check_live_packet(json.loads(content))
    except (BulkReviewError, ValueError, KeyError, TypeError) as exc:
        return HttpResponseBadRequest(str(exc))
    return download(report, f"concept-review-dry-run-{report['sha256'][:16]}.json")
