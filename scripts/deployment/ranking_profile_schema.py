# ruff: noqa: EM101, EM102, TRY003
"""Frozen data-class allowance for exactly two empty achievement metadata tables."""

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

MIGRATION = "rankings.0006_student_achievement_profiles"
MIGRATION_NAME = MIGRATION.split(".", 1)[1]
KIND = "ranking-profile-maintenance-v1"
RECOVERY_POLICY = {"rpo_seconds": 0, "max_age_seconds": 1800, "isolated": True, "encrypted": True}
MODELS = ("ResultClaim", "ResultProfile")
OPERATIONS = [
    ("AlterField", "kind", "rankingcorrectionitem"),
    ("CreateModel", "ResultClaim", None),
    ("CreateModel", "ResultProfile", None),
]
TABLES = frozenset(f"rankings_{name.lower()}" for name in MODELS)
MIGRATION_PATH = Path("inspinia/rankings/migrations/0006_student_achievement_profiles.py")
MIGRATION_SHA256 = "e5cf53b69329c6c21f3caa9523c3c495a71638f338b4f825b563d172c0d19898"
DELTA_SHA256 = "1e39e6ff9903566f6307ed52cb45d8a2b1e464d6131bec19f441918ea29409ba"
EVIDENCE_PATH = "deployment-schema-evidence.json"
POSTGRES_VERSION = 170009
PRIOR_MIGRATIONS = {
    "0001_initial.py": "6bf03bd54a1b4d4f2af7a4fa5a668f10b4322c269afe114d663f8c63cef63e41",
    "0002_alter_assessment_category_and_more.py": "a18bcec950d604e6a97ed3117efabd264ba048dcf0f756498b9c4b88453ea429",
    "0003_importbatch_importrowissue_rankingsnapshot_and_more.py": (
        "1635489bd12f0db4bc766e62fd8f9bf028f8596c8d32066cc7a30ec8091a7695"
    ),
    "0004_remove_rankingsnapshot_rank_snap_season_idx_and_more.py": (
        "8bc96cf15d2ba931e0991a17f60f88d05253af0b7b03e121a0cf00a6b8c566f0"
    ),
    "0005_ranking_analysis_review.py": "50d20a01e577cd06d889b10bd606acd039bbe8534117c8e7a73353a087836499",
}
DIGEST = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_FIELDS = ("state_fingerprint", "schema_fingerprint", "migration_fingerprint")
MAX_DISCLOSURE_BYTES = 8192


