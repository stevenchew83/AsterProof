"""Shared-learning reader capability, checked without importing candidate code."""

from __future__ import annotations

import hashlib
from pathlib import Path  # noqa: TC003

READER_VERSION = 1
# A table is the durable schema marker, independent of rows or feature flags.
# Include partial installation: an incomplete schema must not enable an old reader.
FLOOR_TABLES = (
    "learning_contentdocument",
    "learning_contentpublication",
    "learning_legacycontentlink",
    "training_learningpath",
)
FLOOR_SQL = "SELECT " + " OR ".join(f"to_regclass('public.{table}') IS NOT NULL" for table in FLOOR_TABLES)
# Freeze after integration verification. Changing these bytes requires a reviewed
# capability refresh in the separately installed deployment authority.
READER_SOURCES = {
    "inspinia/learning/asset_views.py": (
        "5d7325fc5ba5b0b540637f31ff56a1408aa3ff9f55b0a110bb71867e7b94e24b"
    ),
    "inspinia/learning/assets.py": (
        "146acd0ba57567b68e32693d54ecf246a68a0224eb0f09dec11b4cbd7790b331"
    ),
    "inspinia/learning/drafts.py": (
        "659b261942fccb8795c06b3fb72a5c0dae85c56564d63427437416deda6dc28e"
    ),
    "inspinia/learning/issues.py": (
        "88f531cf351340fb914585539f674bc9a9f4294e9b6d41d573d0b0d7e59dbd6e"
    ),
    "inspinia/learning/legacy.py": (
        "27fbd30e8228fd72080fe12dd908c1e86beb65c9ef4fedd05589534cf48c8409"
    ),
    "inspinia/learning/models.py": (
        "97236911a546a563dcd20b5589f33e5b73dc9b98a71a4cf6b80e644a3593f2d7"
    ),
    "inspinia/learning/permissions.py": (
        "90aa9bf382d496b1fda66edef3f8c4831c792ebe725ad7a8249e5c206129d27e"
    ),
    "inspinia/learning/publication.py": (
        "01e96c318ca556ee8a30612522f48ce7ae64cd7828d9f423896426c54d6795ac"
    ),
    "inspinia/learning/rendering.py": (
        "5dc60ada7619e108641da7a71d87a21dc3dd72c6c31948c1e6307eb65f17b320"
    ),
    "inspinia/learning/revisions.py": (
        "0eac13fa12083a3b3adf19b9c129ff4463cefc5cbae92ed56f3a4218faf7824d"
    ),
    "inspinia/learning/rights.py": (
        "68335b4a1267310a482504cfbe0a0ca4687e159b7e80e2bdb23f0a0010cef03d"
    ),
    "inspinia/learning/storage.py": (
        "1a76e9ac4066b8a9d37844867d3b53a2f75124e97fe4e1ead8fc671e7a77d1ed"
    ),
    "inspinia/learning/views.py": (
        "8a117afc8a7c044aba35b2ca2bbfda91a73f138c10ec8d57ab75062f75a35f5f"
    ),
    "inspinia/learning/workflow_views.py": (
        "84ca969b101a15b1f69ca90dc057f79b0ed1bb1d190d813396dd4339aec67010"
    ),
    "inspinia/static/js/learning-math.js": (
        "19ffb72c501b1a987b5aa218ed43cf4bcd284cba5d302279ff44664c40cebebe"
    ),
    "inspinia/templates/learning/read.html": (
        "1f67ab56616e75f406713e6409aa5580cc26af327cfe7e4f3c6ba2d24606bf43"
    ),
    "inspinia/templates/website/learning_note.html": (
        "a47b5ccf94ecf4b8b0ee35c5b129664f6db6d530a8b3daf22cda42bb714d3087"
    ),
    "inspinia/templates/website/learning_pathway.html": (
        "9fc422132e70938859de70aea95101bc3ef7d039808cb024a69c8975b0eab3be"
    ),
    "inspinia/training/pathway_models.py": (
        "d9d3ce05e90db85ee557cb45390018a856692933a3aa7d0f039a1fd58f025445"
    ),
    "inspinia/training/pathways.py": (
        "3941c0de4dabce35e1310657c8f7af21287e17ac525bb2c9ac9e4d37980d275a"
    ),
    "inspinia/training/views.py": (
        "523b9992c4cb04c69e2fdb466f4820cdd63554cdb22cd3ccfc34088b4472cee9"
    ),
    "inspinia/website/admin.py": (
        "3de7078f0b23af990117282b2db81f619d0999352351c1b5e963208010bc23b3"
    ),
    "inspinia/website/automation.py": (
        "7eba58b3aa995c59140d87d01a7304cf68ec98843f09df4ca1a21935312e23f2"
    ),
    "inspinia/website/campaigns.py": (
        "25f6b3e0233ecc6f646b4f92cfc58b6449449ef1fc211e1a56f5b660a5b76a31"
    ),
    "inspinia/website/learning.py": (
        "5eade67a6065f90ae5f9e80d5bf08e9e472c7e90dd786f7e3028a90e5ae45ea5"
    ),
    "inspinia/website/models.py": (
        "a80aa2aa86f10081722d04617f53349ca0838417adeb21302b388676a924fad2"
    ),
    "inspinia/website/seo.py": (
        "3f514bdc02046bc9149b140f41f07ae5d8777fe2ad6276f2624080201d5edee6"
    ),
    "inspinia/website/views.py": (
        "49ebaf5de6e8fba4824375ac3d0945267f8b16ebacab0b010e10bf53d94de068"
    ),
}


def reader_sources_match(files):
    if not READER_SOURCES:
        return False
    entries = {item["path"]: item["sha256"] for item in files}
    return all(entries.get(path) == digest for path, digest in READER_SOURCES.items())


def verified_reader_release(release: Path, *, manifest=None):  # noqa: PLR0911 - Each trust-boundary failure is explicit.
    from scripts.deployment.release_manifest import ManifestError
    from scripts.deployment.release_manifest import ReleaseManifest

    try:
        if manifest is None:
            metadata = release / "release-metadata.json"
            if metadata.is_symlink() or metadata.stat().st_size > 2 * 1024 * 1024:
                return False
            manifest = ReleaseManifest.from_bytes(metadata.read_bytes())
        if manifest.learning_reader != READER_VERSION or manifest.release_sha != release.name:
            return False
        if not reader_sources_match(manifest.files):
            return False
        root = release.resolve(strict=True)
        for relative, expected in READER_SOURCES.items():
            path = release / relative
            if any(
                parent.is_symlink()
                for parent in (path, *path.parents)
                if parent == release or release in parent.parents
            ):
                return False
            if not path.resolve(strict=True).is_relative_to(root):
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return False
    except (OSError, ValueError, ManifestError):
        return False
    return True
