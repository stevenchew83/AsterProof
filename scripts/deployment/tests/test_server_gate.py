# ruff: noqa: S108
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment.protocol import ProtocolError
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.server_gate import _installed_authority_matches
from scripts.deployment.server_gate import preflight
from scripts.deployment.server_gate import receive
from scripts.deployment.server_gate import status
from scripts.deployment.server_gate import submit
from scripts.deployment.server_submit import accept_request
from scripts.deployment.server_submit import main as submit_main
from scripts.deployment.target import TargetContract


def _contract(tmp_path: Path) -> TargetContract:
    contract = TargetContract.from_dict(
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
    for directory in (contract.release_root, contract.media_root, contract.registry_dir / "releases"):
        directory.mkdir(parents=True)
    contract.environment_file.write_text("secret=redacted\n")
    return contract


def _envelope(*, digest: str, operation: str = "deploy") -> dict[str, object]:
    return {
        "artifact_digest": digest,
        "deployment_id": "456",
        "migration_class": "none",
        "oidc_token": "header.payload.signature",
        "operation": operation,
        "release_sha": "a" * 40,
        "run_id": "123",
        "target_marker": "asterproof-production",
        "workflow_sha": "a" * 40,
    }


def _frame(value: dict[str, object], suffix: bytes = b"") -> io.BytesIO:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return io.BytesIO(f"{len(payload)}\n".encode() + payload + suffix)


def test_receive_streams_exact_digest_to_fixed_incoming_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    contract = _contract(tmp_path)
    artifact = b"trusted-release-archive"
    digest = hashlib.sha256(artifact).hexdigest()
    monkeypatch.setattr("scripts.deployment.server_gate.validate_authorization", lambda *_args: {"jti": "one"})

    result = receive(contract, _frame(_envelope(digest=digest) | {"artifact_size": len(artifact)}, artifact))

    assert result["status"] == "received"
    assert (contract.incoming_dir / f"123-{'a' * 40}.tar").read_bytes() == artifact


def test_receive_removes_partial_file_on_digest_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    contract = _contract(tmp_path)
    monkeypatch.setattr("scripts.deployment.server_gate.validate_authorization", lambda *_args: {"jti": "one"})

    with pytest.raises(ProtocolError, match="digest"):
        receive(contract, _frame(_envelope(digest="b" * 64) | {"artifact_size": 3}, b"bad"))

    assert list(contract.incoming_dir.iterdir()) == []


def test_preflight_exposes_only_validated_active_and_previous_release_evidence(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    current = contract.releases_dir / ("a" * 40)
    previous = contract.releases_dir / ("b" * 40)
    current.mkdir(parents=True)
    previous.mkdir()
    (contract.release_root / "current").symlink_to(Path("releases") / current.name)
    (contract.release_root / "previous").symlink_to(Path("releases") / previous.name)
    for release, digest, eligible in ((current, "c" * 64, True), (previous, "d" * 64, False)):
        (contract.registry_dir / "releases" / f"{release.name}.json").write_text(
            json.dumps(
                {
                    "artifact_digest": digest,
                    "migration_class": "none",
                    "release_sha": release.name,
                    "rollback_eligible": eligible,
                    "state": "active",
                },
            ),
        )

    result = preflight(contract, authority_matches=lambda: True)

    assert result["active_release"]["release_sha"] == current.name
    assert result["rollback_candidate"]["artifact_digest"] == "d" * 64
    assert result["rollback_candidate"]["rollback_eligible"] is False
    assert result["adoption"] is None
    assert result["checks"]["operations_resolved"] is True

    drifted = preflight(contract, authority_matches=lambda: False)
    assert drifted["checks"]["authority_integrity"] is False
    assert drifted["ok"] is False

    atomic_write_json(
        contract.registry_dir / "operations/41.json",
        {"release_sha": current.name, "run_id": "41", "state": "activating"},
    )
    unresolved = preflight(contract, authority_matches=lambda: True)
    assert unresolved["checks"]["operations_resolved"] is False
    assert unresolved["ok"] is False


def test_preflight_exposes_only_valid_authorized_adoption(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    contract.registry_dir.mkdir(parents=True, exist_ok=True)
    adoption = {
        "authorized_at": "2026-09-01T00:00:00Z",
        "legacy_sha": "a" * 40,
        "legacy_source_root": "/srv/legacy-asterproof",
        "repository": contract.repository,
        "state": "authorized",
        "state_fingerprint": "b" * 64,
        "target_marker": contract.marker,
    }
    (contract.registry_dir / "adoption.json").write_text(json.dumps(adoption))

    assert preflight(contract, authority_matches=lambda: True)["adoption"] == {
        key: value for key, value in adoption.items() if key != "legacy_source_root"
    }

    adoption["state_fingerprint"] = "invalid"
    (contract.registry_dir / "adoption.json").write_text(json.dumps(adoption))
    assert preflight(contract, authority_matches=lambda: True)["adoption"] is None


def test_status_returns_allowlisted_fields_only(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    operation = contract.registry_dir / "operations/123.json"
    operation.parent.mkdir()
    operation.write_text(json.dumps({"run_id": "123", "state": "active", "secret": "must-not-leak"}))

    assert status(contract, _frame({"run_id": "123"})) == {"run_id": "123", "state": "active"}


def test_submit_invokes_only_fixed_no_argument_sudo_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[str] = []

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        observed.extend(command)
        return SimpleNamespace(returncode=0, stdout=b'{"run_id":"123","state":"submitted"}')

    monkeypatch.setattr("scripts.deployment.server_gate.subprocess.run", run)

    assert submit(_frame(_envelope(digest="b" * 64)))["state"] == "submitted"
    assert observed == ["/usr/bin/sudo", "/usr/local/libexec/asterproof-deploy-submit"]


def test_authority_integrity_invokes_only_fixed_no_argument_root_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[str] = []

    def fake_run(command, **_kwargs):
        observed.extend(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("scripts.deployment.server_gate.subprocess.run", fake_run)

    assert _installed_authority_matches() is True
    assert observed == ["/usr/bin/sudo", "/usr/local/libexec/asterproof-authority-check"]


def test_root_submit_helper_rejects_all_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.deployment.server_submit.os.geteuid", lambda: 0)
    monkeypatch.setattr(
        "scripts.deployment.server_submit.sys.argv",
        ["asterproof-deploy-submit", "--contract", "/tmp/x"],
    )

    with pytest.raises(ValueError, match="does not accept arguments"):
        submit_main()

    sudoers = (Path(__file__).parents[3] / "deployment/sudoers/asterproof-deploy-submit.in").read_text()
    assert '/usr/local/libexec/asterproof-authority-check ""' in sudoers
    assert '/usr/local/libexec/asterproof-deploy-submit ""' in sudoers


def test_submit_helper_persists_request_before_start_and_rejects_jti_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    frame = _envelope(digest="b" * 64)
    monkeypatch.setattr(
        "scripts.deployment.server_submit.validate_authorization",
        lambda *_args: {"jti": "unique-token", "workflow_ref": contract.deploy_workflow_ref},
    )
    starts: list[list[str]] = []
    monkeypatch.setattr(
        "scripts.deployment.server_submit.subprocess.run",
        lambda command, **_kwargs: starts.append(command),
    )

    assert accept_request(contract, frame)["state"] == "submitted"
    request = json.loads((contract.registry_dir / "requests/123.json").read_text())
    assert request["workflow_sha"] == "a" * 40
    assert starts == [["/usr/bin/systemctl", "start", "asterproof-deploy-operation@123.service"]]
    with pytest.raises(ValueError, match="already been used"):
        accept_request(contract, frame)
