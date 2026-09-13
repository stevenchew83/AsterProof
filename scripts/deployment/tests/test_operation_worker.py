# ruff: noqa: ARG002, EM101, S108, TC003, TRY003
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.deployment.operation_worker import OperationError
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import prune_releases
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.release_state import atomic_symlink
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.server_activate import activate_release
from scripts.deployment.server_activate import restore_previous
from scripts.deployment.target import TargetContract

OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
OLD_DIGEST = "c" * 64
NEW_DIGEST = "d" * 64
FINGERPRINT = "e" * 64


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
    contract.releases_dir.mkdir(parents=True)
    contract.build_dir.mkdir()
    return contract


def _seed(
    contract: TargetContract,
    *,
    operation: str = "deploy",
    target_sha: str = NEW_SHA,
    digest: str = NEW_DIGEST,
    migration_class: str = "none",
) -> None:
    old = contract.releases_dir / OLD_SHA
    old.mkdir(exist_ok=True)
    atomic_symlink(contract.release_root / "current", old, allowed_root=contract.releases_dir)
    atomic_write_json(
        contract.registry_dir / "releases" / f"{OLD_SHA}.json",
        {
            "artifact_digest": OLD_DIGEST,
            "migration_class": "none",
            "state_fingerprint": FINGERPRINT,
            "release_sha": OLD_SHA,
            "rollback_eligible": True,
            "state": "active",
        },
    )
    request: dict[str, Any] = {
        "artifact_digest": digest,
        "deployment_id": "7",
        "migration_class": migration_class,
        "operation": operation,
        "release_sha": target_sha,
        "run_id": "42",
        "target_marker": contract.marker,
        "workflow_sha": target_sha if operation == "deploy" else NEW_SHA,
        "workflow_ref": contract.deploy_workflow_ref if operation == "deploy" else contract.rollback_workflow_ref,
    }
    atomic_write_json(contract.registry_dir / "requests/42.json", request)
    atomic_write_json(
        contract.registry_dir / "operations/42.json",
        request | {"error_code": None, "state": "verified"},
    )


class FakeBackend(WorkerBackend):
    def __init__(self, *, fail_target: bool = False, fail_candidate: bool = False) -> None:
        super().__init__()
        self.fail_target = fail_target
        self.fail_candidate = fail_candidate
        self.prepared = False

    def prepare(self, contract: TargetContract, request: dict[str, Any], destination: Path) -> None:
        destination.mkdir()
        self.prepared = True

    def candidate_check(self, contract: TargetContract, release: Path) -> None:
        assert self.prepared
        if self.fail_candidate:
            raise OperationError("candidate_check_failed")

    def candidate_migrations_applied(self, contract: TargetContract, release: Path) -> None:
        assert self.prepared

    def publish_permissions(self, contract: TargetContract, staging: Path, release: Path) -> None:
        assert self.prepared
        staging.replace(release)

    def migrate(self, contract: TargetContract, release: Path) -> None:
        raise AssertionError("none-class deployment must not migrate")

    def state_fingerprint(self, contract: TargetContract) -> str:
        return FINGERPRINT

    def legacy_service_matches(self, contract: TargetContract, source_root: Path) -> bool:
        return source_root == Path("/srv/legacy-asterproof")

    def legacy_source_matches(self, contract: TargetContract, source_root: Path, legacy_sha: str) -> bool:
        return source_root == Path("/srv/legacy-asterproof") and legacy_sha == OLD_SHA

    def activate(self, contract: TargetContract, release_sha: str) -> str | None:
        return activate_release(contract, release_sha)

    def restore(self, contract: TargetContract) -> str:
        return restore_previous(contract)

    def verify(self, contract: TargetContract, release_sha: str, artifact_digest: str) -> dict[str, Any]:
        assert release_sha == OLD_SHA
        assert artifact_digest == OLD_DIGEST
        return {"state_fingerprint": FINGERPRINT}

    def restart_and_verify(
        self,
        contract: TargetContract,
        release_sha: str,
        artifact_digest: str,
    ) -> dict[str, Any]:
        if self.fail_target and release_sha == NEW_SHA:
            raise OperationError("health_failed")
        return {"state_fingerprint": FINGERPRINT}


