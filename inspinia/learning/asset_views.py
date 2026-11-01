"""Private files are accessible only through current contextual authorisation."""

from django.core.exceptions import ImproperlyConfigured
from django.http import FileResponse
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from inspinia.learning.assets import ASSET_FILENAME
from inspinia.learning.assets import can_access_asset
from inspinia.learning.models import ContentAsset
from inspinia.learning.permissions import module_enabled


@never_cache
@require_safe
def asset_detail(request, asset_id):
    if not module_enabled():
        raise Http404
    asset = get_object_or_404(ContentAsset, pk=asset_id)
    if not can_access_asset(asset, request.user):
        raise Http404
    match = ASSET_FILENAME.fullmatch(asset.file.name)
    if not match or match[1] != asset.pk.hex:
        raise Http404
    try:
        handle = asset.file.open("rb")
    except (OSError, ValueError, ImproperlyConfigured) as exc:
        raise Http404 from exc
    response = FileResponse(handle, content_type=asset.mime_type)
    response["Content-Disposition"] = "inline"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
