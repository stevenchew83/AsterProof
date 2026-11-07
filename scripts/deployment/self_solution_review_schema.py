# ruff: noqa: EM101, TRY003
"""Trusted allowance for exactly the author review quota table."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.deployment.admin_solution_review_schema import smoke_command as base_smoke_command
from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.concept_schema import audit_matches  # noqa: F401 - exported for the schema contract
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import POSTGRES_VERSION
from scripts.deployment.solution_forum_schema import DIGEST
from scripts.deployment.solution_forum_schema import FINGERPRINT_FIELDS
from scripts.deployment.solution_forum_schema import MAX_DISCLOSURE_BYTES
from scripts.deployment.solution_forum_schema import SHA

MIGRATION_NAME = "0015_self_solution_review_usage"
MIGRATION = "solutions." + MIGRATION_NAME
MIGRATION_PATH = Path("inspinia/solutions/migrations") / f"{MIGRATION_NAME}.py"
EVIDENCE_PATH = "deployment-schema-evidence.json"
MIGRATION_SHA256 = "6f032ea2abe226a203f28dbe7cd81dcda1fbff110a21248d6bb4d63ca7d3aa3b"
PRIOR_MIGRATION_TREE_SHA256 = "d859d1b77eea9d0d36e5c7087ecd9d98c4cbe2fa560edef89435a4d1bc6f83b8"
DELTA_SHA256 = "440336bff8673ea5a35c91e8602f04a0452da01443f12c5655cd49c723c18f71"
OPERATIONS = [("CreateModel", "SelfSolutionReviewUsage", None)]
TABLES = frozenset({"solutions_selfsolutionreviewusage"})
SEQUENCES = frozenset({"solutions_selfsolutionreviewusage_id_seq"})
PLAN_CHECK = f"""from django.conf import settings
if settings.SELF_SOLUTION_REVIEW_ENABLED:
    raise RuntimeError('Author review requests must remain disabled during the release')
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[(type(o).__name__,getattr(o,'name',None),getattr(o,'model_name',None))
                             for o in m.operations]) for m,b in plan]
if actual != [('solutions','{MIGRATION_NAME}',False,{OPERATIONS!r})]:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('solutions','{MIGRATION_NAME}')])\n"


def smoke_command():
    return base_smoke_command() + """
from inspinia.solutions.admin_review_models import AdminSolutionReview, AdminSolutionReviewSettings
if AdminSolutionReviewSettings.objects.get().daily_limit != 10:
    raise RuntimeError('Active revision cannot read review settings')
if AdminSolutionReview.objects.get().problem_label != 'SCHEMA REHEARSAL 2026 P1':
    raise RuntimeError('Active revision cannot read a previously saved review')
"""


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()


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
        raise ConceptSchemaError("author review quota migration bytes differ from the frozen allowance")
    if migration_tree_sha256(release) != PRIOR_MIGRATION_TREE_SHA256:
        raise ConceptSchemaError("Prior migration sources differ from the frozen allowance")


def validate_disclosure(value, *, target_sha):
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
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or type(value["format_version"]) is not int
        or value["format_version"] != 1
        or value["migration"] != MIGRATION
        or value["migration_file_sha256"] != MIGRATION_SHA256
        or not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
        or value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256
        or not isinstance(value["postgresql_rehearsal_sha256"], str)
        or not DIGEST.fullmatch(value["postgresql_rehearsal_sha256"])
    ):
        raise ConceptSchemaError("Invalid bounded author review quota disclosure")
    for state in (value["starting"], value["expected"]):
        if (
            not isinstance(state, dict)
            or set(state) != set(FINGERPRINT_FIELDS)
            or any(not isinstance(item, str) or not DIGEST.fullmatch(item) for item in state.values())
        ):
            raise ConceptSchemaError("Invalid author review quota fingerprints")
    if (
        any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS)
        or len(canonical_json(value)) > MAX_DISCLOSURE_BYTES
    ):
        raise ConceptSchemaError("author review quota disclosure does not describe the bounded additive change")
    return value


def build_evidence(source_sha, active_sha):
    return {
        "format_version": 1,
        "source_sha": source_sha,
        "active_sha": active_sha,
        "postgres_version": POSTGRES_VERSION,
        "migration_file_sha256": MIGRATION_SHA256,
        "delta_sha256": DELTA_SHA256,
        "prior_migration_tree_sha256": PRIOR_MIGRATION_TREE_SHA256,
        "existing_schema_records_triggers_sequences_preserved": True,
        "active_revision_smoke_passed": True,
        "new_self_review_usage_table_empty": True,
        "self_review_generation_disabled": True,
    }


def validate_build_evidence(release: Path, disclosure):
    path = release / EVIDENCE_PATH
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise ConceptSchemaError("Missing or invalid author review quota rehearsal proof")
    content = path.read_bytes()
    expected = build_evidence(disclosure["target_sha"], disclosure["active_sha"])
    try:
        actual = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise ConceptSchemaError("Invalid author review quota rehearsal evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"] or canonical_json(
        actual,
    ) != canonical_json(expected):
        raise ConceptSchemaError("author review quota rehearsal proof does not match this release")


def expected_catalog_audit(start, rehearsal):
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise ConceptSchemaError("Starting catalog identity or PostgreSQL version differs")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    delta = normalize_schema_snapshot(rehearsal)
    if (
        schema_state(delta)["fingerprint"] != DELTA_SHA256
        or delta["extensions"]
        or {row["table"] for row in delta["tables"]} != TABLES
        or any(row["table"] not in TABLES for key in ("columns", "constraints", "indexes") for row in delta[key])
        or any(row["table"] in TABLES for row in before["tables"])
    ):
        raise ConceptSchemaError("Catalog delta is outside the frozen author review quota table")
    rows = start["migration_rows"]
    if (
        ["pages", "0047_study_help"] not in rows
        or ["solutions", "0014_admin_solution_review"] not in rows
        or ["solutions", MIGRATION_NAME] in rows
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
