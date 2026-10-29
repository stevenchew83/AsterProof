# ruff: noqa: E402, EM101, S102, S603, TRY003
"""Prove the exact website migration against an empty, isolated Actions database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment import website_schema
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import POSTGRES_VERSION
from scripts.deployment.schema_rehearsal import _snapshot
from scripts.deployment.schema_rehearsal import configure_rehearsal_database
from scripts.deployment.schema_rehearsal import smoke_command


def existing_records(connection):
    """Hash synthetic pre-existing rows without printing or exporting their values."""
    records = {}
    for table in sorted(connection.introspection.table_names()):
        if table in website_schema.TABLES or table == "django_migrations":
            continue
        digest = hashlib.sha256()
        quoted = connection.ops.quote_name(table)
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT to_jsonb(source)::text FROM {quoted} source "  # noqa: S608 - introspected, quoted table name
                'ORDER BY to_jsonb(source)::text COLLATE "C"',
            )
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    digest.update(row[0].encode())
                    digest.update(b"\0")
        records[table] = digest.hexdigest()
    return records


def existing_sequences(connection):
    new_sequences = sorted(
        table + "_id_seq" for table in website_schema.TABLES if table != "website_newslettersubscriber"
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT schemaname, sequencename, last_value FROM pg_catalog.pg_sequences "
            "WHERE schemaname='public' AND sequencename::text <> ALL(%s) ORDER BY 1,2",
            [new_sequences],
        )
        return cursor.fetchall()


def run(args):
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    os.environ["DJANGO_READ_DOT_ENV_FILE"] = "false"
    from django.conf import settings

    configure_rehearsal_database(settings)
    import django

    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    from inspinia.pages.models import ContestProblemStatement
    from inspinia.pages.models import ProblemSolveRecord
    from inspinia.pages.models import StatementTopicTechnique
    from inspinia.pages.models import UserProblemCompletion
    from inspinia.users.models import User

    if connection.pg_version != POSTGRES_VERSION:
        raise ValueError("Website rehearsal requires the pinned PostgreSQL 17.9 runtime")
    if connection.introspection.table_names():
        raise ValueError("Website rehearsal database must be empty")
    website_schema.validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    executor.migrate([node for node in executor.loader.graph.leaf_nodes() if node[0] != "website"])
    user = User.objects.create(email="schema-rehearsal@example.invalid")
    problem = ProblemSolveRecord.objects.create(
        contest="SCHEMA REHEARSAL",
        year=2026,
        problem="P1",
        topic="ALG",
        mohs=20,
    )
    statement = ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_name="SCHEMA REHEARSAL",
        contest_year=2026,
        problem_number=1,
        problem_code="P1",
        topic="A",
        statement_latex="Synthetic AM-GM statement.",
    )
    StatementTopicTechnique.objects.create(statement=statement, technique="AM-GM", main_topic="ALG", domains=["ALG"])
    UserProblemCompletion.objects.create(user=user, problem_uuid=problem.problem_uuid)
    before = _snapshot(connection)
    records, sequences = existing_records(connection), existing_sequences(connection)
    exec(website_schema.MIGRATION_APPLY, {})
    after = _snapshot(connection)
    delta = {
        category: [row for row in rows if row.get("table") in website_schema.TABLES]
        for category, rows in after.items()
    }
    previous = {
        category: [row for row in rows if row.get("table") not in website_schema.TABLES]
        for category, rows in after.items()
    }
    if {row["table"] for row in delta["tables"]} != website_schema.TABLES or delta["extensions"]:
        raise ValueError("Website rehearsal did not create exactly the five approved tables")
    if previous != before or existing_records(connection) != records or existing_sequences(connection) != sequences:
        raise ValueError("Website rehearsal changed existing schema, records, or sequences")
    fingerprint = schema_state(delta)["fingerprint"]
    if not getattr(args, "record_delta", False) and fingerprint != website_schema.DELTA_SHA256:
        raise ValueError("Website schema delta does not match the frozen PostgreSQL rehearsal")
    smoke_env = {**os.environ, "PYTHONPATH": str(args.active_source.resolve())}
    subprocess.run([sys.executable, "-c", smoke_command()], cwd=args.active_source, env=smoke_env, check=True)
    if (
        _snapshot(connection) != after
        or existing_records(connection) != records
        or existing_sequences(connection) != sequences
    ):
        raise ValueError("Active-release compatibility smoke changed existing schema or data")
    if getattr(args, "record_delta", False):
        # Discovery produces a review fixture, never deployable build evidence.
        output = delta
    else:
        output = {
            "format_version": 1,
            "source_sha": args.release_sha,
            "active_sha": args.active_sha,
            "postgres_version": connection.pg_version,
            "migration_file_sha256": website_schema.MIGRATION_SHA256,
            "delta_sha256": website_schema.DELTA_SHA256,
            "existing_schema_unchanged": True,
            "source_fixture_unchanged": True,
            "active_revision_smoke_passed": True,
            "existing_records_unchanged": True,
            "existing_sequences_unchanged": True,
        }
    args.output.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n")
    print("Website PostgreSQL delta:", fingerprint)  # noqa: T201
    connection.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-source", type=Path, required=True)
    parser.add_argument("--active-sha", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record-delta", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
