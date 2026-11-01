# ruff: noqa: S102 - Execute only the fixed, reviewed migration/AI-check literals under test.
"""The proof-library maintenance proposal is exact, AI-off, and fail-closed."""

import copy
import hashlib
import importlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import community_proof_schema as schema
from scripts.deployment import community_proof_schema_rehearsal as rehearsal
from scripts.deployment import community_schema
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state

ROOT = Path(__file__).resolve().parents[3]
OLD_SHA, NEW_SHA = "1" * 40, "2" * 40


def starting_audit():
    snapshot = {
        "tables": [{"schema": "public", "table": schema.TABLE, "kind": "r"}],
        "columns": [
            {"schema": "public", "table": schema.TABLE, "position": position, "column": name,
             "type": kind, "nullable": False, "default": None, "collation": None}
            for position, name, kind in ((1, "id", "uuid"), (2, "title", "text"), (3, "mohs", "smallint"))
        ],
        "constraints": [], "indexes": [], "extensions": [],
    }
    migrations = [list(pair) for pair in schema.PREREQUISITE_MIGRATIONS]
    state = {
        "database_identity_hash": "a" * 64, "role": "asterproof_catalog",
        "schema": schema_state(snapshot), "migration": migration_state(migrations),
    }
    return {
        "server_version_num": schema.POSTGRES_VERSION, "state": state,
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "catalog_snapshot": snapshot, "migration_rows": migrations,
        "behaviour_fingerprint": schema.BEHAVIOUR_SHA256,
    }


def synthetic_delta():
    """Unit-test catalog data only; this is not a discovered PostgreSQL fixture."""
    empty = {name: [] for name in ("tables", "columns", "constraints", "indexes", "extensions")}
    added, removed = copy.deepcopy(empty), copy.deepcopy(empty)
    for table in sorted(schema.TABLES):
        added["tables"].append({"schema": "public", "table": table, "kind": "r"})
        added["columns"].append({
            "schema": "public", "table": table, "position": 1, "column": "id",
            "type": "bigint" if table == "pages_problempublication" else "uuid",
            "nullable": False, "default": None, "collation": None,
        })
    types = (
        ("timestamp with time zone", True), ("boolean", False), ("text", False), ("boolean", False),
    )
    for position, (name, (kind, nullable)) in enumerate(zip(schema.NEW_COLUMNS, types, strict=True), 4):
        added["columns"].append({
            "schema": "public", "table": schema.TABLE, "position": position, "column": name,
            "type": kind, "nullable": nullable, "default": None, "collation": None,
        })
    original = starting_audit()["catalog_snapshot"]["columns"][-1]
    removed["columns"].append(original)
    added["columns"].append({**original, "nullable": True})
    return schema.normalize_delta({"add": added, "remove": removed})


@pytest.fixture
def frozen_delta(monkeypatch):
    delta = synthetic_delta()
    monkeypatch.setattr(schema, "DELTA_SHA256", schema.delta_digest(delta))
    return delta


@pytest.fixture
def candidate(tmp_path, frozen_delta):
    for name in {**schema.INPUT_HASHES, **schema.PREREQUISITE_HASHES}:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    path = tmp_path / schema.DELTA_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(frozen_delta))
    return tmp_path


def disclosure(delta):
    before = starting_audit()
    return {
        "format_version": 1, "kind": schema.KIND, "active_sha": OLD_SHA, "target_sha": NEW_SHA,
        "input_hashes": schema.INPUT_HASHES.copy(),
        "starting": {
            "state_fingerprint": before["state_fingerprint"],
            "schema_fingerprint": before["state"]["schema"]["fingerprint"],
            "migration_fingerprint": before["state"]["migration"]["fingerprint"],
            "behaviour_fingerprint": schema.BEHAVIOUR_SHA256,
        },
        "expected": schema.expected_catalog_audit(before, delta),
        "postgresql_rehearsal_sha256": hashlib.sha256(
            schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA),
        ).hexdigest(),
        "recovery_policy": schema.RECOVERY_POLICY.copy(),
    }


def test_preparation_sentinel_never_becomes_deployment_evidence(monkeypatch):
    monkeypatch.setattr(schema, "DELTA_SHA256", "0" * 64)
    schema.validate_candidate(ROOT, require_delta=False)
    with pytest.raises(ValueError, match="not been frozen"):
        schema.validate_candidate(ROOT)
    with pytest.raises(ValueError, match="not been frozen"):
        schema.rehearsal_evidence(release_sha=NEW_SHA, active_sha=OLD_SHA)
    with pytest.raises(ValueError, match="not been frozen"):
        schema.validate_disclosure({}, target_sha=NEW_SHA)


