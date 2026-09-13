# ruff: noqa: TC003
from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from scripts.deployment.archive_safety import UnsafeArchiveError
from scripts.deployment.archive_safety import safe_extract
from scripts.deployment.archive_safety import validate_archive
from scripts.deployment.prepare_release import _materialize_internal_symlinks
from scripts.deployment.prepare_release import _rewrite_venv_shebangs
from scripts.deployment.release_manifest import ReleaseManifest
from scripts.deployment.release_manifest import sha256_file


def _write_archive(path: Path, members: list[tarfile.TarInfo], payloads: list[bytes]) -> None:
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as archive:
        for member, payload in zip(members, payloads, strict=True):
            member.uid = member.gid = 0
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(payload))


def _file(name: str, payload: bytes) -> tarfile.TarInfo:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    return member


def test_venv_console_script_shebangs_point_at_promoted_release(tmp_path: Path) -> None:
    staging = tmp_path / "build" / ("a" * 40)
    final = tmp_path / "releases" / staging.name
    binary = staging / ".venv/bin/python"
    console = staging / ".venv/bin/gunicorn"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"binary")
    console.write_bytes(f"#!{staging}/.venv/bin/python\nprint('run')\n".encode())

    _rewrite_venv_shebangs(staging / ".venv", staging=staging, final=final)

    assert console.read_text().startswith(f"#!{final}/.venv/bin/python\n")
    assert binary.read_bytes() == b"binary"


def test_safe_extract_verifies_manifest_and_digest(tmp_path: Path) -> None:
    payload = b"healthy\n"
    manifest = ReleaseManifest(
        repository="owner/AsterProof",
        repository_id="123",
        release_sha="a" * 40,
        run_id="42",
        built_at="2026-09-01T00:00:00Z",
        target_platform="manylinux2014_x86_64",
        python_abi="cp312",
        files=({"path": "app.txt", "sha256": __import__("hashlib").sha256(payload).hexdigest(), "size": 8},),
    )
    metadata = manifest.to_json_bytes()
    archive = tmp_path / "release.tar"
    _write_archive(archive, [_file("app.txt", payload), _file("release-metadata.json", metadata)], [payload, metadata])

    extracted = safe_extract(archive, tmp_path / "release", expected_digest=sha256_file(archive))

    assert extracted.release_sha == "a" * 40
    assert (tmp_path / "release/app.txt").read_bytes() == payload


@pytest.mark.parametrize("name", ["../escape", "/absolute", "dir\\windows", "a/../../escape"])
def test_validate_archive_rejects_unsafe_paths(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "release.tar"
    _write_archive(archive, [_file(name, b"x")], [b"x"])

    with pytest.raises(UnsafeArchiveError):
        validate_archive(archive)


@pytest.mark.parametrize("type_value", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE])
def test_validate_archive_rejects_non_regular_members(tmp_path: Path, type_value: bytes) -> None:
    member = tarfile.TarInfo("unsafe")
    member.type = type_value
    member.linkname = "target"
    archive = tmp_path / "release.tar"
    _write_archive(archive, [member], [b""])

    with pytest.raises(UnsafeArchiveError, match="prohibited"):
        validate_archive(archive)


def test_safe_extract_rejects_manifest_mismatch_and_removes_destination(tmp_path: Path) -> None:
    manifest = ReleaseManifest(
        repository="owner/AsterProof",
        repository_id="123",
        release_sha="a" * 40,
        run_id="42",
        built_at="2026-09-01T00:00:00Z",
        target_platform="manylinux2014_x86_64",
        python_abi="cp312",
        files=({"path": "app.txt", "sha256": "0" * 64, "size": 1},),
    ).to_json_bytes()
    archive = tmp_path / "release.tar"
    _write_archive(archive, [_file("app.txt", b"x"), _file("release-metadata.json", manifest)], [b"x", manifest])
    destination = tmp_path / "release"

    with pytest.raises(UnsafeArchiveError, match="does not match"):
        safe_extract(archive, destination)

    assert not destination.exists()


def test_validate_archive_rejects_unknown_pax_metadata(tmp_path: Path) -> None:
    member = _file("app.txt", b"x")
    member.pax_headers = {"comment": "not allowed"}
    archive = tmp_path / "release.tar"
    _write_archive(archive, [member], [b"x"])

    with pytest.raises(UnsafeArchiveError, match="PAX"):
        validate_archive(archive)


def test_prepared_runtime_materializes_internal_symlinks(tmp_path: Path) -> None:
    destination = tmp_path / "release"
    target = destination / "lib/package.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n")
    link = destination / "lib64"
    link.symlink_to("lib")

    _materialize_internal_symlinks(destination)

    assert not link.is_symlink()
    assert (link / "package.py").read_text() == "VALUE = 1\n"
