# ruff: noqa: EM101, PLR2004, S603, SLF001, TRY003
"""The curated alteration allowance is exact, hash-bound, and data-preserving."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import additive_schema
from scripts.deployment import curated_collections_schema as schema
from scripts.deployment.curated_collections_schema_rehearsal import validate_migration_record
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.protocol import OperationEnvelope
from scripts.deployment.protocol import ProtocolError
from scripts.deployment.protocol import envelope_audience
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.tests.test_concept_schema import END
from scripts.deployment.tests.test_concept_schema import START
from scripts.deployment.tests.test_concept_schema import SchemaBackend
from scripts.deployment.tests.test_concept_schema import disclosure as concept_disclosure
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed
from scripts.deployment.tests.test_protocol import _envelope
from scripts.deployment.validate_dispatch import validate_schema_input

ROOT = Path(__file__).resolve().parents[3]


def test_curated_migration_has_an_explicit_compatible_release_classification():
    from scripts.deployment.migration_plan import CLASS_COMPATIBLE
    from scripts.deployment.migration_plan import load_registry

    entry = load_registry(ROOT / "deployment/migration-classifications.yml")[schema.MIGRATION]
    assert entry["classification"] == CLASS_COMPATIBLE
    assert entry["code_rollback_permitted"] is True
    assert entry["recovery_required"] is False
    assert "existing_collections_personal_with_non_null_owners" in entry["data_preconditions"]


def test_expected_curated_delta_is_frozen_and_structurally_bounded():
    from scripts.deployment.curated_collections_schema_rehearsal import validate_alteration_shape
    from scripts.deployment.schema_fingerprint import sha256_fingerprint

    delta = frozen_delta()
    assert sha256_fingerprint(delta) == schema.DELTA_SHA256
    validate_alteration_shape(delta)
    assert not delta["removed"]["tables"]
    assert not delta["added"]["tables"]
    assert not delta["added"]["indexes"]


def disclosure():
    value = concept_disclosure()
    value.update(migration=schema.MIGRATION, migration_file_sha256=schema.MIGRATION_SHA256)
    value["postgresql_rehearsal_sha256"] = hashlib.sha256(evidence_bytes(build_evidence())).hexdigest()
    value["compatibility_smoke_sha256"] = schema.COMPATIBILITY_SMOKE_SHA256
    return value


def evidence_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def build_evidence():
    return {
        "format_version": 1,
        "source_sha": NEW_SHA,
        "active_sha": OLD_SHA,
        "postgres_version": schema.POSTGRES_VERSION,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "delta_sha256": schema.DELTA_SHA256,
        "only_approved_schema_changed": True,
        "source_fixture_unchanged": True,
        "active_revision_smoke_passed": True,
        "existing_records_unchanged": True,
        "existing_sequences_unchanged": True,
        "existing_collections_personal": True,
        "existing_trigger_definitions_unchanged": True,
    }


def test_router_preserves_existing_allowances_and_only_admits_exact_collections_disclosure():
    for value in (concept_disclosure(), disclosure()):
        assert additive_schema.validate_disclosure(value, target_sha=NEW_SHA) == value
    value = disclosure()
    for change in ({"migration": "website.0002_other"}, {"migration_file_sha256": "0" * 64}):
        with pytest.raises(ValueError, match="outside the approved scope"):
            additive_schema.validate_disclosure({**value, **change}, target_sha=NEW_SHA)
    validate_schema_input(
        json.dumps(value),
        release_sha=NEW_SHA,
        migration_class="backward-compatible-schema",
        initial_adoption=False,
    )


def test_curated_collections_schema_is_bound_to_the_oidc_request_and_cannot_be_used_for_rollback():
    raw = _envelope(release_sha=NEW_SHA, workflow_sha=NEW_SHA, migration_class="backward-compatible-schema")
    raw["schema_disclosure"] = disclosure()
    first = OperationEnvelope.from_dict(raw)
    raw = copy.deepcopy(raw)
    raw["schema_disclosure"]["expected"]["schema_fingerprint"] = "7" * 64
    assert envelope_audience(first.public_dict()) != envelope_audience(OperationEnvelope.from_dict(raw).public_dict())
    for change in ({"migration_class": "none"}, {"operation": "rollback"}, {"schema_disclosure": None}):
        with pytest.raises(ProtocolError):
            OperationEnvelope.from_dict({**raw, **change})


def test_solution_collections_migration_bytes_are_frozen_and_symlinks_rejected(tmp_path):
    path = tmp_path / schema.MIGRATION_PATH
    path.parent.mkdir(parents=True)
    content = (ROOT / schema.MIGRATION_PATH).read_bytes()
    assert hashlib.sha256(content).hexdigest() == schema.MIGRATION_SHA256
    path.write_bytes(content)
    for name in schema.PRIOR_MIGRATIONS:
        (path.parent / name).write_bytes((ROOT / schema.MIGRATION_PATH.parent / name).read_bytes())
    schema.validate_candidate(tmp_path)
    path.write_bytes(content + b"\n")
    with pytest.raises(schema.CuratedCollectionsSchemaError):
        schema.validate_candidate(tmp_path)
    path.unlink()
    path.symlink_to(ROOT / schema.MIGRATION_PATH)
    with pytest.raises(schema.CuratedCollectionsSchemaError):
        schema.validate_candidate(tmp_path)


@pytest.mark.parametrize(
    "field", [
        "existing_records_unchanged", "existing_sequences_unchanged", "existing_collections_personal",
        "existing_trigger_definitions_unchanged",
    ],
)
@pytest.mark.parametrize("value", [False, 1, None])
def test_data_preservation_evidence_must_be_explicit_true(tmp_path, field, value):
    report = build_evidence()
    report[field] = value
    content = evidence_bytes(report)
    (tmp_path / schema.EVIDENCE_PATH).write_bytes(content)
    bound = disclosure()
    bound["postgresql_rehearsal_sha256"] = hashlib.sha256(content).hexdigest()
    with pytest.raises(schema.CuratedCollectionsSchemaError):
        schema.validate_build_evidence(tmp_path, bound)


@pytest.mark.parametrize("extra", [False, True])
def test_solution_collections_plan_guard_remains_literal_under_optimized_python(monkeypatch, extra):
    operations = [type(name, (), {})() for name in ("AddField", "AlterField", "AddConstraint")]
    migration = SimpleNamespace(
        app_label="solutions", name="0008_solutioncollection_kind_and_nullable_owner", operations=operations,
    )
    plan = [(migration, False)]
    if extra:
        plan.append((SimpleNamespace(app_label="users", name="unapproved", operations=operations), False))
    executor = SimpleNamespace(
        loader=SimpleNamespace(graph=SimpleNamespace(
            leaf_nodes=lambda: [("solutions", "0008_solutioncollection_kind_and_nullable_owner")],
        )),
        migration_plan=lambda targets: plan,
    )
    monkeypatch.setattr("django.db.migrations.executor.MigrationExecutor", lambda connection: executor)
    command = compile(schema.PLAN_CHECK, "<frozen-website-plan>", "exec", optimize=2)
    if extra:
        with pytest.raises(RuntimeError, match="Unapproved"):
            exec(command, {})  # noqa: S102 - exact fixed plan guard
    else:
        exec(command, {})  # noqa: S102 - exact fixed plan guard


class CuratedCollectionsBackend(SchemaBackend):
    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        path = destination / schema.MIGRATION_PATH
        path.parent.mkdir(parents=True)
        path.write_bytes((ROOT / schema.MIGRATION_PATH).read_bytes())
        (destination / schema.EVIDENCE_PATH).write_bytes(evidence_bytes(build_evidence()))
        for name in schema.PRIOR_MIGRATIONS:
            (path.parent / name).write_bytes((ROOT / schema.MIGRATION_PATH.parent / name).read_bytes())

    def check_curated_collections_schema(self, contract, release):
        if self.fail_at == "candidate":
            raise schema.CuratedCollectionsSchemaError("Invalid collections candidate")
        schema.validate_candidate(release)

    def migrate_curated_collections_schema(self, contract, release):
        super().migrate_concept_schema(contract, release)


@pytest.mark.parametrize(
    ("failure", "state", "migrated"),
    [
        ("", "active", True),
        ("start", "failed", False),
        ("candidate", "failed", False),
        ("migration", "recovery_required", True),
        ("end", "recovery_required", True),
    ],
)
def test_collections_worker_never_retries_failed_migrations(tmp_path, failure, state, migrated):
    contract = _contract(tmp_path)
    _seed(contract, migration_class="backward-compatible-schema")
    path = contract.registry_dir / "requests/42.json"
    request = read_json(path)
    request["schema_disclosure"] = disclosure()
    atomic_write_json(path, request)
    backend = CuratedCollectionsBackend(fail_at=failure)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == state
    assert backend.migrated == migrated
    assert (contract.release_root / "current").resolve().name == (NEW_SHA if state == "active" else OLD_SHA)
    assert run_operation(contract, "42", backend=backend) == result
    if state == "active":
        assert (
            read_json(contract.registry_dir / f"releases/{OLD_SHA}.json")["state_fingerprint"]
            == END["state_fingerprint"]
        )
    else:
        assert (
            read_json(contract.registry_dir / f"releases/{OLD_SHA}.json")["state_fingerprint"]
            == START["state_fingerprint"]
        )


def test_solution_collections_migration_retains_lock_and_statement_bounds(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("scripts.deployment.operation_worker.subprocess.run", lambda args, **kwargs: seen.append(args))
    WorkerBackend().migrate_curated_collections_schema(_contract(tmp_path), tmp_path / "candidate")
    assert "--setenv=PGOPTIONS=-c lock_timeout=2s -c statement_timeout=30s" in seen[0]
    assert seen[0][-3:] == ["shell", "--command", schema.MIGRATION_APPLY]


def test_only_the_one_new_migration_metadata_record_is_permitted():
    old = [(1, "pages", "0039_catalogue_revision_triggers", "before")]
    new = [*old, (2, "solutions", "0008_solutioncollection_kind_and_nullable_owner", "after")]
    validate_migration_record((old, 1), (new, 2))
    for changed in ([*new, (3, "users", "other", "after")], [(1, "pages", "changed", "before"), new[-1]]):
        with pytest.raises(ValueError, match="beyond its one approved record"):
            validate_migration_record((old, 1), (changed, 2))


def starting_audit():
    from scripts.deployment.schema_fingerprint import canonical_json
    from scripts.deployment.schema_fingerprint import migration_state

    snapshot = json.loads((Path(__file__).parent / "fixtures/solution-collections-schema-delta.json").read_text())
    snapshot["tables"].append({"schema": "public", "table": "solutions_solutionpublicshare", "kind": "r"})
    migrations = [["solutions", "0007_solutioncollection_solutioncollectionentry"]]
    state = {"schema": schema_state(snapshot), "migration": migration_state(migrations)}
    return {
        "server_version_num": schema.POSTGRES_VERSION,
        "catalog_snapshot": snapshot, "migration_rows": migrations, "state": state,
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
    }


def frozen_delta():
    return json.loads((Path(__file__).parent / "fixtures/curated-collections-schema-delta.json").read_text())


def test_expected_audit_changes_only_frozen_owner_kind_constraint_and_migration():
    from scripts.deployment.schema_fingerprint import migration_state

    start = starting_audit()
    unchanged = copy.deepcopy(start)
    result = schema.expected_catalog_audit(start, frozen_delta())
    assert result["migration_fingerprint"] == migration_state([
        *start["migration_rows"], ["solutions", schema.MIGRATION_NAME],
    ])["fingerprint"]
    assert result["schema_fingerprint"] != start["state"]["schema"]["fingerprint"]
    assert start == unchanged


@pytest.mark.parametrize("change", ["new_column", "default", "nullable", "table", "position", "index"])
def test_expected_audit_rejects_any_different_catalog_delta(change):
    delta = frozen_delta()
    if change == "new_column":
        delta["added"]["columns"][0]["column"] = "unapproved"
    elif change == "index":
        delta["added"]["indexes"] = [{
            "schema": "public", "table": schema.TABLE, "name": "unapproved", "definition": "CREATE INDEX x",
        }]
    else:
        delta["added"]["columns"][0][change] = {
            "default": "false", "nullable": not delta["added"]["columns"][0]["nullable"],
            "table": "users_user", "position": 99,
        }[change]
    with pytest.raises(schema.CuratedCollectionsSchemaError):
        schema.expected_catalog_audit(starting_audit(), delta)


@pytest.mark.parametrize(
    "change", ["version", "fingerprint", "missing_table", "missing_prior", "recorded", "owner", "existing_kind"],
)
def test_expected_audit_rejects_starting_drift_or_already_recorded_migration(change):
    from scripts.deployment.schema_fingerprint import canonical_json
    from scripts.deployment.schema_fingerprint import migration_state

    start = starting_audit()
    if change == "version":
        start["server_version_num"] = 170010
    elif change == "fingerprint":
        start["state_fingerprint"] = "0" * 64
    else:
        if change == "missing_table":
            start["catalog_snapshot"]["tables"].clear()
        elif change == "missing_prior":
            start["migration_rows"].clear()
        elif change == "recorded":
            start["migration_rows"].append(["solutions", schema.MIGRATION_NAME])
        elif change == "existing_kind":
            unexpected = copy.deepcopy(frozen_delta()["added"]["columns"][0])
            unexpected["default"] = "'unexpected'::character varying"
            start["catalog_snapshot"]["columns"].append(unexpected)
        elif change == "owner":
            owner = next(row for row in start["catalog_snapshot"]["columns"] if row["column"] == "owner_id")
            owner["nullable"] = True
        start["state"]["schema"] = schema_state(start["catalog_snapshot"])
        start["state"]["migration"] = migration_state(start["migration_rows"])
        start["state_fingerprint"] = hashlib.sha256(canonical_json(start["state"])).hexdigest()
    with pytest.raises(schema.CuratedCollectionsSchemaError):
        schema.expected_catalog_audit(start, frozen_delta())


def test_older_code_probe_uses_explicit_ids_rollback_and_forces_deferred_constraints():
    code = schema.smoke_command()
    assert "SolutionCollection.objects.create(id=900001" in code
    assert "transaction.set_rollback(True)" in code
    assert code.count("connection.check_constraints()") == 2
    assert "No solutions are currently available" in code


def test_allocation_routes_only_exact_curated_rehearsal():
    from scripts.deployment.curated_collections_schema_rehearsal import run
    from scripts.deployment.schema_rehearsal import _approved_rehearsal

    assert _approved_rehearsal(schema.MIGRATION) is run
    assert _approved_rehearsal("solutions.0008_unapproved") is None


def test_rehearsal_rejects_other_postgresql_versions_before_schema_access(monkeypatch):
    from scripts.deployment import curated_collections_schema_rehearsal as rehearsal

    monkeypatch.setattr(rehearsal, "prepare_django", lambda: SimpleNamespace(pg_version=170010))
    with pytest.raises(ValueError, match="pinned PostgreSQL 17.9"):
        rehearsal.run(SimpleNamespace())
