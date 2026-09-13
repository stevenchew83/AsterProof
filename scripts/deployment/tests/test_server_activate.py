# ruff: noqa: PYI034, S108, TC003
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from scripts.deployment.release_state import ReleaseStateError
from scripts.deployment.release_state import atomic_symlink
from scripts.deployment.server_activate import activate_release
from scripts.deployment.server_activate import health_check
from scripts.deployment.server_activate import restore_previous
from scripts.deployment.server_activate import verify_release
from scripts.deployment.server_activate import verify_static_assets
from scripts.deployment.server_activate import write_runtime_state
from scripts.deployment.target import TargetContract


def _contract(tmp_path: Path) -> TargetContract:
    return TargetContract.from_dict(
        {
            "app_user": "asterproof",
            "build_user": "asterproof_build",
            "deploy_user": "asterproof_deploy",
            "deploy_workflow_ref": "owner/AsterProof/.github/workflows/production-deploy.yml@refs/heads/main",
            "environment_file": str(tmp_path / "shared/environment"),
            "format_version": 1,
            "health_url": "https://example.com/healthz/",
            "marker": "asterproof-production",
            "media_root": str(tmp_path / "shared/media"),
            "minimum_free_bytes": 536_870_912,
            "python_executable": "/usr/bin/python3.12",
            "python_abi": "cp312",
            "proxy_service": "nginx.service",
            "scheduler_service": "asterproof-catalog.service",
            "target_platform": "x86_64-manylinux_2_28",
            "tex_executable": "/usr/bin/latexmk",
            "release_root": str(tmp_path / "release-root"),
            "repository": "owner/AsterProof",
            "repository_id": "123",
            "rollback_workflow_ref": "owner/AsterProof/.github/workflows/production-rollback.yml@refs/heads/main",
            "service": "asterproof.service",
            "shared_root": str(tmp_path / "shared"),
            "static_mode": "whitenoise",
        },
    )


def test_activate_and_restore_previous_are_atomic(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    old = contract.releases_dir / ("a" * 40)
    new = contract.releases_dir / ("b" * 40)
    old.mkdir(parents=True)
    new.mkdir()
    atomic_symlink(contract.release_root / "current", old, allowed_root=contract.releases_dir)

    assert activate_release(contract, "b" * 40) == "a" * 40
    assert (contract.release_root / "current").resolve() == new
    assert restore_previous(contract) == "a" * 40
    assert (contract.release_root / "current").resolve() == old
    assert (contract.release_root / "previous").resolve() == new


class _Response(io.BytesIO):
    status = 200

    def __init__(self, value: bytes, url: str = "https://example.com/healthz/") -> None:
        super().__init__(value)
        self.url = url

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url


def test_health_check_rejects_release_identity_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    contract = _contract(tmp_path)
    payload = json.dumps({"process_commit_sha": "c" * 40, "artifact_sha256": "d" * 64}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response(payload))

    with pytest.raises(ReleaseStateError, match="identity"):
        health_check(contract, "a" * 40, "b" * 64)


def test_runtime_state_matches_health_endpoint_contract(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()

    write_runtime_state(
        release,
        release_sha="a" * 40,
        artifact_digest="b" * 64,
        state_fingerprint="c" * 64,
    )

    value = json.loads((release / "runtime-release-state.json").read_text())
    assert set(value) == {
        "artifact_sha256",
        "state_fingerprint",
        "process_commit_sha",
        "recorded_at",
        "schema_version",
        "status",
    }
    assert value["process_commit_sha"] == "a" * 40


def test_static_verification_uses_manifest_hashes_over_configured_https_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    release_sha = "a" * 40
    release = contract.releases_dir / release_sha
    release.mkdir(parents=True)
    css = b"body{}"
    javascript = b"console.log(1)"
    manifest = {
        "built_at": "2026-09-01T00:00:00Z",
        "files": [
            {"path": "staticfiles/css/app.abc.css", "sha256": hashlib.sha256(css).hexdigest(), "size": len(css)},
            {
                "path": "staticfiles/js/app.def.js",
                "sha256": hashlib.sha256(javascript).hexdigest(),
                "size": len(javascript),
            },
        ],
        "format_version": 1,
        "python_abi": "cp312",
        "release_sha": release_sha,
        "repository": contract.repository,
        "repository_id": contract.repository_id,
        "run_id": "1",
        "target_platform": contract.target_platform,
    }
    (release / "release-metadata.json").write_text(json.dumps(manifest))

    def open_request(request, **_kwargs):
        payload = css if request.full_url.endswith(".css") else javascript
        return _Response(payload, request.full_url)

    monkeypatch.setattr("urllib.request.urlopen", open_request)

    verify_static_assets(contract, release_sha)


def test_stabilization_rejects_changed_process_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = _contract(Path("/tmp/asterproof-stabilization-test"))
    evidence = iter(({1: 100}, {1: 101}))
    monkeypatch.setattr("scripts.deployment.server_activate.verify_service_processes", lambda *_args: next(evidence))
    monkeypatch.setattr(
        "scripts.deployment.server_activate.health_check",
        lambda *_args: {"process_commit_sha": "a" * 40},
    )
    monkeypatch.setattr("scripts.deployment.server_activate.verify_static_assets", lambda *_args: None)
    monkeypatch.setattr("scripts.deployment.server_activate.time.sleep", lambda _seconds: None)

    with pytest.raises(ReleaseStateError, match="changed during stabilization"):
        verify_release(contract, "a" * 40, "b" * 64)
