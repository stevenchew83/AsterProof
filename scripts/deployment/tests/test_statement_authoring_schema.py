"""Only the frozen statement-authoring plan may use the existing recovery path."""

import copy
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import catalogue_schema
from scripts.deployment import statement_authoring_schema as schema
from scripts.deployment import validate_dispatch
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.tests.test_catalogue_maintenance import END
from scripts.deployment.tests.test_catalogue_maintenance import START
from scripts.deployment.tests.test_catalogue_maintenance import CatalogueBackend
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed
from scripts.deployment.validate_dispatch import build_migration_disclosure
from scripts.deployment.validate_dispatch import validate_schema_input

ROOT = Path(__file__).resolve().parents[3]


def disclosure():
    return {
        "format_version": 1, "kind": schema.KIND, "active_sha": OLD_SHA, "target_sha": NEW_SHA,
        "input_hashes": schema.INPUT_HASHES.copy(),
        "starting": {**START, "behaviour_fingerprint": catalogue_schema.BEHAVIOUR_SHA256},
        "expected": {**END, "behaviour_fingerprint": catalogue_schema.BEHAVIOUR_SHA256},
        "recovery_policy": schema.RECOVERY_POLICY.copy(),
        "postgresql_rehearsal_sha256": hashlib.sha256(
            schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA),
        ).hexdigest(),
    }


def test_statement_authoring_disclosure_is_explicit_and_reuses_protected_validation():
    value = disclosure()
    assert catalogue_schema.validate_disclosure(value, target_sha=NEW_SHA) == value
    validate_schema_input(json.dumps(value), release_sha=NEW_SHA,
                          migration_class="data-or-non-compatible", initial_adoption=False)


@pytest.mark.parametrize("field", ["kind", "target_sha", "active_sha", "input_hashes", "recovery_policy"])
def test_statement_authoring_disclosure_rejects_unknown_plan_or_weakened_recovery(field):
    value = disclosure()
    value[field] = "changed"
    with pytest.raises(ValueError, match="Statement-authoring|statement-authoring"):
        schema.validate_disclosure(value, target_sha=NEW_SHA)


def test_statement_authoring_preserves_behaviour_and_rejects_fabricated_proof():
    value = disclosure()
    value["expected"]["behaviour_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="trigger"):
        schema.validate_disclosure(value, target_sha=NEW_SHA)
    proof = schema.rehearsal_evidence(release_sha=NEW_SHA, active_sha=OLD_SHA)
    proof["existing_records_unchanged"] = 1
    with pytest.raises(ValueError, match="evidence"):
        schema.validate_rehearsal_evidence(proof, release_sha=NEW_SHA, active_sha=OLD_SHA)


def test_statement_authoring_migration_bytes_and_packaged_proof_are_frozen(tmp_path):
    directory = tmp_path / schema.MIGRATION_PATH.parent
    directory.mkdir(parents=True)
    for name in schema.INPUT_HASHES:
        shutil.copyfile(ROOT / schema.MIGRATION_PATH.parent / name, directory / name)
    schema.validate_candidate(tmp_path)
    value = disclosure()
    (tmp_path / schema.EVIDENCE_PATH).write_bytes(schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA))
    catalogue_schema.validate_build_evidence(tmp_path, value)
    (directory / schema.MIGRATION_PATH.name).write_text("Changed migration")
    with pytest.raises(ValueError, match="frozen hash"):
        schema.validate_candidate(tmp_path)
    (tmp_path / schema.EVIDENCE_PATH).write_text("{}")
    with pytest.raises(ValueError, match="digest"):
        schema.validate_build_evidence(tmp_path, value)


def starting_catalog():
    snapshot = {"tables": [{"schema": "public", "table": schema.TABLE, "kind": "r"}],
                "columns": [], "constraints": [], "indexes": [], "extensions": []}
    for position, (name, change) in enumerate(schema.COLUMN_CHANGES.items(), 1):
        snapshot["columns"].append({
            "schema": "public", "table": schema.TABLE, "column": name, "position": position,
            "type": change["before"][0], "nullable": change["before"][1], "default": None, "collation": None,
        })
    migrations = [["pages", "0039_catalogue_revision_triggers"]]
    state = {"database_identity_hash": "a" * 64, "role": "asterproof_catalog",
             "schema": schema_state(snapshot), "migration": migration_state(migrations)}
    return {"server_version_num": schema.POSTGRES_VERSION, "state": state,
            "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
            "catalog_snapshot": snapshot, "migration_rows": migrations,
            "behaviour_fingerprint": catalogue_schema.BEHAVIOUR_SHA256}


