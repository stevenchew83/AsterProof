"""The deployer admits one frozen evidence column and revision-bound proof."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.deployment import additive_schema
from scripts.deployment import library_ai_schema as schema
from scripts.deployment.concept_schema import ConceptSchemaError


def test_frozen_migration_and_column():
    schema.validate_candidate(Path.cwd())
    before = {
        "tables": [{"schema": "public", "table": schema.TABLE, "kind": "r"}],
        "columns": [], "constraints": [], "indexes": [], "extensions": [],
    }
    assert schema.add_column(before) == {**before, "columns": [schema.COLUMN]}
    with pytest.raises(ConceptSchemaError, match="conflicts"):
        schema.add_column({**before, "columns": [schema.COLUMN]})


def test_disclosure_requires_the_exact_rehearsal_proof(tmp_path):
    active, target = "a" * 40, "b" * 40
    evidence = schema.build_evidence(target, active)
    proof = tmp_path / schema.EVIDENCE_PATH
    proof.write_text(json.dumps(evidence))
    disclosure = {
        "format_version": 1,
        "active_sha": active,
        "target_sha": target,
        "migration": schema.MIGRATION,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "starting": dict.fromkeys(schema.FINGERPRINT_FIELDS, "1" * 64),
        "expected": dict.fromkeys(schema.FINGERPRINT_FIELDS, "2" * 64),
        "postgresql_rehearsal_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
        "compatibility_smoke_sha256": schema.COMPATIBILITY_SMOKE_SHA256,
    }
    assert additive_schema.validate_disclosure(disclosure, target_sha=target) == disclosure
    schema.validate_build_evidence(tmp_path, disclosure)
    proof.write_text(json.dumps({**evidence, "active_revision_smoke_passed": False}))
    disclosure["postgresql_rehearsal_sha256"] = hashlib.sha256(proof.read_bytes()).hexdigest()
    with pytest.raises(ConceptSchemaError, match="does not match"):
        schema.validate_build_evidence(tmp_path, disclosure)
