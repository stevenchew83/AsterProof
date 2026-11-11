# ruff: noqa: EM101, TRY003
"""Trusted allowance for the one nullable problem-library AI evidence column."""

import hashlib
import json
from pathlib import Path

from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.concept_schema import audit_matches  # noqa: F401 - schema contract
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_fingerprint import sha256_fingerprint
from scripts.deployment.schema_rehearsal import POSTGRES_VERSION
from scripts.deployment.schema_rehearsal import smoke_command
from scripts.deployment.solution_forum_schema import DIGEST
from scripts.deployment.solution_forum_schema import FINGERPRINT_FIELDS
from scripts.deployment.solution_forum_schema import MAX_DISCLOSURE_BYTES
from scripts.deployment.solution_forum_schema import SHA

MIGRATION_NAME = "0048_statement_ai_concept_suggestions"
MIGRATION = f"pages.{MIGRATION_NAME}"
MIGRATION_PATH = Path("inspinia/pages/migrations") / f"{MIGRATION_NAME}.py"
MIGRATION_SHA256 = "bc656352bd4e3879f047795539bfc1c9eabaa64d011d26e5dc50f79d769da2d9"
PRIOR_MIGRATION_TREE_SHA256 = "38fb45bb67088ccb5a3585dc46e3d34a18893dfc7341609e796b7bba861c9dfa"
EVIDENCE_PATH = "deployment-schema-evidence.json"
TABLE = "pages_contestproblemstatement"
FIELD = "ai_concept_suggestions"
COLUMN = {
    "schema": "public", "table": TABLE, "position": 30, "column": FIELD,
    "type": "jsonb", "nullable": True, "default": None, "collation": None,
}
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[(type(o).__name__,getattr(o,'model_name',None),getattr(o,'name',None))
                             for o in m.operations]) for m,b in plan]
if actual != [('pages','{MIGRATION_NAME}',False,[('AddField','contestproblemstatement','{FIELD}')])]:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('pages','{MIGRATION_NAME}')])\n"
COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()


def migration_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.glob("inspinia/*/migrations/*")):
        relative = path.relative_to(root)
        if path.suffix not in {".py", ".json"} or relative == MIGRATION_PATH:
            continue
        if path.is_symlink() or not path.is_file():
            raise ConceptSchemaError("Migration source must be a regular file")
        digest.update(relative.as_posix().encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def validate_candidate(release: Path) -> None:
    path = release / MIGRATION_PATH
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != MIGRATION_SHA256:
        raise ConceptSchemaError("AI evidence migration bytes differ from the frozen allowance")
    if migration_tree_sha256(release) != PRIOR_MIGRATION_TREE_SHA256:
        raise ConceptSchemaError("Prior migration sources differ from the frozen allowance")


def validate_disclosure(value, *, target_sha):
    fields = {
        "format_version", "active_sha", "target_sha", "migration", "migration_file_sha256",
        "starting", "expected", "postgresql_rehearsal_sha256", "compatibility_smoke_sha256",
    }
    if (
        not isinstance(value, dict) or set(value) != fields or type(value["format_version"]) is not int
        or value["format_version"] != 1 or value["migration"] != MIGRATION
        or value["migration_file_sha256"] != MIGRATION_SHA256 or value["target_sha"] != target_sha
        or not SHA.fullmatch(target_sha) or not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"]) or value["active_sha"] == target_sha
        or value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256
        or not isinstance(value["postgresql_rehearsal_sha256"], str)
        or not DIGEST.fullmatch(value["postgresql_rehearsal_sha256"])
    ):
        raise ConceptSchemaError("Invalid bounded AI evidence disclosure")
    for state in (value["starting"], value["expected"]):
        if (
            not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS)
            or any(not isinstance(item, str) or not DIGEST.fullmatch(item) for item in state.values())
        ):
            raise ConceptSchemaError("Invalid AI evidence fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise ConceptSchemaError("AI evidence disclosure does not describe an additive change")
    return value


def build_evidence(source_sha, active_sha):
    return {
        "format_version": 1, "source_sha": source_sha, "active_sha": active_sha, "postgres_version": POSTGRES_VERSION,
        "migration_file_sha256": MIGRATION_SHA256, "column_sha256": sha256_fingerprint(COLUMN),
        "prior_migration_tree_sha256": PRIOR_MIGRATION_TREE_SHA256,
        "existing_schema_records_triggers_sequences_preserved": True, "active_revision_smoke_passed": True,
    }


def validate_build_evidence(release: Path, disclosure):
    path = release / EVIDENCE_PATH
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise ConceptSchemaError("Missing or invalid AI evidence rehearsal proof")
    content = path.read_bytes()
    try:
        actual = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise ConceptSchemaError("Invalid AI evidence rehearsal JSON") from exc
    if (
        hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]
        or canonical_json(actual) != canonical_json(build_evidence(disclosure["target_sha"], disclosure["active_sha"]))
    ):
        raise ConceptSchemaError("AI evidence rehearsal proof does not match this release")


def add_column(catalog):
    if not any(row["schema"] == "public" and row["table"] == TABLE for row in catalog["tables"]):
        raise ConceptSchemaError("The problem statement table is missing")
    if any(
        row["schema"] == "public" and row["table"] == TABLE
        and (row["column"] == FIELD or row["position"] >= COLUMN["position"])
        for row in catalog["columns"]
    ):
        raise ConceptSchemaError("The problem statement catalog conflicts with the frozen column")
    return normalize_schema_snapshot({**catalog, "columns": [*catalog["columns"], COLUMN]})


def expected_catalog_audit(start):
    if start.get("server_version_num") != POSTGRES_VERSION or (
        sha256_fingerprint(start["state"]) != start["state_fingerprint"]
    ):
        raise ConceptSchemaError("Starting catalog identity or PostgreSQL version differs")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    rows = start["migration_rows"]
    if (
        ["pages", "0047_study_help"] not in rows or ["pages", MIGRATION_NAME] in rows
        or schema_state(before) != start["state"]["schema"] or migration_state(rows) != start["state"]["migration"]
    ):
        raise ConceptSchemaError("Starting catalog does not match the required migration state")
    state = {
        **start["state"], "schema": schema_state(add_column(before)),
        "migration": migration_state([*rows, ["pages", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": sha256_fingerprint(state), "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
