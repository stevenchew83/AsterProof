"""Local-only frozen evaluation schema and real synthetic SQLite preservation smoke."""
# ruff: noqa: PLR2004

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import evaluation_schema as schema

ROOT = Path(__file__).resolve().parents[3]


def test_exact_migration_bytes_and_create_only_shape_are_frozen(tmp_path):
    schema.validate_candidate(ROOT)
    target = tmp_path / schema.MIGRATION_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes((ROOT / schema.MIGRATION_PATH).read_bytes())
    baseline = target.parent / f"{schema.BASELINE_NAME}.py"
    baseline.write_bytes((ROOT / schema.MIGRATION_PATH.parent / baseline.name).read_bytes())
    schema.validate_candidate(tmp_path)
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(schema.EvaluationSchemaError, match="Migration bytes"):
        schema.validate_candidate(tmp_path)


def test_only_exact_createmodel_plan_is_accepted():
    operation_type = type("CreateModel", (), {})
    operations = []
    for name in schema.MODELS:
        operation = operation_type()
        operation.name = name
        operations.append(operation)
    migration = SimpleNamespace(app_label="solutions", name=schema.MIGRATION_NAME, operations=operations)
    schema.validate_plan([(migration, False)])
    with pytest.raises(schema.EvaluationSchemaError):
        schema.validate_plan([(migration, True)])
    migration.operations.append(SimpleNamespace(name="ExistingModel"))
    with pytest.raises(schema.EvaluationSchemaError):
        schema.validate_plan([(migration, False)])


@pytest.mark.parametrize("database", ["db.sqlite3", "/application/production.sqlite3", ":memory:"])
def test_existing_sqlite_targets_cannot_be_rehearsal_databases(database):
    connection = SimpleNamespace(vendor="sqlite", settings_dict={"NAME": database})
    with pytest.raises(schema.EvaluationSchemaError, match="scratch database"):
        schema.validate_connection(connection)


def test_arbitrary_postgres_target_is_rejected_before_connecting(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    connection = SimpleNamespace(vendor="postgresql", settings_dict={"HOST": "production.invalid"})
    with pytest.raises(schema.EvaluationSchemaError, match="disposable Actions"):
        schema.validate_connection(connection)


def test_sqlite_cli_preserves_seeded_legacy_data_but_never_claims_authoritative_readiness(tmp_path):
    report = tmp_path / "evaluation-schema-smoke.json"
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("OPENAI", "AWS_", "AZURE_", "DATABASE_URL", "DJANGO_"))}
    result = subprocess.run(  # noqa: S603 - fixed local module and temporary artifact path, no shell
        [sys.executable, "-m", "scripts.deployment.evaluation_schema", "--sqlite", "--output", str(report)],
        cwd=ROOT, env=environment, check=True, text=True, capture_output=True, timeout=120,
    )
    assert result.returncode == 0
    value = json.loads(report.read_text())
    assert value["verification_status"] == "local_sqlite_smoke_passed"
    assert value["authoritative_postgresql_rehearsal"] is False
    assert value["engineering_readiness_established"] is False
    assert value["production_migration_authorized"] is False
    assert value["model_readiness"] is False
    assert value["new_tables"] == sorted(schema.TABLES)
    for field in (
        "existing_records_unchanged", "existing_columns_unchanged", "existing_constraints_and_foreign_keys_unchanged",
        "existing_triggers_unchanged", "existing_sequences_unchanged", "foreign_keys_valid",
        "new_tables_empty", "ai_disabled_and_unfunded",
    ):
        assert value[field] is True
    assert len(report.read_bytes()) <= schema.MAX_EVIDENCE_BYTES


def test_ci_has_a_separate_evaluation_rehearsal_without_widening_document_allowance():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "rehearsal=scripts.deployment.evaluation_schema" in workflow
    selected = (
        "scripts/deployment/evaluation_schema.py inspinia/solutions/migrations/0010_offline_evaluation_contract.py"
    )
    assert selected in workflow
    assert "rehearsal=scripts.deployment.solution_document_schema_rehearsal" in workflow
    document = (ROOT / "scripts/deployment/solution_document_schema.py").read_text()
    assert schema.MIGRATION_NAME not in document
