"""Empty ranking metadata prohibits incompatible readers in every activation path."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import ranking_profile_compat as compat
from scripts.deployment.migration_audit import AuditConfig
from scripts.deployment.migration_audit import collect_ranking_profile_reader_floor
from scripts.deployment.operation_worker import OperationError
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.release_manifest import ReleaseManifest
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.server_activate import activate_release
from scripts.deployment.tests.test_operation_worker import FINGERPRINT
from scripts.deployment.tests.test_operation_worker import NEW_DIGEST
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_DIGEST
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import FakeBackend
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed


def test_reviewed_reader_capability_matches_actual_source_bytes():
    root = Path(__file__).resolve().parents[3]
    assert compat.READER_SOURCES
    for relative, expected in compat.READER_SOURCES.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected, relative


def write_reader(release, monkeypatch):
    relative = "inspinia/rankings/profile_models.py"
    body = b"# Synthetic reviewed profile reader, no executable release code.\n"
    digest = hashlib.sha256(body).hexdigest()
    monkeypatch.setattr(compat, "READER_SOURCES", {relative: digest})
    target = release / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    manifest = ReleaseManifest(
        repository="owner/AsterProof",
        repository_id="123",
        release_sha=release.name,
        run_id="42",
        built_at="2026-11-01T00:00:00Z",
        target_platform="manylinux2014_x86_64",
        python_abi="cp312",
        files=({"path": relative, "sha256": digest, "size": len(body)},),
    )
    (release / "release-metadata.json").write_bytes(manifest.to_json_bytes())
    return target


def test_manifest_and_actual_guarded_bytes_must_both_match(tmp_path, monkeypatch):
    release = tmp_path / NEW_SHA
    target = write_reader(release, monkeypatch)
    assert compat.verified_reader_release(release)
    target.write_text("# Stale legacy reader substituted.\n")
    assert not compat.verified_reader_release(release)
    value = json.loads((release / "release-metadata.json").read_bytes())
    value["files"][0]["sha256"] = "0" * 64
    (release / "release-metadata.json").write_bytes(json.dumps(value).encode())
    assert not compat.verified_reader_release(release)


def test_symlink_reader_is_rejected(tmp_path, monkeypatch):
    release = tmp_path / NEW_SHA
    target = write_reader(release, monkeypatch)
    content = target.read_bytes()
    target.unlink()
    elsewhere = tmp_path / "substitute.py"
    elsewhere.write_bytes(content)
    target.symlink_to(elsewhere)
    assert not compat.verified_reader_release(release)


@pytest.mark.parametrize("present", [False, True])
def test_floor_is_identity_bound_metadata_only_even_without_content(present):
    identity = ["synthetic", "asterproof_catalog", "local", "", ""]
    commands = []
    outputs = iter([",".join(identity) + "\n", "t\n" if present else "f\n"])

    def runner(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(stdout=next(outputs))

    config = AuditConfig(
        os_user="asterproof_audit",
        pg_service="asterproof_audit",
        pg_service_file=Path("/etc/pg_service.conf"),
        expected_role="asterproof_catalog",
        expected_database_identity_hash=hashlib.sha256(canonical_json(identity)).hexdigest(),
    )
    result = collect_ranking_profile_reader_floor(config, runner=runner)
    assert result["reader_required"] is present
    assert result["minimum_reader_version"] == (1 if present else 0)
    assert all("BEGIN READ ONLY" in command[-1] and "statement_timeout='10s'" in command[-1] for command in commands)
    assert "to_regclass" in commands[-1][-1]
    assert "public.django_migrations" in commands[-1][-1]
    assert "rankings_studentresult" not in commands[-1][-1]
    assert "rankings_resultprofile" in commands[-1][-1]
    assert "rankings_resultclaim" in commands[-1][-1]


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"format_version": 1, "reader_required": 1, "minimum_reader_version": 1},
        {"format_version": 1, "reader_required": True, "minimum_reader_version": 0},
        {"format_version": 1, "reader_required": True, "minimum_reader_version": True},
    ],
)
def test_unavailable_or_malformed_floor_fails_closed(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(
        "scripts.deployment.operation_worker.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(payload)),
    )
    with pytest.raises(OperationError, match="ranking_profile_reader_floor_unavailable"):
        WorkerBackend().ranking_profile_reader_required(_contract(tmp_path))


class RequiredReaderBackend(FakeBackend):
    def ranking_profile_reader_required(self, contract):
        return True


class VerifiedReaderBackend(RequiredReaderBackend):
    def __init__(self, monkeypatch, **kwargs):
        super().__init__(**kwargs)
        self.monkeypatch = monkeypatch

    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        write_reader(destination, self.monkeypatch)


def test_readerless_deploy_stops_before_activation(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract)
    result = run_operation(contract, "42", backend=RequiredReaderBackend())
    assert result["state"] == "failed"
    assert result["error_code"] == "ranking_profile_reader_required"
    assert (contract.release_root / "current").resolve().name == OLD_SHA


def test_verified_reader_can_deploy_above_floor(tmp_path, monkeypatch):
    contract = _contract(tmp_path)
    _seed(contract)
    result = run_operation(contract, "42", backend=VerifiedReaderBackend(monkeypatch))
    assert result["state"] == "active"
    assert (contract.release_root / "current").resolve().name == NEW_SHA


def test_new_floor_is_rechecked_immediately_before_activation(tmp_path):
    class FloorAppearsBackend(FakeBackend):
        installed = False

        def ranking_profile_reader_required(self, contract):
            return self.installed

        def candidate_check(self, contract, release):
            super().candidate_check(contract, release)
            self.installed = True

    contract = _contract(tmp_path)
    _seed(contract)
    result = run_operation(contract, "42", backend=FloorAppearsBackend())
    assert result["error_code"] == "ranking_profile_reader_required"
    assert (contract.release_root / "current").resolve().name == OLD_SHA


def test_explicit_rollback_cannot_choose_an_old_fallback_reader(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract, operation="rollback", target_sha=OLD_SHA, digest=OLD_DIGEST)
    (contract.releases_dir / NEW_SHA).mkdir()
    atomic_write_json(
        contract.registry_dir / f"releases/{NEW_SHA}.json",
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
    old_record = contract.registry_dir / f"releases/{OLD_SHA}.json"
    atomic_write_json(old_record, {**read_json(old_record), "state": "previous"})
    result = run_operation(contract, "42", backend=RequiredReaderBackend())
    assert result["error_code"] == "ranking_profile_reader_required"
    assert (contract.release_root / "current").resolve().name == NEW_SHA


def test_automatic_recovery_cannot_restore_an_old_fallback_reader(tmp_path, monkeypatch):
    contract = _contract(tmp_path)
    _seed(contract)
    result = run_operation(contract, "42", backend=VerifiedReaderBackend(monkeypatch, fail_target=True))
    assert result["state"] == "recovery_required"
    assert result["error_code"] == "ranking_profile_reader_required"
    assert (contract.release_root / "current").resolve().name == NEW_SHA
