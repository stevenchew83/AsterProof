# ruff: noqa: EM101, TRY003
"""Frozen data-class maintenance scope for independent library solutions."""

import hashlib
import json
import re
from pathlib import Path

from scripts.deployment import catalogue_schema
from scripts.deployment import community_proof_schema
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state

KIND = "multiple-solutions-maintenance-v1"
MIGRATION = "solutions.0017_multiple_problem_solutions"
MIGRATION_NODE = tuple(MIGRATION.split("."))
PREVIOUS = ("solutions", "0016_admin_review_takedown")
PREREQUISITES = (PREVIOUS, ("users", "0010_public_registration"))
ACTIVE_SHA = "bf74e8f4f1159656c88501ab0ab41bd990ffdbc3"
MIGRATION_PATH = Path("inspinia/solutions/migrations/0017_multiple_problem_solutions.py")
DELTA_PATH = Path("scripts/deployment/tests/fixtures/multiple-solutions-schema-delta.json")
INPUT_HASHES = {MIGRATION_PATH.as_posix(): "e28824dd593627c8fd244949a7e63f53ba759a61c6000557c96616c4060b5782"}
PRIOR_TREE_SHA256 = "24b01254544b71b608a8b5ff9bb48d40a1878b8c635d23ce9c27af53cb238a46"
DELTA_SHA256 = "6f470b4d96514fb3040f6f49f6d98d266b5ad0ed12287e67cdb81fe9c58677cf"
TABLE = "solutions_problemsolution"
NEW_COLUMN = "additional_draft_key"
OLD_UNIQUE = "solutions_problemsolution_unique_problem_author"
NEW_INDEXES = frozenset(("solutions_unique_first_draft", "solutions_unique_additional_draft"))
POSTGRES_VERSION = 170009
BEHAVIOUR_SHA256 = community_proof_schema.BEHAVIOUR_SHA256
FINGERPRINT_FIELDS = catalogue_schema.FINGERPRINT_FIELDS
RECOVERY_POLICY = catalogue_schema.RECOVERY_POLICY
EVIDENCE_PATH = "deployment-schema-evidence.json"
MAX_BYTES = 8192
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
OPERATIONS = (
    ("AddField", "problemsolution", NEW_COLUMN, None),
    ("RemoveConstraintPreservingSQLiteTriggers", "problemsolution", OLD_UNIQUE, None),
    ("AddConstraint", "problemsolution", None, "solutions_unique_first_draft"),
    ("AddConstraint", "problemsolution", None, "solutions_unique_additional_draft"),
)
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor = MigrationExecutor(connection)
if connection.pg_version != {POSTGRES_VERSION} or not set({PREREQUISITES!r}).issubset(
    executor.loader.applied_migrations,
):
    raise RuntimeError('The frozen PostgreSQL version and solutions prerequisite are required')
plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
actual = [(m.app_label, m.name, b, tuple((type(o).__name__, getattr(o, 'model_name', None),
    getattr(o, 'name', None), getattr(getattr(o, 'constraint', None), 'name', None))
    for o in m.operations)) for m, b in plan]
