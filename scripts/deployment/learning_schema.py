# ruff: noqa: EM101, EM102, TRY003, S608
# Generated SQL interpolates only the frozen table-name set, never request data.
"""Frozen additive Training schema; activation requires separately installed authority.

The schema establishes a durable learning-reader floor even while every new
content table is empty. Ordinary previous readers are not recovery targets.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path  # noqa: TC003
from typing import Any

from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.schema_fingerprint import FingerprintError
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import REHEARSAL_DATABASE

MIGRATION = "learning.0002_contentdraft_is_archived"
POSTGRES_VERSION = 170009
MIGRATIONS = (
    ("pages", "0045_prerequisitegraphstate_catalogueprerequisite"),
    ("learning", "0001_initial"),
    ("learning", "0002_contentdraft_is_archived"),
    ("training", "0006_learningpath_learningpathrevision_learningpathitem_and_more"),
)
BASE_TARGETS = (
    ("pages", "0044_learning_page_activity"),
    ("training", "0005_subtopic_imo_syllabus_index"),
)
MIGRATION_FILES = {
    "inspinia/pages/migrations/0045_prerequisitegraphstate_catalogueprerequisite.py": (
        "8cfafa4d52e98e17c3a0930d60251aa3c537f300a32a91bc47b648ab7ef0e4bb"
    ),
    "inspinia/learning/migrations/0001_initial.py": "11ce1e1e8c426d5608c974f90d762b218035ad2feed3fda3121f4e1433825521",
    "inspinia/learning/migrations/0002_contentdraft_is_archived.py": (
        "00c085d8ceba6ea39f24b7221512a4bdd0992e90e861d1336c2012d607fb1f29"
    ),
    "inspinia/training/migrations/0006_learningpath_learningpathrevision_learningpathitem_and_more.py": (
        "7114439e759c0ae8c239c4011b678c9106d33f00543c0e3119fe5566102d432b"
    ),
}
MIGRATION_SHA256 = hashlib.sha256(canonical_json(MIGRATION_FILES)).hexdigest()
# Freeze only from normalized actual PostgreSQL 17.9 catalog output.
DELTA_SHA256 = "351ffd6792fc2dfbcd3f670cd78576391f7ebaeced08d7ff317bd3ad19603c24"
APPROVED_POSTGRESQL_DELTA_SHA256 = DELTA_SHA256
PRIOR_MIGRATION_SOURCE_SHA256 = "b4e68a1ea6411837d3047545a24d8d885e4969572ce37109a1e72263e7869f67"
PRIOR_MIGRATION_SOURCE_COUNT = 92
MIGRATION_SUPPORT_FILES = {
    "inspinia/learning/migrations/__init__.py": hashlib.sha256(b"").hexdigest(),
}
EVIDENCE_PATH = "deployment-schema-evidence.json"
REQUIRED_LEARNING_READER = 1
DIGEST = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_FIELDS = ("state_fingerprint", "schema_fingerprint", "migration_fingerprint")
MAX_DISCLOSURE_BYTES = 8192
TABLES = {
    "pages_prerequisitegraphstate",
    "pages_catalogueprerequisite",
    "learning_contentdocument",
    "learning_contentasset",
    "learning_contentassetgrant",
    "learning_contentaction",
    "learning_contentrevision",
    "learning_contentissue",
    "learning_contentdraft",
    "learning_contributionproposal",
    "learning_contributorpermission",
    "learning_legacycontentlink",
    "learning_revisionasset",
    "learning_revisionconcept",
    "learning_contentpublication",
    "training_learningpath",
    "training_learningpathrevision",
    "training_learningpathitem",
    "training_pathreading",
    "training_contentpackimport",
}
REQUIRED_BASE_MIGRATIONS = (
    *BASE_TARGETS,
    ("website", "0003_newsletter_automation"),
    ("solutions", "0010_offline_evaluation_contract"),
)
REQUIRED_BASE_TABLES = {
    "pages_catalogueconcept",
    "training_material",
    "website_librarylecture",
    "solutions_problemsolution",
    "users_user",
    "website_newslettersubscriber",
}
PRESERVATION_FIELDS = (
    "existing_schema_unchanged",
    "source_fixture_unchanged",
    "active_revision_smoke_passed",
    "existing_records_unchanged",
    "existing_sequences_unchanged",
    "existing_trigger_definitions_unchanged",
    "new_learning_tables_empty",
    "empty_schema_reader_floor",
)
OPERATION_SEQUENCES = (
    ["CreateModel"] * 2,
    ["CreateModel"] * 13 + ["AddConstraint"] * 13,
    ["AddField"],
    ["CreateModel"] * 3 + ["AddField"] + ["CreateModel"] * 2 + ["AddConstraint"] * 7,
)


class LearningSchemaError(ConceptSchemaError):
    pass


def smoke_command():
    """Preserved legacy reads only; this never declares an old reader activatable."""
    return f"""from django.conf import settings
