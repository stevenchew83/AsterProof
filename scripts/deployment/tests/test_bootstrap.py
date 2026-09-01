# ruff: noqa: S108
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment.bootstrap import BootstrapError
from scripts.deployment.bootstrap import audit_target
from scripts.deployment.bootstrap import authorize_legacy_adoption
from scripts.deployment.bootstrap import install_authority
from scripts.deployment.bootstrap import render_authorized_key
from scripts.deployment.target import TargetContract


def _materialize_test_snapshot(source: Path, _sha: str, destination: Path) -> None:
    (destination / "scripts").mkdir(parents=True)
    shutil.copy2(source / "scripts/__init__.py", destination / "scripts/__init__.py")
    shutil.copytree(source / "scripts/deployment", destination / "scripts/deployment")
    (destination / "deployment/systemd").mkdir(parents=True)
    shutil.copy2(
        source / "deployment/systemd/asterproof-deploy-operation@.service.in",
        destination / "deployment/systemd/asterproof-deploy-operation@.service.in",
    )
    (destination / "deployment/sudoers").mkdir(parents=True)
    shutil.copy2(
        source / "deployment/sudoers/asterproof-deploy-submit.in",
        destination / "deployment/sudoers/asterproof-deploy-submit.in",
    )


def _contract_data() -> dict[str, object]:
    return {
        "app_user": "asterproof",
        "build_user": "asterproof_build",
        "deploy_workflow_ref": "owner/AsterProof/.github/workflows/production-deploy.yml@refs/heads/main",
        "deploy_user": "asterproof_deploy",
        "environment_file": "/var/lib/asterproof/environment",
        "format_version": 1,
        "health_url": "https://example.com/healthz/",
        "marker": "asterproof-production",
        "media_root": "/var/lib/asterproof/media",
        "minimum_free_bytes": 2_147_483_648,
        "python_executable": "/usr/bin/python3.12",
        "python_abi": "cp312",
        "proxy_service": "nginx.service",
        "scheduler_service": "asterproof-catalog.service",
        "target_platform": "x86_64-manylinux_2_28",
        "tex_executable": "/usr/bin/latexmk",
        "release_root": "/srv/asterproof",
        "repository": "owner/AsterProof",
        "repository_id": "123",
        "rollback_workflow_ref": "owner/AsterProof/.github/workflows/production-rollback.yml@refs/heads/main",
        "service": "asterproof.service",
        "shared_root": "/var/lib/asterproof",
        "static_mode": "whitenoise",
    }


def _fixture(tmp_path: Path) -> tuple[TargetContract, Path]:
    data = _contract_data()
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(data))
    for directory in (
        "srv/asterproof",
        "var/lib/asterproof/media",
        "var/lib/asterproof-deploy",
        "etc/asterproof",
        "usr/bin",
    ):
        (tmp_path / directory).mkdir(parents=True)
    (tmp_path / "var/lib/asterproof/environment").write_text("SECRET=redacted\n")
    (tmp_path / "etc/asterproof/target-marker").write_text("asterproof-production\n")
    (tmp_path / "etc/asterproof/pg_service.conf").write_text("[asterproof_audit]\n")
    (tmp_path / "etc/asterproof/pg_service.conf").chmod(0o600)
    (tmp_path / "usr/bin/python3.12").write_text("")
    (tmp_path / "usr/bin/latexmk").write_text("")
    return TargetContract.from_dict(data), contract_path


def _audit_config(tmp_path: Path) -> Path:
    path = tmp_path / "source-migration-audit.json"
    path.write_text(
        json.dumps(
            {
                "expected_database_identity_hash": "0" * 64,
                "expected_role": "asterproof_catalog",
                "format_version": 1,
                "os_user": "asterproof_audit",
                "pg_service": "asterproof_audit",
                "pg_service_file": "/etc/asterproof/pg_service.conf",
            },
        ),
    )
    return path


def _service_reader(service: str) -> str:
    if service == "asterproof.service":
        return (
            "[Service]\nUser=asterproof\nEnvironmentFile=/var/lib/asterproof/environment\n"
            "WorkingDirectory=/srv/asterproof/current\n"
        )
    if service == "asterproof-catalog.service":
        return (
            "[Service]\nExecStart=/srv/asterproof/current/.venv/bin/python "
            "manage.py recompute_technique_progress_catalog --if-stale\n"
        )
    return (
        "[Service]\n"
        "location /media/ { alias /var/lib/asterproof/media/; }\n"
    )