def test_exact_candidate_and_disclosure_preserve_behavior_and_recovery(candidate, frozen_delta):
    schema.validate_candidate(candidate)
    value = disclosure(frozen_delta)
    assert schema.validate_disclosure(value, target_sha=NEW_SHA) == value
    assert value["starting"]["behaviour_fingerprint"] == value["expected"]["behaviour_fingerprint"]
    assert schema.BEHAVIOUR_SHA256 == community_schema.BEHAVIOUR_SHA256
    assert value["recovery_policy"] == community_schema.RECOVERY_POLICY
    assert all(
        value["starting"][name] != value["expected"][name]
        for name in schema.FINGERPRINT_FIELDS if name != "behaviour_fingerprint"
    )


@pytest.mark.parametrize("name", list(schema.INPUT_HASHES) + list(schema.PREREQUISITE_HASHES))
def test_modified_migration_or_prerequisite_bytes_are_rejected(candidate, name):
    path = candidate / name
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    with pytest.raises(ValueError, match="frozen hash"):
        schema.validate_candidate(candidate)


def test_symlinked_candidate_input_is_rejected(candidate):
    name = next(iter(schema.INPUT_HASHES))
    target = candidate / name
    target.unlink()
    target.symlink_to(ROOT / name)
    with pytest.raises(ValueError, match="frozen hash"):
        schema.validate_candidate(candidate)


@pytest.mark.parametrize("field", ["format_version", "postgres_version", *schema.FLAGS])
def test_truthy_values_cannot_replace_typed_rehearsal_proof(frozen_delta, field):
    proof = schema.rehearsal_evidence(release_sha=NEW_SHA, active_sha=OLD_SHA)
    proof[field] = True if field in {"format_version", "postgres_version"} else 1
    with pytest.raises(ValueError, match="evidence"):
        schema.validate_rehearsal_evidence(proof, release_sha=NEW_SHA, active_sha=OLD_SHA)


def test_discovery_report_is_preparation_only_and_cannot_be_packaged_as_proof(frozen_delta):
    args = SimpleNamespace(release_sha=NEW_SHA, active_sha=OLD_SHA)
    report = rehearsal.discovery_report(args=args, delta=frozen_delta)
    assert report["purpose"] == "preparation-only-discovery"
    assert report["deployment_proof"] is False
    assert report["delta"] == frozen_delta
    with pytest.raises(ValueError, match="evidence"):
        schema.validate_rehearsal_evidence(report, release_sha=NEW_SHA, active_sha=OLD_SHA)


@pytest.mark.parametrize("mutation", [
    "scope", "active_release", "behavior", "unchanged_schema", "recovery", "recovery_type", "proof",
])
def test_disclosure_tampering_is_rejected(frozen_delta, mutation):
    value = disclosure(frozen_delta)
    if mutation == "scope":
        value["input_hashes"] = {}
    elif mutation == "active_release":
        value["active_sha"] = NEW_SHA
    elif mutation == "behavior":
        value["expected"]["behaviour_fingerprint"] = "b" * 64
    elif mutation == "unchanged_schema":
        value["expected"]["schema_fingerprint"] = value["starting"]["schema_fingerprint"]
    elif mutation == "recovery":
        value["recovery_policy"]["rpo_seconds"] = 60
    elif mutation == "recovery_type":
        value["recovery_policy"]["isolated"] = 1
    else:
        value["postgresql_rehearsal_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="Community proof|community proof"):
        schema.validate_disclosure(value, target_sha=NEW_SHA)


def test_packaged_proof_is_digest_and_release_bound(candidate, frozen_delta):
    value = disclosure(frozen_delta)
    path = candidate / schema.EVIDENCE_PATH
    path.write_bytes(schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA))
    schema.validate_build_evidence(candidate, value)
    path.write_bytes(schema.evidence_bytes(release_sha="3" * 40, active_sha=OLD_SHA))
    with pytest.raises(ValueError, match="digest"):
        schema.validate_build_evidence(candidate, value)
    path.unlink()
    path.symlink_to(candidate / schema.DELTA_PATH)
    with pytest.raises(ValueError, match="Invalid packaged"):
        schema.validate_build_evidence(candidate, value)


