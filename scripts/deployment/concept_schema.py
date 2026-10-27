# ruff: noqa: EM101, EM102, TRY003
"""One explicitly approved additive migration; other schema changes stay disabled."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state

MIGRATION = "pages.0036_concept_assignment_reviews"
MIGRATION_NAME = MIGRATION.split(".", 1)[1]
MIGRATION_PATH = Path("inspinia/pages/migrations/0036_concept_assignment_reviews.py")
MIGRATION_SHA256 = "e69f6ed407bfbf0bbf5dad09a6ada8c3f7efdb101db4a3b60c484264b0fde87d"
DELTA_SHA256 = "7d6dc5163ab8406dbcd4e657139c7b746e6ecea041ba098fa0765ef32a85ccfc"
EVIDENCE_PATH = "deployment-schema-evidence.json"
POSTGRES_VERSION = 170009
TABLES = {
    "pages_problemconceptassignment",
    "pages_conceptassignmentreviewbatch",
    "pages_conceptassignmentreviewevent",
    "pages_conceptassignmentstate",
}
DIGEST = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_FIELDS = ("state_fingerprint", "schema_fingerprint", "migration_fingerprint")
MAX_DISCLOSURE_BYTES = 8192
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected=[('pages','{MIGRATION_NAME}',False,['CreateModel']*4)]
if actual != expected:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('pages','{MIGRATION_NAME}')])\n"



class ConceptSchemaError(ValueError):
    pass


def _validate_fingerprints(value: dict[str, Any]) -> None:
    for stage in ("starting", "expected"):
        state = value[stage]
        if not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS):
            raise ConceptSchemaError("Invalid schema fingerprint fields")
        if any(not isinstance(v, str) or not DIGEST.fullmatch(v) for v in state.values()):
            raise ConceptSchemaError("Invalid schema fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise ConceptSchemaError("The approved additive migration must change each fingerprint")


def validate_disclosure(value: Any, *, target_sha: str) -> dict[str, Any]:
    fields = {
        "format_version",
        "active_sha",
        "target_sha",
        "migration",
        "migration_file_sha256",
        "starting",
        "expected",
        "postgresql_rehearsal_sha256",
        "compatibility_smoke_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields or value["format_version"] != 1:
        raise ConceptSchemaError("Invalid bounded schema disclosure")
    if value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256:
        raise ConceptSchemaError("Migration is outside the approved scope")
    if (
        not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise ConceptSchemaError("Schema disclosure release identity mismatch")
    for field in ("postgresql_rehearsal_sha256", "compatibility_smoke_sha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise ConceptSchemaError("Schema rehearsal and compatibility evidence must be frozen")
    _validate_fingerprints(value)
    if len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise ConceptSchemaError("Schema disclosure exceeds its bound")
    return value


def validate_candidate(release: Path) -> None:
    path = release / MIGRATION_PATH
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != MIGRATION_SHA256:
        raise ConceptSchemaError("Candidate migration bytes differ from the approved migration")


def audit_matches(disclosure: dict[str, Any], audit: dict[str, Any], *, stage: str) -> bool:
    return audit.get("server_version_num") == POSTGRES_VERSION and all(
        audit.get(field) == disclosure[stage][field] for field in FINGERPRINT_FIELDS
    )


def validate_build_evidence(release: Path, disclosure: dict[str, Any]) -> None:
    import json

    path = release / EVIDENCE_PATH
    if path.is_symlink() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise ConceptSchemaError("Invalid packaged schema evidence")
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError) as exc:
        raise ConceptSchemaError("Invalid packaged schema evidence JSON") from exc
    expected = {
        "format_version": 1, "source_sha": disclosure["target_sha"], "active_sha": disclosure["active_sha"],
        "postgres_version": POSTGRES_VERSION, "migration_file_sha256": MIGRATION_SHA256, "delta_sha256": DELTA_SHA256,
        "existing_schema_unchanged": True, "source_fixture_unchanged": True, "active_revision_smoke_passed": True,
    }
    if value != expected or any(
        value[field] is not True
        for field in ("existing_schema_unchanged", "source_fixture_unchanged", "active_revision_smoke_passed")
    ):
        raise ConceptSchemaError("Packaged PostgreSQL schema evidence does not match this release")


def expected_catalog_audit(start: dict[str, Any], rehearsal: dict[str, Any]) -> dict[str, Any]:
    """Append the rehearsed four-table delta to catalog metadata, without production data."""
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise ConceptSchemaError("Starting audit identity/version does not match the approved target")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    delta = normalize_schema_snapshot(rehearsal)
    if schema_state(delta)["fingerprint"] != DELTA_SHA256:
        raise ConceptSchemaError("Schema delta differs from the approved rehearsal")
    if any(row["table"] in TABLES for row in before["tables"]):
        raise ConceptSchemaError("Assignment tables already exist")
    if {row["table"] for row in delta["tables"]} != TABLES or delta["extensions"]:
        raise ConceptSchemaError("Rehearsal delta is not exactly the four approved tables")
    if any(row["table"] not in TABLES for field in ("columns", "constraints", "indexes") for row in delta[field]):
        raise ConceptSchemaError("Rehearsal delta changes an existing schema object")
    migrations = start["migration_rows"]
    if ["pages", MIGRATION_NAME] in migrations:
        raise ConceptSchemaError("The approved migration is already recorded")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise ConceptSchemaError("Starting catalog evidence does not match its fingerprints")
    combined = {field: [*before[field], *delta[field]] for field in before}
    state = {
        **start["state"],
        "schema": schema_state(combined),
        "migration": migration_state([*migrations, ["pages", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