def test_audit_is_read_only_and_accepts_explicit_valid_target(tmp_path: Path) -> None:
    contract, contract_path = _fixture(tmp_path)
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    result = audit_target(
        contract,
        contract_path=contract_path,
        root=tmp_path,
        service_reader=_service_reader,
        user_exists=lambda _user: True,
        runtime_matches=lambda *_args: True,
        oidc_reachable=lambda: True,
        source_matches=lambda *_args: True,
        ownership_matches=lambda *_args: True,
        source_root=Path(__file__).parents[3],
    )

    assert not result.ok
    assert not result.checks["trusted_authority_matches"]
    assert not result.checks["migration_audit_configured"]
    assert all(
        value
        for key, value in result.checks.items()
        if key not in {
            "deployment_directories_ready",
            "migration_audit_configured",
            "ssh_authority_directory",
            "trusted_authority_matches",
        }
    )
    assert sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")) == before


def test_audit_fails_closed_on_stale_service_path(tmp_path: Path) -> None:
    contract, contract_path = _fixture(tmp_path)

    result = audit_target(
        contract,
        contract_path=contract_path,
        root=tmp_path,
        service_reader=lambda _service: "WorkingDirectory=/old/checkout",
        user_exists=lambda _user: True,
        runtime_matches=lambda *_args: True,
        oidc_reachable=lambda: True,
        source_matches=lambda *_args: True,
        ownership_matches=lambda *_args: True,
        source_root=Path(__file__).parents[3],
    )

    assert not result.ok
    assert not result.checks["service_uses_current"]
    assert not result.checks["scheduler_uses_current"]


def test_install_requires_marker_confirmation_and_passing_audit(tmp_path: Path) -> None:
    contract, contract_path = _fixture(tmp_path)
    source_root = Path(__file__).parents[3]

    with pytest.raises(BootstrapError, match="confirmation"):
        install_authority(
            contract,
            source_root=source_root,
            contract_path=contract_path,
            deploy_public_key="ssh-ed25519 AAAATEST",
            migration_audit_config=_audit_config(tmp_path),
            expected_authority_sha="a" * 40,
            confirmation="wrong-host",
            root=tmp_path,
            service_reader=_service_reader,
            user_exists=lambda _user: True,
            runtime_matches=lambda *_args: True,
            oidc_reachable=lambda: True,
            source_matches=lambda *_args: True,
            ownership_matches=lambda *_args: True,
            source_sha_reader=lambda _path: "a" * 40,
            snapshot_materializer=_materialize_test_snapshot,
            reload_systemd=False,
        )


def test_install_writes_and_rechecks_trusted_authority_manifest(tmp_path: Path) -> None:
    contract, contract_path = _fixture(tmp_path)
    source_root = Path(__file__).parents[3]
    migration_audit_config = _audit_config(tmp_path)
    expected_contract_bytes = contract_path.read_bytes()
    expected_audit_bytes = migration_audit_config.read_bytes()

    def mutate_inputs_after_snapshot(source: Path, sha: str, destination: Path) -> None:
        contract_path.write_text("{}")
        migration_audit_config.write_text("{}")
        _materialize_test_snapshot(source, sha, destination)

    result = install_authority(
        contract,
        source_root=source_root,
        contract_path=contract_path,
        deploy_public_key="ssh-ed25519 AAAATEST",
        migration_audit_config=migration_audit_config,
        expected_authority_sha="a" * 40,
        confirmation=contract.marker,
        root=tmp_path,
        service_reader=_service_reader,
        user_exists=lambda _user: True,
        runtime_matches=lambda *_args: True,
        oidc_reachable=lambda: True,
        source_matches=lambda *_args: True,
        ownership_matches=lambda *_args: True,
        source_sha_reader=lambda _path: "a" * 40,
        snapshot_materializer=mutate_inputs_after_snapshot,
        reload_systemd=False,
    )

    assert result.ok
    assert result.checks["trusted_authority_matches"]
    assert (tmp_path / "usr/local/libexec/asterproof-authority").is_symlink()
    expected_authority_directory_mode = 0o755
    assert (
        tmp_path / "usr/local/libexec/asterproof-authority/scripts/deployment"
    ).stat().st_mode & 0o777 == expected_authority_directory_mode
    assert (tmp_path / "usr/local/libexec/asterproof-prepare-release").is_file()
    assert (tmp_path / "usr/local/libexec/asterproof-migration-audit").is_file()
    assert (tmp_path / "usr/local/libexec/asterproof-deploy-gateway").read_text().startswith(
        f"#!{contract.python_executable}\n",
    )
    expected_ssh_directory_mode = 0o755
    assert (
        tmp_path / "var/lib/asterproof-deploy/.ssh"
    ).stat().st_mode & 0o777 == expected_ssh_directory_mode
    expected_contract_mode = 0o644
    assert (tmp_path / "etc/asterproof/deployment-target.json").stat().st_mode & 0o777 == expected_contract_mode
    assert (tmp_path / "etc/asterproof/deployment-target.json").read_bytes() == expected_contract_bytes
    assert (tmp_path / "etc/asterproof/migration-audit.json").read_bytes() == expected_audit_bytes
    expected_public_evidence_mode = 0o644
    assert (
        tmp_path / "etc/asterproof/authority-manifest.json"
    ).stat().st_mode & 0o777 == expected_public_evidence_mode
    expected_registry_mode = 0o711
    assert (
        tmp_path / contract.registry_dir.relative_to("/")
    ).stat().st_mode & 0o777 == expected_registry_mode

    adoption = authorize_legacy_adoption(
        contract,
        contract_path=tmp_path / "etc/asterproof/deployment-target.json",
        source_root=source_root,
        confirmation="LEGACY_NON_ROLLBACK",
        root=tmp_path,
        service_reader=_service_reader,
        user_exists=lambda _user: True,
        runtime_matches=lambda *_args: True,
        oidc_reachable=lambda: True,
        source_matches=lambda *_args: True,
        ownership_matches=lambda *_args: True,
        service_uses_source=lambda *_args: True,
        legacy_sha_reader=lambda _path: "a" * 40,
        state_fingerprint_reader=lambda _path: "b" * 64,
    )

    assert adoption["state"] == "authorized"
    assert adoption["legacy_sha"] == "a" * 40
    assert (
        tmp_path / (contract.registry_dir / "adoption.json").relative_to("/")
    ).stat().st_mode & 0o777 == expected_public_evidence_mode