@pytest.mark.parametrize("mutation", [
    "privileges", "extension", "view", "unrelated_column", "existing_index", "remove_table",
    "mohs_type", "added_default", "missing_table", "extra_old_column",
])
def test_unsafe_or_expanded_catalog_delta_is_rejected(mutation):
    delta = synthetic_delta()
    if mutation == "privileges":
        delta["grants"] = [{"role": "public", "permission": "all"}]
    elif mutation == "extension":
        delta["add"]["extensions"].append({"name": "unreviewed", "version": "1"})
    elif mutation == "view":
        delta["add"]["tables"][0]["kind"] = "v"
    elif mutation == "unrelated_column":
        delta["add"]["columns"][0]["table"] = "users_user"
    elif mutation == "existing_index":
        delta["add"]["indexes"].append({
            "schema": "public", "table": schema.TABLE, "name": "unreviewed",
            "definition": "CREATE INDEX unreviewed ON pages_communityproblem (title)",
        })
    elif mutation == "remove_table":
        delta["remove"]["tables"].append({"schema": "public", "table": schema.TABLE, "kind": "r"})
    elif mutation == "mohs_type":
        next(row for row in delta["add"]["columns"] if row["column"] == "mohs")["type"] = "integer"
    elif mutation == "added_default":
        next(row for row in delta["add"]["columns"] if row["column"] == "public_hint")["default"] = "'leak'"
    elif mutation == "missing_table":
        delta["add"]["tables"].pop()
    else:
        delta["add"]["columns"].append({
            "schema": "public", "table": schema.TABLE, "position": 8, "column": "status",
            "type": "text", "nullable": True, "default": None, "collation": None,
        })
    with pytest.raises(ValueError, match="(?i)community proof"):
        schema.validate_delta_shape(delta)


def test_catalog_delta_round_trip_preserves_all_old_objects(frozen_delta):
    before = starting_audit()["catalog_snapshot"]
    after = {
        field: [
            *[row for row in before[field] if row not in frozen_delta["remove"][field]],
            *frozen_delta["add"][field],
        ] for field in before
    }
    assert schema.catalog_delta(before, after) == frozen_delta
    assert normalize_schema_snapshot(before) == normalize_schema_snapshot(
        starting_audit()["catalog_snapshot"],
    )
    audit = starting_audit()
    original = copy.deepcopy(audit)
    expected = schema.expected_catalog_audit(audit, frozen_delta)
    assert audit == original
    assert expected["migration_fingerprint"] == migration_state([
        *audit["migration_rows"], ["pages", schema.MIGRATIONS[0]],
    ])["fingerprint"]


@pytest.mark.parametrize("mutation", ["version", "state", "behavior", "prerequisite", "already_applied", "position"])
def test_invalid_starting_catalog_or_column_order_is_rejected(frozen_delta, mutation):
    start, delta = starting_audit(), copy.deepcopy(frozen_delta)
    if mutation == "version":
        start["server_version_num"] = 170008
    elif mutation == "state":
        start["state"]["role"] = "unexpected"
    elif mutation == "behavior":
        start["behaviour_fingerprint"] = "b" * 64
    elif mutation == "prerequisite":
        start["migration_rows"].pop()
    elif mutation == "already_applied":
        start["migration_rows"].append(["pages", schema.MIGRATIONS[0]])
    else:
        next(row for row in delta["add"]["columns"] if row["column"] == "public_hint")["position"] += 1
    with pytest.raises(ValueError, match="(?i)community proof"):
        schema.expected_catalog_audit(start, delta)


def _fake_executor(plan=None, applied=None):
    operations = []
    for kind, model, name, constraint in schema.OPERATION_SIGNATURES:
        operation = type(kind, (), {})()
        operation.model_name, operation.name = model, name
        operation.constraint = SimpleNamespace(name=constraint) if constraint else None
        operations.append(operation)
    migration = SimpleNamespace(app_label="pages", name=schema.MIGRATIONS[0], operations=operations)
    return SimpleNamespace(
        loader=SimpleNamespace(
            applied_migrations=set(schema.PREREQUISITE_MIGRATIONS) if applied is None else applied,
            graph=SimpleNamespace(leaf_nodes=lambda: [("pages", schema.MIGRATIONS[0])]),
        ),
        migration_plan=lambda targets: [(migration, False)] if plan is None else plan,
    )


@pytest.mark.django_db
def test_runtime_plan_accepts_only_the_literal_model_operations(monkeypatch, settings):
    executor_module = importlib.import_module("django.db.migrations.executor")
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = settings.SOLUTION_AI_REVIEW_ENABLED = False
    fake = _fake_executor()
    monkeypatch.setattr(executor_module, "MigrationExecutor", lambda connection: fake)
    exec(schema.PLAN_CHECK, {})
    fake.migration_plan = lambda targets: [
        (SimpleNamespace(app_label="pages", name="0046_unrelated", operations=[]), False),
    ]
    with pytest.raises(RuntimeError, match="frozen community proof plan"):
        exec(schema.PLAN_CHECK, {})
    fake.migration_plan = lambda targets: [
        *_fake_executor().migration_plan(targets),
        (SimpleNamespace(app_label="solutions", name="0011_extra", operations=[]), False),
    ]
    with pytest.raises(RuntimeError, match="frozen community proof plan"):
        exec(schema.PLAN_CHECK, {})


