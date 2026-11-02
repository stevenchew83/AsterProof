# ruff: noqa: EM101, PLR2004, SLF001, TRY003
"""A privacy cutover cannot recover to a raw-media-only reader."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import solution_image_compat as compat
from scripts.deployment.operation_worker import OperationError
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.release_manifest import ManifestError
from scripts.deployment.release_manifest import ReleaseManifest

ROOT = Path(__file__).resolve().parents[3]


def marker(tmp_path, monkeypatch, value=None):
    monkeypatch.setattr(compat, "ROOT_UID", os.getuid())
    path = tmp_path / compat.MARKER_NAME
    path.write_text(json.dumps(value or {"format_version": 1, "image_reader_required": True}))
    path.chmod(0o644)
    return path


def write_reader(release, monkeypatch):
    relative = "inspinia/solutions/image_access.py"
    body = b"# Reviewed synthetic image reader.\n"
    digest = hashlib.sha256(body).hexdigest()
    monkeypatch.setattr(compat, "READER_SOURCES", {relative: digest})
    target = release / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(body)
    manifest = ReleaseManifest(
        repository="owner/AsterProof",
        repository_id="123",
        release_sha=release.name,
        run_id="42",
        built_at="2026-11-02T00:00:00Z",
        target_platform="manylinux2014_x86_64",
        python_abi="cp312",
        files=({"path": relative, "sha256": digest, "size": len(body)},),
        solution_image_reader=1,
    )
    (release / "release-metadata.json").write_bytes(manifest.to_json_bytes())
    return target


def test_missing_marker_preserves_pre_cutover_behavior(tmp_path):
    assert compat.reader_required(tmp_path) is False
    WorkerBackend().ensure_image_reader(SimpleNamespace(registry_dir=tmp_path), tmp_path / "legacy")


def test_forum_schema_cannot_run_before_privacy_cutover(tmp_path):
    with pytest.raises(OperationError, match="image_privacy_cutover_required"):
        WorkerBackend().check_solution_forum_schema(SimpleNamespace(registry_dir=tmp_path), tmp_path / "candidate")


def test_exact_protected_owner_marker_requires_image_reader(tmp_path, monkeypatch):
    path = marker(tmp_path, monkeypatch)
    content = path.read_bytes()
    assert compat.reader_required(tmp_path) is True
    assert path.read_bytes() == content
    with pytest.raises(OperationError, match="image_reader_required"):
        WorkerBackend().ensure_image_reader(SimpleNamespace(registry_dir=tmp_path), tmp_path / "legacy")


@pytest.mark.parametrize(
    "value",
    [
        {"format_version": True, "image_reader_required": True},
        {"format_version": 1, "image_reader_required": False},
        {"format_version": 1, "image_reader_required": 1},
        {"format_version": 1, "image_reader_required": True, "extra": "ignored"},
    ],
)
def test_malformed_or_disabled_marker_fails_closed(tmp_path, monkeypatch, value):
    marker(tmp_path, monkeypatch, value)
    with pytest.raises(OperationError, match="image_reader_floor_unavailable"):
        WorkerBackend().ensure_image_reader(SimpleNamespace(registry_dir=tmp_path), tmp_path / "legacy")


@pytest.mark.parametrize("change", ["symlink", "fifo", "writable", "owner", "size", "json"])
def test_untrusted_marker_is_rejected(tmp_path, monkeypatch, change):
    path = marker(tmp_path, monkeypatch)
    if change == "symlink":
        destination = tmp_path / "other"
        path.rename(destination)
        path.symlink_to(destination)
    elif change == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif change == "writable":
        path.chmod(0o666)
    elif change == "owner":
        monkeypatch.setattr(compat, "ROOT_UID", os.getuid() + 1)
    elif change == "size":
        path.write_bytes(b" " * (compat.MAX_MARKER_BYTES + 1))
    else:
        path.write_text("not json")
    with pytest.raises(OperationError, match="image_reader_floor_unavailable"):
        WorkerBackend().ensure_image_reader(SimpleNamespace(registry_dir=tmp_path), tmp_path / "legacy")


def test_capability_is_bound_to_manifest_directory_and_actual_source_bytes(tmp_path, monkeypatch):
    release = tmp_path / ("a" * 40)
    target = write_reader(release, monkeypatch)
    assert compat.verified_reader_release(release)
    target.write_bytes(b"# Unreviewed replacement.\n")
    assert not compat.verified_reader_release(release)
    target.unlink()
    target.symlink_to(tmp_path / "outside")
    assert not compat.verified_reader_release(release)


def test_compatible_reader_satisfies_cutover_and_document_guard_is_preserved(tmp_path, monkeypatch):
    registry = tmp_path / "registry"
    registry.mkdir()
    marker(registry, monkeypatch)
    release = tmp_path / ("a" * 40)
    write_reader(release, monkeypatch)
    backend = WorkerBackend()
    contract = SimpleNamespace(registry_dir=registry)
    backend.ensure_image_reader(contract, release)
    monkeypatch.setattr(backend, "document_reader_required", lambda contract: True)
    with pytest.raises(OperationError, match="document_reader_required"):
        backend.ensure_document_reader(contract, release)


@pytest.mark.parametrize("value", [True, "1", 2, -1])
def test_capability_type_and_version_are_strict(tmp_path, monkeypatch, value):
    release = tmp_path / ("a" * 40)
    write_reader(release, monkeypatch)
    path = release / "release-metadata.json"
    raw = json.loads(path.read_text())
    raw["solution_image_reader"] = value
    with pytest.raises(ManifestError, match="image reader capability"):
        ReleaseManifest.from_bytes(json.dumps(raw).encode())


def test_frozen_image_sources_match_the_reviewed_implementation():
    assert compat.READER_SOURCES
    for relative, expected in compat.READER_SOURCES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
