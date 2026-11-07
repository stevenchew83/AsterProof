# ruff: noqa: EM101, EM102, S102, S603, SLF001, TRY003
"""Exact forum preservation proof; production readiness requires isolated PostgreSQL 17.9."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.deployment import evaluation_schema as preservation
from scripts.deployment import solution_forum_schema as schema
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import _snapshot


def preserved_state(connection, tables):
    if connection.vendor != "sqlite":
        return preservation.preserved_state(connection, tables)
    # Django 5.1's SQLite SQL parser cannot introspect some current complex
    # CHECK clauses. PRAGMA plus exact sqlite_master SQL avoids weakening proof.
    rows, columns, constraints = {}, {}, {}
    with connection.cursor() as cursor:
        for table in sorted(tables - {"django_migrations"}):
            quoted = connection.ops.quote_name(table)
            cursor.execute("SELECT * FROM " + quoted)  # noqa: S608
            rows[table] = preservation.fingerprint(sorted(preservation.fingerprint(row) for row in cursor.fetchall()))
            cursor.execute("PRAGMA table_info(" + quoted + ")")
            columns[table] = cursor.fetchall()
            cursor.execute("SELECT type,name,sql FROM sqlite_master WHERE tbl_name=%s ORDER BY type,name", [table])
            constraints[table] = cursor.fetchall()
        cursor.execute("SELECT id,app,name,applied FROM django_migrations ORDER BY id")
        migrations = cursor.fetchall()
        cursor.execute("SELECT name,tbl_name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name")
        triggers = cursor.fetchall()
        cursor.execute("SELECT name,seq FROM sqlite_sequence WHERE name<>'django_migrations' ORDER BY name")
        sequences = cursor.fetchall()
    return {
        "rows": rows,
        "columns": columns,
        "constraints": constraints,
        "migrations": migrations,
        "triggers": triggers,
        "sequences": sequences,
    }


def verify_preservation(connection, old_tables, before):  # noqa: C901 - Explicit preservation gates.
    if set(connection.introspection.table_names()) != old_tables | schema.TABLES:
        raise ValueError("Forum migration changed tables outside its eight-table bundle")
    after = preserved_state(connection, old_tables)
    for key in ("rows", "columns", "constraints", "triggers"):
        if before[key] != after[key]:
            raise ValueError(f"Forum migration changed existing {key}")
    if connection.vendor == "postgresql":
        new_sequences = {f"{table}_id_seq" for table in schema.TABLES if table != "solutions_solutionforumtarget"}
        old_sequences = [row for row in after["sequences"] if row[1] not in new_sequences]
        added_sequences = [row for row in after["sequences"] if row[1] in new_sequences]
        if (
            old_sequences != before["sequences"]
            or {row[1] for row in added_sequences} != new_sequences
            or any(row[0] != "public" or row[2] is not None for row in added_sequences)
        ):
            raise ValueError("Forum migration changed an existing sequence or used a new sequence")
    else:
        old_sequences = [row for row in after["sequences"] if row[0] not in schema.TABLES]
        new_sequences = [row for row in after["sequences"] if row[0] in schema.TABLES]
        if old_sequences != before["sequences"] or any(row[1] != 0 for row in new_sequences):
            raise ValueError("Forum migration changed existing SQLite sequence values or used new ones")
    added = after["migrations"][len(before["migrations"]) :]
    if (
        after["migrations"][:-1] != before["migrations"]
        or len(added) != 1
        or tuple(added[0][1:3]) != ("solutions", schema.MIGRATION_NAME)
        or added[0][0] != before["migrations"][-1][0] + 1
    ):
        raise ValueError("Only the frozen forum migration recorder row may be appended")
    connection.check_constraints()
    with connection.cursor() as cursor:
        for table in sorted(schema.TABLES):
            cursor.execute("SELECT count(*) FROM " + connection.ops.quote_name(table))  # noqa: S608
            if cursor.fetchone() != (0,):
                raise ValueError("Forum tables must remain empty after migration")
        cursor.execute("SELECT enabled,daily_budget_micros,monthly_budget_micros FROM solutions_solutionreviewpolicy")
        if cursor.fetchall() != [(False, 0, 0)]:
            raise ValueError("AI policy must remain disabled and unfunded")


def _prepare_fixture(connection):
    from django.db.migrations.executor import MigrationExecutor

    if connection.introspection.table_names():
        raise ValueError("Forum rehearsal refuses a nonempty database")
    schema.validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "solutions"] + [
        ("solutions", "0012_synthetic_review_prototype"),
    ]
    executor.migrate(targets)
    preservation.seed_legacy(executor, targets, connection)
    old_tables = set(connection.introspection.table_names())
    return old_tables, preserved_state(connection, old_tables)


def _disable_ai(settings):
    settings.SOLUTION_AI_REVIEW_ENABLED = False
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = False
    settings.SYNTHETIC_REVIEW_PROTOTYPE_ENABLED = False
    settings.SOLUTION_AI_EXECUTION_MODE = "offline"
    settings.OPENAI_API_KEY = ""


def run(args):
    os.environ.update(
        OPENAI_API_KEY="",
        SOLUTION_AI_REVIEW_ENABLED="false",
        PROBLEM_STATEMENT_AI_REVIEW_ENABLED="false",
        SOLUTION_AI_EXECUTION_MODE="offline",
    )
    connection = prepare_django()
    from django.conf import settings

    _disable_ai(settings)
    preservation.validate_connection(connection)
    if connection.pg_version != schema.POSTGRES_VERSION:
        raise ValueError("Authoritative forum rehearsal requires disposable PostgreSQL 17.9")
    old_tables, before = _prepare_fixture(connection)
    before_catalog = normalize_schema_snapshot(_snapshot(connection))
    exec(schema.MIGRATION_APPLY, {})
    verify_preservation(connection, old_tables, before)
    after = normalize_schema_snapshot(_snapshot(connection))
    delta = {field: [row for row in rows if row.get("table") in schema.TABLES] for field, rows in after.items()}
    previous = {field: [row for row in rows if row.get("table") not in schema.TABLES] for field, rows in after.items()}
    if previous != before_catalog:
        raise ValueError("Forum migration changed prior schema objects")
    if getattr(args, "discover_delta", None):
        args.discover_delta.write_text(json.dumps(delta, sort_keys=True, indent=2) + "\n")
        raise ValueError("Discovery only: freeze and review this delta, then run the strict rehearsal")
    if schema_state(delta)["fingerprint"] != schema.DELTA_SHA256:
        raise ValueError("Forum schema differs from its exact frozen PostgreSQL delta")
    metadata_after = preserved_state(connection, old_tables)["migrations"]
    smoke_env = {**os.environ, "PYTHONPATH": str(args.active_source.resolve())}
    subprocess.run([sys.executable, "-c", schema.smoke_command()], cwd=args.active_source, env=smoke_env, check=True)
    verify_preservation(connection, old_tables, before)
    if (
        normalize_schema_snapshot(_snapshot(connection)) != after
        or preserved_state(connection, old_tables)["migrations"] != metadata_after
    ):
        raise ValueError("Active application smoke changed schema or migration records")
    output = {
        "format_version": 1,
        "source_sha": args.release_sha,
        "active_sha": args.active_sha,
        "postgres_version": connection.pg_version,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "delta_sha256": schema.DELTA_SHA256,
        "existing_schema_unchanged": True,
        "source_fixture_unchanged": True,
        "active_revision_smoke_passed": True,
        "existing_records_unchanged": True,
        "existing_sequences_unchanged": True,
        "new_forum_tables_empty": True,
        "existing_trigger_definitions_unchanged": True,
        "ai_disabled_and_unfunded": True,
    }
    args.output.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n")
    connection.close()
    return 0


def local_sqlite(output):
    """Own the scratch target; callers cannot redirect this command at existing data."""
    os.environ.update(
        DJANGO_SETTINGS_MODULE="config.settings.test",
        DJANGO_READ_DOT_ENV_FILE="false",
        OPENAI_API_KEY="",
        SOLUTION_AI_REVIEW_ENABLED="false",
        PROBLEM_STATEMENT_AI_REVIEW_ENABLED="false",
    )
    from django.conf import settings

    with tempfile.TemporaryDirectory(prefix="asterproof-forum-schema-") as scratch:
        settings.DATABASES = {
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(Path(scratch) / "rehearsal.sqlite3")},
        }
        _disable_ai(settings)
        import django

        django.setup()
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        old_tables, before = _prepare_fixture(connection)
        # This historical local smoke deliberately stops at the original forum
        # release. The production PLAN_CHECK still rejects any additional leaf.
        executor = MigrationExecutor(connection)
        target = [("solutions", schema.MIGRATION_NAME)]
        plan = executor.migration_plan(target)
        if [(migration.app_label, migration.name, backwards) for migration, backwards in plan] != [
            ("solutions", schema.MIGRATION_NAME, False),
        ]:
            raise ValueError("Local forum preservation smoke has an unexpected migration plan")
        executor.migrate(target, plan=plan)
        verify_preservation(connection, old_tables, before)
        output.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "verification_status": "local_sqlite_smoke_passed",
                    "authoritative_postgresql_rehearsal": False,
                    "production_migration_authorized": False,
                    "existing_records_schema_triggers_sequences_preserved": True,
                    "new_tables_empty": True,
                    "new_tables": sorted(schema.TABLES),
                    "migration_file_sha256": schema.MIGRATION_SHA256,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
        )
        connection.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-source", type=Path)
    parser.add_argument("--active-sha")
    parser.add_argument("--release-sha")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--discover-delta", type=Path)
    parser.add_argument("--sqlite", action="store_true")
    args = parser.parse_args()
    if args.sqlite:
        return local_sqlite(args.output)
    if not all((args.active_source, args.active_sha, args.release_sha)):
        parser.error("PostgreSQL release rehearsal requires active source and exact release identities")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