@pytest.mark.django_db
def test_runtime_plan_requires_applied_prerequisites_and_both_ai_flags_off(monkeypatch, settings):
    executor_module = importlib.import_module("django.db.migrations.executor")
    fake = _fake_executor(applied=set())
    monkeypatch.setattr(executor_module, "MigrationExecutor", lambda connection: fake)
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = settings.SOLUTION_AI_REVIEW_ENABLED = False
    with pytest.raises(RuntimeError, match="prerequisites"):
        exec(schema.PLAN_CHECK, {})
    fake.loader.applied_migrations = set(schema.PREREQUISITE_MIGRATIONS)
    for name in ("PROBLEM_STATEMENT_AI_REVIEW_ENABLED", "SOLUTION_AI_REVIEW_ENABLED"):
        setattr(settings, name, True)
        with pytest.raises(RuntimeError, match="Both AI"):
            exec(schema.PLAN_CHECK, {})
        setattr(settings, name, False)


def test_migration_source_has_exact_operation_identities():
    migration = importlib.import_module("inspinia.pages.migrations." + schema.MIGRATIONS[0])
    actual = tuple((
        type(operation).__name__, getattr(operation, "model_name", None),
        getattr(operation, "name", None), getattr(getattr(operation, "constraint", None), "name", None),
    ) for operation in migration.Migration.operations)
    assert actual == schema.OPERATION_SIGNATURES


def test_migration_recorder_changes_exactly_once():
    before = ([(10, "pages", "0044_learning_page_activity", "before")], 10)
    after = ([*before[0], (11, "pages", schema.MIGRATIONS[0], "after")], 11)
    rehearsal.validate_migration_record(before, after)
    with pytest.raises(ValueError, match="one approved record"):
        rehearsal.validate_migration_record(before, (after[0], 12))
    with pytest.raises(ValueError, match="one approved record"):
        rehearsal.validate_migration_record(before, (after[0] + [(12, "pages", "extra", "extra")], 12))


def test_old_code_smoke_is_database_read_only_and_discovery_cannot_use_sqlite():
    command = schema.smoke_command()
    assert "SET TRANSACTION READ ONLY" in command
    assert "migrate" not in command
    assert ".save(" not in command
    assert ".create(" not in command
    connection = SimpleNamespace(vendor="sqlite")
    with pytest.raises(ValueError, match="pinned PostgreSQL"):
        rehearsal.rehearse(connection, SimpleNamespace(discover_delta=True))


@pytest.mark.django_db
def test_post_migration_ai_check_refuses_any_funded_or_enabled_policy(settings):
    from inspinia.pages.community_models import StatementReviewPolicy

    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = settings.SOLUTION_AI_REVIEW_ENABLED = False
    exec(schema.AI_OFF_CHECK, {})
    policy = StatementReviewPolicy.objects.create(enabled=False, request_budget_micros=1)
    with pytest.raises(RuntimeError, match="disabled and unfunded"):
        exec(schema.AI_OFF_CHECK, {})
    policy.request_budget_micros, policy.enabled = 0, True
    policy.save()
    with pytest.raises(RuntimeError, match="disabled and unfunded"):
        exec(schema.AI_OFF_CHECK, {})


def test_discovery_target_is_validated_before_any_database_catalog_read(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("DATABASE_URL", rehearsal.REHEARSAL_URL)
    connection = SimpleNamespace(vendor="postgresql", settings_dict=rehearsal.REHEARSAL_DATABASE.copy())
    with pytest.raises(ValueError, match="exact isolated Actions"):
        rehearsal.rehearse(connection, SimpleNamespace(discover_delta=True))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    connection.settings_dict["HOST"] = "example.invalid"
    with pytest.raises(ValueError, match="exact isolated Actions"):
        rehearsal.rehearse(connection, SimpleNamespace(discover_delta=True))


def test_privilege_audit_excludes_non_grantable_index_relations():
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, parameters=None):
            calls.append((query, parameters))

        def fetchall(self):
            return []

    connection = SimpleNamespace(cursor=Cursor)
    assert rehearsal.privilege_snapshot(connection) == {
        "roles": [], "memberships": [], "schemas": [], "defaults": [],
        "relations": [], "columns": [], "functions": [],
    }
    relations = next(query for query, _ in calls if "c.relacl" in query)
    columns = next(query for query, _ in calls if "a.attacl" in query)
    assert "c.relkind IN ('r','p','S','v','m','f')" in relations
    assert "c.relkind IN ('r','p','v','m','f')" in columns
    assert "inherit_option,set_option" in next(query for query, _ in calls if "pg_auth_members" in query)
    for query, parameters in calls:
        if "c.relacl" in query or "a.attacl" in query:
            assert set(parameters[0]) == {*schema.TABLES, "pages_problempublication_id_seq"}