def test_install_rejects_deploy_controlled_ssh_directory_symlink_before_mutating_target(tmp_path: Path) -> None:
    contract, contract_path = _fixture(tmp_path)
    source_root = Path(__file__).parents[3]
    victim = tmp_path / "victim-directory"
    victim.mkdir(mode=0o700)
    (tmp_path / "var/lib/asterproof-deploy/.ssh").symlink_to(victim)

    with pytest.raises(BootstrapError, match="SSH directory is unsafe"):
        install_authority(
            contract,
            source_root=source_root,
            contract_path=contract_path,
            deploy_public_key="ssh-ed25519 AAAATEST",
            migration_audit_config=_audit_config(tmp_path),
            expected_authority_sha="a" * 40,
            confirmation=contract.marker,
            root=tmp_path,
            service_reader=_service_reader,
            user_exists=lambda _user: True,
            runtime_matches=lambda *_args: True,
            oidc_reachable=lambda: True,
            source_matches=lambda *_args: True,
            ownership_matches=lambda *_args: True,
            source_sha_reader=lambda _path: "a" * 40,
            snapshot_materializer=_materialize_test_snapshot,
            reload_systemd=False,
        )

    expected_victim_mode = 0o700
    assert victim.stat().st_mode & 0o777 == expected_victim_mode


def test_legacy_adoption_requires_explicit_nonrollback_confirmation(tmp_path: Path) -> None:
    contract, contract_path = _fixture(tmp_path)

    with pytest.raises(BootstrapError, match="non-rollback"):
        authorize_legacy_adoption(
            contract,
            contract_path=contract_path,
            source_root=Path(__file__).parents[3],
            confirmation="yes",
            root=tmp_path,
        )


def test_legacy_adoption_rejects_residual_managed_state(tmp_path: Path, monkeypatch) -> None:
    contract, contract_path = _fixture(tmp_path)
    releases = tmp_path / contract.releases_dir.relative_to("/")
    releases.mkdir(parents=True)
    (tmp_path / (contract.release_root / "previous").relative_to("/")).symlink_to(
        Path("releases") / ("a" * 40),
    )
    monkeypatch.setattr(
        "scripts.deployment.bootstrap.audit_target",
        lambda *_args, **_kwargs: SimpleNamespace(ok=True),
    )

    with pytest.raises(BootstrapError, match="release links must be absent"):
        authorize_legacy_adoption(
            contract,
            contract_path=contract_path,
            source_root=Path(__file__).parents[3],
            confirmation="LEGACY_NON_ROLLBACK",
            root=tmp_path,
        )


def test_authorized_key_has_forced_command_and_forwarding_restriction() -> None:
    value = render_authorized_key("ssh-ed25519 AAAATEST deploy")

    assert value.startswith('restrict,command="/usr/local/libexec/asterproof-deploy-gateway ')
    assert "deployment-target.json" in value
    assert value.endswith("ssh-ed25519 AAAATEST deploy\n")


@pytest.mark.parametrize("key", ["ssh-rsa AAAA", "ssh-ed25519 AAAA\ncommand=sh", "not-a-key"])
def test_authorized_key_rejects_unsafe_input(key: str) -> None:
    with pytest.raises(BootstrapError):
        render_authorized_key(key)
