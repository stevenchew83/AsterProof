"""Permission-checked delivery for managed solution images; paths are never authority."""

import re
from urllib.parse import urlsplit

from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.db import transaction
from django.http import FileResponse
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import re_path
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from PIL import Image
from PIL import UnidentifiedImageError

from inspinia.solutions.document_source import solution_source
from inspinia.solutions.forum_access import can_read_solution
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionBodyImage
from inspinia.solutions.models import SolutionPublicShare
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.roles import user_has_admin_role

MANAGED_IMAGE_PATH = re.compile(r"solution_body_images/[0-9a-f]{32}\.(?:png|jpe?g|gif|webp)", re.IGNORECASE)
IMAGE_REFERENCE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}


def _without_tex_comments(source):
    lines = []
    for line in source.splitlines():
        escaped = False
        end = len(line)
        for position, character in enumerate(line):
            if character == "%" and not escaped:
                end = position
                break
            escaped = not escaped if character == "\\" else False
        lines.append(line[:end])
    return "\n".join(lines)


def image_paths(source):
    """Extract only supported includegraphics paths, without accepting URLs or traversal."""
    return sorted({
        match.group(1).strip() for match in IMAGE_REFERENCE.finditer(_without_tex_comments(source or ""))
        if MANAGED_IMAGE_PATH.fullmatch(match.group(1).strip())
    })


def snapshot_image_paths(snapshot):
    if not isinstance(snapshot, dict):
        return []
    document = snapshot.get("document") or {}
    source = document.get("source", "") if isinstance(document, dict) else ""
    if not isinstance(source, str):
        return []
    blocks = snapshot.get("blocks") or []
    if isinstance(blocks, list):
        source += "\n" + "\n".join(
            str(block.get("source", block.get("body_source", "")))
            for block in blocks if isinstance(block, dict) and block.get("format", "latex") == "latex"
        )
    return image_paths(source)


def _base_url(name, args):
    # reverse requires the path argument. Strip only this known placeholder.
    placeholder = "solution_body_images/" + "0" * 32 + ".png"
    return reverse(name, args=[*args, placeholder]).removesuffix(placeholder)


def internal_image_base_url(solution_pk):
    return _base_url("solutions:solution_image", [solution_pk])


def editor_image_base_url(problem_uuid):
    return _base_url("solutions:solution_editor_image", [problem_uuid])


def public_image_base_url(share):
    return _base_url("solutions:public_solution_asset", [share.token, share.revision])


def _unavailable():
    response = HttpResponse(status=404)
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


def _historical_reference(solution, image_path):
    target_model = apps.all_models["solutions"].get("solutionforumtarget")
    if target_model is None:
        return False
    try:
        # Text prefilter is portable to SQLite; exact membership remains mandatory.
        with transaction.atomic():
            candidates = target_model.objects.filter(
                solution=solution, image_paths__icontains=image_path,
            ).values_list("image_paths", flat=True)
            return any(isinstance(paths, list) and image_path in paths for paths in candidates.iterator(chunk_size=32))
    except DatabaseError:
        # The compatibility image release precedes the forum schema. Fail closed.
        return False


def _serve_image(solution, image_path):
    if not MANAGED_IMAGE_PATH.fullmatch(image_path):
        return _unavailable()
    image = SolutionBodyImage.objects.filter(solution=solution, file=image_path).first()
    if image is None:
        return _unavailable()
    try:
        with image.file.open("rb") as stream, Image.open(stream) as decoded:
            content_type = IMAGE_TYPES.get(decoded.format)
            decoded.verify()
        # Pillow closes its input; reopen the storage object for streaming.
        if not content_type:
            return _unavailable()
        stream = image.file.open("rb")
    except (OSError, ValueError, UnidentifiedImageError):
        return _unavailable()
    response = FileResponse(stream, content_type=content_type)
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Referrer-Policy"] = "same-origin"
    return response


@login_required
@never_cache
@require_safe
def solution_image_view(request, solution_pk, image_path):
    solution = get_object_or_404(ProblemSolution.objects.select_related("current_revision"), pk=solution_pk)
    if not user_can_access_app_features(request.user) or not can_read_solution(request.user, solution):
        return _unavailable()
    if solution.author_id != request.user.pk and not user_has_admin_role(request.user):
        referenced = (
            image_path in image_paths(solution_source(solution)) or _historical_reference(solution, image_path)
        )
        if not referenced:
            return _unavailable()
    return _serve_image(solution, image_path)


@login_required
@never_cache
@require_safe
def solution_editor_image_view(request, problem_uuid, image_path):
    if not user_can_access_app_features(request.user):
        return _unavailable()
    solution = get_object_or_404(
        ProblemSolution, author=request.user, problem__problem_uuid=problem_uuid, additional_draft_key__isnull=True,
    )
    return _serve_image(solution, image_path)


@never_cache
@require_safe
def public_solution_asset_view(request, token, revision, image_path):
    share = SolutionPublicShare.objects.select_related("solution").filter(
        token=token, revision=revision, is_active=True,
    ).first()
    if share is None or image_path not in snapshot_image_paths(share.snapshot):
        return _unavailable()
    return _serve_image(share.solution, image_path)


@never_cache
@require_safe
def raw_solution_image_unavailable(request, **kwargs):
    return _unavailable()


def raw_image_urlpatterns():
    """Block the configured development-media path before Django's static helper."""
    prefix = urlsplit(settings.MEDIA_URL).path.strip("/")
    prefix = prefix + "/" if prefix else ""
    return [re_path(r"^" + re.escape(prefix) + r"solution_body_images(?:/.*)?$", raw_solution_image_unavailable)]
