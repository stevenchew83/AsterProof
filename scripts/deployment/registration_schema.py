# ruff: noqa: EM101, TRY003
"""Trusted allowance for the single public-registration setting."""

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

MIGRATION_NAME = "0010_public_registration"
MIGRATION = "users." + MIGRATION_NAME
MIGRATION_PATH = Path("inspinia/users/migrations") / f"{MIGRATION_NAME}.py"
MIGRATION_SHA256 = "86e9f7965a5fea11e72c4193e0a6426284e2f4c120049adb3572af969bb983d4"
PRIOR_MIGRATION_TREE_SHA256 = "4421a02a563758c777b4eeada0e465fb1a3505f43e27b7fc2c3b5a050767ec16"
DELTA_SHA256 = "c64550950502eb63038a96e59c4fc7774bda4b2700cfc00e143cf6b5f64a59f3"
EVIDENCE_PATH = "deployment-schema-evidence.json"
TABLE = "users_useraccesssettings"
COLUMNS = {"allow_public_registration"}
PREVIOUS = ("users", "0009_user_solution_guide_status")
OPERATIONS = [
    ("AddField", "allow_public_registration", "useraccesssettings"),
    ("AlterField", "event_type", "auditevent"),
]
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[(type(o).__name__,getattr(o,'name',None),getattr(o,'model_name',None))
                             for o in m.operations]) for m,b in plan]
if actual != [('users','{MIGRATION_NAME}',False,{OPERATIONS!r})]:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('users','{MIGRATION_NAME}')])\n"
SMOKE_COMMAND = """import django
from django.conf import settings
from django.core.management import call_command
from scripts.deployment.schema_rehearsal import configure_rehearsal_database
configure_rehearsal_database(settings)
django.setup()
from django.db import connection, transaction
from inspinia.users.models import UserAccessSettings
call_command('check')
call_command('migrate', check=True, verbosity=0)
if not UserAccessSettings.objects.get(pk=1).auto_approve_new_users:
    raise RuntimeError('Active revision could not read existing access settings')
with transaction.atomic():
    UserAccessSettings.objects.filter(pk=1).delete()
    UserAccessSettings.objects.create(pk=1, auto_approve_new_users=False)
    with connection.cursor() as cursor:
        cursor.execute('SELECT allow_public_registration FROM users_useraccesssettings WHERE id = %s', [1])
        if cursor.fetchone() != (True,):
            raise RuntimeError('Old settings inserts must default to open registration')
    transaction.set_rollback(True)
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
        raise ConceptSchemaError("Public registration migration differs from the frozen bytes")
    if migration_tree_sha256(release) != PRIOR_MIGRATION_TREE_SHA256:
        raise ConceptSchemaError("Prior migration sources differ from the frozen public registration allowance")


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
        raise ConceptSchemaError("Invalid bounded public registration schema disclosure")
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
        "existing_settings_default_open": True,
        "registration_gate_verified": True,
    }
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def validate_build_evidence(release: Path, disclosure):
    path = release / EVIDENCE_PATH
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise ConceptSchemaError("Missing or invalid public registration rehearsal evidence")
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
        raise ConceptSchemaError("Catalog delta differs from the frozen public registration allowance")
    current_columns = [row for row in before["columns"] if row["schema"] == "public" and row["table"] == TABLE]
    if (
        {(row["position"], row["column"]) for row in current_columns}
        != {(1, "id"), (2, "auto_approve_new_users"), (3, "created_at"), (4, "updated_at")}
        or any(row["column"] in COLUMNS for row in current_columns)
        or max(row["position"] for row in current_columns) + 1 != min(row["position"] for row in delta["columns"])
    ):
        raise ConceptSchemaError("Existing access settings columns differ from the approved starting shape")
    rows = start["migration_rows"]
    if (
        list(PREVIOUS) not in rows or ["users", MIGRATION_NAME] in rows
        or schema_state(before) != start["state"]["schema"]
        or migration_state(rows) != start["state"]["migration"]
    ):
        raise ConceptSchemaError("Starting catalog does not match the required migration state")
    state = {
        **start["state"],
        "schema": schema_state({field: [*before[field], *delta[field]] for field in before}),
        "migration": migration_state([*rows, ["users", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
