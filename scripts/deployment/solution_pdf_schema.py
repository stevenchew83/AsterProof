# ruff: noqa: EM101, EM102, TRY003
"""Frozen solution_pdf schema allowance; no other migration is admitted."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import smoke_command as base_smoke_command

MIGRATION = "solutions.0004_solution_pdf_display_options"
MIGRATION_NAME = MIGRATION.split(".", 1)[1]
MIGRATION_PATH = Path("inspinia/solutions/migrations/0004_solution_pdf_display_options.py")
MIGRATION_SHA256 = "780264c13e1b190b0fd3eec3046c1178b24c2feffa5c425bae499dc3a306184f"
DELTA_SHA256 = "65f4aeacf31c34c71fb75dc8c5c30b7f7f0ead22bdd1a616998e7cd750f595b7"
EVIDENCE_PATH = "deployment-schema-evidence.json"
POSTGRES_VERSION = 170009
TABLE = "solutions_problemsolution"
COLUMNS = {"pdf_show_author", "pdf_show_date", "pdf_show_footer"}
PRIOR_MIGRATIONS = {
    "0001_initial.py": "6a02f941ad2a4fd10399df55522a1626109d0cbd4f50ddd4233d39ca03a27c2b",
    "0002_seed_solution_block_types.py": "d95d066d5e3cce66ba030af8e0305d456c2f1cb57684f8aa22985ffa61e545df",
    "0003_solution_body_image.py": "623f0ac3a8e6953f1ba9713cb2b6aefbc40bcd12d64b7743293fc7260b701b82",
}
DIGEST = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_FIELDS = ("state_fingerprint", "schema_fingerprint", "migration_fingerprint")
MAX_DISCLOSURE_BYTES = 8192
BASE_COLUMNS = (
    "id", "title", "status", "summary", "submitted_at", "published_at",
    "created_at", "updated_at", "author_id", "problem_id",
)


def smoke_command():
    return base_smoke_command() + """
from inspinia.solutions.models import ProblemSolution
solution=ProblemSolution.objects.get(title='Synthetic preserved solution')
if solution.blocks.get().body_source != 'Synthetic preserved proof.':
    raise RuntimeError('Active revision solution read failed')
"""


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected=[('solutions','{MIGRATION_NAME}',False,['AddDisplayField']*3)]
if actual != expected:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('solutions','{MIGRATION_NAME}')])\n"


class SolutionPdfSchemaError(ConceptSchemaError):
    pass


def _validate_fingerprints(value: dict[str, Any]) -> None:
    for stage in ("starting", "expected"):
        state = value[stage]
        if not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS):
            raise SolutionPdfSchemaError("Invalid schema fingerprint fields")
        if any(not isinstance(v, str) or not DIGEST.fullmatch(v) for v in state.values()):
            raise SolutionPdfSchemaError("Invalid schema fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise SolutionPdfSchemaError("The approved additive migration must change each fingerprint")


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
        raise SolutionPdfSchemaError("Invalid bounded schema disclosure")
    if value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256:
        raise SolutionPdfSchemaError("Migration is outside the approved scope")
    if (
        not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise SolutionPdfSchemaError("Schema disclosure release identity mismatch")
    for field in ("postgresql_rehearsal_sha256", "compatibility_smoke_sha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise SolutionPdfSchemaError("Schema rehearsal and compatibility evidence must be frozen")
    if value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256:
        raise SolutionPdfSchemaError("SolutionPdf compatibility smoke differs from the approved fixed command")
    _validate_fingerprints(value)
    if len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise SolutionPdfSchemaError("Schema disclosure exceeds its bound")
    return value


def validate_candidate(release: Path) -> None:
    paths = {MIGRATION_PATH: MIGRATION_SHA256}
    paths.update({MIGRATION_PATH.parent / name: digest for name, digest in PRIOR_MIGRATIONS.items()})
    for relative, digest in paths.items():
        path = release / relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SolutionPdfSchemaError("Candidate migration bytes differ from the frozen solution plan")


def audit_matches(disclosure: dict[str, Any], audit: dict[str, Any], *, stage: str) -> bool:
    return audit.get("server_version_num") == POSTGRES_VERSION and all(
        audit.get(field) == disclosure[stage][field] for field in FINGERPRINT_FIELDS
    )


def validate_build_evidence(release: Path, disclosure: dict[str, Any]) -> None:
    import json

    path = release / EVIDENCE_PATH
    if path.is_symlink() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise SolutionPdfSchemaError("Invalid packaged schema evidence")
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise SolutionPdfSchemaError("Invalid packaged schema evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise SolutionPdfSchemaError("Packaged website rehearsal proof digest does not match its disclosure")
    expected = {
        "format_version": 1,
        "source_sha": disclosure["target_sha"],
        "active_sha": disclosure["active_sha"],
        "postgres_version": POSTGRES_VERSION,
        "migration_file_sha256": MIGRATION_SHA256,
        "delta_sha256": DELTA_SHA256,
        "existing_schema_unchanged": True,
        "source_fixture_unchanged": True,
        "active_revision_smoke_passed": True,
        "existing_records_unchanged": True,
        "existing_sequences_unchanged": True,
        "existing_solution_defaults_true": True,
        "existing_trigger_definitions_unchanged": True,
    }
    if value != expected or any(
        value[field] is not True
        for field in (
            "existing_schema_unchanged",
            "source_fixture_unchanged",
            "active_revision_smoke_passed",
            "existing_records_unchanged",
            "existing_sequences_unchanged",
            "existing_solution_defaults_true",
            "existing_trigger_definitions_unchanged",
        )
    ):
        raise SolutionPdfSchemaError("Packaged PostgreSQL schema evidence does not match this release")


def expected_catalog_audit(start: dict[str, Any], rehearsal: dict[str, Any]) -> dict[str, Any]:
    """Append only the three frozen column records to verified catalog metadata."""
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise SolutionPdfSchemaError("Starting audit identity/version does not match the approved target")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    delta = normalize_schema_snapshot(rehearsal)
    if schema_state(delta)["fingerprint"] != DELTA_SHA256:
        raise SolutionPdfSchemaError("Schema delta differs from the frozen three-column fixture")
    if not any(row["schema"] == "public" and row["table"] == TABLE for row in before["tables"]):
        raise SolutionPdfSchemaError("Existing solution table is required")
    existing_columns = sorted(
        (row for row in before["columns"] if row["schema"] == "public" and row["table"] == TABLE),
        key=lambda row: row["position"],
    )
    if [(row["position"], row["column"]) for row in existing_columns] != list(enumerate(BASE_COLUMNS, 1)):
        raise SolutionPdfSchemaError("Existing solution columns differ from the frozen starting shape")
    if any(row["table"] == TABLE and row["column"] in COLUMNS for row in before["columns"]):
        raise SolutionPdfSchemaError("PDF display columns already exist")
    if any(delta[field] for field in ("tables", "constraints", "indexes", "extensions")) or (
        {row["column"] for row in delta["columns"]} != COLUMNS
        or any(row["schema"] != "public" or row["table"] != TABLE for row in delta["columns"])
    ):
        raise SolutionPdfSchemaError("Schema delta is not exactly the three approved columns")
    migrations = start["migration_rows"]
    if ["solutions", MIGRATION_NAME] in migrations:
        raise SolutionPdfSchemaError("The frozen migration is already recorded")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise SolutionPdfSchemaError("Starting catalog evidence does not match its fingerprints")
    combined = {field: [*before[field], *delta[field]] for field in before}
    state = {
        **start["state"],
        "schema": schema_state(combined),
        "migration": migration_state([*migrations, ["solutions", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
