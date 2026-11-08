# ruff: noqa: EM101, TRY003 - Fixed errors identify the failed release gate.
"""Hash-bound production allowance for the two admin solution review tables."""

import hashlib
import json
from pathlib import Path

from scripts.deployment import solution_forum_schema as forum
from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state

MIGRATION = "solutions.0014_admin_solution_review"
MIGRATION_NAME = "0014_admin_solution_review"
MIGRATION_PATH = Path("inspinia/solutions/migrations") / f"{MIGRATION_NAME}.py"
MIGRATION_SHA256 = "e6864c8d676f119c9a974855260be82894139cf01af693ea3ce054b0b8cffad1"
DELTA_SHA256 = "9953a484111c4f3d58112582c500771c80d9b0c8c09b6be56d2f65638859da12"
POSTGRES_VERSION = forum.POSTGRES_VERSION
EVIDENCE_PATH = forum.EVIDENCE_PATH
TABLES = frozenset({"solutions_adminsolutionreview", "solutions_adminsolutionreviewsettings"})
OPERATIONS = [("CreateModel", "AdminSolutionReviewSettings"), ("CreateModel", "AdminSolutionReview")]
FINGERPRINT_FIELDS = forum.FINGERPRINT_FIELDS
PRESERVATION_FLAGS = (
    "existing_schema_unchanged",
    "existing_records_unchanged",
    "existing_sequences_unchanged",
    "existing_trigger_definitions_unchanged",
    "active_revision_smoke_passed",
    "new_admin_review_tables_empty",
    "admin_ai_generation_disabled",
)


def smoke_command():
    return forum.smoke_command() + """
from django.urls import reverse, resolve
from inspinia.solutions.forum_models import SolutionForumTarget
target = SolutionForumTarget.objects.get(solution=solution)
if target.snapshot['document']['source'] != solution.current_revision.body_source:
    raise RuntimeError('Active revision cannot read the prior forum snapshot')
url = reverse('solutions:solution_detail', args=[solution.pk])
if resolve(url).view_name != 'solutions:solution_detail':
    raise RuntimeError('Active revision solution route changed')
"""


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()
PLAN_CHECK = f"""from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
if settings.ADMIN_SOLUTION_REVIEW_ENABLED:
    raise RuntimeError('Admin review generation must be disabled during migration')
executor = MigrationExecutor(connection)
plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
actual = [(m.app_label, m.name, backwards, [(type(op).__name__, getattr(op, 'name', None))
          for op in m.operations]) for m, backwards in plan]
if actual != [('solutions', '{MIGRATION_NAME}', False, {OPERATIONS!r})]:
    raise RuntimeError('Unexpected admin review migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('solutions', '{MIGRATION_NAME}')])\n"


def validate_candidate(release):
    forum.validate_candidate(release)
    path = release / MIGRATION_PATH
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != MIGRATION_SHA256:
        raise ConceptSchemaError("Admin review migration does not match its frozen bytes")


def validate_disclosure(value, *, target_sha):
    fields = {
        "format_version", "active_sha", "target_sha", "migration", "migration_file_sha256", "starting", "expected",
        "postgresql_rehearsal_sha256", "compatibility_smoke_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields or type(value["format_version"]) is not int:
        raise ConceptSchemaError("Invalid admin review schema disclosure")
    identity = (value["format_version"], value["migration"], value["migration_file_sha256"])
    if identity != (1, MIGRATION, MIGRATION_SHA256):
        raise ConceptSchemaError("Admin review disclosure does not match the frozen migration")
    active = value["active_sha"]
    if (not isinstance(active, str) or not forum.SHA.fullmatch(active) or not forum.SHA.fullmatch(target_sha)
            or value["target_sha"] != target_sha or active == target_sha):
        raise ConceptSchemaError("Admin review disclosure has an invalid release identity")
    if (value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256
            or not isinstance(value["postgresql_rehearsal_sha256"], str)
            or not forum.DIGEST.fullmatch(value["postgresql_rehearsal_sha256"])):
        raise ConceptSchemaError("Admin review disclosure has invalid rehearsal evidence")
    forum._validate_fingerprints(value)  # noqa: SLF001 - same frozen fingerprint format
    return value


def audit_matches(disclosure, audit, *, stage):
    return forum.audit_matches(disclosure, audit, stage=stage)


def build_evidence(*, source_sha, active_sha):
    return {
        "format_version": 1,
        "source_sha": source_sha,
        "active_sha": active_sha,
        "postgres_version": POSTGRES_VERSION,
        "migration_file_sha256": MIGRATION_SHA256,
        "delta_sha256": DELTA_SHA256,
        **dict.fromkeys(PRESERVATION_FLAGS, True),
    }


def validate_build_evidence(release, disclosure):
    path = release / EVIDENCE_PATH
    if path.is_symlink() or path.stat().st_size > forum.MAX_DISCLOSURE_BYTES:
        raise ConceptSchemaError("Invalid admin review evidence file")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise ConceptSchemaError("Admin review rehearsal evidence digest differs")
    value = json.loads(content)
    expected = build_evidence(source_sha=disclosure["target_sha"], active_sha=disclosure["active_sha"])
    if value != expected or any(value[field] is not True for field in PRESERVATION_FLAGS):
        raise ConceptSchemaError("Admin review rehearsal did not prove the required preservation checks")


def expected_catalog_audit(start, rehearsal):
    """Compute post-migration fingerprints from catalog metadata and the frozen delta."""
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise ConceptSchemaError("Invalid starting catalog identity or PostgreSQL version")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    delta = normalize_schema_snapshot(rehearsal)
    if schema_state(delta)["fingerprint"] != DELTA_SHA256:
        raise ConceptSchemaError("Admin review catalog delta does not match its frozen digest")
    existing_tables = {row["table"] for row in before["tables"] if row["schema"] == "public"}
    if TABLES & existing_tables or "solutions_solutionforumtarget" not in existing_tables:
        raise ConceptSchemaError("Admin review tables already exist or their forum target table is absent")
    migrations = start["migration_rows"]
    if ["solutions", forum.MIGRATION_NAME] not in migrations or ["solutions", MIGRATION_NAME] in migrations:
        raise ConceptSchemaError("Admin review migration history does not match its predecessor")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise ConceptSchemaError("Starting catalog does not match its recorded fingerprints")
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
