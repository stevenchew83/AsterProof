"""Verify that an attested release enforces the stored registration policy."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from scripts.deployment.release_manifest import ManifestError
from scripts.deployment.release_manifest import ReleaseManifest
from scripts.deployment.release_manifest import sha256_file

FLOOR_SQL = """
SELECT EXISTS (
    SELECT 1 FROM pg_catalog.pg_attribute
    WHERE attrelid = to_regclass('public.users_useraccesssettings')
      AND attname = 'allow_public_registration' AND attnum > 0 AND NOT attisdropped
) OR EXISTS (
    SELECT 1 FROM public.django_migrations
    WHERE app = 'users' AND name = '0010_public_registration'
)
"""
# Freeze the allauth adapter and the effective registration policy.
READER_SOURCES = {
    "inspinia/users/adapters.py": "b84465dc1d2d849a040f9e4b446286338d5961e9c7c3297ae8dcb0903a3523b5",
    "inspinia/users/models.py": "37ddd16879d4f66a63c723ed4d11357d594c7cadfe3fea9a91cd4e5b5836757f",
}


def verified_reader_release(release: Path) -> bool:
    try:
        metadata = release / "release-metadata.json"
        if metadata.is_symlink() or metadata.stat().st_size > 2 * 1024 * 1024:
            return False
        manifest = ReleaseManifest.from_bytes(metadata.read_bytes())
        if manifest.release_sha != release.name:
            return False
        entries = {entry["path"]: entry["sha256"] for entry in manifest.files}
        root = release.resolve(strict=True)
        for relative, digest in READER_SOURCES.items():
            path = release / relative
            if (
                entries.get(relative) != digest
                or path.is_symlink()
                or not path.resolve(strict=True).is_relative_to(root)
                or sha256_file(path) != digest
            ):
                return False
    except (OSError, ValueError, ManifestError):
        return False
    return True
