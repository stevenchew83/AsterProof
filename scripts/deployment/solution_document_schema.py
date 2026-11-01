# ruff: noqa: EM101, EM102, S608, TRY003
"""Frozen additive solution document and private review schema allowance."""

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
from scripts.deployment.schema_fingerprint import sha256_fingerprint
from scripts.deployment.schema_rehearsal import smoke_command as base_smoke_command

MIGRATION = "solutions.0009_problemsolution_edit_version_solutionreviewpolicy_and_more"
MIGRATION_NAME = MIGRATION.split(".", 1)[1]
MIGRATION_PATH = Path(
    "inspinia/solutions/migrations/0009_problemsolution_edit_version_solutionreviewpolicy_and_more.py",
)
MIGRATION_SHA256 = "c942e9376aaf99417debf7d1ef2cf76719652b581e21087b674b06a8046d161c"
DELTA_SHA256 = "3bffcd3a7ef866f815dc8b72aec89444bcfb6d3c1bf88ea34439d9695a2445b3"
EVIDENCE_PATH = "deployment-schema-evidence.json"
POSTGRES_VERSION = 170009
TABLE = "solutions_problemsolution"
TABLES = {"solutions_solutionrevision", "solutions_solutionreview", "solutions_solutionreviewpolicy"}
COLUMNS = {"current_revision_id", "edit_version"}
BASE_COLUMNS = (
    "id", "title", "status", "summary", "submitted_at", "published_at", "created_at", "updated_at",
    "author_id", "problem_id", "pdf_show_author", "pdf_show_date", "pdf_show_footer",
)
PRIOR_MIGRATIONS = {
    "0008_solutioncollection_kind_and_nullable_owner.py": (
        "bc5cc1f10fafc0605223eedcd3ddbfb05d49f270b707bc2401fd93d676ddac28"
    ),
    "0007_solutioncollection_solutioncollectionentry.py": (
        "19074904c0dd2305a82291b818753ba489d9a11c2b910289d646d01989b61bb7"
    ),
    "0006_solution_share_daily_views.py": "b8065ef9ad04103558a0badf03ec9ed1f2c9079829b9b2fa042afed2e0dbd932",
    "0001_initial.py": "6a02f941ad2a4fd10399df55522a1626109d0cbd4f50ddd4233d39ca03a27c2b",
    "0002_seed_solution_block_types.py": "d95d066d5e3cce66ba030af8e0305d456c2f1cb57684f8aa22985ffa61e545df",
    "0003_solution_body_image.py": "623f0ac3a8e6953f1ba9713cb2b6aefbc40bcd12d64b7743293fc7260b701b82",
    "0004_solution_pdf_display_options.py": "780264c13e1b190b0fd3eec3046c1178b24c2feffa5c425bae499dc3a306184f",
    "0005_solutionpublicshare.py": "0309eeb67b809651c59b6ab9e49bac7955ed00b38083fa060742d3031537bb77",
}
DIGEST = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_FIELDS = ("state_fingerprint", "schema_fingerprint", "migration_fingerprint")
MAX_DISCLOSURE_BYTES = 8192


def smoke_command():
    return base_smoke_command() + """
from django.db import connection, transaction
from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.models import ProblemSolution
solution=ProblemSolution.objects.get(title='Synthetic preserved solution')
if solution.blocks.get().body_source != 'Synthetic preserved proof.':
    raise RuntimeError('Active revision solution read failed')
with transaction.atomic():
    problem=ProblemSolveRecord.objects.create(id=900001, contest='OLD INSERT',year=2026,problem='P1',topic='ALG')
    inserted=ProblemSolution.objects.create(
        id=900002,author_id=solution.author_id,problem_id=problem.pk,title='Old insert')
    with connection.cursor() as cursor:
        cursor.execute('SELECT edit_version,current_revision_id FROM solutions_problemsolution WHERE id=%s',
                       [inserted.pk])
        if cursor.fetchone() != (0,None):
            raise RuntimeError('Old-code solution insert did not receive durable defaults')
    transaction.set_rollback(True)
"""


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected=[('solutions','{MIGRATION_NAME}',False,['AddEditVersionField','CreateModel','CreateModel','CreateModel','AddField','AddConstraint','AddConstraint','AddIndex','AddConstraint'])]
if actual != expected:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('solutions','{MIGRATION_NAME}')])\n"


class SolutionDocumentSchemaError(ConceptSchemaError):
    pass


