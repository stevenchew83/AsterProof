# ruff: noqa: EM101, EM102, TRY003
"""Frozen offline evaluation schema allowance; no other migration is admitted."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.evaluation_schema import MODELS
from scripts.deployment.evaluation_schema import TABLES
from scripts.deployment.evaluation_schema import validate_candidate as validate_shape
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import smoke_command as base_smoke_command

MIGRATION = "solutions.0010_offline_evaluation_contract"
MIGRATION_NAME = MIGRATION.split(".", 1)[1]
MIGRATION_PATH = Path("inspinia/solutions/migrations/0010_offline_evaluation_contract.py")
MIGRATION_SHA256 = "9fee1f590a8cdde9df9d30c201a49caea20a5c31efe2f4b0aa7c92171d4844a8"
DELTA_SHA256 = "e34c2715374cba7a9aab59c473d3308c4dcd656896509c76165972cf568842d0"
EVIDENCE_PATH = "deployment-schema-evidence.json"
POSTGRES_VERSION = 170009
PRIOR_MIGRATIONS = {
    "0009_problemsolution_edit_version_solutionreviewpolicy_and_more.py": (
        "c942e9376aaf99417debf7d1ef2cf76719652b581e21087b674b06a8046d161c"
    ),
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
from inspinia.solutions.models import ProblemSolution, SolutionReviewPolicy
from django.conf import settings
if settings.SOLUTION_AI_REVIEW_ENABLED or settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED:
    raise RuntimeError('AI must remain disabled during compatibility smoke')
solution=ProblemSolution.objects.get(title='Synthetic preserved solution')
if solution.blocks.get().body_source != 'Synthetic preserved proof.':
    raise RuntimeError('Active revision block read failed')
if (solution.edit_version != 7 or solution.current_revision.sequence != 1
    or solution.current_revision.body_source != 'Synthetic immutable document before the evaluation migration.'):
    raise RuntimeError('Active revision document read failed')
if SolutionReviewPolicy.objects.filter(enabled=True).exists():
    raise RuntimeError('Review policy must remain disabled')
"""


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()
PLAN_CHECK = f"""from django.conf import settings
if settings.SOLUTION_AI_REVIEW_ENABLED or settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED:
    raise RuntimeError('AI must remain disabled for the offline evaluation release')
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[(type(o).__name__,getattr(o,'name',None)) for o in m.operations]) for m,b in plan]
expected=[('solutions','{MIGRATION_NAME}',False,{[('CreateModel', name) for name in MODELS]!r})]
if actual != expected:
    raise RuntimeError('Unapproved pending migration plan')
from django.db.models import Q
from inspinia.solutions.models import SolutionReviewPolicy
if SolutionReviewPolicy.objects.filter(
    Q(enabled=True) | ~Q(daily_budget_micros=0) | ~Q(monthly_budget_micros=0)
).exists():
    raise RuntimeError('Review policy must remain disabled and unfunded')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('solutions','{MIGRATION_NAME}')])\n"


class SolutionEvaluationSchemaError(ConceptSchemaError):
    pass


def _validate_fingerprints(value: dict[str, Any]) -> None:
    for stage in ("starting", "expected"):
        state = value[stage]
        if not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS):
            raise SolutionEvaluationSchemaError("Invalid schema fingerprint fields")
        if any(not isinstance(v, str) or not DIGEST.fullmatch(v) for v in state.values()):
            raise SolutionEvaluationSchemaError("Invalid schema fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise SolutionEvaluationSchemaError("The approved additive migration must change each fingerprint")


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
        raise SolutionEvaluationSchemaError("Invalid bounded schema disclosure")
    if value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256:
        raise SolutionEvaluationSchemaError("Migration is outside the approved scope")
    if (
        not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise SolutionEvaluationSchemaError("Schema disclosure release identity mismatch")
    for field in ("postgresql_rehearsal_sha256", "compatibility_smoke_sha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise SolutionEvaluationSchemaError("Schema rehearsal and compatibility evidence must be frozen")
    if value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256:
        raise SolutionEvaluationSchemaError("Evaluation compatibility smoke differs from the approved fixed command")
    _validate_fingerprints(value)
    if len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise SolutionEvaluationSchemaError("Schema disclosure exceeds its bound")
    return value


def validate_candidate(release: Path) -> None:
    try:
        validate_shape(release)
    except ValueError as exc:
        raise SolutionEvaluationSchemaError(
            "Candidate migration bytes differ from the frozen evaluation plan",
        ) from exc
    paths = {MIGRATION_PATH: MIGRATION_SHA256}
    paths.update({MIGRATION_PATH.parent / name: digest for name, digest in PRIOR_MIGRATIONS.items()})
    for relative, digest in paths.items():
        path = release / relative
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SolutionEvaluationSchemaError("Candidate migration bytes differ from the frozen solution plan")


def audit_matches(disclosure: dict[str, Any], audit: dict[str, Any], *, stage: str) -> bool:
    return audit.get("server_version_num") == POSTGRES_VERSION and all(
        audit.get(field) == disclosure[stage][field] for field in FINGERPRINT_FIELDS
    )


def validate_build_evidence(release: Path, disclosure: dict[str, Any]) -> None:
    import json

    path = release / EVIDENCE_PATH
    if path.is_symlink() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise SolutionEvaluationSchemaError("Invalid packaged schema evidence")
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise SolutionEvaluationSchemaError("Invalid packaged schema evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise SolutionEvaluationSchemaError("Packaged evaluation rehearsal proof digest does not match its disclosure")
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
        "new_evidence_tables_empty": True,
        "existing_trigger_definitions_unchanged": True,
        "ai_disabled_and_unfunded": True,
    }
    if value != expected or any(
        value[field] is not True
        for field in (
            "existing_schema_unchanged",
            "source_fixture_unchanged",
            "active_revision_smoke_passed",
            "existing_records_unchanged",
            "existing_sequences_unchanged",
            "new_evidence_tables_empty",
            "existing_trigger_definitions_unchanged",
            "ai_disabled_and_unfunded",
        )
    ):
        raise SolutionEvaluationSchemaError("Packaged PostgreSQL schema evidence does not match this release")


def expected_catalog_audit(start: dict[str, Any], rehearsal: dict[str, Any]) -> dict[str, Any]:
    """Append the rehearsed nineteen-table delta to catalog metadata, without production data."""
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise SolutionEvaluationSchemaError("Starting audit identity/version does not match the approved target")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    delta = normalize_schema_snapshot(rehearsal)
    if schema_state(delta)["fingerprint"] != DELTA_SHA256:
        raise SolutionEvaluationSchemaError("Schema delta differs from the approved rehearsal")
    if any(row["table"] in TABLES for row in before["tables"]):
        raise SolutionEvaluationSchemaError("Evaluation table already exists")
    if {row["table"] for row in delta["tables"]} != TABLES or delta["extensions"]:
        raise SolutionEvaluationSchemaError("Rehearsal delta is not exactly the nineteen approved tables")
    if any(row["table"] not in TABLES for field in ("columns", "constraints", "indexes") for row in delta[field]):
        raise SolutionEvaluationSchemaError("Rehearsal delta changes an existing schema object")
    if not any(
        row["schema"] == "public" and row["table"] == "solutions_solutionrevision" for row in before["tables"]
    ):
        raise SolutionEvaluationSchemaError("Existing document revision table is required")
    migrations = start["migration_rows"]
    if ["solutions", "0009_problemsolution_edit_version_solutionreviewpolicy_and_more"] not in migrations:
        raise SolutionEvaluationSchemaError("The previous solution migration must already be recorded")
    if ["solutions", MIGRATION_NAME] in migrations:
        raise SolutionEvaluationSchemaError("The approved migration is already recorded")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise SolutionEvaluationSchemaError("Starting catalog evidence does not match its fingerprints")
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
