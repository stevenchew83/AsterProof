"""The public registration allowance binds the exact plan, evidence, and reader."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.deployment import additive_schema
from scripts.deployment import registration_compat
from scripts.deployment import registration_schema as schema
from scripts.deployment.migration_plan import load_registry
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.release_manifest import ReleaseManifest
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.tests.test_concept_schema import SchemaBackend
from scripts.deployment.tests.test_concept_schema import disclosure as concept_disclosure
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed

ROOT = Path(__file__).resolve().parents[3]


def disclosure():
    return {
        **concept_disclosure(),
        "migration": schema.MIGRATION,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "postgresql_rehearsal_sha256": hashlib.sha256(schema.evidence_bytes(NEW_SHA, OLD_SHA)).hexdigest(),
        "compatibility_smoke_sha256": schema.COMPATIBILITY_SMOKE_SHA256,
    }


def frozen_delta():
    return json.loads((Path(__file__).parent / "fixtures/registration-schema-delta.json").read_text())


def test_exact_migration_tree_and_catalog_delta():
    schema.validate_candidate(ROOT)
    assert schema_state(frozen_delta())["fingerprint"] == schema.DELTA_SHA256
    registry = load_registry(ROOT / "deployment/migration-classifications.yml")
    assert registry[schema.MIGRATION]["classification"] == "backward-compatible-schema"


@pytest.mark.parametrize(
    "change",
    [
        {"migration": "users.0010_other"},
        {"migration_file_sha256": "0" * 64},
        {"compatibility_smoke_sha256": "0" * 64},
        {"format_version": True},
    ],
)
def test_disclosure_rejects_wrong_migration_and_evidence(change):
    assert additive_schema.validate_disclosure(disclosure(), target_sha=NEW_SHA) == disclosure()
    with pytest.raises(ValueError, match="scope|disclosure"):
        additive_schema.validate_disclosure(disclosure() | change, target_sha=NEW_SHA)


def test_expected_catalog_requires_the_previous_migration_and_adds_only_the_frozen_column():
    delta = frozen_delta()
    before = {name: [] for name in delta}
    before["columns"] = [
        delta["columns"][0] | {"position": position, "column": column}
        for position, column in enumerate(("id", "auto_approve_new_users", "created_at", "updated_at"), 1)
    ]
    migrations = [list(schema.PREVIOUS)]
    state = {"schema": schema_state(before), "migration": migration_state(migrations)}
    start = {
        "server_version_num": schema.POSTGRES_VERSION, "state": state, "catalog_snapshot": before,
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(), "migration_rows": migrations,
    }
    expected = schema.expected_catalog_audit(start, delta)
    assert expected["schema_fingerprint"] == schema_state(before | {
        "columns": before["columns"] + delta["columns"],
    })["fingerprint"]
    with pytest.raises(ValueError, match="starting shape"):
        schema.expected_catalog_audit(start | {"catalog_snapshot": before | {"columns": []}}, delta)
    with pytest.raises(ValueError, match="required migration state"):
        schema.expected_catalog_audit(start | {"migration_rows": []}, delta)


def write_reader_manifest(release):
    files = []
    for relative, digest in registration_compat.READER_SOURCES.items():
        data = (ROOT / relative).read_bytes()
        target = release / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files.append({"path": relative, "sha256": digest, "size": len(data)})
    manifest = ReleaseManifest(
        repository="stevenchew83/AsterProof", repository_id="1165803960", release_sha=release.name,
        run_id="42", built_at="2026-11-08T00:00:00Z", target_platform="linux-aarch64", python_abi="cp312",
        files=tuple(files),
    )
    (release / "release-metadata.json").write_bytes(manifest.to_json_bytes())


def test_reader_requires_frozen_gate_bytes_in_manifest_and_release(tmp_path):
    release = tmp_path / NEW_SHA
    write_reader_manifest(release)
    assert registration_compat.verified_reader_release(release)
    (release / "inspinia/users/adapters.py").write_text("pass\n")
    assert not registration_compat.verified_reader_release(release)


class RegistrationBackend(SchemaBackend):
    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        write_reader_manifest(destination)
        (destination / schema.EVIDENCE_PATH).write_bytes(schema.evidence_bytes(NEW_SHA, OLD_SHA))

    def check_registration_schema(self, contract, release):
        assert release.name == NEW_SHA

    def migrate_registration_schema(self, contract, release):
        self.migrate_concept_schema(contract, release)

    def registration_reader_required(self):
        return self.stage == "expected"


@pytest.mark.parametrize("failure", ["", "activation"])
def test_migration_and_automatic_recovery_guard(tmp_path, failure):
    contract = _contract(tmp_path)
    _seed(contract, migration_class="backward-compatible-schema")
    request_path = contract.registry_dir / "requests/42.json"
    atomic_write_json(request_path, read_json(request_path) | {"schema_disclosure": disclosure()})
    backend = RegistrationBackend(fail_at=failure)

    result = run_operation(contract, "42", backend=backend)

    assert backend.migrated
    assert (contract.release_root / "current").resolve().name == NEW_SHA
    if failure:
        assert result["state"] == "recovery_required"
        assert result["error_code"] == "registration_reader_required"
    else:
        assert result["state"] == "active"
