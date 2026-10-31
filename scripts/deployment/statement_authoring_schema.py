# ruff: noqa: EM101, TRY003
"""Proposed, frozen pages.0040 maintenance allowance; installation is separate."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from scripts.deployment import catalogue_schema
from scripts.deployment import solution_pdf_schema
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state

KIND = "statement-authoring-maintenance-v1"
MIGRATION = "pages.0040_statement_authoring_metadata"
MIGRATION_NAME = MIGRATION.split(".", 1)[1]
MIGRATION_PATH = Path("inspinia/pages/migrations/0040_statement_authoring_metadata.py")
INPUT_HASHES = {
    "0040_statement_authoring_metadata.py": "38094d06e4f6f5bbd02ec68bce8d55600d11cb680b469ec86a4972e998322466",
    "0039_catalogue_revision_triggers.py": "03c531d47c50320c3f99f557ffd94df15e869b9cfceb5efa5b30700766c0c5ed",
}
TABLE = "pages_problemsolverecord"
# The only admitted PostgreSQL column changes. Positions, defaults, collations,
# constraints, indexes, functions, triggers, rows and all other columns stay intact.
COLUMN_CHANGES = {
    "mohs": {"before": ("integer", False), "after": ("integer", True)},
    "contest": {"before": ("character varying(64)", False), "after": ("character varying(128)", False)},
    "contest_year_problem": {
        "before": ("character varying(128)", True), "after": ("character varying(160)", True),
    },
}
DELTA_SHA256 = hashlib.sha256(canonical_json(COLUMN_CHANGES)).hexdigest()
POSTGRES_VERSION = 170009
FINGERPRINT_FIELDS = catalogue_schema.FINGERPRINT_FIELDS
RECOVERY_POLICY = catalogue_schema.RECOVERY_POLICY
EVIDENCE_PATH = "deployment-schema-evidence.json"
MAX_DISCLOSURE_BYTES = 8192
FLAGS = (
    "schema_delta_exact", "source_fixture_unchanged", "existing_records_unchanged",
    "existing_sequences_unchanged", "existing_trigger_definitions_unchanged",
    "active_revision_smoke_passed", "unknown_difficulty_roundtrip_passed",
)
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected=[('pages','{MIGRATION_NAME}',False,['RunPython','AlterField','AlterField','AlterField','RunPython'])]
if actual != expected:
    raise RuntimeError('Pending migrations differ from the frozen statement-authoring plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('pages','{MIGRATION_NAME}')])\n"


def smoke_command():
    return solution_pdf_schema.smoke_command()


def validate_candidate(release: Path) -> None:
    for name, digest in INPUT_HASHES.items():
        path = release / MIGRATION_PATH.parent / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Statement-authoring migration input differs from its frozen hash")


def changed_schema(snapshot: dict) -> dict:
    value = normalize_schema_snapshot(snapshot)
    seen = set()
    columns = []
    for row in value["columns"]:
        changed_row = row
        if row["schema"] == "public" and row["table"] == TABLE and row["column"] in COLUMN_CHANGES:
            name = row["column"]
            change = COLUMN_CHANGES[name]
            if name in seen or (row["type"], row["nullable"]) != change["before"]:
                raise ValueError("Existing statement-authoring column differs from the frozen starting shape")
            seen.add(name)
            changed_row = {**row, "type": change["after"][0], "nullable": change["after"][1]}
        columns.append(changed_row)
    if seen != set(COLUMN_CHANGES):
        raise ValueError("Statement-authoring requires exactly its three existing columns")
    return normalize_schema_snapshot({**value, "columns": columns})


def rehearsal_evidence(*, release_sha: str, active_sha: str) -> dict:
    return {
        "format_version": 1, "source_sha": release_sha, "active_sha": active_sha,
        "postgres_version": POSTGRES_VERSION, "input_hashes": INPUT_HASHES,
        "delta_sha256": DELTA_SHA256, "behaviour_sha256": catalogue_schema.BEHAVIOUR_SHA256,
        **dict.fromkeys(FLAGS, True),
    }


def evidence_bytes(*, release_sha: str, active_sha: str) -> bytes:
    return (json.dumps(rehearsal_evidence(release_sha=release_sha, active_sha=active_sha),
                       sort_keys=True, indent=2) + "\n").encode()


def validate_rehearsal_evidence(value: dict, *, release_sha: str, active_sha: str) -> None:
    if value != rehearsal_evidence(release_sha=release_sha, active_sha=active_sha) or any(
        value.get(field) is not True for field in FLAGS
    ):
        raise ValueError("Statement-authoring rehearsal evidence does not match this exact release")


def validate_disclosure(value: object, *, target_sha: str) -> dict:
    fields = {
        "format_version", "kind", "active_sha", "target_sha", "input_hashes", "starting", "expected",
        "postgresql_rehearsal_sha256", "recovery_policy",
    }
    if not isinstance(value, dict) or set(value) != fields or type(value["format_version"]) is not int:
        raise ValueError("Malformed statement-authoring maintenance disclosure")
    if value["format_version"] != 1 or value["kind"] != KIND or value["input_hashes"] != INPUT_HASHES:
        raise ValueError("Statement-authoring maintenance is outside its frozen scope")
    if (
        not isinstance(target_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", target_sha)
        or not isinstance(value["active_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", value["active_sha"])
        or value["target_sha"] != target_sha or value["active_sha"] == target_sha
    ):
        raise ValueError("Statement-authoring maintenance release identity mismatch")
    for stage in ("starting", "expected"):
        data = value[stage]
        if not isinstance(data, dict) or set(data) != set(FINGERPRINT_FIELDS) or any(
            not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in data.values()
        ):
            raise ValueError("Invalid statement-authoring maintenance fingerprints")
        if data["behaviour_fingerprint"] != catalogue_schema.BEHAVIOUR_SHA256:
            raise ValueError("Statement-authoring must preserve the frozen catalogue trigger definitions")
    if any(value["starting"][key] == value["expected"][key] for key in FINGERPRINT_FIELDS[:-1]):
        raise ValueError("Statement-authoring must change schema and migration state")
    policy = value["recovery_policy"]
    if not isinstance(policy, dict) or policy != RECOVERY_POLICY or any(
        type(policy[key]) is not type(expected) for key, expected in RECOVERY_POLICY.items()
    ):
        raise ValueError("Statement-authoring requires the unchanged verified-recovery policy")
    digest = hashlib.sha256(evidence_bytes(release_sha=target_sha, active_sha=value["active_sha"])).hexdigest()
    if value["postgresql_rehearsal_sha256"] != digest or len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise ValueError("Statement-authoring rehearsal digest differs from the exact release")
    return value


def validate_build_evidence(release: Path, disclosure: dict) -> None:
    path = release / EVIDENCE_PATH
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise ValueError("Invalid packaged statement-authoring rehearsal proof")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise ValueError("Packaged statement-authoring rehearsal digest differs")
    validate_rehearsal_evidence(
        json.loads(data), release_sha=disclosure["target_sha"], active_sha=disclosure["active_sha"],
    )


def expected_catalog_audit(start: dict) -> dict:
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ) or start.get("behaviour_fingerprint") != catalogue_schema.BEHAVIOUR_SHA256:
        raise ValueError("Starting statement-authoring audit identity/version/behaviour mismatch")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    migrations = start["migration_rows"]
    if ["pages", MIGRATION_NAME] in migrations or ["pages", "0039_catalogue_revision_triggers"] not in migrations:
        raise ValueError("Statement-authoring migration baseline is invalid or already applied")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise ValueError("Starting statement-authoring metadata differs from its fingerprints")
    state = {
        **start["state"], "schema": schema_state(changed_schema(before)),
        "migration": migration_state([*migrations, ["pages", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
        "behaviour_fingerprint": catalogue_schema.BEHAVIOUR_SHA256,
    }
