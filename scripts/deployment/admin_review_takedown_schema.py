# ruff: noqa: EM101, TRY003
"""Trusted allowance for exactly the two AI review take-down columns."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.concept_schema import audit_matches  # noqa: F401 - used by the trusted schema contract
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import POSTGRES_VERSION
from scripts.deployment.solution_forum_schema import DIGEST
from scripts.deployment.solution_forum_schema import MAX_DISCLOSURE_BYTES
from scripts.deployment.solution_forum_schema import SHA
from scripts.deployment.solution_pdf_schema import _validate_fingerprints

MIGRATION_NAME = "0016_admin_review_takedown"
MIGRATION = "solutions." + MIGRATION_NAME
MIGRATION_PATH = Path("inspinia/solutions/migrations") / f"{MIGRATION_NAME}.py"
MIGRATION_SHA256 = "ca04751a38ab612c6cbef7ea963c3dda200fd55b2ad62ada678abbf8e8ccba86"
PRIOR_MIGRATION_TREE_SHA256 = "cd055f18a1cba2b1fe7c8f911276cec937af966042ebf2858b324a5b583a7591"
DELTA_SHA256 = "526c227f18b1a4cc0fac1c550f0e6cdc94c17f54b8ef2e5dd861fbe1f277faf6"
EVIDENCE_PATH = "deployment-schema-evidence.json"
TABLE = "solutions_adminsolutionreview"
COLUMNS = {"taken_down_at", "taken_down_by_id"}
PREVIOUS = ("solutions", "0015_self_solution_review_usage")
OPERATIONS = [
    ("AddField", "taken_down_at", "adminsolutionreview"),
    ("AddField", "taken_down_by", "adminsolutionreview"),
]
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[(type(o).__name__,getattr(o,'name',None),getattr(o,'model_name',None))
                             for o in m.operations]) for m,b in plan]
if actual != [('solutions','{MIGRATION_NAME}',False,{OPERATIONS!r})]:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('solutions','{MIGRATION_NAME}')])\n"
SMOKE_COMMAND = """import django
from django.conf import settings
from django.core.management import call_command
from scripts.deployment.schema_rehearsal import configure_rehearsal_database
configure_rehearsal_database(settings)
django.setup()
from inspinia.solutions.admin_review_models import AdminSolutionReview
call_command('check')
call_command('migrate', check=True, verbosity=0)
review = AdminSolutionReview.objects.get(problem_label='SCHEMA REHEARSAL 2026 P1')
if (review.status, review.score, review.feedback, bool(review.published_at), review.notification) != (
    'completed', 0, 'Preserved synthetic review feedback.', True, 'pending',
):
    raise RuntimeError('Active revision could not read the original published review')
"""
COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(SMOKE_COMMAND.encode()).hexdigest()


def migration_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.glob("inspinia/**/migrations/*")):
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
        raise ConceptSchemaError("Review take-down migration differs from the frozen bytes")
    if migration_tree_sha256(release) != PRIOR_MIGRATION_TREE_SHA256:
        raise ConceptSchemaError("Prior migration sources differ from the frozen review take-down allowance")


def validate_disclosure(value, *, target_sha):
    fields = {
        "format_version", "active_sha", "target_sha", "migration", "migration_file_sha256", "starting", "expected",
        "postgresql_rehearsal_sha256", "compatibility_smoke_sha256",
    }
    if (
        not isinstance(value, dict) or set(value) != fields
        or type(value["format_version"]) is not int or value["format_version"] != 1
        or value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256
        or not isinstance(value["active_sha"], str) or not SHA.fullmatch(value["active_sha"])
        or not SHA.fullmatch(target_sha) or value["target_sha"] != target_sha or value["active_sha"] == target_sha
        or value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256
        or not isinstance(value["postgresql_rehearsal_sha256"], str)
        or not DIGEST.fullmatch(value["postgresql_rehearsal_sha256"])
        or len(canonical_json(value)) > MAX_DISCLOSURE_BYTES
    ):
        raise ConceptSchemaError("Invalid bounded review take-down schema disclosure")
    _validate_fingerprints(value)
    return value


def evidence_bytes(source_sha, active_sha):
    value = {
        "format_version": 1,
        "source_sha": source_sha,
        "active_sha": active_sha,
        "postgres_version": POSTGRES_VERSION,
        "migration_file_sha256": MIGRATION_SHA256,
        "delta_sha256": DELTA_SHA256,
        "prior_migration_tree_sha256": PRIOR_MIGRATION_TREE_SHA256,
        "existing_records_schema_triggers_sequences_preserved": True,
        "active_revision_smoke_passed": True,
        "take_down_columns_initially_null": True,
    }
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def validate_build_evidence(release: Path, disclosure):
    path = release / EVIDENCE_PATH
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise ConceptSchemaError("Missing or invalid review take-down rehearsal evidence")
    data = path.read_bytes()
    if (
        hashlib.sha256(data).hexdigest() != disclosure["postgresql_rehearsal_sha256"]
        or data != evidence_bytes(disclosure["target_sha"], disclosure["active_sha"])
    ):
        raise ConceptSchemaError("Review take-down rehearsal evidence differs from this release")


def expected_catalog_audit(start, rehearsal):
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise ConceptSchemaError("Starting catalog identity or PostgreSQL version differs")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    delta = normalize_schema_snapshot(rehearsal)
    if schema_state(delta)["fingerprint"] != DELTA_SHA256:
        raise ConceptSchemaError("Catalog delta differs from the frozen review take-down allowance")
    current_columns = [row for row in before["columns"] if row["table"] == TABLE]
    if (
        not current_columns
        or any(row["column"] in COLUMNS for row in current_columns)
        or max(row["position"] for row in current_columns) + 1 != min(row["position"] for row in delta["columns"])
    ):
        raise ConceptSchemaError("Existing review columns differ from the approved starting shape")
    rows = start["migration_rows"]
    if (
        list(PREVIOUS) not in rows or ["solutions", MIGRATION_NAME] in rows
        or schema_state(before) != start["state"]["schema"]
        or migration_state(rows) != start["state"]["migration"]
    ):
        raise ConceptSchemaError("Starting catalog does not match the required migration state")
    state = {
        **start["state"],
        "schema": schema_state({field: [*before[field], *delta[field]] for field in before}),
        "migration": migration_state([*rows, ["solutions", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
