"""Anonymous readers see only the explicitly shared snapshot."""

from django.conf import settings
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_safe

from inspinia.solutions.models import SolutionCollection
from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.share_analytics import record_public_view
from inspinia.solutions.sharing import public_collection_url
from inspinia.solutions.sharing import public_description
from inspinia.solutions.sharing import public_preview_image
from inspinia.solutions.sharing import public_share_url
from inspinia.solutions.sharing import whatsapp_share_url


def _private_cache(response):
    # Revocation is checked on every page/image request, including old revisions.
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Referrer-Policy"] = "same-origin"
    return response


def _unavailable(request):
    return _private_cache(render(request, "website/shared_solution_unavailable.html", {
        "page_title": "Solution unavailable",
        "public_operator_name": settings.PUBLIC_OPERATOR_NAME,
        "hide_newsletter": True,
        "noindex": True,
    }, status=404))


@require_safe
def public_solution_view(request, token):
    share = SolutionPublicShare.objects.annotate(owner_id=F("solution__author_id")).defer("preview_image").filter(
        token=token, is_active=True,
    ).first()
    if share is None:
        return _unavailable(request)
    url = public_share_url(share)
    image_url = settings.PUBLIC_SITE_ORIGIN.rstrip("/") + reverse(
        "solutions:public_solution_image", args=[share.token, share.revision],
    )
    response = _private_cache(render(request, "website/shared_solution.html", {
        "page_title": share.snapshot["title"],
        "page_description": public_description(share.snapshot),
        "canonical_url": url,
        "social_image_url": image_url,
        "social_image_alt": "AsterProof logo",
        "snapshot": share.snapshot,
        "whatsapp_url": whatsapp_share_url(url),
        "public_operator_name": settings.PUBLIC_OPERATOR_NAME,
        "hide_newsletter": True,
        "noindex": True,
        "shared_solution": True,
        "solution_media_url": settings.MEDIA_URL,
    }))
    record_public_view(request, share)
    return response


@require_safe
def public_solution_image_view(request, token, revision):
    share = SolutionPublicShare.objects.filter(token=token, revision=revision, is_active=True).only("pk").first()
    if share is None:
        return _unavailable(request)
    response = HttpResponse(public_preview_image(), content_type="image/jpeg")
    response["X-Content-Type-Options"] = "nosniff"
    return _private_cache(response)


@require_safe
def public_collection_view(request, token):
    collection = SolutionCollection.objects.filter(token=token, is_active=True).first()
    if collection is None or collection.kind not in SolutionCollection.Kind.values:
        return _unavailable(request)
    entries = collection.entries.filter(
        share__is_active=True,
        share__token=F("share_token"),
    ).select_related("share").defer("share__preview_image")
    if collection.kind == SolutionCollection.Kind.PERSONAL:
        entries = entries.filter(share__solution__author_id=collection.owner_id)
    rows = [{"anchor": f"solution-{entry.anchor}", "snapshot": entry.share.snapshot} for entry in entries]
    url = public_collection_url(collection)
    return _private_cache(render(request, "website/shared_collection.html", {
        "collection": collection,
        "collection_rows": rows,
        "page_title": collection.title,
        "page_description": f"{len(rows)} shared solutions. Read the full collection on AsterProof.",
        "canonical_url": url,
        "social_image_url": settings.PUBLIC_SITE_ORIGIN.rstrip("/") + static("images/asterproof-share-logo.jpg"),
        "social_image_alt": "AsterProof logo",
        "whatsapp_url": whatsapp_share_url(url),
        "public_operator_name": settings.PUBLIC_OPERATOR_NAME,
        "hide_newsletter": True,
        "noindex": True,
        "shared_solution": True,
        "solution_media_url": settings.MEDIA_URL,
    }))
