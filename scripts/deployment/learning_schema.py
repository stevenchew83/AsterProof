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
    ("pages", "0046_prerequisitegraphstate_catalogueprerequisite"),
    ("learning", "0001_initial"),
    ("learning", "0002_contentdraft_is_archived"),
    ("training", "0006_learningpath_learningpathrevision_learningpathitem_and_more"),
)
BASE_TARGETS = (
    ("pages", "0045_community_proof_library"),
    ("training", "0005_subtopic_imo_syllabus_index"),
)
MIGRATION_FILES = {
    "inspinia/pages/migrations/0046_prerequisitegraphstate_catalogueprerequisite.py": (
        "39aaefdb7de8a53c2ec37379c9465cbccf3a07f6aeb477a4efcbefbdf47bf173"
    ),
    "inspinia/learning/migrations/0001_initial.py": "2918a6cd85ef8a8fafb28cd1c0ba4ec40969ccba85acdafa02d5c4e20a408656",
    "inspinia/learning/migrations/0002_contentdraft_is_archived.py": (
        "00c085d8ceba6ea39f24b7221512a4bdd0992e90e861d1336c2012d607fb1f29"
    ),
    "inspinia/training/migrations/0006_learningpath_learningpathrevision_learningpathitem_and_more.py": (
        "806b3b818aa97ba078e932b29094aed71026f64889b9d70d8d491ddd3caa4b1e"
    ),
}
MIGRATION_SHA256 = hashlib.sha256(canonical_json(MIGRATION_FILES)).hexdigest()
# Freeze only from normalized actual PostgreSQL 17.9 catalog output.
DELTA_SHA256 = "351ffd6792fc2dfbcd3f670cd78576391f7ebaeced08d7ff317bd3ad19603c24"
APPROVED_POSTGRESQL_DELTA_SHA256 = DELTA_SHA256
PRIOR_MIGRATION_SOURCE_SHA256 = "97c7440d16d6e7c258f5681c63c9d078506c3537312c710a0c7466f8bb40038a"
PRIOR_MIGRATION_SOURCE_COUNT = 93
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
    "pages_communityproblem",
    "pages_communityattempt",
    "pages_communitycontentreport",
    "pages_communityprivateasset",
    "pages_communityproblemrevision",
    "pages_communitysolution",
    "pages_communitysolutionasset",
    "pages_communitysolutionrevision",
    "pages_moderationevent",
    "pages_problempublication",
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


def smoke_command(database=None):
    """Preserved legacy reads only; this never declares an old reader activatable."""
    database = REHEARSAL_DATABASE if database is None else database
    return f"""from django.conf import settings
settings.DATABASES={{'default': {database!r}}}
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
from inspinia.pages.community_models import CommunityProblem
from inspinia.pages.proof_models import (
    CommunityAttempt,CommunityContentReport,CommunityPrivateAsset,CommunityProblemRevision,
    CommunitySolution,CommunitySolutionAsset,CommunitySolutionRevision,ModerationEvent,ProblemPublication,
)
from inspinia.pages.proof_library import active_publications,public_solutions
import hashlib
labels=('private','unlisted','public','held','withdrawn')
problems=CommunityProblem.objects.filter(title__startswith='Synthetic preserved Community ')
if problems.count() != 5:
    raise RuntimeError('Previous Community reader lost a visibility case')
active=set(active_publications().values_list('problem__title',flat=True))
expected_active={{'Synthetic preserved Community '+label for label in ('unlisted','public','withdrawn')}}
if active != expected_active:
    raise RuntimeError('Previous Community publication privacy changed')
listed=set(active_publications().filter(visibility='public').values_list('problem__title',flat=True))
if listed != {{'Synthetic preserved Community public','Synthetic preserved Community withdrawn'}}:
    raise RuntimeError('Previous Community public discovery changed')
for label in labels:
    problem=problems.get(title='Synthetic preserved Community '+label)
    if (problem.solution_outline != 'Synthetic private outline '+label+'.'
            or problem.legacy_member_visible or not problem.solution_known):
        raise RuntimeError('Previous Community private problem metadata changed')
    publication=ProblemPublication.objects.get(problem=problem)
    if publication.version != 2 or publication.is_held != (label=='held'):
        raise RuntimeError('Previous Community publication hold/version changed')
    if publication.visibility != (label if label in ('private','unlisted') else 'public'):
        raise RuntimeError('Previous Community visibility changed')
    published_statement=publication.statement_revision
    if (published_statement.number != 2 or published_statement.snapshot['statement_latex']
            != 'Synthetic fixed statement '+label+' revision 2.'):
        raise RuntimeError('Previous Community immutable statement changed')
    attempt=CommunityAttempt.objects.get(problem=problem)
    if attempt.body_source != 'Synthetic private attempt body '+label+'.' or attempt.version != 3:
        raise RuntimeError('Previous Community private attempt changed')
    private_asset=CommunityPrivateAsset.objects.get(attempt=attempt)
    private_data=('Synthetic private image bytes '+label+'.').encode()
    if bytes(private_asset.data) != private_data or private_asset.sha256 != hashlib.sha256(private_data).hexdigest():
        raise RuntimeError('Previous Community private image bytes changed')
    solution=CommunitySolution.objects.get(problem=problem)
    if solution.status != ('withdrawn' if label=='withdrawn' else 'approved') or solution.is_held != (label=='held'):
        raise RuntimeError('Previous Community solution moderation changed')
    if solution.current_revision.number != 2 or solution.current_revision.source_attempt_id != attempt.pk:
        raise RuntimeError('Previous Community current revision identity changed')
    if public_solutions(publication).count() != (0 if label in ('held','withdrawn') else 1):
        raise RuntimeError('Previous Community held/withdrawn proof visibility changed')
    if (CommunityProblemRevision.objects.filter(problem=problem).count() != 2
            or CommunitySolutionRevision.objects.filter(solution=solution).count() != 2):
        raise RuntimeError('Previous Community immutable revision history changed')
    for revision in solution.revisions.all():
        expected_body='Synthetic fixed public proof '+label+' revision '+str(revision.number)+'.'
        if (revision.body_source != expected_body
                or revision.content_digest != hashlib.sha256(expected_body.encode()).hexdigest()):
            raise RuntimeError('Previous Community fixed proof revision changed')
        asset=CommunitySolutionAsset.objects.get(revision=revision)
        data=('Synthetic public image bytes '+label+' revision '+str(revision.number)+'.').encode()
        if bytes(asset.data) != data or asset.sha256 != hashlib.sha256(data).hexdigest():
            raise RuntimeError('Previous Community fixed public image bytes changed')
    report=CommunityContentReport.objects.get(problem=problem)
    if (report.details != 'Synthetic private report '+label+'.'
            or report.status != ('resolved' if label=='held' else 'open')):
        raise RuntimeError('Previous Community private report state changed')
    if ModerationEvent.objects.filter(problem=problem).count() != (5 if label=='withdrawn' else 4):
        raise RuntimeError('Previous Community moderation history changed')
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