def test_expected_catalog_changes_only_three_existing_columns_and_one_migration():
    start = starting_catalog()
    original = copy.deepcopy(start)
    end = schema.expected_catalog_audit(start)
    assert start == original
    assert end["behaviour_fingerprint"] == start["behaviour_fingerprint"]
    assert end["state_fingerprint"] != start["state_fingerprint"]
    assert end["migration_fingerprint"] == migration_state([
        *start["migration_rows"], ["pages", schema.MIGRATION_NAME],
    ])["fingerprint"]
    malformed = copy.deepcopy(start["catalog_snapshot"])
    malformed["columns"][0]["type"] = "bigint"
    with pytest.raises(ValueError, match="starting shape"):
        schema.changed_schema(malformed)


class AuthoringBackend(CatalogueBackend):
    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        proof = schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA)
        (destination / schema.EVIDENCE_PATH).write_bytes(proof)

    def catalogue_audit(self, contract):
        audit = super().catalogue_audit(contract)
        if self.failure != self.stage:
            audit["behaviour_fingerprint"] = catalogue_schema.BEHAVIOUR_SHA256
        return audit

    def check_statement_authoring_schema(self, contract, release):
        if self.failure == "candidate":
            message = "Changed authoring migration"
            raise ValueError(message)

    def migrate_statement_authoring_schema(self, contract, release):
        return CatalogueBackend.migrate_catalogue_schema(self, contract, release)

    def check_catalogue_schema(self, contract, release):
        pytest.fail("Statement authoring must not run the catalogue seed plan")

    def migrate_catalogue_schema(self, contract, release):
        pytest.fail("Statement authoring must not run the catalogue seed plan")


def authoring_request(contract):
    _seed(contract, migration_class="data-or-non-compatible")
    path = contract.registry_dir / "requests/42.json"
    request = read_json(path)
    request["schema_disclosure"] = disclosure()
    atomic_write_json(path, request)


def test_authoring_worker_requires_backup_restore_preservation_before_activation(tmp_path):
    contract = _contract(tmp_path)
    authoring_request(contract)
    backend = AuthoringBackend()
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "active"
    assert backend.events == ["preflight", "drain", "backup", "verify_recovery", "migrate",
                              "refresh", "preserve", "activate", "health", "resume"]
    assert read_json(contract.registry_dir / f"releases/{NEW_SHA}.json")["rollback_eligible"] is False
    assert run_operation(contract, "42", backend=backend) == result


@pytest.mark.parametrize("failure", ["drain", "backup", "receipt", "migration", "expected", "preserve", "activation"])
def test_authoring_worker_never_blindly_rolls_back_or_retries_after_drain(tmp_path, failure):
    contract = _contract(tmp_path)
    authoring_request(contract)
    result = run_operation(contract, "42", backend=AuthoringBackend(failure))
    assert result["state"] == "recovery_required"
    assert run_operation(contract, "42", backend=AuthoringBackend()) == result


@pytest.mark.parametrize("failure", ["starting", "candidate", "preflight"])
def test_authoring_worker_rejects_invalid_preflight_without_draining_production(tmp_path, failure):
    contract = _contract(tmp_path)
    authoring_request(contract)
    backend = AuthoringBackend(failure)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "failed"
    assert "drain" not in backend.events


def test_authoring_backend_uses_only_its_frozen_plan_and_migration_command(monkeypatch):
    calls = []
    monkeypatch.setattr(WorkerBackend, "_run_candidate", lambda *args, **kwargs: calls.append((args, kwargs)))
    backend = WorkerBackend()
    backend.check_statement_authoring_schema(None, ROOT)
    backend.migrate_statement_authoring_schema(None, ROOT)
    assert calls[0][0][-1] == ["shell", "--command", schema.PLAN_CHECK]
    assert calls[1][0][-1] == ["shell", "--command", schema.MIGRATION_APPLY]
    assert calls[1][1] == {"migration": True}


def test_release_disclosure_admits_only_the_exact_new_migration(monkeypatch):
    monkeypatch.setattr(validate_dispatch.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout=f"A\t{schema.MIGRATION_PATH.as_posix()}\n",
    ))
    value = build_migration_disclosure(
        repository=ROOT, active_sha=OLD_SHA, target_sha=NEW_SHA,
        registry_path=ROOT / "deployment/migration-classifications.yml", declared_class="data-or-non-compatible",
    )
    assert value["migrations"] == [{"migration": schema.MIGRATION, "classification": "data-or-non-compatible"}]
