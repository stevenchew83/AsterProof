"""The 0017 allowance admits only its exact plan and preserves recovery gates."""
# ruff: noqa: ARG002, EM101, TRY003

import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import database_recovery
from scripts.deployment import maintenance_schema
from scripts.deployment import multiple_solutions_preservation as preservation
from scripts.deployment import multiple_solutions_schema as schema
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

ROOT = Path(__file__).resolve().parents[3]


def disclosure(active_sha):
    return {
        "format_version": 1, "kind": schema.KIND, "active_sha": active_sha, "target_sha": NEW_SHA,
        "input_hashes": schema.INPUT_HASHES.copy(),
        "starting": {**START, "behaviour_fingerprint": schema.BEHAVIOUR_SHA256},
        "expected": {**END, "behaviour_fingerprint": schema.BEHAVIOUR_SHA256},
        "recovery_policy": schema.RECOVERY_POLICY.copy(),
        "postgresql_rehearsal_sha256": hashlib.sha256(
            schema.evidence_bytes(release_sha=NEW_SHA, active_sha=active_sha),
        ).hexdigest(),
    }


@pytest.fixture
def frozen_candidate(tmp_path):
    library_ai = Path("inspinia/pages/migrations/0048_statement_ai_concept_suggestions.py")
    files = [
        path.relative_to(ROOT) for path in ROOT.glob("inspinia/**/migrations/*")
        if path.suffix in {".py", ".json"}
    ]
    for relative in {*files, schema.DELTA_PATH} - {library_ai}:
        staged = tmp_path / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes((ROOT / relative).read_bytes())
    return tmp_path


def test_frozen_source_and_delta(frozen_candidate):
    schema.validate_candidate(frozen_candidate)
    delta = schema.frozen_delta(ROOT)
    assert [item["column"] for item in delta["add"]["columns"]] == [schema.NEW_COLUMN]
    assert {item["name"] for item in delta["add"]["indexes"]} == schema.NEW_INDEXES
    assert [item["name"] for item in delta["remove"]["constraints"]] == [schema.OLD_UNIQUE]
    assert [item["name"] for item in delta["remove"]["indexes"]] == [schema.OLD_UNIQUE]


