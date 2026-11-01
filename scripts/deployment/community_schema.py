# ruff: noqa: EM101, TRY003
"""Exact community maintenance allowance after the statement-reporting release."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from scripts.deployment import catalogue_schema
from scripts.deployment import solution_pdf_schema
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state

KIND = "community-problems-maintenance-v1"
MIGRATIONS = ("0042_community_problems", "0043_statement_similarity_source")
MIGRATION_CLASSES = ("backward-compatible-schema", "data-or-non-compatible")
INPUT_HASHES = {
    "inspinia/pages/migrations/0042_community_problems.py": (
        "6d0e0da75b317154aa1102922e08f04387bff62bd1d5ecd485d416619de07b93"
    ),
    "inspinia/pages/migrations/0043_statement_similarity_source.py": (
        "0c13e1213ecf0686fbd966d22a387438b2ea2b805f932e2afd1fd35ff552dab7"
    ),
}
INITIALIZATION_HASHES = {
    "inspinia/pages/statement_similarity.py": "36791ecacdb560540ecbc81800fcf956e5337dfcd35e7887b3c951f2800a0a7e",
    "inspinia/pages/community_models.py": "0fdb9d1bc7bc65c10fb8c9e3c0a7cc3ee1372a730647d37a3fed1b6b1a7e9077",
    "inspinia/pages/management/commands/refresh_statement_similarity_index.py": (
        "5b9484b8e6973c7db32aa5f1e3e1a7980836fae7157e067d9c98c6841cd9cd78"
    ),
}
TABLES = frozenset(
    "pages_" + name
    for name in (
        "statementreviewpolicy",
        "statementsimilarityindex",
        "communityproblem",
        "communityproblemreview",
        "statementsimilaritydocument",
        "statementaireview",
        "statementsimilarityterm",
        "statementsimilaritysource",
    )
)
DELTA_SHA256 = "5207935ea199048e58e8e7796ca79a39757826e976fe139bc1eb33e9178970da"
BEHAVIOUR_SHA256 = "5d0c68e538f93cc53c865d7e06b18042a5c4e240651f04fb4b8399fa6fd3d698"
POSTGRES_VERSION = 170009
FINGERPRINT_FIELDS = catalogue_schema.FINGERPRINT_FIELDS
RECOVERY_POLICY = catalogue_schema.RECOVERY_POLICY
EVIDENCE_PATH = "deployment-schema-evidence.json"
DELTA_PATH = Path("scripts/deployment/tests/fixtures/community-schema-delta.json")
MAX_DISCLOSURE_BYTES = 8192
FUNCTION_SQL = catalogue_schema.FUNCTION_SQL.replace(
    "p.proname='asterproof_catalogue_revision'",
    "p.proname IN ('asterproof_catalogue_revision','asterproof_statement_similarity_revision')",
)
TRIGGERS_SQL = catalogue_schema.TRIGGERS_SQL.replace(
    "left(t.tgname,13) = 'ap_catalogue_'",
    "(left(t.tgname,13) = 'ap_catalogue_' OR t.tgname='ap_statement_similarity_revision')",
)
FLAGS = (
    "schema_delta_exact",
    "source_fixture_unchanged",
    "existing_records_unchanged",
    "existing_sequences_unchanged",
    "existing_trigger_definitions_unchanged",
    "active_revision_smoke_passed",
    "runtime_invalidation_passed",
    "index_ready",
    "ai_review_disabled",
    "authenticated_routes_passed",
)
PLAN_CHECK = f"""from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
if getattr(settings, 'PROBLEM_STATEMENT_AI_REVIEW_ENABLED', False) is not False:
    raise RuntimeError('Community AI review must remain disabled')
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected=[('pages','{MIGRATIONS[0]}',False,['CreateModel']*7),
          ('pages','{MIGRATIONS[1]}',False,['CreateModel','RunPython'])]