def test_root_worker_rejects_deploy_controlled_archive_symlink(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    contract.incoming_dir.mkdir()
    contract.processing_dir.mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.write_text("unchanged")
    archive = contract.incoming_dir / f"42-{NEW_SHA}.tar"
    archive.symlink_to(victim)
    request = {"run_id": "42", "release_sha": NEW_SHA}

    with pytest.raises(OperationError, match="artifact_missing"):
        WorkerBackend().prepare(contract, request, contract.build_dir / NEW_SHA)

    assert victim.read_text() == "unchanged"
    assert archive.is_symlink()


def test_processing_archive_stays_root_owned_and_build_read_only(tmp_path: Path, monkeypatch) -> None:
    processing_archive_mode = 0o440
    contract = _contract(tmp_path)
    contract.incoming_dir.mkdir()
    contract.processing_dir.mkdir(parents=True)
    archive = contract.incoming_dir / f"42-{NEW_SHA}.tar"
    archive.write_bytes(b"archive")
    incoming_inode = archive.stat().st_ino
    observed_chown: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "scripts.deployment.operation_worker.pwd.getpwnam",
        lambda _user: SimpleNamespace(pw_gid=os.getgid()),
    )
    monkeypatch.setattr(
        "scripts.deployment.operation_worker.os.fchown",
        lambda _fd, uid, gid: observed_chown.append((uid, gid)),
    )

    def fake_run(_command, **_kwargs):
        processing = contract.processing_dir / archive.name
        assert processing.stat().st_mode & 0o777 == processing_archive_mode
        assert processing.stat().st_ino != incoming_inode
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("scripts.deployment.operation_worker.subprocess.run", fake_run)
    request = {
        "artifact_digest": NEW_DIGEST,
        "release_sha": NEW_SHA,
        "run_id": "42",
    }

    WorkerBackend().prepare(contract, request, contract.build_dir / NEW_SHA)

    assert observed_chown == [(0, os.getgid())]
    assert not archive.exists()
    assert not (contract.processing_dir / archive.name).exists()


def test_none_release_checks_for_unapplied_candidate_migrations(tmp_path: Path, monkeypatch) -> None:
    contract = _contract(tmp_path)
    observed: list[list[str]] = []
    backend = WorkerBackend()
    monkeypatch.setattr(backend, "_run_candidate", lambda _contract, _release, args: observed.append(args))

    backend.candidate_migrations_applied(contract, contract.releases_dir / NEW_SHA)

    assert observed == [["migrate", "--check"]]


def test_candidate_check_rejects_missing_migration_files(tmp_path: Path, monkeypatch) -> None:
    contract = _contract(tmp_path)
    observed: list[list[str]] = []
    backend = WorkerBackend()
    monkeypatch.setattr(backend, "_run_candidate", lambda _contract, _release, args: observed.append(args))

    backend.candidate_check(contract, contract.releases_dir / NEW_SHA)

    assert observed == [["check", "--deploy"], ["makemigrations", "--check", "--dry-run"]]


def test_promotion_moves_frozen_build_tree_into_root_release_area(tmp_path: Path, monkeypatch) -> None:
    contract = _contract(tmp_path)
    staging = contract.build_dir / NEW_SHA
    staging.mkdir()
    payload = staging / "manage.py"
    payload.write_text("pass\n")
    payload.chmod(0o444)
    nested = staging / "package"
    nested.mkdir()
    (nested / "module.py").write_text("VALUE = 1\n")
    (nested / "module.py").chmod(0o444)
    nested.chmod(0o555)
    staging.chmod(0o555)
    observed: list[Path] = []
    monkeypatch.setattr(
        "scripts.deployment.operation_worker.pwd.getpwnam",
        lambda _user: SimpleNamespace(pw_uid=os.getuid()),
    )
    def fake_chown(path, *_args, **_kwargs):
        observed.append(Path(path))
        if Path(path) == staging:
            staging.chmod(0o755)

    monkeypatch.setattr("scripts.deployment.operation_worker.os.chown", fake_chown)
    release = contract.releases_dir / NEW_SHA

    WorkerBackend().publish_permissions(contract, staging, release)

    assert release.is_dir()
    assert not staging.exists()
    assert payload in observed
    assert (release / "manage.py").is_file()
    assert (release / "package/module.py").is_file()


