"""Validated private raster assets, contextual access and reference-safe cleanup."""

import hashlib
import os
import re
import uuid
import warnings
from datetime import timedelta
from io import BytesIO
from itertools import islice

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import DatabaseError
from django.db import connection
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from PIL import Image
from PIL import ImageOps
from PIL import UnidentifiedImageError

from inspinia.learning.permissions import is_publisher
from inspinia.learning.permissions import module_enabled
from inspinia.learning.permissions import require_draft_owner
from inspinia.users.roles import user_can_access_app_features

MAX_UPLOAD_BYTES = 3 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_DOCUMENT_ASSETS = 20
MAX_AUTHOR_BYTES = 100 * 1024 * 1024
MAX_CLEANUP_BATCH = 1000
FORMATS = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"), "WEBP": ("webp", "image/webp")}
ASSET_TOKEN = re.compile(r"asset:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
ASSET_FILENAME = re.compile(r"assets/([0-9a-f]{32})\.(png|jpg|webp)\Z")


def _models():
    from inspinia.learning import models

    return models


def _consume_limit(key, maximum, seconds):
    key = "learning-upload:" + salted_hmac("learning.asset-limits.v1", key).hexdigest()
    try:
        cache.add(key, 0, timeout=seconds)
        count = cache.incr(key)
        return isinstance(count, int) and count <= maximum
    except (ValueError, OSError):
        return False


def normalise_image(upload):
    """Inspect and decode bytes, then re-encode pixels without embedded metadata."""
    if getattr(upload, "size", 0) > MAX_UPLOAD_BYTES:
        msg = "Keep each image within 3 MiB."
        raise ValidationError(msg)
    data = upload.read(MAX_UPLOAD_BYTES + 1)
    if not data or len(data) > MAX_UPLOAD_BYTES:
        msg = "Keep each image within 3 MiB."
        raise ValidationError(msg)
    declared = (getattr(upload, "content_type", "") or "").split(";")[0].lower()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as check:
                image_format = check.format
                if image_format not in FORMATS:
                    msg = "Upload a PNG, JPEG or static WebP image."
                    raise ValidationError(msg)
                if getattr(check, "n_frames", 1) != 1:
                    msg = "Animated and multi-frame images are not supported."
                    raise ValidationError(msg)
                if check.width * check.height > MAX_IMAGE_PIXELS:
                    msg = "Keep each image within 16 million pixels."
                    raise ValidationError(msg)
                check.verify()
            with Image.open(BytesIO(data)) as original:
                original.load()
                image = ImageOps.exif_transpose(original)
                image = image.convert("RGBA" if "A" in image.getbands() and image_format != "JPEG" else "RGB")
                image.info.clear()
                width, height = image.size
                output = BytesIO()
                options = {"quality": 90} if image_format in {"JPEG", "WEBP"} else {}
                image.save(output, format=image_format, **options)
                encoded = output.getvalue()
    except (
        OSError,
        ValueError,
        SyntaxError,
        UnidentifiedImageError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        msg = "The image could not be decoded safely."
        raise ValidationError(msg) from exc
    extension, mime_type = FORMATS[image_format]
    if declared and declared != mime_type:
        msg = "The image type does not match its decoded contents."
        raise ValidationError(msg)
    if len(encoded) > MAX_UPLOAD_BYTES:
        msg = "The normalised image exceeds 3 MiB; use a smaller image."
        raise ValidationError(msg)
    return {
        "data": encoded,
        "extension": extension,
        "mime_type": mime_type,
        "width": width,
        "height": height,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def store_asset(*, draft, user, upload):
    require_draft_owner(draft, user)
    from inspinia.learning.storage import LearningAssetStorage

    try:
        _ = LearningAssetStorage().location
    except ImproperlyConfigured as exc:
        msg = "Private image upload is unavailable right now. Your source is preserved."
        raise ValidationError(msg) from exc
    if not _consume_limit(f"attempt:{user.pk}", 10, 60):
        msg = "Image uploads are temporarily limited. Your writing is preserved."
        raise ValidationError(msg)
    image = normalise_image(upload)
    models = _models()
    with transaction.atomic():
        models.ContentDocument.objects.select_for_update().get(pk=draft.document_id)
        locked = models.ContentDraft.objects.select_for_update().get(pk=draft.pk)
        require_draft_owner(locked, user)
        get_user_model().objects.select_for_update().get(pk=user.pk)
        active = models.ContentAsset.objects.filter(owner=user).exclude(state=models.ContentAsset.State.DELETED)
        used = active.aggregate(total=Sum("byte_size"))["total"] or 0
        if used + len(image["data"]) > MAX_AUTHOR_BYTES:
            msg = "Your retained learning images have reached the 100 MiB allowance."
            raise ValidationError(msg)
        if not _consume_limit("accepted-global", 200, 86400):
            msg = "The daily learning-image allowance has been reached."
            raise ValidationError(msg)
        asset = models.ContentAsset(
            owner=user,
            document_id=draft.document_id,
            sha256=image["sha256"],
            byte_size=len(image["data"]),
            mime_type=image["mime_type"],
            width=image["width"],
            height=image["height"],
        )
        try:
            asset.file.save("upload." + image["extension"], ContentFile(image["data"]), save=False)
        except OSError as exc:
            msg = "Private image storage is unavailable. Your source has not changed."
            raise ValidationError(msg) from exc
        try:
            asset.save()
        except DatabaseError as exc:
            # Never unlink here: a successful transaction with a lost response
            # must not lose its file. Scheduled cleanup can reconcile old orphans.
            msg = "The image could not be attached. It remains private for later cleanup; your source is preserved."
            raise ValidationError(msg) from exc
    return asset


def asset_payload(asset):
    return {
        "id": str(asset.pk),
        "path": f"asset:{asset.pk}",
        "url": reverse("website:learning_asset", kwargs={"asset_id": asset.pk}),
    }


def can_access_asset(asset, user):  # noqa: PLR0911 - Explicit current-publication and private ownership states.
    models = _models()
    if not module_enabled() or asset.state != models.ContentAsset.State.ACTIVE:
        return False
    current = models.ContentPublication.objects.filter(revision__asset_links__asset=asset)
    if current.filter(public_visible=True).exists():
        return True
    approved = bool(getattr(user, "is_active", False) and user_can_access_app_features(user))
    if not approved:
        return False
    if current.filter(training_visible=True).exists() or asset.owner_id == user.pk:
        return True
    submitted = models.ContributionProposal.objects.filter(revision__asset_links__asset=asset)
    if is_publisher(user) and submitted.exists():
        return True
    if submitted.filter(author_id=user.pk).exists():
        return True
    if models.ContentDraft.objects.filter(
        author=user, document_id=asset.document_id, base_revision__asset_links__asset=asset,
    ).exists():
        return True
    return models.ContentAssetGrant.objects.filter(asset=asset, document__drafts__author=user).exists()


def _reference_rows(metadata):
    if not isinstance(metadata, dict) or not isinstance(metadata.get("assets", []), list):
        msg = "Image references must be a list of managed assets."
        raise ValidationError(msg)
    rows = metadata.get("assets", [])
    if len(rows) > MAX_DOCUMENT_ASSETS:
        msg = "Keep each document within 20 referenced images."
        raise ValidationError(msg)
    seen = set()
    for row in rows:
        try:
            key = str(uuid.UUID(str(row["id"])))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            msg = "An image reference is invalid."
            raise ValidationError(msg) from exc
        if key in seen:
            msg = "List each referenced image only once."
            raise ValidationError(msg)
        seen.add(key)
        for name, maximum in (("alt", 500), ("caption", 1000), ("credit", 500)):
            if not isinstance(row.get(name, ""), str) or len(row.get(name, "")) > maximum:
                msg = "An image description, caption or credit is invalid."
                raise ValidationError(msg)
        yield key, row


def validate_draft_assets(draft, user, *, require_alt=True, lock=True):
    """Validate supported references; callers saving references retain these locks."""
    require_draft_owner(draft, user)
    models = _models()
    references = dict(_reference_rows(draft.metadata))
    tokens = {str(uuid.UUID(value)) for value in ASSET_TOKEN.findall(draft.body_source)}
    if tokens != set(references):
        msg = "Every image token needs its matching managed image description."
        raise ValidationError(msg)
    query = models.ContentAsset.objects.filter(pk__in=references).order_by("pk")
    if lock and connection.in_atomic_block:
        query = query.select_for_update()
    assets = list(query)
    if len(assets) != len(references):
        msg = "A referenced image is unavailable."
        raise ValidationError(msg)
    for asset in assets:
        if asset.state != models.ContentAsset.State.ACTIVE:
            msg = "A referenced image is being removed or is unavailable."
            raise ValidationError(msg)
        own = asset.owner_id == user.pk and asset.document_id == draft.document_id
        inherited = bool(
            draft.base_revision_id
            and models.RevisionAsset.objects.filter(
                asset=asset,
                revision_id=draft.base_revision_id,
                revision__document_id=draft.document_id,
            ).exists(),
        )
        current = models.ContentPublication.objects.filter(
            document_id=draft.document_id, training_visible=True, revision__asset_links__asset=asset,
        ).exists()
        granted = models.ContentAssetGrant.objects.filter(asset=asset, document_id=draft.document_id).exists()
        if not (own or inherited or current or granted):
            msg = "This image has not been authorised for this document."
            raise PermissionDenied(msg)
        if require_alt and not references[str(asset.pk)].get("alt", "").strip():
            msg = "Add a meaningful image description before checkpointing or submitting."
            raise ValidationError(msg)
    return assets


def asset_files_available(revision):
    """Publication preflight only; run before obtaining publication locks."""
    for link in revision.asset_links.select_related("asset"):
        asset = link.asset
        match = ASSET_FILENAME.fullmatch(asset.file.name)
        if not match or match[1] != asset.pk.hex:
            msg = "A retained image has an invalid storage identity."
            raise ValidationError(msg)
        try:
            with asset.file.open("rb") as handle:
                data = handle.read(MAX_UPLOAD_BYTES + 1)
        except (OSError, ValueError, ImproperlyConfigured) as exc:
            msg = "A retained image file is missing; publication has not changed."
            raise ValidationError(msg) from exc
        if len(data) != asset.byte_size or hashlib.sha256(data).hexdigest() != asset.sha256:
            msg = "A retained image does not match its approved file."
            raise ValidationError(msg)
    return True


def asset_mapping(*, user, draft=None, revision=None):
    if (draft is None) == (revision is None):
        msg = "Choose one draft or revision image context."
        raise ValueError(msg)
    if draft is not None:
        assets = validate_draft_assets(draft, user, require_alt=False, lock=False)
        refs = dict(_reference_rows(draft.metadata))
    else:
        links = list(revision.asset_links.select_related("asset"))
        assets = [link.asset for link in links]
        refs = {
            str(link.asset_id): {"alt": link.alt_text, "caption": link.caption, "credit": link.credit}
            for link in links
        }
    result = {}
    for asset in assets:
        if not can_access_asset(asset, user):
            msg = "A referenced image is unavailable in this reading context."
            raise PermissionDenied(msg)
        result[str(asset.pk)] = {**refs[str(asset.pk)], "url": asset_payload(asset)["url"]}
    return result


def _has_references(asset):
    models = _models()
    if asset.revision_links.exists():
        return True
    documents = {asset.document_id}
    documents.update(asset.reuse_grants.values_list("document_id", flat=True))
    for metadata in models.ContentDraft.objects.filter(document_id__in=documents).values_list("metadata", flat=True):
        try:
            if str(asset.pk) in dict(_reference_rows(metadata)):
                return True
        except ValidationError:
            # Malformed draft metadata is not permission to delete possible retained work.
            return True
    return False


def cleanup_assets(*, dry_run=True, limit=100, now=None):
    if not 1 <= limit <= MAX_CLEANUP_BATCH:
        msg = "Choose a cleanup limit from 1 to 1000."
        raise ValidationError(msg)
    models = _models()
    cutoff = (now or timezone.now()) - timedelta(days=7)
    candidates = (
        models.ContentAsset.objects.filter(created_at__lt=cutoff)
        .exclude(state=models.ContentAsset.State.DELETED)
        .order_by("created_at", "pk")[:limit]
    )
    result = {"dry_run": dry_run, "eligible": [], "deleted": [], "failed": []}
    for candidate in candidates:
        with transaction.atomic():
            asset = models.ContentAsset.objects.select_for_update().get(pk=candidate.pk)
            if asset.state == models.ContentAsset.State.ACTIVE and _has_references(asset):
                continue
            result["eligible"].append(str(asset.pk))
            if dry_run:
                continue
            asset.state = models.ContentAsset.State.DELETING
            asset.save(update_fields=["state"])
        try:
            asset.file.storage.delete(asset.file.name)
        except OSError:
            result["failed"].append(str(asset.pk))
            continue
        models.ContentAsset.objects.filter(pk=asset.pk, state=models.ContentAsset.State.DELETING).update(
            state=models.ContentAsset.State.DELETED,
        )
        result["deleted"].append(str(asset.pk))
    _cleanup_untracked(result, cutoff=cutoff, limit=limit)
    return result


def _cleanup_untracked(result, *, cutoff, limit):
    """Failed DB inserts can leave private files without an asset row."""
    from inspinia.learning.storage import LearningAssetStorage

    if len(result["eligible"]) >= limit:
        return
    storage = LearningAssetStorage()
    directory = storage.path("assets")
    try:
        entries = os.scandir(directory)
    except FileNotFoundError:
        return
    with entries:
        for entry in islice(entries, limit):
            if len(result["eligible"]) >= limit:
                break
            name = "assets/" + entry.name
            match = ASSET_FILENAME.fullmatch(name)
            if (not match or entry.is_symlink() or not entry.is_file(follow_symlinks=False)
                    or entry.stat(follow_symlinks=False).st_mtime >= cutoff.timestamp()):
                continue
            # Upload identities are freshly generated and never supplied/reused by
            # authors. Old untracked paths cannot be attached without a live row.
            if _models().ContentAsset.objects.filter(pk=uuid.UUID(hex=match[1])).exists():
                continue
            identity = "orphan:" + str(uuid.UUID(hex=match[1]))
            result["eligible"].append(identity)
            if result["dry_run"]:
                continue
            try:
                storage.delete(name)
            except OSError:
                result["failed"].append(identity)
            else:
                result["deleted"].append(identity)
