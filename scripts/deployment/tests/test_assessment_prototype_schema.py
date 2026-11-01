# ruff: noqa: EM101, PLR2004, S603, SLF001, TRY003
"""The bounded assessment_prototype allowance is exact, hash-bound, and data-preserving."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts.deployment import additive_schema
from scripts.deployment import assessment_prototype_schema as schema
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


def test_expected_assessment_prototype_delta_is_frozen_and_checked_by_postgresql_rehearsal():
    delta = json.loads((Path(__file__).parent / "fixtures/assessment-prototype-schema-delta.json").read_text())
    assert schema_state(delta)["fingerprint"] == schema.DELTA_SHA256
    assert {row["table"] for row in delta["tables"]} == schema.TABLES
    assert len(schema.TABLES) == 4
    assert not delta["extensions"]


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
        "existing_schema_unchanged": True,
        "source_fixture_unchanged": True,
        "active_revision_smoke_passed": True,
        "existing_records_unchanged": True,
        "existing_sequences_unchanged": True,
        "new_evidence_tables_empty": True,
        "existing_trigger_definitions_unchanged": True,
        "ai_disabled_and_unfunded": True,
        "synthetic_prototype_disabled": True,
    }


def test_router_preserves_existing_allowances_and_only_admits_exact_assessment_prototype_disclosure():
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


@pytest.mark.parametrize("change", ["none", "missing_second", "extra", "reordered"])
def test_production_disclosure_accepts_only_the_complete_frozen_two_migration_bundle(tmp_path, monkeypatch, change):
    workflow = yaml.safe_load((ROOT / ".github/workflows/production-deploy.yml").read_text())
    step = next(
        step
        for step in workflow["jobs"]["disclose"]["steps"]
        if step["name"] == "Derive reviewed migration disclosure"
    )
    snippet = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    migrations = [
        {"migration": f"{app}.{name}", "classification": "backward-compatible-schema"}
        for app, name in schema.MIGRATIONS
    ]
    if change == "missing_second":
        migrations.pop()
    elif change == "extra":
        migrations.append({"migration": "solutions.0013_unapproved", "classification": "backward-compatible-schema"})
    elif change == "reordered":
        migrations.reverse()
    path = tmp_path / "disclosure.json"
    path.write_text(
        json.dumps(
            {
                "active_sha": OLD_SHA,
                "target_sha": NEW_SHA,
                "classification": "backward-compatible-schema",
                "migrations": migrations,
            }
        )
    )
    monkeypatch.setenv("SCHEMA_DISCLOSURE", json.dumps(disclosure()))
    monkeypatch.setattr(sys, "argv", ["disclosure", str(path)])
    command = compile(snippet, "<production-disclosure>", "exec", optimize=2)
    if change == "none":
        exec(command, {})  # noqa: S102 - Execute the exact checked-in workflow's Python contract.
        assert json.loads(path.read_text())["schema_disclosure"] == disclosure()
    else:
        with pytest.raises(SystemExit, match="outside the approved migrations"):
            exec(command, {})  # noqa: S102 - Execute the exact checked-in workflow's Python contract.


def test_assessment_prototype_schema_is_bound_to_the_oidc_request_and_cannot_be_used_for_rollback():
    raw = _envelope(release_sha=NEW_SHA, workflow_sha=NEW_SHA, migration_class="backward-compatible-schema")
    raw["schema_disclosure"] = disclosure()
    first = OperationEnvelope.from_dict(raw)
    raw = copy.deepcopy(raw)
    raw["schema_disclosure"]["expected"]["schema_fingerprint"] = "7" * 64
    assert envelope_audience(first.public_dict()) != envelope_audience(OperationEnvelope.from_dict(raw).public_dict())
    for change in ({"migration_class": "none"}, {"operation": "rollback"}, {"schema_disclosure": None}):
        with pytest.raises(ProtocolError):
            OperationEnvelope.from_dict({**raw, **change})


def test_assessment_prototype_migration_bytes_are_frozen_and_symlinks_rejected(tmp_path):
    path = tmp_path / schema.MIGRATION_PATH
    path.parent.mkdir(parents=True)
    content = (ROOT / schema.MIGRATION_PATH).read_bytes()
    assert hashlib.sha256(content).hexdigest() == schema.MIGRATION_SHA256
    path.write_bytes(content)
    (tmp_path / schema.SECOND_MIGRATION_PATH).write_bytes((ROOT / schema.SECOND_MIGRATION_PATH).read_bytes())
    for name in schema.PRIOR_MIGRATIONS:
        (path.parent / name).write_bytes((ROOT / schema.MIGRATION_PATH.parent / name).read_bytes())
    schema.validate_candidate(tmp_path)
    path.write_bytes(content + b"\n")
    with pytest.raises(schema.AssessmentPrototypeSchemaError):
        schema.validate_candidate(tmp_path)
    path.unlink()
    path.symlink_to(ROOT / schema.MIGRATION_PATH)
    with pytest.raises(schema.AssessmentPrototypeSchemaError):
        schema.validate_candidate(tmp_path)


@pytest.mark.parametrize(
    "field",
    [
        "existing_records_unchanged",
        "existing_sequences_unchanged",
        "new_evidence_tables_empty",
        "existing_trigger_definitions_unchanged",
        "synthetic_prototype_disabled",
        "ai_disabled_and_unfunded",
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
    with pytest.raises(schema.AssessmentPrototypeSchemaError):
        schema.validate_build_evidence(tmp_path, bound)


@pytest.mark.parametrize("change", ["none", "extra", "renamed", "backwards", "funded"])
def test_assessment_prototype_plan_guard_remains_literal_under_optimized_python(monkeypatch, change):
    plan = [
        (SimpleNamespace(app_label=app, name=name, operations=[type(kind, (), {})() for kind in kinds]), False)
        for (app, name), kinds in zip(schema.MIGRATIONS, schema.OPERATION_SEQUENCES, strict=True)
    ]
    operations = plan[0][0].operations
    if change == "extra":
        plan.append((SimpleNamespace(app_label="users", name="unapproved", operations=operations), False))
    executor = SimpleNamespace(
        loader=SimpleNamespace(
            graph=SimpleNamespace(
                leaf_nodes=lambda: [("solutions", schema.MIGRATION_NAME)],
            ),
        ),
        migration_plan=lambda targets: plan,
    )
    if change == "renamed":
        operations[-1] = type("AlterField", (), {})()
    if change == "backwards":
        plan[0] = (plan[0][0], True)
    from django.conf import settings

    monkeypatch.setattr(settings, "SOLUTION_AI_REVIEW_ENABLED", False)
    monkeypatch.setattr(settings, "PROBLEM_STATEMENT_AI_REVIEW_ENABLED", False)
    monkeypatch.setattr(settings, "SYNTHETIC_REVIEW_PROTOTYPE_ENABLED", False)
    monkeypatch.setattr(
        "inspinia.solutions.models.SolutionReviewPolicy.objects.filter",
        lambda *args, **kwargs: SimpleNamespace(exists=lambda: change == "funded"),
    )
    monkeypatch.setattr("django.db.migrations.executor.MigrationExecutor", lambda connection: executor)
    command = compile(schema.PLAN_CHECK, "<frozen-website-plan>", "exec", optimize=2)
    if change != "none":
        with pytest.raises(RuntimeError, match="Unapproved|disabled and unfunded"):
            exec(command, {})  # noqa: S102 - exact fixed plan guard
    else:
        exec(command, {})  # noqa: S102 - exact fixed plan guard


class AssessmentPrototypeBackend(SchemaBackend):
    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        path = destination / schema.MIGRATION_PATH
        path.parent.mkdir(parents=True)
        path.write_bytes((ROOT / schema.MIGRATION_PATH).read_bytes())
        (destination / schema.SECOND_MIGRATION_PATH).write_bytes((ROOT / schema.SECOND_MIGRATION_PATH).read_bytes())
        (destination / schema.EVIDENCE_PATH).write_bytes(evidence_bytes(build_evidence()))
        for name in schema.PRIOR_MIGRATIONS:
            (path.parent / name).write_bytes((ROOT / schema.MIGRATION_PATH.parent / name).read_bytes())

    def check_assessment_prototype_schema(self, contract, release):
        if self.fail_at == "candidate":
            raise schema.AssessmentPrototypeSchemaError("Invalid assessment_prototype candidate")
        schema.validate_candidate(release)

    def migrate_assessment_prototype_schema(self, contract, release):
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
def test_assessment_prototype_worker_never_retries_failed_migrations(tmp_path, failure, state, migrated):
    contract = _contract(tmp_path)
    _seed(contract, migration_class="backward-compatible-schema")
    path = contract.registry_dir / "requests/42.json"
    request = read_json(path)
    request["schema_disclosure"] = disclosure()
    atomic_write_json(path, request)
    backend = AssessmentPrototypeBackend(fail_at=failure)
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


def test_assessment_prototype_migration_retains_lock_and_statement_bounds(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("scripts.deployment.operation_worker.subprocess.run", lambda args, **kwargs: seen.append(args))
    WorkerBackend().migrate_assessment_prototype_schema(_contract(tmp_path), tmp_path / "candidate")
    assert "--setenv=PGOPTIONS=-c lock_timeout=2s -c statement_timeout=30s" in seen[0]
    assert seen[0][-3:] == ["shell", "--command", schema.MIGRATION_APPLY]


def starting_audit():
    from scripts.deployment.schema_fingerprint import canonical_json
    from scripts.deployment.schema_fingerprint import migration_state

    snapshot = {field: [] for field in ("tables", "columns", "constraints", "indexes", "extensions")}
    snapshot["tables"] = [{"schema": "public", "table": "solutions_solutionrevision", "kind": "r"}]
    migrations = [
        ["solutions", "0009_problemsolution_edit_version_solutionreviewpolicy_and_more"],
        ["solutions", "0010_offline_evaluation_contract"],
    ]
    state = {"schema": schema_state(snapshot), "migration": migration_state(migrations)}
    return {
        "server_version_num": schema.POSTGRES_VERSION,
        "catalog_snapshot": snapshot,
        "migration_rows": migrations,
        "state": state,
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
    }


def frozen_delta():
    return json.loads((Path(__file__).parent / "fixtures/assessment-prototype-schema-delta.json").read_text())


def test_expected_audit_adds_only_four_frozen_tables_and_two_migration_records():
    from scripts.deployment.schema_fingerprint import migration_state

    start = starting_audit()
    unchanged = copy.deepcopy(start)
    result = schema.expected_catalog_audit(start, frozen_delta())
    assert (
        result["migration_fingerprint"]
        == migration_state(
            [
                *start["migration_rows"],
                *[list(migration) for migration in schema.MIGRATIONS],
            ],
        )["fingerprint"]
    )
    assert result["schema_fingerprint"] != start["state"]["schema"]["fingerprint"]
    assert start == unchanged


@pytest.mark.parametrize("change", ["new_column", "default", "nullable", "table", "position", "index"])
def test_expected_audit_rejects_any_different_catalog_delta(change):
    delta = frozen_delta()
    if change == "new_column":
        delta["columns"][0]["column"] = "unapproved"
    elif change == "index":
        delta["indexes"] = [
            {
                "schema": "public",
                "table": sorted(schema.TABLES)[0],
                "name": "unapproved",
                "definition": "CREATE INDEX x",
            },
        ]
    else:
        delta["columns"][0][change] = {
            "default": "false",
            "nullable": True,
            "table": "users_user",
            "position": 99,
        }[change]
    with pytest.raises(schema.AssessmentPrototypeSchemaError):
        schema.expected_catalog_audit(starting_audit(), delta)


@pytest.mark.parametrize("change", ["version", "fingerprint", "missing_table", "missing_prior", "recorded"])
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
            start["state"]["schema"] = schema_state(start["catalog_snapshot"])
        elif change == "missing_prior":
            start["migration_rows"].clear()
            start["state"]["migration"] = migration_state(start["migration_rows"])
        else:
            start["migration_rows"].append(["solutions", schema.MIGRATION_NAME])
            start["state"]["migration"] = migration_state(start["migration_rows"])
        start["state_fingerprint"] = hashlib.sha256(canonical_json(start["state"])).hexdigest()
    with pytest.raises(schema.AssessmentPrototypeSchemaError):
        schema.expected_catalog_audit(start, frozen_delta())


@pytest.mark.parametrize(
    "flag",
    ["SOLUTION_AI_REVIEW_ENABLED", "PROBLEM_STATEMENT_AI_REVIEW_ENABLED", "SYNTHETIC_REVIEW_PROTOTYPE_ENABLED"],
)
def test_plan_refuses_any_enabled_ai_pipeline_before_inspecting_or_applying_migrations(monkeypatch, flag):
    from django.conf import settings

    monkeypatch.setattr(settings, flag, True)
    with pytest.raises(RuntimeError, match="AI must remain disabled"):
        exec(compile(schema.PLAN_CHECK, "<offline-plan>", "exec", optimize=2), {})  # noqa: S102


def test_production_rehearsal_route_is_separate_from_completed_document_allowance():
    from scripts.deployment.assessment_prototype_schema_rehearsal import run
    from scripts.deployment.schema_rehearsal import _approved_rehearsal

    assert _approved_rehearsal(schema.MIGRATION) is run
    assert schema.MIGRATION_NAME not in (ROOT / "scripts/deployment/solution_document_schema.py").read_text()


def test_evaluation_migration_has_exact_compatible_classification_without_activation_authority():
    from scripts.deployment.migration_plan import load_registry

    entry = load_registry(ROOT / "deployment/migration-classifications.yml")[schema.MIGRATION]
    assert entry["classification"] == "backward-compatible-schema"
    assert entry["code_rollback_permitted"] is True
    assert entry["recovery_required"] is False
    assert "student_statement_ai_and_synthetic_prototype_disabled" in entry["data_preconditions"]
    assert "no_provider_or_worker_activation" in entry["data_preconditions"]