def test_catalog_projection_requires_exact_removed_objects_and_appended_slot():
    delta = schema.frozen_delta(ROOT)
    snapshot = copy.deepcopy(delta["remove"])
    snapshot["tables"] = [{"schema": "public", "table": schema.TABLE, "kind": "r"}]
    snapshot["columns"] = [
        {**delta["add"]["columns"][0], "column": column, "position": position}
        for position, column in enumerate(preservation.SOLUTION_COLUMNS, 1)
    ]
    migrations = [list(node) for node in schema.PREREQUISITES]

    def audit(snapshot):
        state = {
            "schema": schema_state(snapshot), "migration": migration_state(migrations), "role": "asterproof_catalog",
        }
        return {
            "server_version_num": schema.POSTGRES_VERSION, "behaviour_fingerprint": schema.BEHAVIOUR_SHA256,
            "catalog_snapshot": snapshot, "migration_rows": migrations, "state": state,
            "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        }

    result = schema.expected_catalog_audit(audit(snapshot), delta)
    expected = migration_state([*migrations, list(schema.MIGRATION_NODE)])
    assert result["migration_fingerprint"] == expected["fingerprint"]
    invalid = {**snapshot, "constraints": []}
    with pytest.raises(ValueError, match="delta does not match"):
        schema.expected_catalog_audit(audit(invalid), delta)


@pytest.mark.parametrize("field", ["active_sha", "target_sha", "input_hashes", "recovery_policy",
                                 "postgresql_rehearsal_sha256"])
def test_disclosure_rejects_identity_scope_and_evidence_changes(field):
    value = disclosure(schema.ACTIVE_SHA)
    assert maintenance_schema.validate_disclosure(value, target_sha=NEW_SHA) == value
    value[field] = None
    with pytest.raises(ValueError, match="Multiple-solutions"):
        maintenance_schema.validate_disclosure(value, target_sha=NEW_SHA)


def test_exact_postgresql_evidence_must_be_packaged(tmp_path):
    value = disclosure(schema.ACTIVE_SHA)
    path = tmp_path / schema.EVIDENCE_PATH
    path.write_bytes(schema.evidence_bytes(release_sha=NEW_SHA, active_sha=schema.ACTIVE_SHA))
    maintenance_schema.validate_build_evidence(tmp_path, value)
    path.write_bytes(path.read_bytes().replace(b"deployment-proof", b"local-rehearsal"))
    with pytest.raises(ValueError, match="proof differs"):
        maintenance_schema.validate_build_evidence(tmp_path, value)


def test_dispatch_requires_exact_migration_and_active_baseline(monkeypatch, frozen_candidate):
    changes = ["A\t" + schema.MIGRATION_PATH.as_posix()]

    def git(arguments, **kwargs):
        if arguments[:2] == ["git", "diff"]:
            return SimpleNamespace(stdout="\n".join(changes))
        return SimpleNamespace(stdout=b"LEARNING_READER_BRIDGE = False\n", returncode=0)

    monkeypatch.setattr(validate_dispatch.subprocess, "run", git)
    args = {
        "repository": frozen_candidate, "active_sha": schema.ACTIVE_SHA, "target_sha": NEW_SHA,
        "registry_path": ROOT / "deployment/migration-classifications.yml", "declared_class": "data-or-non-compatible",
    }
    assert validate_dispatch.build_migration_disclosure(**args)["migrations"] == [
        {"migration": schema.MIGRATION, "classification": "data-or-non-compatible"},
    ]
    with pytest.raises(validate_dispatch.DispatchValidationError, match="reviewed baseline"):
        validate_dispatch.build_migration_disclosure(**{**args, "active_sha": OLD_SHA})
    changes.append("A\tinspinia/pages/migrations/0047_study_help.py")
    with pytest.raises(validate_dispatch.DispatchValidationError, match="exact frozen"):
        validate_dispatch.build_migration_disclosure(**args)


def test_record_comparison_rejects_old_record_and_sequence_changes():
    digest = {"rows": 1, "sha256": "a" * 64}
    after = {
        "tables": [
            {"schema": "public", "table": name, **digest} for name in (schema.TABLE, "django_migrations")
        ],
        "sequences": [{"schema": "public", "sequence": "django_migrations_id_seq", **digest}],
        "large_objects": digest, "migration_rows": 1, "nonoriginal_solutions": 0,
    }
    before = {
        **copy.deepcopy(after),
        "schema_snapshot": {"columns": [
            {"schema": "public", "table": schema.TABLE, "position": position, "column": column}
            for position, column in enumerate(preservation.SOLUTION_COLUMNS, 1)
        ]},
    }
    assert preservation.compare_preserved(before, after)["verified"]
    after["nonoriginal_solutions"] = 1
    with pytest.raises(database_recovery.RecoveryError, match="unexpected_rows"):
        preservation.compare_preserved(before, after)
    after["nonoriginal_solutions"] = 0
    after["sequences"][0]["rows"] = 0
    with pytest.raises(database_recovery.RecoveryError, match="original_records_changed"):
        preservation.compare_preserved(before, after)


class MultipleSolutionsBackend(CatalogueBackend):
    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        (destination / schema.EVIDENCE_PATH).write_bytes(
            schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA),
        )

    def community_audit(self, contract):
        audit = super().catalogue_audit(contract)
        if self.failure != self.stage:
            audit["behaviour_fingerprint"] = schema.BEHAVIOUR_SHA256
        return audit

    def check_multiple_solutions_schema(self, contract, release):
        return super().check_catalogue_schema(contract, release)

    def migrate_multiple_solutions_schema(self, contract, release):
        return super().migrate_catalogue_schema(contract, release)

    def verify_multiple_solutions_records(self, contract, run_id, active_sha):
        return super().verify_catalogue_records(contract, run_id, active_sha)

    def verify_catalogue_records(self, contract, run_id, active_sha):
        pytest.fail("The worker must verify original solution records through the 0017 projection")

    def refresh_catalogue(self, contract, release):
        pytest.fail("0017 does not modify unrelated application data")


@pytest.mark.parametrize(("failure", "expected"), [("", "active"), ("preserve", "recovery_required")])
def test_worker_verifies_recovery_and_original_records_before_activation(tmp_path, monkeypatch, failure, expected):
    monkeypatch.setattr(schema, "ACTIVE_SHA", OLD_SHA)
    contract = _contract(tmp_path)
    _seed(contract, migration_class="data-or-non-compatible")
    request_path = contract.registry_dir / "requests/42.json"
    atomic_write_json(request_path, {**read_json(request_path), "schema_disclosure": disclosure(OLD_SHA)})
    backend = MultipleSolutionsBackend(failure)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == expected
    assert backend.events[:6] == ["preflight", "drain", "backup", "verify_recovery", "migrate", "preserve"]
    if failure:
        assert "activate" not in backend.events
    else:
        assert backend.events[6:] == ["activate", "health", "resume"]
        assert read_json(contract.registry_dir / f"releases/{NEW_SHA}.json")["rollback_eligible"] is False


def test_worker_preflight_is_read_only_and_apply_is_bounded(monkeypatch, frozen_candidate):
    calls = []
    monkeypatch.setattr(WorkerBackend, "_run_candidate", lambda *args, **kwargs: calls.append((args[-1], kwargs)))
    backend = WorkerBackend()
    backend.check_multiple_solutions_schema(None, frozen_candidate)
    backend.migrate_multiple_solutions_schema(None, frozen_candidate)
    assert calls == [
        (["shell", "--command", schema.PLAN_CHECK], {"read_only": True}),
        (["shell", "--command", schema.MIGRATION_APPLY], {"migration": True}),
    ]