settings.DATABASES={{'default': {REHEARSAL_DATABASE!r}}}
settings.CONCEPT_ASSIGNMENTS_ENABLED=False
import django
django.setup()
from django.core.management import call_command
from inspinia.training.models import Material,MaterialCompletion,PointLedger,Submission
from inspinia.solutions.models import ProblemSolution,SolutionPublicShare
from inspinia.website.models import LibraryLecture,NewsletterSubscriber
call_command('check')
if Material.objects.filter(slug__startswith='learning-preserved-').count() != 5:
    raise RuntimeError('Previous Training reader lost a subject or Foundations')
if MaterialCompletion.objects.count() != 5 or PointLedger.objects.count() != 5 or Submission.objects.count() != 5:
    raise RuntimeError('Previous Training progress identity changed')
if LibraryLecture.objects.filter(slug='learning-preserved',is_published=True).count() != 4:
    raise RuntimeError('Previous public lecture reader changed')
solution=ProblemSolution.objects.get(title='Synthetic preserved solution')
if solution.blocks.get().body_source != 'Synthetic private original proof.':
    raise RuntimeError('Previous solution reader changed')
if SolutionPublicShare.objects.get(solution=solution).snapshot.get('body') != 'Synthetic fixed public copy.':
    raise RuntimeError('Previous public solution snapshot changed')
if NewsletterSubscriber.objects.get(email='synthetic-subscriber@example.invalid').status != 'confirmed':
    raise RuntimeError('Previous subscriber state changed')
"""


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()
EXPECTED_PLAN = [
    (app, name, False, operations) for (app, name), operations in zip(MIGRATIONS, OPERATION_SEQUENCES, strict=True)
]
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
if connection.vendor != 'postgresql' or connection.pg_version != {POSTGRES_VERSION!r}:
    raise RuntimeError('Learning schema requires the pinned PostgreSQL 17.9 runtime')
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected={EXPECTED_PLAN!r}
if actual != expected:
    raise RuntimeError('Unapproved pending learning migration bundle')
"""
MIGRATION_APPLY = (
    PLAN_CHECK
    + f"""executor.migrate({list(MIGRATIONS)!r})
with connection.cursor() as cursor:
    for table in {sorted(TABLES)!r}:
        cursor.execute('SELECT count(*) FROM ' + connection.ops.quote_name(table))
        if cursor.fetchone() != (0,):
            raise RuntimeError('Learning schema unexpectedly created teaching content')
    cursor.execute(
        "SELECT to_regclass('public.learning_contentdocument') IS NOT NULL "
        "AND to_regclass('public.learning_contentpublication') IS NOT NULL "
        "AND to_regclass('public.learning_legacycontentlink') IS NOT NULL "
        "AND to_regclass('public.training_learningpath') IS NOT NULL"
    )
    if cursor.fetchone() != (True,):
        raise RuntimeError('Learning schema did not establish the durable compatible-reader floor')
"""
)


def _require_frozen_delta():
    if not isinstance(DELTA_SHA256, str) or not DIGEST.fullmatch(DELTA_SHA256):
        raise LearningSchemaError(
            "Learning production schema allowance is unavailable until its real PostgreSQL delta is frozen",
        )


def _file_hash(release, path):
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent == release or release in parent.parents):
        raise LearningSchemaError("Learning migration bytes cannot come from symlinks")
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise LearningSchemaError("Learning migration bytes are unavailable") from exc


def validate_candidate(release: Path) -> None:
    for relative, expected in {**MIGRATION_FILES, **MIGRATION_SUPPORT_FILES}.items():
        if _file_hash(release, release / relative) != expected:
            raise LearningSchemaError("Learning migration bytes differ from the frozen bundle")
    prior = {}
    for path in (release / "inspinia").rglob("*"):
        if path.name == "migrations" and path.is_symlink():
            raise LearningSchemaError("Learning migration directories cannot be symlinks")
        if path.parent.name != "migrations" or path.suffix not in {".py", ".json"}:
            continue
        relative = path.relative_to(release).as_posix()
        if relative not in MIGRATION_FILES and relative not in MIGRATION_SUPPORT_FILES:
            prior[relative] = _file_hash(release, path)
    if (
        len(prior) != PRIOR_MIGRATION_SOURCE_COUNT
        or hashlib.sha256(canonical_json(prior)).hexdigest() != PRIOR_MIGRATION_SOURCE_SHA256
    ):
        raise LearningSchemaError("Historical migration sources differ from the frozen learning baseline")


