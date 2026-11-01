"""Private image persistence, contextual delivery and retained-reference cleanup."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Event

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db import connections
from django.db import transaction
from django.test import RequestFactory
from django.utils import timezone
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from inspinia.learning.asset_views import asset_detail
from inspinia.learning.assets import MAX_UPLOAD_BYTES
from inspinia.learning.assets import asset_files_available
from inspinia.learning.assets import can_access_asset
from inspinia.learning.assets import cleanup_assets
from inspinia.learning.assets import normalise_image
from inspinia.learning.assets import store_asset
from inspinia.learning.assets import validate_draft_assets
from inspinia.learning.models import ContentAsset
from inspinia.learning.models import ContentDocument
from inspinia.learning.models import ContentDraft
from inspinia.learning.models import ContentPublication
from inspinia.learning.models import ContentRevision
from inspinia.learning.models import ContributionProposal
from inspinia.learning.models import RevisionAsset
from inspinia.learning.storage import LearningAssetStorage
from inspinia.users.tests.factories import UserFactory


def image_upload(*, size=(20, 15), image_format="PNG", content_type="image/png", exif=None):
    output = BytesIO()
    Image.new("RGB", size, "navy").save(output, format=image_format, **({"exif": exif} if exif else {}))
    return SimpleUploadedFile("clipboard.png", output.getvalue(), content_type=content_type)


@pytest.fixture
def workspace(settings, tmp_path, db):
    settings.LEARNING_MODULE_ENABLED = True
    settings.LEARNING_CONTRIBUTIONS_ENABLED = True
    settings.LEARNING_PRIVATE_ASSET_ROOT = str(tmp_path / "private")
    settings.MEDIA_ROOT = str(tmp_path / "public")
    cache.clear()
    author = UserFactory()
    publisher = UserFactory()
    settings.LEARNING_PUBLISHER_USER_ID = publisher.pk
    document = ContentDocument.objects.create(creator=author)
    draft = ContentDraft.objects.create(document=document, author=author)
    asset = store_asset(draft=draft, user=author, upload=image_upload())
    return author, publisher, draft, asset


def retain_asset(draft, asset, *, sequence=1):
    revision = ContentRevision.objects.create(document=draft.document, author=draft.author, sequence=sequence,
        title="A diagram", body_source=f"![Diagram](asset:{asset.pk})", source_digest="a" * 64)
    RevisionAsset.objects.create(revision=revision, asset=asset, alt_text="An original synthetic diagram")
    return revision


def test_image_is_decoded_reencoded_and_embedded_metadata_removed():
    exif = Image.Exif()
    exif[315] = "Private synthetic author"
    image = normalise_image(image_upload(image_format="JPEG", content_type="image/jpeg", exif=exif))
    assert image["mime_type"] == "image/jpeg"
    assert (image["width"], image["height"]) == (20, 15)
    with Image.open(BytesIO(image["data"])) as decoded:
        assert not decoded.getexif()


def test_png_metadata_is_not_carried_into_normalised_pixels():
    output = BytesIO()
    info = PngInfo()
    info.add_text("Comment", "Private annotation")
    Image.new("RGB", (10, 10), "red").save(output, format="PNG", pnginfo=info)
    result = normalise_image(SimpleUploadedFile("paste.png", output.getvalue(), content_type="image/png"))
    with Image.open(BytesIO(result["data"])) as decoded:
        assert "Comment" not in decoded.info
        assert not decoded.getexif()


@pytest.mark.parametrize("upload", [
    SimpleUploadedFile("bad.png", b"not an image", content_type="image/png"),
    SimpleUploadedFile("huge.png", b"x" * (MAX_UPLOAD_BYTES + 1), content_type="image/png"),
])
def test_invalid_or_excessive_compressed_bytes_are_rejected(upload):
    with pytest.raises(ValidationError):
        normalise_image(upload)


def test_mime_spoof_pixels_and_animation_are_rejected():
    with pytest.raises(ValidationError, match="type does not match"):
        normalise_image(image_upload(content_type="image/jpeg"))
    with pytest.raises(ValidationError, match="16 million"):
        normalise_image(image_upload(size=(4001, 4000)))
    output = BytesIO()
    Image.new("RGB", (5, 5), "red").save(output, format="PNG", save_all=True,
        append_images=[Image.new("RGB", (5, 5), "blue")], duration=100)
    with pytest.raises(ValidationError, match="multi-frame"):
        normalise_image(SimpleUploadedFile("animated.png", output.getvalue(), content_type="image/png"))


def test_corrupted_png_crc_is_a_validation_error_instead_of_server_error():
    encoded = bytearray(image_upload().read())
    chunk = encoded.index(b"IDAT")
    length = int.from_bytes(encoded[chunk - 4:chunk], "big")
    encoded[chunk + 4 + length] ^= 0x01
    with pytest.raises(ValidationError, match="could not be decoded safely"):
        normalise_image(SimpleUploadedFile("corrupt.png", bytes(encoded), content_type="image/png"))


def test_storage_fails_closed_without_private_root_or_under_public_media(settings, tmp_path):
    settings.LEARNING_PRIVATE_ASSET_ROOT = ""
    with pytest.raises(ImproperlyConfigured):
        _ = LearningAssetStorage().location
    settings.MEDIA_ROOT = str(tmp_path / "public")
    settings.LEARNING_PRIVATE_ASSET_ROOT = str(tmp_path / "public" / "private")
    with pytest.raises(ImproperlyConfigured, match="public file root"):
        _ = LearningAssetStorage().location
    with pytest.raises(NotImplementedError):
        LearningAssetStorage().url("anything")


def test_paste_persists_outside_public_media_and_is_private_before_submission(workspace, settings):
    author, publisher, draft, asset = workspace
    assert asset.file.storage.exists(asset.file.name)
    assert not asset.file.path.startswith(settings.MEDIA_ROOT)
    assert can_access_asset(asset, author)
    assert not can_access_asset(asset, publisher)
    assert not can_access_asset(asset, UserFactory(is_superuser=True))
    assert not can_access_asset(asset, AnonymousUser())
    with pytest.raises(PermissionDenied):
        store_asset(draft=draft, user=publisher, upload=image_upload())


def test_missing_private_storage_refuses_upload_as_preserved_validation_error(workspace, settings):
    author, _, draft, _ = workspace
    settings.LEARNING_PRIVATE_ASSET_ROOT = ""
    with pytest.raises(ValidationError, match="Private image upload is unavailable"):
        store_asset(draft=draft, user=author, upload=image_upload())


def test_reference_checks_require_authorisation_and_description(workspace):
    author, publisher, draft, asset = workspace
    draft.body_source = f"![](asset:{asset.pk})"
    draft.metadata = {"assets": [{"id": str(asset.pk), "alt": "", "caption": "", "credit": ""}]}
    assert validate_draft_assets(draft, author, require_alt=False) == [asset]
    with pytest.raises(ValidationError, match="meaningful image description"):
        validate_draft_assets(draft, author)
    stranger_draft = ContentDraft.objects.create(document=ContentDocument.objects.create(), author=publisher,
        body_source=draft.body_source, metadata={"assets": [{"id": str(asset.pk), "alt": "Copied ID"}]})
    with pytest.raises(PermissionDenied, match="not been authorised"):
        validate_draft_assets(stranger_draft, publisher)


def test_retained_byte_quota_is_checked_again_at_acceptance(workspace, monkeypatch):
    from inspinia.learning import assets

    author, _, draft, asset = workspace
    monkeypatch.setattr(assets, "MAX_AUTHOR_BYTES", asset.byte_size)
    before = ContentAsset.objects.count()
    with pytest.raises(ValidationError, match="100 MiB"):
        store_asset(draft=draft, user=author, upload=image_upload())
    assert ContentAsset.objects.count() == before


def test_limiter_failure_rejects_upload_before_file_acceptance(workspace, monkeypatch):
    author, _, draft, _ = workspace

    def unavailable(_key):
        raise OSError

    monkeypatch.setattr(cache, "incr", unavailable)
    before = ContentAsset.objects.count()
    with pytest.raises(ValidationError, match="temporarily limited"):
        store_asset(draft=draft, user=author, upload=image_upload())
    assert ContentAsset.objects.count() == before


def test_submitted_training_public_and_historical_access_are_separate(workspace):
    author, publisher, draft, asset = workspace
    reader = UserFactory()
    pending = UserFactory(is_approved=False)
    revision = retain_asset(draft, asset)
    ContributionProposal.objects.create(document=draft.document, author=author, revision=revision,
        base_publication_version=0, review_digest="a" * 64)
    assert can_access_asset(asset, publisher)
    assert not can_access_asset(asset, reader)
    publication = ContentPublication.objects.create(document=draft.document, revision=revision, training_visible=True)
    assert can_access_asset(asset, reader)
    assert not can_access_asset(asset, pending)
    publication.public_visible = True
    publication.save()
    assert can_access_asset(asset, pending)
    assert can_access_asset(asset, AnonymousUser())
    publication.public_visible = False
    publication.save()
    assert can_access_asset(asset, reader)
    assert not can_access_asset(asset, AnonymousUser())
    replacement = ContentRevision.objects.create(document=draft.document, author=author, sequence=2,
        title="Text only", body_source="No diagram", source_digest="b" * 64)
    publication.revision = replacement
    publication.save()
    assert not can_access_asset(asset, reader)
    assert asset.file.storage.exists(asset.file.name)


def test_public_asset_delivery_rechecks_state_and_uses_no_store(workspace):
    _, _, draft, asset = workspace
    revision = retain_asset(draft, asset)
    publication = ContentPublication.objects.create(document=draft.document, revision=revision,
        training_visible=True, public_visible=True)
    request = RequestFactory().get("/library/assets/")
    request.user = AnonymousUser()
    response = asset_detail(request, asset.pk)
    assert b"".join(response.streaming_content)
    assert {"private", "no-store", "no-cache"}.issubset(response["Cache-Control"].split(", "))
    assert response["X-Content-Type-Options"] == "nosniff"
    publication.public_visible = False
    publication.save()
    from django.http import Http404

    with pytest.raises(Http404):
        asset_detail(request, asset.pk)


def test_correction_draft_may_reuse_only_its_approved_base_images(workspace):
    _, _, draft, asset = workspace
    revision = retain_asset(draft, asset)
    author = UserFactory()
    correction = ContentDraft.objects.create(document=draft.document, author=author, base_revision=revision,
        body_source=revision.body_source,
        metadata={"assets": [{"id": str(asset.pk), "alt": "Same original diagram"}]})
    assert validate_draft_assets(correction, author) == [asset]
    assert can_access_asset(asset, author)


def test_missing_or_changed_persisted_file_blocks_publication_preflight(workspace):
    _, _, draft, asset = workspace
    revision = retain_asset(draft, asset)
    assert asset_files_available(revision)
    asset.file.storage.delete(asset.file.name)
    with pytest.raises(ValidationError, match="missing"):
        asset_files_available(revision)


def test_cleanup_defaults_to_dry_run_and_retained_revisions_survive(workspace):
    _, _, draft, asset = workspace
    ContentAsset.objects.filter(pk=asset.pk).update(created_at=timezone.now() - timedelta(days=8))
    inspected = cleanup_assets()
    assert inspected["eligible"] == [str(asset.pk)]
    assert inspected["deleted"] == []
    assert asset.file.storage.exists(asset.file.name)
    retain_asset(draft, asset)
    draft.delete()
    assert cleanup_assets(dry_run=False)["eligible"] == []
    assert asset.file.storage.exists(asset.file.name)


def test_cleanup_tombstone_prevents_new_reference_and_failed_unlink_can_resume(workspace, monkeypatch):
    author, _, draft, asset = workspace
    ContentAsset.objects.filter(pk=asset.pk).update(created_at=timezone.now() - timedelta(days=8))
    storage = asset.file.storage

    def fail(_name):
        raise OSError

    monkeypatch.setattr(storage, "delete", fail)
    assert cleanup_assets(dry_run=False)["failed"] == [str(asset.pk)]
    asset.refresh_from_db()
    assert asset.state == ContentAsset.State.DELETING
    draft.body_source = f"![Diagram](asset:{asset.pk})"
    draft.metadata = {"assets": [{"id": str(asset.pk), "alt": "A late reference"}]}
    with pytest.raises(ValidationError, match="being removed"):
        validate_draft_assets(draft, author)
    monkeypatch.undo()
    assert cleanup_assets(dry_run=False)["deleted"] == [str(asset.pk)]
    assert not storage.exists(asset.file.name)


def test_cleanup_handles_old_failed_insert_files_but_not_unrelated_files(workspace):
    _, _, _, asset = workspace
    storage = asset.file.storage
    key = uuid.uuid4()
    name = storage.save(f"assets/{key.hex}.png", ContentFile(b"private orphan"))
    other = storage.save("assets/not-an-owned-name.txt", ContentFile(b"unrelated"))
    old = (timezone.now() - timedelta(days=8)).timestamp()
    os.utime(storage.path(name), (old, old))
    os.utime(storage.path(other), (old, old))
    inspected = cleanup_assets()
    assert "orphan:" + str(key) in inspected["eligible"]
    assert storage.exists(name)
    assert "orphan:" + str(key) in cleanup_assets(dry_run=False)["deleted"]
    assert not storage.exists(name)
    assert storage.exists(other)


@pytest.mark.django_db(transaction=True)
def test_postgresql_cleanup_waits_for_reference_creation(settings, tmp_path):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL is required to verify row-lock exclusion")
    settings.LEARNING_PRIVATE_ASSET_ROOT = str(tmp_path / "private")
    settings.MEDIA_ROOT = str(tmp_path / "public")
    settings.LEARNING_MODULE_ENABLED = settings.LEARNING_CONTRIBUTIONS_ENABLED = True
    cache.clear()
    author = UserFactory()
    draft = ContentDraft.objects.create(document=ContentDocument.objects.create(), author=author)
    asset = store_asset(draft=draft, user=author, upload=image_upload())
    ContentAsset.objects.filter(pk=asset.pk).update(created_at=timezone.now() - timedelta(days=8))
    locked = Event()
    release = Event()

    def attach():
        try:
            with transaction.atomic():
                ContentAsset.objects.select_for_update().get(pk=asset.pk)
                locked.set()
                assert release.wait(5)
                current = ContentDraft.objects.get(pk=draft.pk)
                current.body_source = f"![Diagram](asset:{asset.pk})"
                current.metadata = {"assets": [{"id": str(asset.pk), "alt": "Protected reference"}]}
                validate_draft_assets(current, author)
                current.save()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(attach)
        assert locked.wait(5)
        cleaner = pool.submit(cleanup_assets, dry_run=False)
        release.set()
        writer.result(timeout=10)
        assert cleaner.result(timeout=10)["deleted"] == []
    assert asset.file.storage.exists(asset.file.name)