def test_retention_preserves_current_previous_and_nonterminal_releases(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    shas = [f"{index:x}" * 40 for index in range(1, 8)]
    for index, release_sha in enumerate(shas):
        release = contract.releases_dir / release_sha
        release.mkdir()
        os.utime(release, ns=(index + 1, index + 1))
    atomic_symlink(
        contract.release_root / "current",
        contract.releases_dir / shas[0],
        allowed_root=contract.releases_dir,
    )
    atomic_symlink(
        contract.release_root / "previous",
        contract.releases_dir / shas[1],
        allowed_root=contract.releases_dir,
    )
    atomic_write_json(
        contract.registry_dir / "operations/99.json",
        {"release_sha": shas[2], "state": "activating"},
    )

    removed = prune_releases(contract, max_retained=5, expected_uid=os.getuid())

    assert set(removed) == {shas[3], shas[4]}
    assert all((contract.releases_dir / release_sha).is_dir() for release_sha in shas[:3])
    assert all((contract.releases_dir / release_sha).is_dir() for release_sha in shas[5:])

def test_deploy_activates_and_records_release(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    _seed(contract)

    result = run_operation(contract, "42", backend=FakeBackend())

    assert result["state"] == "active"
    assert (contract.release_root / "current").resolve().name == NEW_SHA
    record = read_json(contract.registry_dir / "releases" / f"{NEW_SHA}.json")
    assert record["artifact_digest"] == NEW_DIGEST
    assert record["rollback_eligible"] is True


def test_post_activation_failure_restores_eligible_previous(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    _seed(contract)

    result = run_operation(contract, "42", backend=FakeBackend(fail_target=True))

    assert result["state"] == "rolled_back"
    assert result["error_code"] == "activation_failed"
    assert (contract.release_root / "current").resolve().name == OLD_SHA


def test_pre_activation_failure_discards_unreferenced_candidate_for_safe_retry(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    _seed(contract)

    result = run_operation(contract, "42", backend=FakeBackend(fail_candidate=True))

    assert result["state"] == "failed"
    assert result["error_code"] == "candidate_check_failed"
    assert not (contract.releases_dir / NEW_SHA).exists()
    assert (contract.release_root / "current").resolve().name == OLD_SHA


def test_compatible_migration_fails_closed_without_bound_disclosure(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    _seed(contract, migration_class="backward-compatible-schema")

    result = run_operation(contract, "42", backend=FakeBackend())

    assert result["state"] == "failed"
    assert result["error_code"] == "migration_disclosure_contract_missing"
    assert (contract.release_root / "current").resolve().name == OLD_SHA


def test_repeated_terminal_request_is_idempotent(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    _seed(contract)
    backend = FakeBackend()
    first = run_operation(contract, "42", backend=backend)

    second = run_operation(contract, "42", backend=FakeBackend(fail_target=True))

    assert second == first


def test_interrupted_nonterminal_operation_fails_closed(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    _seed(contract)
    state_path = contract.registry_dir / "operations/42.json"
    state = read_json(state_path)
    atomic_write_json(state_path, state | {"state": "activating"})

    result = run_operation(contract, "42", backend=FakeBackend())

    assert result["state"] == "recovery_required"
    assert result["error_code"] == "interrupted_operation"


@pytest.mark.parametrize("prior_state", ["recovery_required", "unknown_future_state"])
def test_new_operation_is_blocked_by_unresolved_prior_operation(tmp_path: Path, prior_state: str) -> None:
    contract = _contract(tmp_path)
    _seed(contract)
    atomic_write_json(
        contract.registry_dir / "operations/41.json",
        {"release_sha": OLD_SHA, "run_id": "41", "state": prior_state},
    )

    result = run_operation(contract, "42", backend=FakeBackend())

    assert result["state"] == "failed"
    assert result["error_code"] == "unresolved_operation_exists"
    assert (contract.release_root / "current").resolve().name == OLD_SHA


def test_explicit_rollback_requires_exact_previous_record(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    _seed(contract, operation="rollback", target_sha=OLD_SHA, digest=OLD_DIGEST)
    newer = contract.releases_dir / NEW_SHA
    newer.mkdir()
    atomic_write_json(
        contract.registry_dir / "releases" / f"{NEW_SHA}.json",
        {
            "artifact_digest": NEW_DIGEST,
            "migration_class": "none",
            "state_fingerprint": FINGERPRINT,
            "release_sha": NEW_SHA,
            "rollback_eligible": True,
            "state": "active",
        },
    )
    activate_release(contract, NEW_SHA)
    old_record_path = contract.registry_dir / "releases" / f"{OLD_SHA}.json"
    atomic_write_json(old_record_path, read_json(old_record_path) | {"state": "previous"})

    result = run_operation(contract, "42", backend=FakeBackend())

    assert result["state"] == "rolled_back"
    assert (contract.release_root / "current").resolve().name == OLD_SHA


def test_explicit_rollback_rejects_live_database_state_drift(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    _seed(contract, operation="rollback", target_sha=OLD_SHA, digest=OLD_DIGEST)
    newer = contract.releases_dir / NEW_SHA
    newer.mkdir()
    atomic_write_json(
        contract.registry_dir / "releases" / f"{NEW_SHA}.json",
        {
            "artifact_digest": NEW_DIGEST,
            "migration_class": "none",
            "state_fingerprint": FINGERPRINT,
            "release_sha": NEW_SHA,
            "rollback_eligible": True,
            "state": "active",
        },
    )
    old_record_path = contract.registry_dir / "releases" / f"{OLD_SHA}.json"
    atomic_write_json(old_record_path, read_json(old_record_path) | {"state": "previous"})
    activate_release(contract, NEW_SHA)

    class DriftedBackend(FakeBackend):
        def state_fingerprint(self, contract: TargetContract) -> str:
            return "f" * 64

    result = run_operation(contract, "42", backend=DriftedBackend())

    assert result["state"] == "failed"
    assert result["error_code"] == "rollback_database_state_drift"
    assert (contract.release_root / "current").resolve().name == NEW_SHA


def test_first_adoption_activates_without_inventing_rollback_baseline(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    request = {
        "artifact_digest": NEW_DIGEST,
        "deployment_id": "7",
        "migration_class": "none",
        "operation": "deploy",
        "release_sha": NEW_SHA,
        "run_id": "42",
        "target_marker": contract.marker,
        "workflow_sha": NEW_SHA,
        "workflow_ref": contract.deploy_workflow_ref,
    }
    atomic_write_json(contract.registry_dir / "requests/42.json", request)
    atomic_write_json(
        contract.registry_dir / "operations/42.json",
        request | {"error_code": None, "state": "verified"},
    )
    atomic_write_json(
        contract.registry_dir / "adoption.json",
        {
            "authorized_at": "2026-09-01T00:00:00Z",
            "legacy_sha": OLD_SHA,
            "legacy_source_root": "/srv/legacy-asterproof",
            "state_fingerprint": FINGERPRINT,
            "repository": contract.repository,
            "state": "authorized",
            "target_marker": contract.marker,
        },
    )

    result = run_operation(contract, "42", backend=FakeBackend())

    assert result["state"] == "active"
    adoption = read_json(contract.registry_dir / "adoption.json")
    assert adoption["state"] == "consumed"
    assert adoption["consumed_by_release_sha"] == NEW_SHA
    assert not (contract.release_root / "previous").exists()


def test_first_adoption_health_failure_requires_recovery(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    request = {
        "artifact_digest": NEW_DIGEST,
        "deployment_id": "7",
        "migration_class": "none",
        "operation": "deploy",
        "release_sha": NEW_SHA,
        "run_id": "42",
        "target_marker": contract.marker,
        "workflow_sha": NEW_SHA,
        "workflow_ref": contract.deploy_workflow_ref,
    }
    atomic_write_json(contract.registry_dir / "requests/42.json", request)
    atomic_write_json(
        contract.registry_dir / "operations/42.json",
        request | {"error_code": None, "state": "verified"},
    )
    atomic_write_json(
        contract.registry_dir / "adoption.json",
        {
            "authorized_at": "2026-09-01T00:00:00Z",
            "legacy_sha": OLD_SHA,
            "legacy_source_root": "/srv/legacy-asterproof",
            "state_fingerprint": FINGERPRINT,
            "repository": contract.repository,
            "state": "authorized",
            "target_marker": contract.marker,
        },
    )

    result = run_operation(contract, "42", backend=FakeBackend(fail_target=True))

    assert result["state"] == "recovery_required"
    assert result["error_code"] == "activation_failed_ineligible_rollback"
