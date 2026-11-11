"""Study Help admits only its exact disabled additive schema and packaged proof."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.deployment import additive_schema
from scripts.deployment import self_solution_review_schema
from scripts.deployment import study_help_schema as schema
from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.schema_fingerprint import schema_state


def test_study_help_schema_bytes_and_frozen_delta_agree(tmp_path):
    root = Path.cwd()
    successors = {
        self_solution_review_schema.MIGRATION_PATH,
        Path("inspinia/solutions/migrations/0016_admin_review_takedown.py"),
        Path("inspinia/users/migrations/0010_public_registration.py"),
        Path("inspinia/solutions/migrations/0017_multiple_problem_solutions.py"),
        Path("inspinia/pages/migrations/0048_statement_ai_concept_suggestions.py"),
    }
    for migration in root.glob("inspinia/*/migrations/*"):
        relative = migration.relative_to(root)
        if migration.suffix in {".py", ".json"} and relative not in successors:
            staged = tmp_path / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(migration.read_bytes())
    schema.validate_candidate(tmp_path)
    fixture = Path(__file__).parent / "fixtures/study-help-schema-delta.json"
    delta = json.loads(fixture.read_text())
    assert {table["table"] for table in delta["tables"]} == schema.TABLES
    assert not delta["extensions"]
    assert schema_state(delta)["fingerprint"] == schema.DELTA_SHA256
    assert "settings.STUDY_HELP_ENABLED or settings.STUDY_HELP_EVALUATION_ENABLED" in schema.PLAN_CHECK


def test_study_help_disclosure_rejects_changed_evidence(tmp_path):
    active, candidate = "a" * 40, "b" * 40
    evidence = tmp_path / schema.EVIDENCE_PATH
    evidence.write_text(json.dumps(schema.build_evidence(candidate, active)))
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

    tampered = schema.build_evidence(candidate, active)
    tampered["study_help_and_paid_evaluation_disabled"] = False
    evidence.write_text(json.dumps(tampered))
    disclosure["postgresql_rehearsal_sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    with pytest.raises(ConceptSchemaError, match="does not match"):
        schema.validate_build_evidence(tmp_path, disclosure)
