# ruff: noqa: EM101, TRY003
"""Trusted allowance for exactly the disabled Study Help schema."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.concept_schema import audit_matches  # noqa: F401 - exported for the schema contract
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import POSTGRES_VERSION
from scripts.deployment.schema_rehearsal import smoke_command as base_smoke_command
from scripts.deployment.solution_forum_schema import DIGEST
from scripts.deployment.solution_forum_schema import FINGERPRINT_FIELDS
from scripts.deployment.solution_forum_schema import MAX_DISCLOSURE_BYTES
from scripts.deployment.solution_forum_schema import SHA

MIGRATION_NAME = "0047_study_help"
MIGRATION = "pages." + MIGRATION_NAME
MIGRATION_PATH = Path("inspinia/pages/migrations") / (MIGRATION_NAME + ".py")
EVIDENCE_PATH = "deployment-schema-evidence.json"
MIGRATION_SHA256 = "83b777e62719d28c44021b49169ba60a205a4862711745bd2651a68324f4b5ca"
PRIOR_MIGRATION_TREE_SHA256 = "015da4a77a152d5abf9f1b2d5c6a3d5ef163a128f6fa284a7fd4454886af2274"
DELTA_SHA256 = "4a5541a4702c907733a151067bad3008914b954e79c1edf5f3bb61222501e227"
OPERATIONS = [
    ("CreateModel", "StudyHelpEnrollment", None),
    ("CreateModel", "StudyHelpPrompt", None),
    ("CreateModel", "StudyHelpAdminEvent", None),
    ("CreateModel", "StudyHelpSpend", None),
    ("CreateModel", "StudyHelpRequest", None),
    ("CreateModel", "StudyHelpPolicy", None),
    ("CreateModel", "StudyHelpQualification", None),
    ("CreateModel", "StudyHelpEvent", None),
    ("CreateModel", "StudyHelpRestriction", None),
    ("AddIndex", None, "studyhelprequest"),
    ("AddIndex", None, "studyhelprequest"),
    ("AddConstraint", None, "studyhelprequest"),
    ("AddConstraint", None, "studyhelprequest"),
    ("AddConstraint", None, "studyhelprequest"),
    ("AddConstraint", None, "studyhelprequest"),
    ("AddConstraint", None, "studyhelprequest"),
]
TABLES = frozenset(f"pages_{name.lower()}" for operation, name, _ in OPERATIONS if operation == "CreateModel")
SEQUENCES = frozenset(
    f"pages_{name}_id_seq"
    for name in (
        "studyhelpadminevent",
        "studyhelpenrollment",
        "studyhelpevent",
        "studyhelpqualification",
        "studyhelprestriction",
    )
)
PLAN_CHECK = f"""from django.conf import settings
if settings.STUDY_HELP_ENABLED or settings.STUDY_HELP_EVALUATION_ENABLED:
    raise RuntimeError('Study Help and paid evaluation must remain disabled during the release')
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[(type(o).__name__,getattr(o,'name',None),getattr(o,'model_name',None))
                             for o in m.operations]) for m,b in plan]
if actual != [('pages','{MIGRATION_NAME}',False,{OPERATIONS!r})]:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('pages','{MIGRATION_NAME}')])\n"


def smoke_command():
    return (
        base_smoke_command()
        + """
from inspinia.solutions.models import ProblemSolution
solution = ProblemSolution.objects.get(title='Synthetic preserved solution')
if solution.blocks.get().body_source != 'Synthetic preserved proof.':
    raise RuntimeError('Active revision solution read failed')
"""
    )


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
        raise ConceptSchemaError("Study Help migration bytes differ from the frozen allowance")
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
        raise ConceptSchemaError("Invalid bounded Study Help disclosure")
    for state in (value["starting"], value["expected"]):
        if (
            not isinstance(state, dict)
            or set(state) != set(FINGERPRINT_FIELDS)
            or any(not isinstance(item, str) or not DIGEST.fullmatch(item) for item in state.values())
        ):
            raise ConceptSchemaError("Invalid Study Help fingerprints")
    if (
        any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS)
        or len(canonical_json(value)) > MAX_DISCLOSURE_BYTES
    ):
        raise ConceptSchemaError("Study Help disclosure does not describe the bounded additive change")
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
        "new_study_help_tables_empty": True,
        "study_help_and_paid_evaluation_disabled": True,
    }


def validate_build_evidence(release: Path, disclosure):
    path = release / EVIDENCE_PATH
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise ConceptSchemaError("Missing or invalid Study Help rehearsal proof")
    content = path.read_bytes()
    expected = build_evidence(disclosure["target_sha"], disclosure["active_sha"])
    try:
        actual = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise ConceptSchemaError("Invalid Study Help rehearsal evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"] or canonical_json(
        actual,
    ) != canonical_json(expected):
        raise ConceptSchemaError("Study Help rehearsal proof does not match this release")


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
        raise ConceptSchemaError("Catalog delta is outside the frozen Study Help tables")
    rows = start["migration_rows"]
    if (
        ["pages", "0046_prerequisitegraphstate_catalogueprerequisite"] not in rows
        or ["solutions", "0014_admin_solution_review"] not in rows
        or ["pages", MIGRATION_NAME] in rows
        or schema_state(before) != start["state"]["schema"]
        or migration_state(rows) != start["state"]["migration"]
    ):
        raise ConceptSchemaError("Starting catalog does not match the required migration state")
    state = {
        **start["state"],
        "schema": schema_state({field: [*before[field], *delta[field]] for field in before}),
        "migration": migration_state([*rows, ["pages", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
