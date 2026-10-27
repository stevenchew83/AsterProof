# ruff: noqa: ARG002, EM101, PLR2004, S108, SLF001, TRY003
"""Exact catalogue maintenance, durable drain/backup boundaries and no data rollback."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import catalogue_schema as catalogue
from scripts.deployment.operation_worker import OperationError
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.protocol import OperationEnvelope
from scripts.deployment.protocol import ProtocolError
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.tests.test_operation_worker import FINGERPRINT
from scripts.deployment.tests.test_operation_worker import NEW_DIGEST
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_DIGEST
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import FakeBackend
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed
from scripts.deployment.tests.test_schema_fingerprint import _snapshot
from scripts.deployment.validate_dispatch import DispatchValidationError
from scripts.deployment.validate_dispatch import validate_schema_input

START = {
    "state_fingerprint": FINGERPRINT,
    "schema_fingerprint": "1" * 64,
    "migration_fingerprint": "2" * 64,
    "behaviour_fingerprint": catalogue.EMPTY_BEHAVIOUR_SHA256,
}
END = {
    "state_fingerprint": "f" * 64,
    "schema_fingerprint": "3" * 64,
    "migration_fingerprint": "4" * 64,
    "behaviour_fingerprint": catalogue.BEHAVIOUR_SHA256,
}


def disclosure():
    return {
        "format_version": 1,
        "kind": catalogue.KIND,
        "active_sha": OLD_SHA,
        "target_sha": NEW_SHA,
        "input_hashes": catalogue.INPUT_HASHES.copy(),
        "starting": START.copy(),
        "expected": END.copy(),
        "postgresql_rehearsal_sha256": catalogue.rehearsal_digest(release_sha=NEW_SHA, active_sha=OLD_SHA),
        "recovery_policy": catalogue.RECOVERY_POLICY.copy(),
    }


def request_with_catalogue(contract):
    _seed(contract, migration_class="data-or-non-compatible")
    path = contract.registry_dir / "requests/42.json"
    request = read_json(path)
    request["schema_disclosure"] = disclosure()
    atomic_write_json(path, request)
    return request


class CatalogueBackend(FakeBackend):
    def __init__(self, failure=""):
        super().__init__()
        self.failure, self.stage, self.events = failure, "starting", []

    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        proof = catalogue.rehearsal_evidence(release_sha=NEW_SHA, active_sha=OLD_SHA)
        (destination / catalogue.EVIDENCE_PATH).write_text(json.dumps(proof, indent=2) + "\n")

    def catalogue_audit(self, contract):
        audit = copy.deepcopy(START if self.stage == "starting" else END)
        audit["server_version_num"] = 170009
        if self.failure == self.stage:
            audit["behaviour_fingerprint"] = "0" * 64
        return audit

    def check_catalogue_schema(self, contract, release):
        if self.failure == "candidate":
            raise ValueError("Altered migration")

    def preflight_recovery(self, contract):
        self.events.append("preflight")
        if self.failure == "preflight":
            raise OperationError("recovery_preflight_failed")

    def drain(self, contract, state_path):
        self.events.append("drain")
        assert read_json(state_path)["state"] == "draining"
        if self.failure == "drain":
            raise OperationError("maintenance_drain_incomplete")
        value = read_json(state_path)
        value["maintenance_scheduler_was_active"] = True
        atomic_write_json(state_path, value)

    def create_recovery(self, contract, run_id, active_sha, fingerprint):
        self.events.append("backup")
        assert run_id == "42"
        assert active_sha == OLD_SHA
        assert fingerprint == FINGERPRINT
        assert read_json(contract.registry_dir / "operations/42.json")["state"] == "backing_up"
        if self.failure == "backup":
            raise OperationError("recovery_backup_or_restore_failed")
        return {}

    def verify_recovery(self, contract, run_id, active_sha, fingerprint):
        self.events.append("verify_recovery")
        if self.failure == "receipt":
            raise OperationError("recovery_receipt_invalid")
        return {"backup_id": "42", "archive_sha256": "5" * 64}

    def assert_database_drained(self):
        return None

    def migrate_catalogue_schema(self, contract, release):
        self.events.append("migrate")
        self.stage = "expected"
        if self.failure == "migration":
            raise OperationError("migration_failed")

    def refresh_catalogue(self, contract, release):
        self.events.append("refresh")
        if self.failure == "refresh":
            raise OperationError("refresh_failed")

    def verify_catalogue_records(self, contract, run_id, active_sha):
        self.events.append("preserve")
        if self.failure == "preserve":
            raise OperationError("catalogue_original_records_changed")

    def state_fingerprint(self, contract):
        return (START if self.stage == "starting" else END)["state_fingerprint"]

    def activate(self, contract, release_sha):
        self.events.append("activate")
        return super().activate(contract, release_sha)

    def restart_and_verify(self, contract, release_sha, artifact_digest):
        self.events.append("health")
        if self.failure == "activation":
            raise OperationError("health_failed")
        return {"state_fingerprint": END["state_fingerprint"]}

    def restore(self, contract):
        raise AssertionError("A data-class deployment must never automatically restore code")

    def resume_scheduler(self, contract, state_path):
        self.events.append("resume")
        if self.failure == "resume":
            raise OperationError("scheduler_resume_failed")


def test_catalogue_deploy_has_verified_recovery_before_migration_and_no_rollback_eligibility(tmp_path):
    contract = _contract(tmp_path)
    request_with_catalogue(contract)
    backend = CatalogueBackend()
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "active"
    assert backend.events == [
        "preflight",
        "drain",
        "backup",
        "verify_recovery",
        "migrate",
        "refresh",
        "preserve",
        "activate",
        "health",
        "resume",
    ]
    assert result["recovery_archive_sha256"] == "5" * 64
    assert read_json(contract.registry_dir / f"releases/{NEW_SHA}.json")["rollback_eligible"] is False
    assert (contract.release_root / "current").resolve().name == NEW_SHA
    assert run_operation(contract, "42", backend=backend) == result


@pytest.mark.parametrize(
    ("failure", "state", "drained"),
    [
        ("starting", "failed", False),
        ("candidate", "failed", False),
        ("preflight", "failed", False),
        ("drain", "recovery_required", True),
        ("backup", "recovery_required", True),
        ("receipt", "recovery_required", True),
        ("migration", "recovery_required", True),
        ("expected", "recovery_required", True),
        ("refresh", "recovery_required", True),
        ("activation", "recovery_required", True),
        ("resume", "recovery_required", True),
    ],
)
def test_catalogue_failure_boundaries_never_retry_backup_or_rollback(tmp_path, failure, state, drained):
    contract = _contract(tmp_path)
    request_with_catalogue(contract)
    backend = CatalogueBackend(failure)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == state
    assert (contract.releases_dir / NEW_SHA).exists() == drained
    assert ("migrate" in backend.events) is (failure in {"migration", "expected", "refresh", "activation", "resume"})
    events = backend.events.copy()
    assert run_operation(contract, "42", backend=backend) == result
    assert backend.events == events


def test_manual_rollback_from_data_class_is_blocked(tmp_path):
    contract = _contract(tmp_path)
    request = request_with_catalogue(contract)
    assert run_operation(contract, "42", backend=CatalogueBackend())["state"] == "active"
    rollback = {
        **request,
        "run_id": "43",
        "deployment_id": "43",
        "operation": "rollback",
        "release_sha": OLD_SHA,
        "artifact_digest": OLD_DIGEST,
        "migration_class": "none",
    }
    rollback.pop("schema_disclosure")
    atomic_write_json(contract.registry_dir / "requests/43.json", rollback)
    atomic_write_json(contract.registry_dir / "operations/43.json", {**rollback, "state": "verified"})
    result = run_operation(contract, "43", backend=CatalogueBackend())
    assert result["state"] == "failed"
    assert result["error_code"] == "rollback_requires_independent_recovery"
    assert (contract.release_root / "current").resolve().name == NEW_SHA


@pytest.mark.parametrize("state", ["draining", "backing_up", "migrating"])
def test_interrupted_maintenance_requires_reconciliation(tmp_path, state):
    contract = _contract(tmp_path)
    request_with_catalogue(contract)
    path = contract.registry_dir / "operations/42.json"
    value = read_json(path)
    value["state"] = state
    atomic_write_json(path, value)
    result = run_operation(contract, "42", backend=CatalogueBackend())
    assert result["state"] == "recovery_required"
    assert result["error_code"] == "interrupted_operation"


def test_data_class_protocol_requires_exact_catalogue_disclosure_and_policy():
    raw = {
        "operation": "deploy",
        "run_id": "42",
        "deployment_id": "42",
        "workflow_sha": NEW_SHA,
        "release_sha": NEW_SHA,
        "artifact_digest": NEW_DIGEST,
        "target_marker": "asterproof-production",
        "migration_class": "data-or-non-compatible",
        "oidc_token": "synthetic-token",
        "schema_disclosure": disclosure(),
    }
    OperationEnvelope.from_dict(raw)
    validate_schema_input(
        json.dumps(disclosure()), release_sha=NEW_SHA,
        migration_class="data-or-non-compatible", initial_adoption=False,
    )
    for change in [{"schema_disclosure": None}, {"operation": "rollback"}, {"migration_class": "none"}]:
        with pytest.raises(ProtocolError):
            OperationEnvelope.from_dict({**raw, **change})
    for key, value in [("recovery_policy", {}), ("input_hashes", {}), ("kind", "arbitrary-migration")]:
        changed = disclosure()
        changed[key] = value
        with pytest.raises(ValueError, match="Catalogue maintenance"):
            catalogue.validate_disclosure(changed, target_sha=NEW_SHA)
    with pytest.raises(DispatchValidationError):
        validate_schema_input(
            json.dumps(disclosure()),
            release_sha=NEW_SHA,
            migration_class="data-or-non-compatible",
            initial_adoption=True,
        )


def test_native_candidate_commands_have_fixed_scope_and_duration(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(
        "scripts.deployment.operation_worker.subprocess.run", lambda args, **kwargs: commands.append((args, kwargs)),
    )
    backend = WorkerBackend()
    contract = _contract(tmp_path)
    backend.migrate_catalogue_schema(contract, tmp_path / "candidate")
    assert commands[0][0][-3:] == ["shell", "--command", catalogue.MIGRATION_APPLY]
    assert "--setenv=PGOPTIONS=-c lock_timeout=2s -c statement_timeout=30s" in commands[0][0]
    backend.refresh_catalogue(contract, tmp_path / "candidate")
    assert "--property=RuntimeMaxSec=900s" in commands[1][0]
    assert commands[1][1]["timeout"] == 930


def test_writer_session_guard_is_identity_checked_metadata_only(monkeypatch):
    config = SimpleNamespace(expected_database_identity_hash="a" * 64)
    monkeypatch.setattr("scripts.deployment.migration_audit.AuditConfig.load", lambda _path: config)
    monkeypatch.setattr(
        "scripts.deployment.migration_audit.collect_identity", lambda _config: {"database_identity_hash": "a" * 64},
    )
    queries = []
    monkeypatch.setattr(
        "scripts.deployment.migration_audit._run_query", lambda _config, sql: queries.append(sql) or "0\n",
    )
    WorkerBackend().assert_database_drained()
    assert "pg_stat_activity" in queries[0]
    assert "usename<>current_user" in queries[0]
    monkeypatch.setattr("scripts.deployment.migration_audit._run_query", lambda *_args: "1\n")
    with pytest.raises(OperationError, match="writers_present"):
        WorkerBackend().assert_database_drained()


def starting_catalogue_audit():
    before = _snapshot()
    migrations = [["pages", "0036_concept_assignment_reviews"]]
    state = {
        "database_identity_hash": "0" * 64, "role": "asterproof_catalog",
        "schema": schema_state(before), "migration": migration_state(migrations),
    }
    return {
        "state": state, "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "server_version_num": 170009, "catalog_snapshot": before, "migration_rows": migrations,
    }


def test_expected_audit_uses_the_verified_public_schema_delta_and_exact_migrations():
    # Public DDL metadata from pinned PostgreSQL proof 40487423449, never production rows.
    delta = json.loads((Path(__file__).parent / "fixtures/catalogue-schema-delta.json").read_text())
    start = starting_catalogue_audit()
    expected = catalogue.expected_catalog_audit(start, delta)
    combined = {key: start["catalog_snapshot"][key] + delta[key] for key in delta}
    assert expected["schema_fingerprint"] == schema_state(combined)["fingerprint"]
    rows = start["migration_rows"] + [["pages", name] for name in catalogue.MIGRATIONS]
    assert expected["migration_fingerprint"] == migration_state(rows)["fingerprint"]
    assert expected["behaviour_fingerprint"] == catalogue.BEHAVIOUR_SHA256
    delta["tables"].pop()
    with pytest.raises(ValueError, match="frozen rehearsal"):
        catalogue.expected_catalog_audit(start, delta)
    start["state_fingerprint"] = "1" * 64
    with pytest.raises(ValueError, match="identity/version"):
        catalogue.expected_catalog_audit(start, delta)


@pytest.mark.parametrize(
    ("scenario", "error"),
    [
        ("inactive", None), ("scheduler_sigterm", None),
        ("scheduler_exit_error", "maintenance_drain_incomplete"),
        ("scheduler_sigkill", "maintenance_drain_incomplete"),
        ("scheduler_pid_present", "maintenance_drain_incomplete"),
        ("scheduler_cgroup_present", "maintenance_cgroup_not_empty"),
        ("app_sigterm", "maintenance_drain_incomplete"),
        ("timer_active", "maintenance_drain_incomplete"),
        ("writers_present", "maintenance_database_writers_present"),
    ],
)
def test_real_drain_accepts_only_a_fully_stopped_scheduler_after_sigterm(tmp_path, monkeypatch, scenario, error):
    contract = _contract(tmp_path)
    timer = contract.scheduler_service.removesuffix(".service") + ".timer"
    properties = {
        timer: {"ActiveState": "inactive"},
        contract.service: {"ActiveState": "inactive", "MainPID": "0", "ControlGroup": ""},
        contract.scheduler_service: {
            "ActiveState": "inactive", "MainPID": "0", "ControlGroup": "/scheduler",
            "Result": "success", "ExecMainCode": "1", "ExecMainStatus": "0",
        },
    }
    scheduler = properties[contract.scheduler_service]
    if scenario not in {"inactive", "app_sigterm", "timer_active"}:
        scheduler.update(ActiveState="failed", Result="signal", ExecMainCode="2", ExecMainStatus="15")
    if scenario == "scheduler_exit_error":
        scheduler.update(Result="exit-code", ExecMainCode="1", ExecMainStatus="1")
    if scenario == "scheduler_sigkill":
        scheduler["ExecMainStatus"] = "9"
    if scenario == "scheduler_pid_present":
        scheduler["MainPID"] = "123"
    if scenario == "app_sigterm":
        properties[contract.service].update(
            ActiveState="failed", Result="signal", ExecMainCode="2", ExecMainStatus="15",
        )
    if scenario == "timer_active":
        properties[timer]["ActiveState"] = "active"
    group = tmp_path / "cgroups/scheduler"
    group.mkdir(parents=True)
    (group / "cgroup.procs").write_text("123\n" if scenario == "scheduler_cgroup_present" else "")
    original_path = Path
    monkeypatch.setattr(
        "scripts.deployment.operation_worker.Path",
        lambda value: tmp_path / "cgroups" if str(value) == "/sys/fs/cgroup" else original_path(value),
    )
    state_path = tmp_path / "operation.json"
    atomic_write_json(state_path, {"state": "draining"})
    backend = WorkerBackend()
    monkeypatch.setattr(backend, "_scheduler_plan", lambda _contract: (timer, True))
    monkeypatch.setattr(backend, "_unit_properties", lambda unit, _names: properties[unit])
    commands = []
    monkeypatch.setattr(
        "scripts.deployment.operation_worker.subprocess.run", lambda args, **kwargs: commands.append((args, kwargs)),
    )
    writer_checks = []

    def assert_no_writers():
        writer_checks.append(True)
        if scenario == "writers_present":
            raise OperationError("maintenance_database_writers_present")

    monkeypatch.setattr(backend, "assert_database_drained", assert_no_writers)
    if error:
        with pytest.raises(OperationError, match=error):
            backend.drain(contract, state_path)
        assert bool(writer_checks) == (scenario == "writers_present")
    else:
        backend.drain(contract, state_path)
        assert writer_checks == [True]
        assert read_json(state_path)["maintenance_scheduler_stop_result"] == scheduler
    assert commands[0][0] == ["/usr/bin/systemctl", "stop", timer, contract.scheduler_service, contract.service]
    assert commands[0][1]["timeout"] == 90
