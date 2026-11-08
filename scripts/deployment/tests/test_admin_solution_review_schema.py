"""The release guard admits only the reviewed migration, schema, and reader."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.deployment import additive_schema
from scripts.deployment import admin_solution_review_schema as schema
from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.migration_plan import load_registry
from scripts.deployment.schema_fingerprint import schema_state

ROOT = Path(__file__).resolve().parents[3]
CANDIDATE = "c" * 40
BASELINE = "b" * 40


def test_only_two_new_tables_and_exact_migration_are_registered():
    schema.validate_candidate(ROOT)
    fixture = Path(__file__).with_name("fixtures") / "admin-solution-review-schema-delta.json"
    delta = json.loads(fixture.read_text())
    assert schema_state(delta)["fingerprint"] == schema.DELTA_SHA256
    assert {row["table"] for row in delta["tables"]} == schema.TABLES
    assert not delta["extensions"]
    assert load_registry(ROOT / "deployment/migration-classifications.yml")[schema.MIGRATION]["classification"] == (
        "backward-compatible-schema"
    )


def test_disclosure_and_attested_evidence_reject_mutated_inputs(tmp_path):
    evidence = schema.build_evidence(source_sha=CANDIDATE, active_sha=BASELINE)
    evidence_path = tmp_path / schema.EVIDENCE_PATH
    content = json.dumps(evidence).encode()
    evidence_path.write_bytes(content)
    disclosure = {
        "format_version": 1,
        "active_sha": BASELINE,
        "target_sha": CANDIDATE,
        "migration": schema.MIGRATION,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "starting": dict.fromkeys(schema.FINGERPRINT_FIELDS, "a" * 64),
        "expected": dict.fromkeys(schema.FINGERPRINT_FIELDS, "b" * 64),
        "postgresql_rehearsal_sha256": hashlib.sha256(content).hexdigest(),
        "compatibility_smoke_sha256": schema.COMPATIBILITY_SMOKE_SHA256,
    }
    assert additive_schema.validate_disclosure(disclosure, target_sha=CANDIDATE) == disclosure
    schema.validate_build_evidence(tmp_path, disclosure)
    with pytest.raises(ConceptSchemaError, match="frozen migration"):
        additive_schema.validate_disclosure(
            {**disclosure, "migration_file_sha256": "0" * 64}, target_sha=CANDIDATE,
        )
    altered = json.dumps({**evidence, "existing_records_unchanged": False}).encode()
    evidence_path.write_bytes(altered)
    with pytest.raises(ConceptSchemaError, match="evidence digest"):
        schema.validate_build_evidence(tmp_path, disclosure)
    with pytest.raises(ConceptSchemaError, match="preservation checks"):
        schema.validate_build_evidence(
            tmp_path, {**disclosure, "postgresql_rehearsal_sha256": hashlib.sha256(altered).hexdigest()},
        )