if actual != [(*{MIGRATION_NODE!r}, False, {OPERATIONS!r})]:
    raise RuntimeError('Pending migrations differ from the frozen multiple-solutions plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([{MIGRATION_NODE!r}])\n"
FLAGS = (
    "schema_delta_exact", "prior_migration_sources_unchanged", "existing_records_unchanged",
    "existing_sequences_unchanged", "existing_behaviour_unchanged", "existing_privileges_unchanged",
    "migration_record_exact", "existing_solutions_use_original_slot", "active_reader_passed_read_only",
    "new_draft_isolation_verified",
)


def migration_tree_sha256(root):
    digest = hashlib.sha256()
    for path in sorted(root.glob("inspinia/**/migrations/*")):
        relative = path.relative_to(root)
        if path.suffix not in {".py", ".json"} or relative == MIGRATION_PATH:
            continue
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Migration history contains an unsafe path")
        digest.update(relative.as_posix().encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def frozen_delta(release):
    path = release / DELTA_PATH
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(release.resolve()):
        raise ValueError("Frozen multiple-solutions catalog delta is unavailable")
    delta = community_proof_schema.normalize_delta(json.loads(path.read_bytes()))
    if community_proof_schema.delta_digest(delta) != DELTA_SHA256:
        raise ValueError("Multiple-solutions catalog delta differs from PostgreSQL 17.9 proof")
    return delta


def validate_candidate(release):
    path = release / MIGRATION_PATH
    if (
        path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(release.resolve())
        or hashlib.sha256(path.read_bytes()).hexdigest() != INPUT_HASHES[MIGRATION_PATH.as_posix()]
        or migration_tree_sha256(release) != PRIOR_TREE_SHA256
    ):
        raise ValueError("Multiple-solutions migration or prior history differs from its frozen bytes")
    frozen_delta(release)


def evidence_bytes(*, release_sha, active_sha):
    record = {
        "format_version": 1, "purpose": "deployment-proof", "source_sha": release_sha, "active_sha": active_sha,
        "postgres_version": POSTGRES_VERSION, "input_hashes": INPUT_HASHES, "prior_tree_sha256": PRIOR_TREE_SHA256,
        "delta_sha256": DELTA_SHA256, "behaviour_sha256": BEHAVIOUR_SHA256, **dict.fromkeys(FLAGS, True),
    }
    return (json.dumps(record, sort_keys=True, indent=2) + "\n").encode()


def validate_disclosure(value, *, target_sha):
    fields = {
        "format_version", "kind", "active_sha", "target_sha", "input_hashes", "starting", "expected",
        "postgresql_rehearsal_sha256", "recovery_policy",
    }
    if not isinstance(value, dict) or set(value) != fields or type(value.get("format_version")) is not int:
        raise ValueError("Invalid multiple-solutions maintenance disclosure")
    if (
        value["format_version"] != 1 or value["kind"] != KIND or value["input_hashes"] != INPUT_HASHES
        or value["active_sha"] != ACTIVE_SHA or not isinstance(target_sha, str) or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha or target_sha == ACTIVE_SHA
    ):
        raise ValueError("Multiple-solutions release identity or migration bytes differ")
    for name in ("starting", "expected"):
        state = value[name]
        if (
            not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS)
            or any(not isinstance(item, str) or not DIGEST.fullmatch(item) for item in state.values())
            or state["behaviour_fingerprint"] != BEHAVIOUR_SHA256
        ):
            raise ValueError("Invalid multiple-solutions catalog fingerprints")
    if any(value["starting"][key] == value["expected"][key] for key in FINGERPRINT_FIELDS
           if key != "behaviour_fingerprint"):
        raise ValueError("Multiple-solutions maintenance requires a changed catalog and migration state")
    policy = value["recovery_policy"]
    if (
        not isinstance(policy, dict) or policy != RECOVERY_POLICY
        or any(type(policy[key]) is not type(expected) for key, expected in RECOVERY_POLICY.items())
    ):
        raise ValueError("Multiple-solutions maintenance requires verified recovery and disables code rollback")
    evidence = evidence_bytes(release_sha=target_sha, active_sha=ACTIVE_SHA)
    if value["postgresql_rehearsal_sha256"] != hashlib.sha256(evidence).hexdigest():
        raise ValueError("Multiple-solutions PostgreSQL proof is not bound to the exact release")
    if len(canonical_json(value)) > MAX_BYTES:
        raise ValueError("Multiple-solutions disclosure exceeds its bound")
    return value


def validate_build_evidence(release, disclosure):
    path = release / EVIDENCE_PATH
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Missing bounded multiple-solutions PostgreSQL proof")
    content = path.read_bytes()
    if (
        hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]
        or content != evidence_bytes(release_sha=disclosure["target_sha"], active_sha=disclosure["active_sha"])
    ):
        raise ValueError("Packaged multiple-solutions proof differs from the authorized release")


def expected_catalog_audit(start, delta):
    if (
        start.get("server_version_num") != POSTGRES_VERSION
        or start.get("behaviour_fingerprint") != BEHAVIOUR_SHA256
        or hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise ValueError("Production baseline version, behavior or state differs")
    delta = community_proof_schema.normalize_delta(delta)
    if community_proof_schema.delta_digest(delta) != DELTA_SHA256:
        raise ValueError("Catalog delta is outside the frozen multiple-solutions scope")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    migrations = start["migration_rows"]
    if (
        not all(list(node) in migrations for node in PREREQUISITES) or list(MIGRATION_NODE) in migrations
        or schema_state(before) != start["state"]["schema"]
        or migration_state(migrations) != start["state"]["migration"]
    ):
        raise ValueError("Production baseline migrations or schema do not match the audit")
    solution_columns = [row for row in before["columns"] if row["schema"] == "public" and row["table"] == TABLE]
    if not solution_columns or max(row["position"] for row in solution_columns) + 1 != (
        delta["add"]["columns"][0]["position"]
    ):
        raise ValueError("Multiple-solutions column does not append at its frozen position")
    combined = {}
    for key, rows in before.items():
        if any(row not in rows for row in delta["remove"][key]) or any(row in rows for row in delta["add"][key]):
            raise ValueError("The frozen multiple-solutions delta does not match the starting catalog")
        combined[key] = [*[row for row in rows if row not in delta["remove"][key]], *delta["add"][key]]
    ending = {
        **start["state"], "schema": schema_state(combined),
        "migration": migration_state([*migrations, list(MIGRATION_NODE)]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(ending)).hexdigest(),
        "schema_fingerprint": ending["schema"]["fingerprint"],
        "migration_fingerprint": ending["migration"]["fingerprint"],
        "behaviour_fingerprint": BEHAVIOUR_SHA256,
    }
