# ruff: noqa: TC003
from __future__ import annotations

import json

import pytest

from scripts.deployment.release_manifest import ManifestError
from scripts.deployment.release_manifest import ReleaseManifest


def _manifest(**overrides: object) -> ReleaseManifest:
    values = {
        "repository": "owner/AsterProof",
        "repository_id": "123",
        "release_sha": "a" * 40,
        "run_id": "42",
        "built_at": "2026-09-01T00:00:00Z",
        "target_platform": "manylinux2014_x86_64",
        "python_abi": "cp312",
        "files": ({"path": "manage.py", "sha256": "b" * 64, "size": 123},),
    }
    values.update(overrides)
    return ReleaseManifest(**values)


def test_manifest_round_trip_is_canonical() -> None:
    encoded = _manifest().to_json_bytes()

    assert ReleaseManifest.from_bytes(encoded) == _manifest()
    assert encoded.endswith(b"\n")
    assert b"archive_sha256" not in encoded


@pytest.mark.parametrize(
    ("field", "value"),
    [("release_sha", "main"), ("run_id", "1/2"), ("repository", "owner"), ("python_abi", "3.12")],
)
def test_manifest_rejects_invalid_identity_fields(field: str, value: str) -> None:
    with pytest.raises(ManifestError):
        _manifest(**{field: value}).validate()


def test_manifest_rejects_unknown_shape() -> None:
    payload = json.loads(_manifest().to_json_bytes())
    del payload["release_sha"]

    with pytest.raises(ManifestError, match="malformed"):
        ReleaseManifest.from_bytes(json.dumps(payload).encode())
