# ruff: noqa: EM101, S102, S603, TRY003
"""Verify the frozen column on the disposable PostgreSQL 17.9 release database."""

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

from scripts.deployment import library_ai_schema as schema
from scripts.deployment.newsletter_schema_rehearsal import existing_sequences
from scripts.deployment.newsletter_schema_rehearsal import migration_metadata
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_rehearsal import REHEARSAL_DATABASE
from scripts.deployment.schema_rehearsal import _arguments
from scripts.deployment.schema_rehearsal import _snapshot
from scripts.deployment.solution_collections_schema_rehearsal import trigger_definitions


def preserved_records(connection):
    records = {}
    with connection.cursor() as cursor:
        for table in sorted(set(connection.introspection.table_names()) - {"django_migrations"}):
            expression = "to_jsonb(source)"
            params = []
            if table == schema.TABLE:
                expression += " - %s::text"
                params = [schema.FIELD, schema.FIELD]
            quoted = connection.ops.quote_name(table)
            cursor.execute(
                f"SELECT ({expression})::text FROM {quoted} source "  # noqa: S608 - fixed expression and quoted table
                f'ORDER BY ({expression})::text COLLATE "C"',
                params,
            )
            digest = sha256()
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    digest.update(row[0].encode() + b"\0")
            records[table] = digest.hexdigest()
    return records, existing_sequences(connection), trigger_definitions(connection)


def verify_migration(connection, *, catalog, records, recorder):
    if normalize_schema_snapshot(_snapshot(connection)) != schema.add_column(catalog):
        raise ValueError("The catalog delta differs from the frozen nullable column")
    if preserved_records(connection) != records:
        raise ValueError("The migration changed an existing row, sequence or trigger")
    old_rows, old_sequence = recorder
    rows, sequence = migration_metadata(connection)
    if (
        len(rows) != len(old_rows) + 1 or rows[:-1] != old_rows
        or rows[-1][:3] != (old_sequence + 1, "pages", schema.MIGRATION_NAME) or sequence != old_sequence + 1
    ):
        raise ValueError("Only the approved migration recorder row may be appended")
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pages_contestproblemstatement WHERE ai_concept_suggestions IS NOT NULL")
        if cursor.fetchone() != (0,):
            raise ValueError("The new evidence column must be empty")


def run(args):
    connection = prepare_django()
    from django.db.migrations.executor import MigrationExecutor

    if connection.pg_version != schema.POSTGRES_VERSION or connection.introspection.table_names():
        raise ValueError("AI evidence rehearsal requires an empty disposable PostgreSQL 17.9 database")
    schema.validate_candidate(Path.cwd())
    if (
        (args.active_source / schema.MIGRATION_PATH).exists()
        or schema.migration_tree_sha256(args.active_source) != schema.PRIOR_MIGRATION_TREE_SHA256
    ):
        raise ValueError("Active source does not match the frozen pre-migration tree")
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node != ("pages", schema.MIGRATION_NAME)]
    executor.migrate([*targets, ("pages", "0047_study_help")])
    active_env = {**os.environ, "PYTHONPATH": str(args.active_source.resolve())}
    seed = (
        "from django.conf import settings\n"
        f"settings.DATABASES = {{'default': {REHEARSAL_DATABASE!r}}}\n"
        "import django\ndjango.setup()\n"
        "from scripts.deployment.newsletter_schema_rehearsal import seed_fixture, seed_subscribers\n"
        "seed_fixture()\nseed_subscribers()\n"
    )
    subprocess.run([sys.executable, "-c", seed], cwd=args.active_source, env=active_env, check=True)
    before = {
        "catalog": normalize_schema_snapshot(_snapshot(connection)),
        "records": preserved_records(connection),
        "recorder": migration_metadata(connection),
    }
    exec(schema.MIGRATION_APPLY, {})
    verify_migration(connection, **before)
    subprocess.run(
        [sys.executable, "-c", schema.smoke_command()], cwd=args.active_source, env=active_env, check=True,
    )
    verify_migration(connection, **before)
    evidence = schema.build_evidence(args.release_sha, args.active_sha)
    args.output.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run(_arguments()))
