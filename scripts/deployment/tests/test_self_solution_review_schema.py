"""Verify the quota migration allowance and the evidence required for dispatch."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.deployment import additive_schema
from scripts.deployment import self_solution_review_schema as schema
from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.schema_fingerprint import schema_state


def test_frozen_migration_and_quota_table_delta(tmp_path):
    root = Path.cwd()
    successor = Path("inspinia/solutions/migrations/0016_admin_review_takedown.py")
    later_registration = Path("inspinia/users/migrations/0010_public_registration.py")
    multiple_solutions = Path("inspinia/solutions/migrations/0017_multiple_problem_solutions.py")
    for migration in root.glob("inspinia/**/migrations/*"):
        relative = migration.relative_to(root)
        if migration.suffix in {".py", ".json"} and relative not in {successor, later_registration, multiple_solutions}:
            staged = tmp_path / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(migration.read_bytes())
    schema.validate_candidate(tmp_path)
    (tmp_path / successor).write_bytes((root / successor).read_bytes())
    with pytest.raises(ConceptSchemaError, match="Prior migration sources"):
        schema.validate_candidate(tmp_path)
    fixture = Path(__file__).parent / "fixtures/self-solution-review-schema-delta.json"
    delta = json.loads(fixture.read_text())
    assert {table["table"] for table in delta["tables"]} == schema.TABLES
    assert not delta["extensions"]
    assert schema_state(delta)["fingerprint"] == schema.DELTA_SHA256


def test_disclosure_requires_evidence_that_author_requests_were_disabled(tmp_path):
    active, candidate = "a" * 40, "b" * 40
    evidence = tmp_path / schema.EVIDENCE_PATH
    record = schema.build_evidence(candidate, active)
    evidence.write_text(json.dumps(record))
    disclosure = {
        "format_version": 1,
        "active_sha": active,
        "target_sha": candidate,
        "migration": schema.MIGRATION,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "starting": dict.fromkeys(schema.FINGERPRINT_FIELDS, "1" * 64),
        "expected": dict.fromkeys(schema.FINGERPRINT_FIELDS, "2" * 64),
        "postgresql_rehearsal_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        "compatibility_smoke_sha256": schema.COMPATIBILITY_SMOKE_SHA256,
    }
    assert additive_schema.validate_disclosure(disclosure, target_sha=candidate) == disclosure
    schema.validate_build_evidence(tmp_path, disclosure)

    record["self_review_generation_disabled"] = False
    evidence.write_text(json.dumps(record))
    disclosure["postgresql_rehearsal_sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    with pytest.raises(ConceptSchemaError, match="does not match"):
        schema.validate_build_evidence(tmp_path, disclosure)