def _validate_fingerprints(value):
    for stage in ("starting", "expected"):
        state = value[stage]
        if not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS):
            raise LearningSchemaError("Invalid schema fingerprint fields")
        if any(not isinstance(item, str) or not DIGEST.fullmatch(item) for item in state.values()):
            raise LearningSchemaError("Invalid schema fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise LearningSchemaError("The learning migration must change each fingerprint")


def validate_disclosure(value: Any, *, target_sha: str) -> dict[str, Any]:
    _require_frozen_delta()
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
    ):
        raise LearningSchemaError("Invalid bounded schema disclosure")
    if value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256:
        raise LearningSchemaError("Migration is outside the approved learning scope")
    if (
        not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not isinstance(target_sha, str)
        or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise LearningSchemaError("Schema disclosure release identity mismatch")
    for field in ("postgresql_rehearsal_sha256", "compatibility_smoke_sha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise LearningSchemaError("Schema rehearsal and compatibility evidence must be frozen")
    if value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256:
        raise LearningSchemaError("Learning compatibility smoke differs from its frozen preservation command")
    _validate_fingerprints(value)
    if len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise LearningSchemaError("Schema disclosure exceeds its bound")
    return value


def audit_matches(disclosure, audit, *, stage):
    return (
        stage in {"starting", "expected"}
        and audit.get("server_version_num") == POSTGRES_VERSION
        and all(audit.get(field) == disclosure.get(stage, {}).get(field) for field in FINGERPRINT_FIELDS)
        and all(isinstance(audit.get(field), str) and DIGEST.fullmatch(audit[field]) for field in FINGERPRINT_FIELDS)
    )


def validate_build_evidence(release: Path, disclosure) -> None:
    validate_disclosure(disclosure, target_sha=disclosure.get("target_sha"))
    path = release / EVIDENCE_PATH
    try:
        if path.is_symlink() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
            raise LearningSchemaError("Invalid packaged learning schema evidence")
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, ValueError, UnicodeError) as exc:
        raise LearningSchemaError("Invalid packaged learning schema evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise LearningSchemaError("Packaged learning rehearsal digest does not match its disclosure")
    expected = {
        "format_version": 1,
        "source_sha": disclosure["target_sha"],
        "active_sha": disclosure["active_sha"],
        "postgres_version": POSTGRES_VERSION,
        "migration_file_sha256": MIGRATION_SHA256,
        "delta_sha256": DELTA_SHA256,
        "required_learning_reader": REQUIRED_LEARNING_READER,
        "ordinary_previous_reader_compatible": False,
        **dict.fromkeys(PRESERVATION_FIELDS, True),
    }
    if (
        value != expected
        or type(value.get("format_version")) is not int
        or type(value.get("required_learning_reader")) is not int
        or value.get("ordinary_previous_reader_compatible") is not False
        or any(value.get(field) is not True for field in PRESERVATION_FIELDS)
    ):
        raise LearningSchemaError("Packaged PostgreSQL learning evidence does not match this release")


def expected_catalog_audit(start, rehearsal):  # noqa: C901 - Explicit frozen-catalog boundary checks.
    """Append only the frozen new tables and four migration identities."""
    _require_frozen_delta()
    try:
        if (
            start.get("server_version_num") != POSTGRES_VERSION
            or hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
        ):
            raise LearningSchemaError("Starting audit identity/version differs from the reviewed target")
        before = normalize_schema_snapshot(start["catalog_snapshot"])
        delta = normalize_schema_snapshot(rehearsal)
        if schema_state(delta)["fingerprint"] != DELTA_SHA256:
            raise LearningSchemaError("Schema delta differs from the frozen PostgreSQL learning rehearsal")
        if {row["table"] for row in delta["tables"]} != TABLES or delta["extensions"]:
            raise LearningSchemaError("Rehearsal delta is not exactly the twenty new learning tables")
        if any(row["schema"] != "public" for key, rows in delta.items() if key != "extensions" for row in rows):
            raise LearningSchemaError("Learning delta is outside the public schema")
        if any(row["table"] not in TABLES for key in ("columns", "constraints", "indexes") for row in delta[key]):
            raise LearningSchemaError("Learning delta changes an existing schema object")
        existing_tables = {row["table"] for row in before["tables"] if row["schema"] == "public"}
        if existing_tables & TABLES or not existing_tables >= REQUIRED_BASE_TABLES:
            raise LearningSchemaError("Learning tables already exist or required preserved tables are missing")
        migrations = start["migration_rows"]
        if any(list(node) not in migrations for node in REQUIRED_BASE_MIGRATIONS):
            raise LearningSchemaError("The reviewed previous migration baseline must already be recorded")
        if any(list(node) in migrations for node in MIGRATIONS):
            raise LearningSchemaError("A learning migration is already recorded")
        if (
            schema_state(before) != start["state"]["schema"]
            or migration_state(migrations) != start["state"]["migration"]
        ):
            raise LearningSchemaError("Starting catalog evidence does not match its fingerprints")
        combined = {field: [*before[field], *delta[field]] for field in before}
        state = {
            **start["state"],
            "schema": schema_state(combined),
            "migration": migration_state([*migrations, *[list(node) for node in MIGRATIONS]]),
        }
    except (KeyError, TypeError, FingerprintError) as exc:
        raise LearningSchemaError("Malformed starting catalog or rehearsal evidence") from exc
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
