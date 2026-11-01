# ruff: noqa: EM101, EM102, TRY003
"""Frozen synthetic assessment prototype schema allowance; no other migration is admitted."""

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
from scripts.deployment.solution_evaluation_schema import smoke_command as base_smoke_command

MIGRATION = "solutions.0011_problem_evaluation_packages"
MIGRATION_NAME = MIGRATION.split(".", 1)[1]
MIGRATION_PATH = Path("inspinia/solutions/migrations/0011_problem_evaluation_packages.py")
MIGRATION_SHA256 = "84d90530396e51ca2cbd1c2bfb65ebb6c50de0e5af2db912d0d3091592c7dad3"
DELTA_SHA256 = "2189a047bfbf7bc636149708e5590f7a974dbc32d58e4b993e87c15d8b177adc"
EVIDENCE_PATH = "deployment-schema-evidence.json"
POSTGRES_VERSION = 170009
SECOND_MIGRATION_NAME = "0012_synthetic_review_prototype"
SECOND_MIGRATION_PATH = MIGRATION_PATH.with_name(SECOND_MIGRATION_NAME + ".py")
SECOND_MIGRATION_SHA256 = "0b17355ca04f2cc39a2535d52573c0130ea44256d725f813e6bc4cff53952cf4"
MIGRATIONS = (("solutions", MIGRATION_NAME), ("solutions", SECOND_MIGRATION_NAME))
MODELS = ("ProblemEvaluationPackage", "EvaluationPackageApproval", "SyntheticReview", "SyntheticHintReveal")
TABLES = frozenset("solutions_" + name.lower() for name in MODELS)
OPERATION_SEQUENCES = (["CreateModel"] * 2 + ["AddConstraint"] * 3, ["CreateModel"] * 2 + ["AddConstraint"] * 4)
EXPECTED_PLAN = [
    (app, name, False, operations) for (app, name), operations in zip(MIGRATIONS, OPERATION_SEQUENCES, strict=True)
]
PRIOR_MIGRATIONS = {
    "0010_offline_evaluation_contract.py": "9fee1f590a8cdde9df9d30c201a49caea20a5c31efe2f4b0aa7c92171d4844a8",
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
    return base_smoke_command().replace(
        "import django",
        "settings.SYNTHETIC_REVIEW_PROTOTYPE_ENABLED=False\nimport django",
        1,
    )


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()
PLAN_CHECK = f"""from django.conf import settings
if (settings.SOLUTION_AI_REVIEW_ENABLED or settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED
    or getattr(settings, "SYNTHETIC_REVIEW_PROTOTYPE_ENABLED", False)):
    raise RuntimeError('AI must remain disabled for the offline evaluation release')
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected={EXPECTED_PLAN!r}
if actual != expected:
    raise RuntimeError('Unapproved pending migration plan')
from django.db.models import Q
from inspinia.solutions.models import SolutionReviewPolicy
if SolutionReviewPolicy.objects.filter(
    Q(enabled=True) | ~Q(daily_budget_micros=0) | ~Q(monthly_budget_micros=0)
).exists():
    raise RuntimeError('Review policy must remain disabled and unfunded')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('solutions','{SECOND_MIGRATION_NAME}')])\n"


class AssessmentPrototypeSchemaError(ConceptSchemaError):
    pass


def _validate_fingerprints(value: dict[str, Any]) -> None:
    for stage in ("starting", "expected"):
        state = value[stage]
        if not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS):
            raise AssessmentPrototypeSchemaError("Invalid schema fingerprint fields")
        if any(not isinstance(v, str) or not DIGEST.fullmatch(v) for v in state.values()):
            raise AssessmentPrototypeSchemaError("Invalid schema fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise AssessmentPrototypeSchemaError("The approved additive migration must change each fingerprint")


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
        raise AssessmentPrototypeSchemaError("Invalid bounded schema disclosure")
    if value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256:
        raise AssessmentPrototypeSchemaError("Migration is outside the approved scope")
    if (
        not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise AssessmentPrototypeSchemaError("Schema disclosure release identity mismatch")
    for field in ("postgresql_rehearsal_sha256", "compatibility_smoke_sha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise AssessmentPrototypeSchemaError("Schema rehearsal and compatibility evidence must be frozen")
    if value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256:
        raise AssessmentPrototypeSchemaError("Evaluation compatibility smoke differs from the approved fixed command")
    _validate_fingerprints(value)
    if len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise AssessmentPrototypeSchemaError("Schema disclosure exceeds its bound")
    return value


def validate_candidate(release: Path) -> None:
    paths = {MIGRATION_PATH: MIGRATION_SHA256, SECOND_MIGRATION_PATH: SECOND_MIGRATION_SHA256}
    paths.update({MIGRATION_PATH.parent / name: digest for name, digest in PRIOR_MIGRATIONS.items()})
    for relative, digest in paths.items():
        path = release / relative
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise AssessmentPrototypeSchemaError("Candidate migration bytes differ from the frozen solution plan")


def audit_matches(disclosure: dict[str, Any], audit: dict[str, Any], *, stage: str) -> bool:
    return audit.get("server_version_num") == POSTGRES_VERSION and all(
        audit.get(field) == disclosure[stage][field] for field in FINGERPRINT_FIELDS
    )


def validate_build_evidence(release: Path, disclosure: dict[str, Any]) -> None:
    import json

    path = release / EVIDENCE_PATH
    if path.is_symlink() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise AssessmentPrototypeSchemaError("Invalid packaged schema evidence")
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise AssessmentPrototypeSchemaError("Invalid packaged schema evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise AssessmentPrototypeSchemaError("Packaged prototype proof digest does not match its disclosure")
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
        "synthetic_prototype_disabled": True,
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
            "synthetic_prototype_disabled",
        )
    ):
        raise AssessmentPrototypeSchemaError("Packaged PostgreSQL schema evidence does not match this release")


def expected_catalog_audit(start: dict[str, Any], rehearsal: dict[str, Any]) -> dict[str, Any]:
    """Append the rehearsed four-table delta to catalog metadata, without production data."""
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise AssessmentPrototypeSchemaError("Starting audit identity/version does not match the approved target")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    delta = normalize_schema_snapshot(rehearsal)
    if schema_state(delta)["fingerprint"] != DELTA_SHA256:
        raise AssessmentPrototypeSchemaError("Schema delta differs from the approved rehearsal")
    if any(row["table"] in TABLES for row in before["tables"]):
        raise AssessmentPrototypeSchemaError("Evaluation table already exists")
    if {row["table"] for row in delta["tables"]} != TABLES or delta["extensions"]:
        raise AssessmentPrototypeSchemaError("Rehearsal delta is not exactly the four approved tables")
    if any(row["table"] not in TABLES for field in ("columns", "constraints", "indexes") for row in delta[field]):
        raise AssessmentPrototypeSchemaError("Rehearsal delta changes an existing schema object")
    if not any(row["schema"] == "public" and row["table"] == "solutions_solutionrevision" for row in before["tables"]):
        raise AssessmentPrototypeSchemaError("Existing document revision table is required")
    migrations = start["migration_rows"]
    if ["solutions", "0010_offline_evaluation_contract"] not in migrations:
        raise AssessmentPrototypeSchemaError("The previous solution migration must already be recorded")
    if any(list(migration) in migrations for migration in MIGRATIONS):
        raise AssessmentPrototypeSchemaError("The approved migration is already recorded")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise AssessmentPrototypeSchemaError("Starting catalog evidence does not match its fingerprints")
    combined = {field: [*before[field], *delta[field]] for field in before}
    state = {
        **start["state"],
        "schema": schema_state(combined),
        "migration": migration_state([*migrations, *[list(migration) for migration in MIGRATIONS]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