if actual != expected:
    raise RuntimeError('Pending migrations differ from the frozen community plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('pages','{MIGRATIONS[-1]}')])\n"
INDEX_CHECK = """from django.conf import settings
from inspinia.pages.community_models import StatementReviewPolicy, StatementAIReview
from inspinia.pages.statement_similarity import index_ready
if getattr(settings, 'PROBLEM_STATEMENT_AI_REVIEW_ENABLED', False) is not False:
    raise RuntimeError('Community AI review must remain disabled')
if StatementReviewPolicy.objects.filter(enabled=True).exists() or StatementAIReview.objects.exists():
    raise RuntimeError('Community AI review policy/jobs must remain inactive')
if not index_ready():
    raise RuntimeError('Community similarity index is not current')
"""


def smoke_command():
    return solution_pdf_schema.smoke_command()


def validate_candidate(release: Path) -> None:
    for name, expected in {**INPUT_HASHES, **INITIALIZATION_HASHES}.items():
        path = release / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Community migration or initialization source differs from its frozen hash")


def behaviour_snapshot(connection):
    with connection.cursor() as cursor:
        cursor.execute(FUNCTION_SQL)
        functions = [list(row) for row in cursor.fetchall()]
        cursor.execute(TRIGGERS_SQL)
        triggers = [list(row) for row in cursor.fetchall()]
    return {"functions": functions, "triggers": triggers}


def rehearsal_evidence(*, release_sha: str, active_sha: str) -> dict:
    return {
        "format_version": 1,
        "source_sha": release_sha,
        "active_sha": active_sha,
        "postgres_version": POSTGRES_VERSION,
        "input_hashes": INPUT_HASHES,
        "initialization_hashes": INITIALIZATION_HASHES,
        "delta_sha256": DELTA_SHA256,
        "behaviour_sha256": BEHAVIOUR_SHA256,
        **dict.fromkeys(FLAGS, True),
    }


def evidence_bytes(*, release_sha: str, active_sha: str) -> bytes:
    return (
        json.dumps(rehearsal_evidence(release_sha=release_sha, active_sha=active_sha), sort_keys=True, indent=2) + "\n"
    ).encode()


def validate_rehearsal_evidence(value, *, release_sha, active_sha):
    if (
        not isinstance(value, dict)
        or type(value.get("format_version")) is not int
        or type(value.get("postgres_version")) is not int
        or value != rehearsal_evidence(release_sha=release_sha, active_sha=active_sha)
        or any(value.get(field) is not True for field in FLAGS)
    ):
        raise ValueError("Community rehearsal evidence does not match the exact release")


def validate_disclosure(value: object, *, target_sha: str) -> dict:
    fields = {
        "format_version",
        "kind",
        "active_sha",
        "target_sha",
        "input_hashes",
        "starting",
        "expected",
        "postgresql_rehearsal_sha256",
        "recovery_policy",
    }
    if not isinstance(value, dict) or set(value) != fields or type(value["format_version"]) is not int:
        raise ValueError("Malformed community maintenance disclosure")
    if value["format_version"] != 1 or value["kind"] != KIND or value["input_hashes"] != INPUT_HASHES:
        raise ValueError("Community maintenance is outside its frozen scope")
    if (
        not isinstance(target_sha, str)
        or not re.fullmatch(r"[0-9a-f]{40}", target_sha)
        or not isinstance(value["active_sha"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", value["active_sha"])
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise ValueError("Community maintenance release identity mismatch")
    for stage in ("starting", "expected"):
        data = value[stage]
        if (
            not isinstance(data, dict)
            or set(data) != set(FINGERPRINT_FIELDS)
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in data.values())
        ):
            raise ValueError("Invalid community maintenance fingerprints")
    if (
        value["starting"]["behaviour_fingerprint"] != catalogue_schema.BEHAVIOUR_SHA256
        or value["expected"]["behaviour_fingerprint"] != BEHAVIOUR_SHA256
        or any(value["starting"][key] == value["expected"][key] for key in FINGERPRINT_FIELDS)
    ):
        raise ValueError("Community maintenance requires the frozen starting and ending behaviour")
    policy = value["recovery_policy"]
    if (
        not isinstance(policy, dict)
        or policy != RECOVERY_POLICY
        or any(type(policy[key]) is not type(expected) for key, expected in RECOVERY_POLICY.items())
    ):
        raise ValueError("Community maintenance requires the unchanged verified-recovery policy")
    proof_digest = hashlib.sha256(evidence_bytes(release_sha=target_sha, active_sha=value["active_sha"])).hexdigest()
    if value["postgresql_rehearsal_sha256"] != proof_digest or len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise ValueError("Community maintenance rehearsal digest differs from the exact release")
    return value


def validate_build_evidence(release: Path, disclosure: dict) -> None:
    path = release / EVIDENCE_PATH
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise ValueError("Invalid packaged community rehearsal proof")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise ValueError("Packaged community rehearsal digest differs")
    validate_rehearsal_evidence(
        json.loads(data),
        release_sha=disclosure["target_sha"],
        active_sha=disclosure["active_sha"],
    )


def expected_catalog_audit(start: dict, delta: dict) -> dict:
    if (
        start.get("server_version_num") != POSTGRES_VERSION
        or (hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"])
        or start.get("behaviour_fingerprint") != catalogue_schema.BEHAVIOUR_SHA256
    ):
        raise ValueError("Starting community audit identity/version/behaviour mismatch")
    before, delta = normalize_schema_snapshot(start["catalog_snapshot"]), normalize_schema_snapshot(delta)
    if schema_state(delta)["fingerprint"] != DELTA_SHA256 or {r["table"] for r in delta["tables"]} != TABLES:
        raise ValueError("Community schema delta differs from the frozen rehearsal")
    if delta["extensions"] or any(r["table"] in TABLES for r in before["tables"]):
        raise ValueError("Community schema already exists or changes extensions")
    if any(row["table"] not in TABLES for field in ("columns", "constraints", "indexes") for row in delta[field]):
        raise ValueError("Community delta modifies an existing schema object")
    migrations = start["migration_rows"]
    if any(["pages", name] in migrations for name in MIGRATIONS):
        raise ValueError("Community migration baseline has already advanced")
    if ["pages", "0041_statement_issue_reports"] not in migrations:
        raise ValueError("Community requires its statement-reporting baseline")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise ValueError("Starting community metadata differs from its fingerprints")
    state = {
        **start["state"],
        "schema": schema_state({field: [*before[field], *delta[field]] for field in before}),
        "migration": migration_state([*migrations, *[["pages", name] for name in MIGRATIONS]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
        "behaviour_fingerprint": BEHAVIOUR_SHA256,
    }
