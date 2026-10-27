"""Frozen catalogue migration inputs and metadata-only trigger/function audit.

This module supplies verification primitives. It does not enable a deployment
class, install authority, or grant a production maintenance operation.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from scripts.deployment.schema_fingerprint import canonical_json

MIGRATIONS = (
    "0037_catalogue_tables",
    "0038_seed_catalogue",
    "0039_catalogue_revision_triggers",
)
INPUT_HASHES = {
    "0037_catalogue_tables.py": "5eccd458a588eab19bc3bbfd4d58a2b7a0ab40bcefabbd7b53fcf226acb2ca18",
    "0038_seed_catalogue.py": "ea1fedfed7c0220a89dad21d5cb5bd1d7edc5ebe2a3e74746254429fa7577d16",
    "0038_catalogue_seed.json": "e98f5329e697597ef4dcadeb77d912213237365b05d3207d76391581222386f6",
    "0039_catalogue_revision_triggers.py": "03c531d47c50320c3f99f557ffd94df15e869b9cfceb5efa5b30700766c0c5ed",
}
TABLES = frozenset(
    "pages_" + name
    for name in (
        "cataloguesubject", "cataloguearea", "catalogueconcept", "catalogueconceptarea",
        "catalogueconceptrelation", "catalogueconceptalias", "conceptlibrarysnapshot",
        "cataloguestate", "catalogueproblem", "catalogueproblemconcept", "userconceptprogresssummary",
    )
)
# PostgreSQL 17.9 proof: Actions run 40485838675, artifact 12725162197.
# These bind the complete additive table delta and exact trigger/function bodies.
DELTA_SHA256 = "688fe37d565e69fe6547264c2b48ee60689972fbf8007023939b813ed9f49e94"
BEHAVIOUR_SHA256 = "d20b95dd341b53b253bed83d0145c9d3301c80f323c6eff313e3fe066d514f40"
TRIGGER_TABLES = frozenset(
    [
        "pages_contestproblemstatement", "pages_problemsolverecord", "pages_statementtopictechnique",
        "pages_problemtopictechnique", "pages_problemconceptassignment", "pages_conceptassignmentstate",
        "solutions_problemsolution", "solutions_problemsolutionblock",
    ],
) | (TABLES - {
    "pages_conceptlibrarysnapshot", "pages_cataloguestate", "pages_catalogueproblem",
    "pages_catalogueproblemconcept", "pages_userconceptprogresssummary",
})
FUNCTION_SQL = """
SELECT n.nspname,p.proname,pg_catalog.pg_get_function_identity_arguments(p.oid),
       pg_catalog.pg_get_functiondef(p.oid),p.prosecdef,p.proconfig::text
FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='public' AND p.proname='asterproof_catalogue_revision'
ORDER BY 1,2,3
"""
TRIGGERS_SQL = """
SELECT n.nspname,c.relname,t.tgname,pg_catalog.pg_get_triggerdef(t.oid,true),t.tgenabled
FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND NOT t.tgisinternal AND left(t.tgname,13) = 'ap_catalogue_'
ORDER BY 1,2,3
"""
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor = MigrationExecutor(connection)
plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
actual = [(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected = [('pages',{MIGRATIONS[0]!r},False,['CreateModel']*11+['AddConstraint']*3),
            ('pages',{MIGRATIONS[1]!r},False,['RunPython']),
            ('pages',{MIGRATIONS[2]!r},False,['RunPython'])]
if actual != expected:
    raise RuntimeError('Pending migrations differ from the frozen catalogue plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('pages',{MIGRATIONS[-1]!r})])\n"


def validate_candidate(root: Path) -> None:
    for name, digest in INPUT_HASHES.items():
        path = root / "inspinia/pages/migrations" / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            message = f"Catalogue migration input differs from its reviewed hash: {name}"
            raise ValueError(message)


def behaviour_snapshot(connection) -> dict:
    """Read only the frozen function/trigger names from PostgreSQL metadata."""
    result = {}
    with connection.cursor() as cursor:
        for name, sql in (("functions", FUNCTION_SQL), ("triggers", TRIGGERS_SQL)):
            cursor.execute(sql)
            result[name] = [list(row) for row in cursor.fetchall()]
    return result


def behaviour_fingerprint(snapshot: dict) -> str:
    return hashlib.sha256(canonical_json(snapshot)).hexdigest()


def validate_behaviour_shape(snapshot: dict) -> None:
    functions, triggers = snapshot["functions"], snapshot["triggers"]
    if len(functions) != 1 or functions[0][:3] != ["public", "asterproof_catalogue_revision", ""]:
        message = "Expected exactly the approved no-argument catalogue trigger function"
        raise ValueError(message)
    if functions[0][4:] != [False, None]:
        message = "Catalogue trigger function must retain invoker security and default configuration"
        raise ValueError(message)
    expected = {("public", t, "ap_catalogue_" + t, "O") for t in TRIGGER_TABLES}
    if len(triggers) != len(expected) or {(r[0], r[1], r[2], r[4]) for r in triggers} != expected:
        message = "Catalogue trigger names, enabled states or tables differ from the reviewed scope"
        raise ValueError(message)


def validate_rehearsal_evidence(value: dict, *, release_sha: str, active_sha: str) -> None:
    """Bind build proof to this release; truthy strings/integers are not proof."""
    if (
        not re.fullmatch(r"[0-9a-f]{40}", release_sha)
        or not re.fullmatch(r"[0-9a-f]{40}", active_sha)
        or release_sha == active_sha
    ):
        message = "Catalogue PostgreSQL proof requires distinct immutable release revisions"
        raise ValueError(message)
    expected = {
        "format_version": 1, "source_sha": release_sha, "active_sha": active_sha,
        "postgres_version": 170009, "input_hashes": INPUT_HASHES,
        "delta_sha256": DELTA_SHA256, "behaviour_sha256": BEHAVIOUR_SHA256,
        "existing_schema_unchanged": True, "existing_records_unchanged": True,
        "active_revision_smoke_passed": True, "runtime_invalidation_passed": True,
        "trigger_uninstall_reinstall_passed": True,
    }
    flags = [k for k, v in expected.items() if v is True]
    if (
        not isinstance(value, dict) or type(value.get("format_version")) is not int
        or value != expected or any(value[k] is not True for k in flags)
    ):
        message = "Catalogue PostgreSQL proof does not match the frozen release and behaviour"
        raise ValueError(message)
