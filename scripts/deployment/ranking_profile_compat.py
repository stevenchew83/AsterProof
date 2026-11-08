"""Ranking profile reader capability, checked without importing candidate code."""

from __future__ import annotations

import hashlib
from pathlib import Path  # noqa: TC003

READER_VERSION = 1
# Either empty table, or a recorded installation, retains the reader floor.
FLOOR_SQL = (
    "SELECT to_regclass('public.rankings_resultprofile') IS NOT NULL "
    "OR to_regclass('public.rankings_resultclaim') IS NOT NULL "
    "OR EXISTS (SELECT 1 FROM public.django_migrations "
    "WHERE app='rankings' AND name='0006_student_achievement_profiles')"
)
# These bytes are checked against the attested manifest and actual release files.
READER_SOURCES = {
    "inspinia/rankings/profile_models.py": (
        "67447095bc4200f84aedd6112e7b32feff4dd2bc78c4d4f48b05f592829fb41c"
    ),
    "inspinia/rankings/models.py": (
        "e24840aee6ec83dbf617b93d4a779d8568c30c89c5a5f5970b12cb665cf085ad"
    ),
    "inspinia/rankings/analysis_models.py": (
        "0f8bdb34213aafa272f9cff5bfe740e35ce4df04503118b8a48b791dfdd825b7"
    ),
    "inspinia/rankings/services/corrections.py": (
        "bfa4ab3cd851dcc43e00509d1656a5d400b07ced9c9aa3e5e65efdafd8b2d308"
    ),
    "inspinia/rankings/correction_views.py": (
        "c6c184dfc511a9a1b88df357c02cfea7e2f2b2ec0f264fadb56f7239b74d6d12"
    ),
    "inspinia/rankings/correction_forms.py": (
        "32cb2c354167b996550e6f854437ad7097e1b5cd2e9f8b4430e01e6ea105a262"
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
        if manifest.release_sha != release.name:
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
