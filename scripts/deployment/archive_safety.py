# ruff: noqa: C901, EM101, PLR0912, PLR2004, TRY003, TRY300, TRY301
from __future__ import annotations

import os
import shutil
import stat
import tarfile
from pathlib import Path
from pathlib import PurePosixPath

from scripts.deployment.release_manifest import ManifestError
from scripts.deployment.release_manifest import ReleaseManifest
from scripts.deployment.release_manifest import sha256_file

DEFAULT_MAX_MEMBERS = 100_000
DEFAULT_MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED_PAX_HEADERS = {"path"}


class UnsafeArchiveError(ValueError):
    pass


def _validate_name(name: str) -> PurePosixPath:
    if not name or name.startswith("/") or "\\" in name or "\x00" in name:
        raise UnsafeArchiveError("unsafe archive member name")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafeArchiveError("unsafe archive member path")
    return path


def validate_archive(
    archive_path: Path,
    *,
    expected_digest: str | None = None,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_expanded_bytes: int = DEFAULT_MAX_EXPANDED_BYTES,
) -> list[tarfile.TarInfo]:
    if expected_digest is not None and sha256_file(archive_path) != expected_digest:
        raise UnsafeArchiveError("release artifact digest mismatch")

    members: list[tarfile.TarInfo] = []
    seen: set[str] = set()
    expanded = 0
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            for member in archive:
                if len(members) >= max_members:
                    raise UnsafeArchiveError("release artifact has too many members")
                path = _validate_name(member.name)
                normalized = path.as_posix()
                if normalized in seen:
                    raise UnsafeArchiveError("release artifact has duplicate members")
                seen.add(normalized)
                if not (member.isdir() or member.isreg()):
                    raise UnsafeArchiveError("release artifact contains a prohibited member type")
                if set(member.pax_headers) - ALLOWED_PAX_HEADERS:
                    raise UnsafeArchiveError("release artifact contains unsupported PAX metadata")
                if member.uid != 0 or member.gid != 0:
                    raise UnsafeArchiveError("release artifact contains unexpected ownership")
                mode = stat.S_IMODE(member.mode)
                if member.isdir() and mode != 0o755:
                    raise UnsafeArchiveError("release directory has unexpected mode")
                if member.isreg() and mode not in {0o644, 0o755}:
                    raise UnsafeArchiveError("release file has unexpected mode")
                expanded += member.size
                if expanded > max_expanded_bytes:
                    raise UnsafeArchiveError("release artifact expands beyond the configured limit")
                members.append(member)
    except (tarfile.TarError, OSError) as exc:
        raise UnsafeArchiveError("release artifact cannot be read") from exc
    return members


def safe_extract(
    archive_path: Path,
    destination: Path,
    *,
    expected_digest: str | None = None,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_expanded_bytes: int = DEFAULT_MAX_EXPANDED_BYTES,
) -> ReleaseManifest:
    members = validate_archive(
        archive_path,
        expected_digest=expected_digest,
        max_members=max_members,
        max_expanded_bytes=max_expanded_bytes,
    )
    if destination.exists():
        raise UnsafeArchiveError("release destination already exists")
    destination.mkdir(mode=0o755, parents=False)
    root = destination.resolve()
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            for member in members:
                relative = Path(*PurePosixPath(member.name).parts)
                target = destination / relative
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                if target.parent.resolve() == root or root in target.parent.resolve().parents:
                    pass
                else:
                    raise UnsafeArchiveError("release member escapes destination")
                if member.isdir():
                    target.mkdir(mode=0o755, exist_ok=True)
                    continue
                source = archive.extractfile(member)
                if source is None:
                    raise UnsafeArchiveError("release file payload is missing")
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(target, flags, member.mode)
                with os.fdopen(fd, "wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)

        manifest_path = destination / "release-metadata.json"
        manifest = ReleaseManifest.from_bytes(manifest_path.read_bytes())
        expected_files = {item["path"]: item for item in manifest.files}
        actual_files = {
            path.relative_to(destination).as_posix(): path
            for path in destination.rglob("*")
            if path.is_file() and path.name != "release-metadata.json"
        }
        if set(actual_files) != set(expected_files):
            raise UnsafeArchiveError("release contents do not match the manifest")
        for relative, path in actual_files.items():
            item = expected_files[relative]
            if path.stat().st_size != item["size"] or sha256_file(path) != item["sha256"]:
                raise UnsafeArchiveError("release file does not match the manifest")
        return manifest
    except (OSError, ManifestError) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        if isinstance(exc, UnsafeArchiveError):
            raise
        raise UnsafeArchiveError("release extraction failed") from exc
    except UnsafeArchiveError:
        shutil.rmtree(destination, ignore_errors=True)
        raise
