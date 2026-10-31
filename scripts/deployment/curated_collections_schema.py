# ruff: noqa: EM101, EM102, S608, TRY003
"""Frozen site-owned curated collection schema allowance; no other migration is admitted."""

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

MIGRATION = "solutions.0008_solutioncollection_kind_and_nullable_owner"
MIGRATION_NAME = MIGRATION.split(".", 1)[1]
MIGRATION_PATH = Path("inspinia/solutions/migrations/0008_solutioncollection_kind_and_nullable_owner.py")
MIGRATION_SHA256 = "bc5cc1f10fafc0605223eedcd3ddbfb05d49f270b707bc2401fd93d676ddac28"
DELTA_SHA256 = "defe0ce5c2fa6086831fb485ddde3a46f20f5d00c0695206a0b193e6142bd5d3"
EVIDENCE_PATH = "deployment-schema-evidence.json"
POSTGRES_VERSION = 170009
TABLE = "solutions_solutioncollection"
TABLES = {TABLE, "solutions_solutioncollectionentry"}
PRIOR_MIGRATIONS = {
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
import uuid
from django.db import connection, transaction
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from inspinia.users.models import User
from inspinia.solutions.models import ProblemSolution, SolutionCollection, SolutionCollectionEntry, SolutionPublicShare
from inspinia.solutions.public_views import public_collection_view
solution=ProblemSolution.objects.get(title='Synthetic preserved solution')
if solution.blocks.get().body_source != 'Synthetic preserved proof.':
    raise RuntimeError('Active revision solution read failed')
with transaction.atomic():
    # Old ORM omits the unknown kind field. Its durable database default must work.
    personal=SolutionCollection.objects.create(id=900001, owner_id=solution.author_id, title='Old insert')
    with connection.cursor() as cursor:
        cursor.execute('SELECT kind FROM solutions_solutioncollection WHERE id=%s', [personal.pk])
        if cursor.fetchone() != ('personal',):
            raise RuntimeError('Old-code personal insert did not receive its database default')
        cursor.execute(
            'INSERT INTO solutions_solutioncollection '
            '(id,title,introduction,token,revision,is_active,created_at,updated_at,owner_id,kind) '
            'VALUES (%s,%s,%s,%s,%s,true,%s,%s,NULL,%s)',
            [900002,'Synthetic site collection','',uuid.uuid4(),uuid.uuid4(),
             timezone.now(),timezone.now(),'admin_curated'],
        )
    curated=SolutionCollection.objects.get(pk=900002)
    creator=User.objects.create(id=900003, email='former-curator@schema-rehearsal.example.invalid')
    contributor=User.objects.create(id=900004, email='contributor@schema-rehearsal.example.invalid')
    other=ProblemSolution.objects.create(id=900005, author_id=contributor.pk,
                                        problem_id=solution.problem_id, title='Contributor')
    source=SolutionPublicShare.objects.create(id=900006, solution=other, source_updated_at=timezone.now(),
                                            snapshot={'title':'Synthetic other public copy'}, preview_image=b'')
    kept=SolutionPublicShare.objects.get(solution=solution)
    SolutionCollectionEntry.objects.create(id=900007,collection=curated,share=kept,position=1,share_token=kept.token)
    SolutionCollectionEntry.objects.create(id=900008,collection=curated,share=source,position=2,share_token=source.token)
    request=RequestFactory().get('/')
    request.user=AnonymousUser()
    response=public_collection_view(request, curated.token)
    if response.status_code != 200 or b'No solutions are currently available' not in response.content:
        raise RuntimeError('Old-code curated public read did not fail safely with empty content')
    creator.delete()
    connection.check_constraints()
    if not SolutionCollection.objects.filter(pk=curated.pk).exists() or curated.entries.count()!=2:
        raise RuntimeError('Former-curator deletion affected site-owned content')
    contributor.delete()
    connection.check_constraints()
    if (not SolutionCollection.objects.filter(pk=curated.pk).exists()
        or list(curated.entries.values_list('share_id',flat=True))!=[kept.pk]):
        raise RuntimeError('Contributor deletion affected another contributor or container')
    transaction.set_rollback(True)
"""


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected=[('solutions','{MIGRATION_NAME}',False,['AddField','AlterField','AddConstraint'])]
if actual != expected:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('solutions','{MIGRATION_NAME}')])\n"


class CuratedCollectionsSchemaError(ConceptSchemaError):
    pass


def _validate_fingerprints(value: dict[str, Any]) -> None:
    for stage in ("starting", "expected"):
        state = value[stage]
        if not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS):
            raise CuratedCollectionsSchemaError("Invalid schema fingerprint fields")
        if any(not isinstance(v, str) or not DIGEST.fullmatch(v) for v in state.values()):
            raise CuratedCollectionsSchemaError("Invalid schema fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise CuratedCollectionsSchemaError("The approved curated migration must change each fingerprint")


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
        raise CuratedCollectionsSchemaError("Invalid bounded schema disclosure")
    if value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256:
        raise CuratedCollectionsSchemaError("Migration is outside the approved scope")
    if (
        not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise CuratedCollectionsSchemaError("Schema disclosure release identity mismatch")
    for field in ("postgresql_rehearsal_sha256", "compatibility_smoke_sha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise CuratedCollectionsSchemaError("Schema rehearsal and compatibility evidence must be frozen")
    if value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256:
        raise CuratedCollectionsSchemaError("Collections compatibility smoke differs from the approved fixed command")
    _validate_fingerprints(value)
    if len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise CuratedCollectionsSchemaError("Schema disclosure exceeds its bound")
    return value


def validate_candidate(release: Path) -> None:
    paths = {MIGRATION_PATH: MIGRATION_SHA256}
    paths.update({MIGRATION_PATH.parent / name: digest for name, digest in PRIOR_MIGRATIONS.items()})
    for relative, digest in paths.items():
        path = release / relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise CuratedCollectionsSchemaError("Candidate migration bytes differ from the frozen solution plan")


def audit_matches(disclosure: dict[str, Any], audit: dict[str, Any], *, stage: str) -> bool:
    return audit.get("server_version_num") == POSTGRES_VERSION and all(
        audit.get(field) == disclosure[stage][field] for field in FINGERPRINT_FIELDS
    )


def validate_build_evidence(release: Path, disclosure: dict[str, Any]) -> None:
    import json

    path = release / EVIDENCE_PATH
    if path.is_symlink() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise CuratedCollectionsSchemaError("Invalid packaged schema evidence")
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise CuratedCollectionsSchemaError("Invalid packaged schema evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise CuratedCollectionsSchemaError("Packaged collection proof digest does not match its disclosure")
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
        "existing_collections_personal": True,
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
            "existing_collections_personal",
            "existing_trigger_definitions_unchanged",
        )
    ):
        raise CuratedCollectionsSchemaError("Packaged PostgreSQL schema evidence does not match this release")


def schema_delta(before, after):
    """Record both sides of the exact alteration; catalogue rows are never guessed."""
    return {
        "removed": {field: [row for row in before[field] if row not in after[field]] for field in before},
        "added": {field: [row for row in after[field] if row not in before[field]] for field in before},
    }


def apply_delta(before, delta):
    if not isinstance(delta, dict) or set(delta) != {"removed", "added"}:
        raise CuratedCollectionsSchemaError("Invalid curated schema alteration")
    removed = normalize_schema_snapshot(delta["removed"])
    added = normalize_schema_snapshot(delta["added"])
    if sha256_fingerprint({"removed": removed, "added": added}) != DELTA_SHA256:
        raise CuratedCollectionsSchemaError("Schema delta differs from the approved rehearsal")
    # The frozen digest is authoritative; require an exact starting owner-column match too.
    result = {}
    for field in before:
        if any(row not in before[field] for row in removed[field]):
            raise CuratedCollectionsSchemaError("Starting catalogue does not contain the approved original object")
        kept = [row for row in before[field] if row not in removed[field]]
        identity = {
            "columns": ("schema", "table", "column"),
            "constraints": ("schema", "table", "name"),
        }.get(field)
        if any(
            row in kept or (identity and any(all(row[key] == old[key] for key in identity) for old in kept))
            for row in added[field]
        ):
            raise CuratedCollectionsSchemaError("Curated schema addition already exists")
        result[field] = [*kept, *added[field]]
    return normalize_schema_snapshot(result)


def expected_catalog_audit(start: dict[str, Any], rehearsal: dict[str, Any]) -> dict[str, Any]:
    """Apply only the frozen owner-nullability, kind/default, and ownership-check change."""
    if start.get("server_version_num") != POSTGRES_VERSION or (
        sha256_fingerprint(start["state"]) != start["state_fingerprint"]
    ):
        raise CuratedCollectionsSchemaError("Starting audit identity/version does not match the approved target")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    if not all(any(row["schema"] == "public" and row["table"] == table for row in before["tables"])
               for table in TABLES | {"solutions_solutionpublicshare"}):
        raise CuratedCollectionsSchemaError("Existing collection and public-share tables are required")
    migrations = start["migration_rows"]
    if ["solutions", "0007_solutioncollection_solutioncollectionentry"] not in migrations:
        raise CuratedCollectionsSchemaError("The previous solution migration must already be recorded")
    if ["solutions", MIGRATION_NAME] in migrations:
        raise CuratedCollectionsSchemaError("The approved migration is already recorded")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise CuratedCollectionsSchemaError("Starting catalog evidence does not match its fingerprints")
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