def smoke_command():
    return (
        (
            "from django.conf import settings\n"
            "settings.SYNTHETIC_REVIEW_PROTOTYPE_ENABLED=False\n" + base_smoke_command()
        )
        + """
from inspinia.solutions.models import ProblemSolution, SolutionReviewPolicy
from django.conf import settings
if (settings.SOLUTION_AI_REVIEW_ENABLED or settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED
    or settings.SYNTHETIC_REVIEW_PROTOTYPE_ENABLED):
    raise RuntimeError('AI must remain disabled during compatibility smoke')
solution=ProblemSolution.objects.get(title='Synthetic preserved solution')
if solution.blocks.get().body_source != 'Synthetic preserved proof.':
    raise RuntimeError('Active revision block read failed')
if (solution.edit_version != 7 or solution.current_revision.sequence != 1
    or solution.current_revision.body_source != 'Synthetic immutable document before the evaluation migration.'):
    raise RuntimeError('Active revision document read failed')
from inspinia.solutions.image_access import internal_image_base_url
if '/solutions/entries/' not in internal_image_base_url(solution.pk):
    raise RuntimeError('Active release does not provide the image-aware recovery baseline')
if SolutionReviewPolicy.objects.filter(enabled=True).exists():
    raise RuntimeError('Review policy must remain disabled')
from decimal import Decimal
from django.test import RequestFactory
from inspinia.rankings.models import StudentResult
from inspinia.rankings.result_views import assessment_results_view, result_history_view
from inspinia.users.models import User
rows=list(StudentResult.objects.filter(assessment__code='RANKING_SCHEMA_SYNTHETIC').order_by('raw_score'))
if len(rows)!=2 or rows[0].raw_score != Decimal(0) or rows[0].student_id == rows[1].student_id:
    raise RuntimeError('Preserved ranking zero score or separate identities changed')
actor=User.objects.get(email='schema-rehearsal@example.invalid')
actor.role='moderator'
for view, path, params in (
    (assessment_results_view, '/rankings/results/', {'assessment': rows[0].assessment_id}),
    (result_history_view, '/rankings/history/', {'season':2026}),
):
    request=RequestFactory().get(path, params)
    request.user=actor
    response=view(request)
    if response.status_code != 200 or b'Synthetic Separate Student' not in response.content:
        raise RuntimeError('Active revision ranking read failed')
from inspinia.rankings.views import student_detail_view
request=RequestFactory().get('/rankings/students/' + str(rows[0].student_id) + '/', {'type':'scores'})
request.user=actor
response=student_detail_view(request, rows[0].student_id)
if (response.status_code != 200 or b'Synthetic Separate Student' not in response.content
    or b'0.00' not in response.content):
    raise RuntimeError('Active revision student profile read failed')
from inspinia.rankings.correction_views import correction_queue
request=RequestFactory().get('/rankings/analysis/corrections/', {'status':'all'})
request.user=actor
response=correction_queue(request)
if response.status_code != 200 or b'Synthetic preserved review' not in response.content:
    raise RuntimeError('Active revision correction reader failed')
"""
    )


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()
PLAN_CHECK = f"""from django.conf import settings
if (settings.SOLUTION_AI_REVIEW_ENABLED or settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED
    or settings.SYNTHETIC_REVIEW_PROTOTYPE_ENABLED):
    raise RuntimeError('AI must remain disabled for the offline ranking profile release')
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[(type(o).__name__,getattr(o,'name',None),getattr(o,'model_name',None))
                            for o in m.operations]) for m,b in plan]
expected=[('rankings','{MIGRATION_NAME}',False,{OPERATIONS!r})]
if actual != expected:
    raise RuntimeError('Unapproved pending migration plan')
from django.db.models import Q
from inspinia.solutions.models import SolutionReviewPolicy
if SolutionReviewPolicy.objects.filter(
    Q(enabled=True) | ~Q(daily_budget_micros=0) | ~Q(monthly_budget_micros=0)
).exists():
    raise RuntimeError('Review policy must remain disabled and unfunded')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('rankings','{MIGRATION_NAME}')])\n"


class RankingProfileSchemaError(ConceptSchemaError):
    pass


def _validate_fingerprints(value: dict[str, Any]) -> None:
    for stage in ("starting", "expected"):
        state = value[stage]
        if not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS):
            raise RankingProfileSchemaError("Invalid schema fingerprint fields")
        if any(not isinstance(v, str) or not DIGEST.fullmatch(v) for v in state.values()):
            raise RankingProfileSchemaError("Invalid schema fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise RankingProfileSchemaError("The approved additive migration must change each fingerprint")


def _validate_recovery_policy(policy):
    if (not isinstance(policy, dict) or policy != RECOVERY_POLICY
        or any(type(policy[key]) is not type(expected) for key, expected in RECOVERY_POLICY.items())):
        raise RankingProfileSchemaError("Ranking profile maintenance requires fixed verified recovery")


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
    fields |= {"kind", "recovery_policy"}
    if (not isinstance(value, dict) or set(value) != fields
        or type(value["format_version"]) is not int or value["format_version"] != 1):
        raise RankingProfileSchemaError("Invalid bounded schema disclosure")
    if value["kind"] != KIND:
        raise RankingProfileSchemaError("Ranking profile maintenance is outside the approved scope")
    _validate_recovery_policy(value["recovery_policy"])
    if value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256:
        raise RankingProfileSchemaError("Migration is outside the approved scope")
    if (
        not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not isinstance(target_sha, str) or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise RankingProfileSchemaError("Schema disclosure release identity mismatch")
    for field in ("postgresql_rehearsal_sha256", "compatibility_smoke_sha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise RankingProfileSchemaError("Schema rehearsal and compatibility evidence must be frozen")
    if value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256:
        raise RankingProfileSchemaError(
            "Ranking profile compatibility smoke differs from the approved fixed command",
        )
    expected_proof = hashlib.sha256(evidence_bytes(release_sha=target_sha, active_sha=value["active_sha"])).hexdigest()
    if value["postgresql_rehearsal_sha256"] != expected_proof:
        raise RankingProfileSchemaError("Profile rehearsal digest differs from the exact release proof")
    _validate_fingerprints(value)
    if len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise RankingProfileSchemaError("Schema disclosure exceeds its bound")
    return value


def validate_candidate(release: Path) -> None:
    paths = {MIGRATION_PATH: MIGRATION_SHA256}
    paths.update({MIGRATION_PATH.parent / name: digest for name, digest in PRIOR_MIGRATIONS.items()})
    for relative, digest in paths.items():
        path = release / relative
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RankingProfileSchemaError("Candidate migration bytes differ from the frozen ranking plan")


def audit_matches(disclosure: dict[str, Any], audit: dict[str, Any], *, stage: str) -> bool:
    return audit.get("server_version_num") == POSTGRES_VERSION and all(
        audit.get(field) == disclosure[stage][field] for field in FINGERPRINT_FIELDS
    )


def rehearsal_evidence(*, release_sha, active_sha):
    return {
        "format_version": 1,
        "source_sha": release_sha,
        "active_sha": active_sha,
        "postgres_version": POSTGRES_VERSION,
        "migration_file_sha256": MIGRATION_SHA256,
        "delta_sha256": DELTA_SHA256,
        "existing_schema_unchanged": True,
        "source_fixture_unchanged": True,
        "active_revision_smoke_passed": True,
        "existing_records_unchanged": True,
        "existing_sequences_unchanged": True,
        "new_review_tables_empty": True,
        "existing_trigger_definitions_unchanged": True,
        "existing_privileges_unchanged": True,
        "ai_disabled_and_unfunded": True,
    }


def evidence_bytes(*, release_sha, active_sha):
    import json

    value = rehearsal_evidence(release_sha=release_sha, active_sha=active_sha)
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def validate_build_evidence(release: Path, disclosure: dict[str, Any]) -> None:
    import json

    path = release / EVIDENCE_PATH
    if path.is_symlink() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise RankingProfileSchemaError("Invalid packaged schema evidence")
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise RankingProfileSchemaError("Invalid packaged schema evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise RankingProfileSchemaError(
            "Packaged ranking profile rehearsal proof digest does not match its disclosure",
        )
    expected = rehearsal_evidence(release_sha=disclosure["target_sha"], active_sha=disclosure["active_sha"])
    if not isinstance(value, dict) or type(value.get("format_version")) is not int or value != expected or any(
        value[field] is not True
        for field in (
            "existing_schema_unchanged",
            "source_fixture_unchanged",
            "active_revision_smoke_passed",
            "existing_records_unchanged",
            "existing_sequences_unchanged",
            "new_review_tables_empty",
            "existing_trigger_definitions_unchanged",
            "existing_privileges_unchanged",
            "ai_disabled_and_unfunded",
        )
    ):
        raise RankingProfileSchemaError("Packaged PostgreSQL schema evidence does not match this release")


def expected_catalog_audit(start: dict[str, Any], rehearsal: dict[str, Any]) -> dict[str, Any]:
    """Append only the rehearsed two-table delta to catalog metadata, without production data."""
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise RankingProfileSchemaError("Starting audit identity/version does not match the approved target")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    delta = normalize_schema_snapshot(rehearsal)
    if schema_state(delta)["fingerprint"] != DELTA_SHA256:
        raise RankingProfileSchemaError("Schema delta differs from the approved rehearsal")
    if any(row["table"] in TABLES for row in before["tables"]):
        raise RankingProfileSchemaError("Ranking profile table already exists")
    if {row["table"] for row in delta["tables"]} != TABLES or delta["extensions"]:
        raise RankingProfileSchemaError("Rehearsal delta is not exactly the two approved tables")
    if any(row["table"] not in TABLES for field in ("columns", "constraints", "indexes") for row in delta[field]):
        raise RankingProfileSchemaError("Rehearsal delta changes an existing schema object")
    if not any(row["schema"] == "public" and row["table"] == "rankings_studentresult" for row in before["tables"]):
        raise RankingProfileSchemaError("Existing ranking result table is required")
    migrations = start["migration_rows"]
    if ["rankings", "0005_ranking_analysis_review"] not in migrations:
        raise RankingProfileSchemaError("The previous ranking migration must already be recorded")
    if ["rankings", MIGRATION_NAME] in migrations:
        raise RankingProfileSchemaError("The approved migration is already recorded")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise RankingProfileSchemaError("Starting catalog evidence does not match its fingerprints")
    combined = {field: [*before[field], *delta[field]] for field in before}
    state = {
        **start["state"],
        "schema": schema_state(combined),
        "migration": migration_state([*migrations, ["rankings", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
