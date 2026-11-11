"""Verify the exact review take-down allowance and fail-closed boundaries."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.deployment import additive_schema
from scripts.deployment import admin_review_takedown_schema as schema
from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.solution_forum_schema import FINGERPRINT_FIELDS

FIXTURES = Path(__file__).parent / "fixtures"


def test_frozen_candidate_and_rehearsal_delta(tmp_path):
    root = Path.cwd()
    successor = Path("inspinia/solutions/migrations/0017_multiple_problem_solutions.py")
    registration = Path("inspinia/users/migrations/0010_public_registration.py")
    library_ai = Path("inspinia/pages/migrations/0048_statement_ai_concept_suggestions.py")
    for source in root.glob("inspinia/**/migrations/*"):
        relative = source.relative_to(root)
        if source.suffix in {".py", ".json"} and relative not in {successor, registration, library_ai}:
            staged = tmp_path / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(source.read_bytes())
    schema.validate_candidate(tmp_path)
    (tmp_path / successor).write_bytes((root / successor).read_bytes())
    with pytest.raises(ConceptSchemaError, match="Prior migration sources"):
        schema.validate_candidate(tmp_path)
    delta = json.loads((FIXTURES / "admin-review-takedown-schema-delta.json").read_bytes())
    assert schema_state(delta)["fingerprint"] == schema.DELTA_SHA256
    assert {row["column"] for row in delta["columns"]} == schema.COLUMNS
    assert all(row["nullable"] and row["default"] is None for row in delta["columns"])
    assert [row["type"] for row in delta["constraints"]] == ["f"]
    assert not delta["tables"]
    assert not delta["extensions"]


def test_expected_catalog_appends_only_the_two_columns_and_actor_reference():
    before = json.loads((FIXTURES / "admin-solution-review-schema-delta.json").read_bytes())
    delta = json.loads((FIXTURES / "admin-review-takedown-schema-delta.json").read_bytes())
    rows = [list(schema.PREVIOUS)]
    state = {"schema": schema_state(before), "migration": migration_state(rows)}
    start = {
        "server_version_num": schema.POSTGRES_VERSION,
        "state": state,
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "catalog_snapshot": before,
        "migration_rows": rows,
    }
    expected = schema.expected_catalog_audit(start, delta)
    assert expected["schema_fingerprint"] == schema_state({
        key: before[key] + delta[key] for key in before
    })["fingerprint"]
    assert expected["migration_fingerprint"] == migration_state([
        *rows, ["solutions", schema.MIGRATION_NAME],
    ])["fingerprint"]
    delta["columns"][0]["nullable"] = False
    with pytest.raises(ConceptSchemaError, match="Catalog delta"):
        schema.expected_catalog_audit(start, delta)


def test_disclosure_and_packaged_evidence_are_bound_to_the_exact_release(tmp_path):
    active, target = "a" * 40, "b" * 40
    data = schema.evidence_bytes(target, active)
    path = tmp_path / schema.EVIDENCE_PATH
    path.write_bytes(data)
    disclosure = {
        "format_version": 1,
        "migration": schema.MIGRATION,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "active_sha": active,
        "target_sha": target,
        "starting": dict.fromkeys(FINGERPRINT_FIELDS, "1" * 64),
        "expected": dict.fromkeys(FINGERPRINT_FIELDS, "2" * 64),
        "postgresql_rehearsal_sha256": hashlib.sha256(data).hexdigest(),
        "compatibility_smoke_sha256": schema.COMPATIBILITY_SMOKE_SHA256,
    }
    assert additive_schema.validate_disclosure(disclosure, target_sha=target) == disclosure
    schema.validate_build_evidence(tmp_path, disclosure)
    with pytest.raises(ConceptSchemaError, match="disclosure"):
        additive_schema.validate_disclosure(disclosure, target_sha="c" * 40)
    path.write_bytes(schema.evidence_bytes(target, "c" * 40))
    with pytest.raises(ConceptSchemaError, match="differs"):
        schema.validate_build_evidence(tmp_path, disclosure)
