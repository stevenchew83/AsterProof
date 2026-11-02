# ruff: noqa: EM101, PLR2004, S102, SLF001, TRY003
"""Frozen additive migration and a reader floor across all activation paths."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import additive_schema
from scripts.deployment import solution_document_compat as compat
from scripts.deployment import solution_document_schema as schema
from scripts.deployment.build_release import build_release
from scripts.deployment.migration_audit import AuditConfig
from scripts.deployment.migration_audit import collect_document_reader_floor
from scripts.deployment.operation_worker import OperationError
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.release_manifest import ManifestError
from scripts.deployment.release_manifest import ReleaseManifest
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import sha256_fingerprint
from scripts.deployment.server_activate import activate_release
from scripts.deployment.solution_document_schema_rehearsal import validate_alteration_shape
from scripts.deployment.tests.test_concept_schema import SchemaBackend
from scripts.deployment.tests.test_concept_schema import disclosure as concept_disclosure
from scripts.deployment.tests.test_operation_worker import FINGERPRINT
from scripts.deployment.tests.test_operation_worker import NEW_DIGEST
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_DIGEST
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import FakeBackend
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed

ROOT = Path(__file__).resolve().parents[3]


def frozen_delta():
    return json.loads((Path(__file__).parent / "fixtures/solution-document-schema-delta.json").read_text())


def evidence():
    return {
        "format_version": 1, "source_sha": NEW_SHA, "active_sha": OLD_SHA,
        "postgres_version": schema.POSTGRES_VERSION, "migration_file_sha256": schema.MIGRATION_SHA256,
        "delta_sha256": schema.DELTA_SHA256, "only_approved_schema_changed": True,
        "source_fixture_unchanged": True, "active_revision_smoke_passed": True,
        "existing_records_unchanged": True, "existing_sequences_unchanged": True,
        "document_schema_defaults_safe": True, "existing_trigger_definitions_unchanged": True,
    }


def evidence_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def disclosure():
    return {
        **concept_disclosure(), "migration": schema.MIGRATION, "migration_file_sha256": schema.MIGRATION_SHA256,
        "compatibility_smoke_sha256": schema.COMPATIBILITY_SMOKE_SHA256,
        "postgresql_rehearsal_sha256": hashlib.sha256(evidence_bytes(evidence())).hexdigest(),
    }


def write_reader(release, monkeypatch):
    path = "inspinia/solutions/document_source.py"
    body = b"# Reviewed synthetic continuous-document reader.\n"
    digest = hashlib.sha256(body).hexdigest()
    monkeypatch.setattr(compat, "READER_SOURCES", {path: digest})
    target = release / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    manifest = ReleaseManifest(
        repository="owner/AsterProof", repository_id="123", release_sha=release.name,
        run_id="42", built_at="2026-11-01T00:00:00Z", target_platform="manylinux2014_x86_64",
        python_abi="cp312", files=({"path": path, "sha256": digest, "size": len(body)},),
        solution_document_reader=1,
    )
    (release / "release-metadata.json").write_bytes(manifest.to_json_bytes())
    return target


def test_document_delta_is_real_frozen_and_only_additive():
    delta = frozen_delta()
    assert sha256_fingerprint(delta) == schema.DELTA_SHA256
    validate_alteration_shape(delta)
    assert not any(delta["removed"].values())
    assert {row["table"] for row in delta["added"]["tables"]} == schema.TABLES


def test_reviewed_reader_capability_matches_the_actual_implementation_sources():
    for relative, expected in compat.IMAGE_COMPATIBILITY_SOURCES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_document_migration_and_all_earlier_migrations_are_hash_bound(tmp_path):
    path = tmp_path / schema.MIGRATION_PATH
    path.parent.mkdir(parents=True)
    for name in (schema.MIGRATION_PATH.name, *schema.PRIOR_MIGRATIONS):
        (path.parent / name).write_bytes((ROOT / schema.MIGRATION_PATH.parent / name).read_bytes())
    schema.validate_candidate(tmp_path)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(schema.SolutionDocumentSchemaError):
        schema.validate_candidate(tmp_path)


def test_router_and_registry_admit_only_exact_document_migration():
    from scripts.deployment.migration_plan import load_registry

    value = disclosure()
    assert additive_schema.validate_disclosure(value, target_sha=NEW_SHA) == value
    entry = load_registry(ROOT / "deployment/migration-classifications.yml")[schema.MIGRATION]
    assert entry["classification"] == "backward-compatible-schema"
    assert "document_writes_disabled_until_compatible_reader_baseline" in entry["data_preconditions"]
    with pytest.raises(schema.SolutionDocumentSchemaError, match="outside the approved scope"):
        additive_schema.validate_disclosure({**value, "migration_file_sha256": "0" * 64}, target_sha=NEW_SHA)


@pytest.mark.parametrize("field", [
    "existing_records_unchanged", "existing_sequences_unchanged", "document_schema_defaults_safe",
    "existing_trigger_definitions_unchanged", "active_revision_smoke_passed",
])
@pytest.mark.parametrize("value", [False, 1, None])
def test_preservation_and_compatibility_proof_requires_explicit_true(tmp_path, field, value):
    report = {**evidence(), field: value}
    content = evidence_bytes(report)
    (tmp_path / schema.EVIDENCE_PATH).write_bytes(content)
    bound = {**disclosure(), "postgresql_rehearsal_sha256": hashlib.sha256(content).hexdigest()}
    with pytest.raises(schema.SolutionDocumentSchemaError):
        schema.validate_build_evidence(tmp_path, bound)


@pytest.mark.parametrize("extra", [False, True])
def test_complete_pending_operation_sequence_is_literal_even_under_optimized_python(monkeypatch, extra):
    names = [
        "AddEditVersionField", "CreateModel", "CreateModel", "CreateModel", "AddField",
        "AddConstraint", "AddConstraint", "AddIndex", "AddConstraint",
    ]
    migration = SimpleNamespace(
        app_label="solutions", name=schema.MIGRATION_NAME,
        operations=[type(name, (), {})() for name in names],
    )
    plan = [(migration, False)]
    if extra:
        plan.append((SimpleNamespace(app_label="users", name="other", operations=[]), False))
    executor = SimpleNamespace(
        loader=SimpleNamespace(graph=SimpleNamespace(leaf_nodes=lambda: [("solutions", schema.MIGRATION_NAME)])),
        migration_plan=lambda targets: plan,
    )
    monkeypatch.setattr("django.db.migrations.executor.MigrationExecutor", lambda connection: executor)
    if extra:
        with pytest.raises(RuntimeError, match="Unapproved"):
            exec(compile(schema.PLAN_CHECK, "<document-plan>", "exec", optimize=2), {})
    else:
        exec(compile(schema.PLAN_CHECK, "<document-plan>", "exec", optimize=2), {})


def test_reader_capability_is_bound_to_manifest_and_actual_frozen_bytes(tmp_path, monkeypatch):
    release = tmp_path / NEW_SHA
    target = write_reader(release, monkeypatch)
    assert compat.verified_reader_release(release)
    target.write_bytes(b"# Block-only reader substituted.\n")
    assert not compat.verified_reader_release(release)
    payload = json.loads((release / "release-metadata.json").read_text())
    payload["files"][0]["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ManifestError, match="reader bytes"):
        ReleaseManifest.from_bytes(json.dumps(payload).encode())


def test_artifact_builder_declares_only_reviewed_reader_bytes(tmp_path, monkeypatch):
    source = tmp_path / "source" / NEW_SHA
    target = write_reader(source, monkeypatch)
    relative = target.relative_to(source)
    monkeypatch.setattr("scripts.deployment.build_release._tracked_files", lambda root, sha: [relative])
    static, wheels = tmp_path / "static", tmp_path / "wheels"
    static.mkdir()
    wheels.mkdir()
    arguments = {
        "repository_root": source, "static_root": static, "wheelhouse": wheels,
        "output": tmp_path / "release.tar", "repository": "owner/AsterProof", "repository_id": "123",
        "release_sha": NEW_SHA, "run_id": "42", "target_platform": "manylinux2014_x86_64",
        "python_abi": "cp312", "built_at": "2026-11-01T00:00:00Z", "source_date_epoch": 1,
    }
    build_release(**arguments)
    import tarfile

    with tarfile.open(arguments["output"]) as archive:
        manifest = ReleaseManifest.from_bytes(archive.extractfile("release-metadata.json").read())
    assert manifest.solution_document_reader == compat.READER_VERSION
    target.write_bytes(b"Reader changed without capability review.\n")
    with pytest.raises(ValueError, match="reviewed capability refresh"):
        build_release(**arguments)


@pytest.mark.parametrize("present", [False, True])
def test_reader_floor_is_identity_bound_read_only_metadata_only(present):
    identity = ["synthetic", "asterproof_catalog", "local", "", ""]
    commands = []
    outputs = iter([",".join(identity) + "\n", "t\n" if present else "f\n"])

    def runner(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(stdout=next(outputs))

    config = AuditConfig(
        os_user="asterproof_audit", pg_service="asterproof_audit", pg_service_file=Path("/etc/pg_service.conf"),
        expected_role="asterproof_catalog",
        expected_database_identity_hash=hashlib.sha256(canonical_json(identity)).hexdigest(),
    )
    assert collect_document_reader_floor(config, runner=runner)["reader_required"] is present
    assert all("BEGIN READ ONLY" in command[-1] and "statement_timeout='10s'" in command[-1] for command in commands)
    assert "to_regclass" in commands[-1][-1]
    assert "snapshot" not in commands[-1][-1]
    assert "SELECT 1 FROM" not in commands[-1][-1]


class RequiredReaderBackend(FakeBackend):
    def document_reader_required(self, contract):
        return True


class VerifiedReaderBackend(RequiredReaderBackend):
    def __init__(self, monkeypatch):
        super().__init__()
        self.monkeypatch = monkeypatch

    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        write_reader(destination, self.monkeypatch)


def test_verified_reader_forward_deploy_remains_available_above_floor(tmp_path, monkeypatch):
    contract = _contract(tmp_path)
    _seed(contract)
    result = run_operation(contract, "42", backend=VerifiedReaderBackend(monkeypatch))
    assert result["state"] == "active"
    assert (contract.release_root / "current").resolve().name == NEW_SHA


@pytest.mark.parametrize("payload", [[], {}, {"format_version": 1, "reader_required": 1}])
def test_unavailable_or_malformed_reader_floor_fails_closed(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(
        "scripts.deployment.operation_worker.subprocess.run", lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps(payload),
        ),
    )
    with pytest.raises(OperationError, match="document_reader_floor_unavailable"):
        WorkerBackend().document_reader_required(_contract(tmp_path))


def test_readerless_forward_deploy_is_rejected_before_activation(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract)
    result = run_operation(contract, "42", backend=RequiredReaderBackend())
    assert result["state"] == "failed"
    assert result["error_code"] == "document_reader_required"
    assert (contract.release_root / "current").resolve().name == OLD_SHA


def test_readerless_explicit_rollback_keeps_the_current_release(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract, operation="rollback", target_sha=OLD_SHA, digest=OLD_DIGEST)
    (contract.releases_dir / NEW_SHA).mkdir()
    atomic_write_json(contract.registry_dir / f"releases/{NEW_SHA}.json", {
        "artifact_digest": NEW_DIGEST, "migration_class": "none", "state_fingerprint": FINGERPRINT,
        "release_sha": NEW_SHA, "rollback_eligible": True, "state": "active",
    })
    activate_release(contract, NEW_SHA)
    old_record = contract.registry_dir / f"releases/{OLD_SHA}.json"
    atomic_write_json(old_record, {**read_json(old_record), "state": "previous"})
    result = run_operation(contract, "42", backend=RequiredReaderBackend())
    assert result["state"] == "failed"
    assert result["error_code"] == "document_reader_required"
    assert (contract.release_root / "current").resolve().name == NEW_SHA


class DocumentBackend(SchemaBackend):
    def __init__(self, monkeypatch, **kwargs):
        super().__init__(**kwargs)
        self.monkeypatch = monkeypatch

    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        write_reader(destination, self.monkeypatch)
        path = destination / schema.MIGRATION_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        for name in (schema.MIGRATION_PATH.name, *schema.PRIOR_MIGRATIONS):
            (path.parent / name).write_bytes((ROOT / schema.MIGRATION_PATH.parent / name).read_bytes())
        (destination / schema.EVIDENCE_PATH).write_bytes(evidence_bytes(evidence()))

    def document_reader_required(self, contract):
        return self.migrated

    def check_solution_document_schema(self, contract, release):
        schema.validate_candidate(release)

    def migrate_solution_document_schema(self, contract, release):
        super().migrate_concept_schema(contract, release)


@pytest.mark.parametrize(("failure", "state"), [("", "active"), ("migration", "recovery_required")])
def test_exact_schema_worker_runs_once_with_verified_reader_and_bound_evidence(tmp_path, monkeypatch, failure, state):
    contract = _contract(tmp_path)
    _seed(contract, migration_class="backward-compatible-schema")
    path = contract.registry_dir / "requests/42.json"
    atomic_write_json(path, {**read_json(path), "schema_disclosure": disclosure()})
    backend = DocumentBackend(monkeypatch, fail_at=failure)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == state
    assert backend.migrated
    assert run_operation(contract, "42", backend=backend) == result


def test_activation_failure_cannot_automatically_restore_block_only_baseline(tmp_path, monkeypatch):
    contract = _contract(tmp_path)
    _seed(contract, migration_class="backward-compatible-schema")
    path = contract.registry_dir / "requests/42.json"
    atomic_write_json(path, {**read_json(path), "schema_disclosure": disclosure()})
    result = run_operation(contract, "42", backend=DocumentBackend(monkeypatch, fail_at="activation"))
    assert result["state"] == "recovery_required"
    assert result["error_code"] == "document_reader_required"
    assert (contract.release_root / "current").resolve().name == NEW_SHA


def test_activation_recovery_can_restore_a_verified_document_reader(tmp_path, monkeypatch):
    contract = _contract(tmp_path)
    _seed(contract, migration_class="backward-compatible-schema")
    write_reader(contract.releases_dir / OLD_SHA, monkeypatch)
    path = contract.registry_dir / "requests/42.json"
    atomic_write_json(path, {**read_json(path), "schema_disclosure": disclosure()})
    result = run_operation(contract, "42", backend=DocumentBackend(monkeypatch, fail_at="activation"))
    assert result["state"] == "rolled_back"
    assert (contract.release_root / "current").resolve().name == OLD_SHA
