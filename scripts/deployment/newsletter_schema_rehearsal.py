# ruff: noqa: E402, EM101, S102, S603, TRY003
"""Prove the exact newsletter migration against an empty, isolated Actions database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment import newsletter_schema
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import POSTGRES_VERSION
from scripts.deployment.schema_rehearsal import _snapshot
from scripts.deployment.schema_rehearsal import configure_rehearsal_database
from scripts.deployment.schema_rehearsal import smoke_command

# CI fixture only. Production's schema-audit role retains its existing access.
SUBSCRIBERS_SQL = """
SELECT count(*)::text,
       encode(sha256(convert_to(coalesce(string_agg(to_jsonb(source)::text, E'\\n' ORDER BY source.id), ''),
                                'UTF8')), 'hex')
FROM public.website_newslettersubscriber source
"""


def subscriber_snapshot(connection):
    with connection.cursor() as cursor:
        cursor.execute(SUBSCRIBERS_SQL)
        return cursor.fetchone()


def existing_records(connection):
    """Hash synthetic pre-existing rows without printing or exporting their values."""
    records = {}
    for table in sorted(connection.introspection.table_names()):
        if table in newsletter_schema.TABLES or table == "django_migrations":
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
    # Both new tables have UUID primary keys; only the migration recorder advances.
    new_sequences = ["django_migrations_id_seq"]
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT schemaname, sequencename, last_value FROM pg_catalog.pg_sequences "
            "WHERE schemaname='public' AND sequencename::text <> ALL(%s) ORDER BY 1,2",
            [new_sequences],
        )
        return cursor.fetchall()


def migration_metadata(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, app, name, applied::text FROM django_migrations ORDER BY id")
        rows = cursor.fetchall()
        cursor.execute(
            "SELECT last_value FROM pg_catalog.pg_sequences "
            "WHERE schemaname='public' AND sequencename='django_migrations_id_seq'",
        )
        return rows, cursor.fetchone()[0]


def validate_migration_record(before, after):
    rows_before, sequence_before = before
    rows_after, sequence_after = after
    if (
        len(rows_after) != len(rows_before) + 1
        or rows_after[:-1] != rows_before
        or rows_after[-1][1:3] != ("website", "0002_newsletter_campaigns")
        or rows_after[-1][0] != sequence_before + 1
        or sequence_after != sequence_before + 1
    ):
        raise ValueError("Newsletter rehearsal changed migration metadata beyond its one approved record")


def seed_fixture():
    from inspinia.pages.models import ContestProblemStatement
    from inspinia.pages.models import ProblemSolveRecord
    from inspinia.pages.models import StatementTopicTechnique
    from inspinia.pages.models import UserProblemCompletion
    from inspinia.users.models import User

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
    UserProblemCompletion.objects.create(user=user, problem=problem, statement=statement)


def seed_subscribers():
    from django.utils import timezone

    from inspinia.website.models import LibraryArea
    from inspinia.website.models import LibraryConcept
    from inspinia.website.models import LibraryLecture
    from inspinia.website.models import NewsletterSubscriber

    for status in NewsletterSubscriber.Status.values:
        NewsletterSubscriber.objects.create(
            email=status + "@schema-rehearsal.example.invalid", status=status,
            requested_at=timezone.now(),
            confirmed_at=timezone.now() if status != NewsletterSubscriber.Status.PENDING else None,
            unsubscribed_at=timezone.now() if status == NewsletterSubscriber.Status.UNSUBSCRIBED else None,
        )
    area = LibraryArea.objects.create(title="Synthetic area", subject="geometry")
    concept = LibraryConcept.objects.create(title="Synthetic concept", area=area)
    LibraryLecture.objects.create(title="Synthetic lecture", concept=concept)


def prepare_django():
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    os.environ["DJANGO_READ_DOT_ENV_FILE"] = "false"
    from django.conf import settings

    configure_rehearsal_database(settings)
    import django

    django.setup()
    from django.db import connection
    return connection


def run(args):
    connection = prepare_django()
    from django.db.migrations.executor import MigrationExecutor

    if connection.pg_version != POSTGRES_VERSION:
        raise ValueError("Newsletter rehearsal requires the pinned PostgreSQL 17.9 runtime")
    if connection.introspection.table_names():
        raise ValueError("Newsletter rehearsal database must be empty")
    newsletter_schema.validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    executor.migrate(
        [node for node in executor.loader.graph.leaf_nodes() if node[0] != "website"]
        + [("website", "0001_initial")],
    )
    seed_fixture()
    seed_subscribers()
    before = _snapshot(connection)
    records, sequences = existing_records(connection), existing_sequences(connection)
    subscriber_before = subscriber_snapshot(connection)
    if subscriber_before[0] != "3":
        raise ValueError("Subscriber preservation fixture is incomplete")
    metadata_before = migration_metadata(connection)
    exec(newsletter_schema.MIGRATION_APPLY, {})
    metadata_after = migration_metadata(connection)
    validate_migration_record(metadata_before, metadata_after)
    after = _snapshot(connection)
    delta = {
        category: [row for row in rows if row.get("table") in newsletter_schema.TABLES]
        for category, rows in after.items()
    }
    previous = {
        category: [row for row in rows if row.get("table") not in newsletter_schema.TABLES]
        for category, rows in after.items()
    }
    if {row["table"] for row in delta["tables"]} != newsletter_schema.TABLES or delta["extensions"]:
        raise ValueError("Newsletter rehearsal did not create exactly the two approved tables")
    records_after, sequences_after = existing_records(connection), existing_sequences(connection)
    if subscriber_snapshot(connection) != subscriber_before:
        raise ValueError("Newsletter migration changed existing subscriber data")
    if previous != before or records_after != records or sequences_after != sequences:
        changed_records = sorted(table for table in records if records[table] != records_after.get(table))
        message = (
            f"Newsletter preservation failed: schema={previous != before}, "
            f"records={changed_records}, sequences={sequences_after != sequences}"
        )
        raise ValueError(message)
    fingerprint = schema_state(delta)["fingerprint"]
    if not getattr(args, "record_delta", False) and fingerprint != newsletter_schema.DELTA_SHA256:
        raise ValueError("Newsletter schema delta does not match the frozen PostgreSQL rehearsal")
    smoke_env = {**os.environ, "PYTHONPATH": str(args.active_source.resolve())}
    subprocess.run([sys.executable, "-c", smoke_command()], cwd=args.active_source, env=smoke_env, check=True)
    if (
        _snapshot(connection) != after
        or existing_records(connection) != records
        or existing_sequences(connection) != sequences
        or migration_metadata(connection) != metadata_after
        or subscriber_snapshot(connection) != subscriber_before
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
            "migration_file_sha256": newsletter_schema.MIGRATION_SHA256,
            "delta_sha256": newsletter_schema.DELTA_SHA256,
            "existing_schema_unchanged": True,
            "source_fixture_unchanged": True,
            "active_revision_smoke_passed": True,
            "existing_records_unchanged": True,
            "existing_sequences_unchanged": True,
            "existing_subscribers_unchanged": True,
        }
    args.output.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n")
    print("Newsletter PostgreSQL delta:", fingerprint)  # noqa: T201
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