def _validate_fingerprints(value: dict[str, Any]) -> None:
    for stage in ("starting", "expected"):
        state = value[stage]
        if not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS):
            raise SolutionDocumentSchemaError("Invalid schema fingerprint fields")
        if any(not isinstance(v, str) or not DIGEST.fullmatch(v) for v in state.values()):
            raise SolutionDocumentSchemaError("Invalid schema fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise SolutionDocumentSchemaError("The approved document migration must change each fingerprint")


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
        raise SolutionDocumentSchemaError("Invalid bounded schema disclosure")
    if value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256:
        raise SolutionDocumentSchemaError("Migration is outside the approved scope")
    if (
        not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise SolutionDocumentSchemaError("Schema disclosure release identity mismatch")
    for field in ("postgresql_rehearsal_sha256", "compatibility_smoke_sha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise SolutionDocumentSchemaError("Schema rehearsal and compatibility evidence must be frozen")
    if value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256:
        raise SolutionDocumentSchemaError("Collections compatibility smoke differs from the approved fixed command")
    _validate_fingerprints(value)
    if len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise SolutionDocumentSchemaError("Schema disclosure exceeds its bound")
    return value


def validate_candidate(release: Path) -> None:
    paths = {MIGRATION_PATH: MIGRATION_SHA256}
    paths.update({MIGRATION_PATH.parent / name: digest for name, digest in PRIOR_MIGRATIONS.items()})
    for relative, digest in paths.items():
        path = release / relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SolutionDocumentSchemaError("Candidate migration bytes differ from the frozen solution plan")


def audit_matches(disclosure: dict[str, Any], audit: dict[str, Any], *, stage: str) -> bool:
    return audit.get("server_version_num") == POSTGRES_VERSION and all(
        audit.get(field) == disclosure[stage][field] for field in FINGERPRINT_FIELDS
    )


def validate_build_evidence(release: Path, disclosure: dict[str, Any]) -> None:
    import json

    path = release / EVIDENCE_PATH
    if path.is_symlink() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise SolutionDocumentSchemaError("Invalid packaged schema evidence")
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise SolutionDocumentSchemaError("Invalid packaged schema evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise SolutionDocumentSchemaError("Packaged document proof digest does not match its disclosure")
    expected = {
        "format_version": 1,
        "source_sha": disclosure["target_sha"],
        "active_sha": disclosure["active_sha"],
        "postgres_version": POSTGRES_VERSION,
        "migration_file_sha256": MIGRATION_SHA256,
        "delta_sha256": DELTA_SHA256,
        "only_approved_schema_changed": True,
        "source_fixture_unchanged": True,
        "active_revision_smoke_passed": True,
        "existing_records_unchanged": True,
        "existing_sequences_unchanged": True,
        "document_schema_defaults_safe": True,
        "existing_trigger_definitions_unchanged": True,
    }
    if value != expected or any(
        value[field] is not True
        for field in (
            "only_approved_schema_changed",
            "source_fixture_unchanged",
            "active_revision_smoke_passed",
            "existing_records_unchanged",
            "existing_sequences_unchanged",
            "document_schema_defaults_safe",
            "existing_trigger_definitions_unchanged",
        )
    ):
        raise SolutionDocumentSchemaError("Packaged PostgreSQL schema evidence does not match this release")


def schema_delta(before, after):
    """Record both sides of the exact alteration; catalogue rows are never guessed."""
    return {
        "removed": {field: [row for row in before[field] if row not in after[field]] for field in before},
        "added": {field: [row for row in after[field] if row not in before[field]] for field in before},
    }


def apply_delta(before, delta):
    if not isinstance(delta, dict) or set(delta) != {"removed", "added"}:
        raise SolutionDocumentSchemaError("Invalid document schema alteration")
    removed = normalize_schema_snapshot(delta["removed"])
    added = normalize_schema_snapshot(delta["added"])
    if sha256_fingerprint({"removed": removed, "added": added}) != DELTA_SHA256:
        raise SolutionDocumentSchemaError("Schema delta differs from the approved rehearsal")
    # The frozen digest is authoritative; require an exact starting-object match too.
    result = {}
    for field in before:
        if any(row not in before[field] for row in removed[field]):
            raise SolutionDocumentSchemaError("Starting catalogue does not contain the approved original object")
        kept = [row for row in before[field] if row not in removed[field]]
        identity = {
            "columns": ("schema", "table", "column"),
            "constraints": ("schema", "table", "name"),
        }.get(field)
        if any(
            row in kept or (identity and any(all(row[key] == old[key] for key in identity) for old in kept))
            for row in added[field]
        ):
            raise SolutionDocumentSchemaError("Document schema addition already exists")
        result[field] = [*kept, *added[field]]
    return normalize_schema_snapshot(result)


def expected_catalog_audit(start: dict[str, Any], rehearsal: dict[str, Any]) -> dict[str, Any]:
    """Apply only the frozen document/review additive schema delta."""
    if start.get("server_version_num") != POSTGRES_VERSION or (
        sha256_fingerprint(start["state"]) != start["state_fingerprint"]
    ):
        raise SolutionDocumentSchemaError("Starting audit identity/version does not match the approved target")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    if not all(any(row["schema"] == "public" and row["table"] == table for row in before["tables"])
               for table in {TABLE, "solutions_problemsolutionblock", "solutions_solutionpublicshare"}):
        raise SolutionDocumentSchemaError("Existing solution, block, and public-share tables are required")
    columns = sorted(
        (row for row in before["columns"] if row["table"] == TABLE), key=lambda row: row["position"],
    )
    if [(row["position"], row["column"]) for row in columns] != list(enumerate(BASE_COLUMNS, 1)):
        raise SolutionDocumentSchemaError("Existing solution columns differ from the frozen starting shape")
    if any(row["table"] in TABLES for row in before["tables"]):
        raise SolutionDocumentSchemaError("Document/review tables already exist")
    migrations = start["migration_rows"]
    if ["solutions", "0008_solutioncollection_kind_and_nullable_owner"] not in migrations:
        raise SolutionDocumentSchemaError("The previous solution migration must already be recorded")
    if ["solutions", MIGRATION_NAME] in migrations:
        raise SolutionDocumentSchemaError("The approved migration is already recorded")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise SolutionDocumentSchemaError("Starting catalog evidence does not match its fingerprints")
    combined = apply_delta(before, rehearsal)
    state = {
        **start["state"],
        "schema": schema_state(combined),
        "migration": migration_state([*migrations, ["solutions", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": sha256_fingerprint(state),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
