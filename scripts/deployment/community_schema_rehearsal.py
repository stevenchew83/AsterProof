# ruff: noqa: E402, EM101, S102, S603, TRY003
"""Rehearse the exact approved community bundle in empty PostgreSQL 17.9."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from http import HTTPStatus
from pathlib import Path

from scripts.deployment import catalogue_schema
from scripts.deployment import community_schema as schema
from scripts.deployment.newsletter_schema_rehearsal import migration_metadata
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.newsletter_schema_rehearsal import seed_fixture
from scripts.deployment.newsletter_schema_rehearsal import seed_subscribers
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import _snapshot
from scripts.deployment.solution_pdf_schema_rehearsal import trigger_definitions
from scripts.deployment.statement_reports_schema_rehearsal import seed_shared_snapshots
from scripts.deployment.statement_reports_schema_rehearsal import seed_solution


def migration_sources(root):
    excluded = set(schema.INPUT_HASHES)
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "inspinia").rglob("*")
        if path.parent.name == "migrations"
        and path.suffix in {".py", ".json"}
        and path.relative_to(root).as_posix() not in excluded
    }


def existing_records(connection):
    records = {}
    for table in sorted(connection.introspection.table_names()):
        if table == "django_migrations" or table in schema.TABLES:
            continue
        hashed = hashlib.sha256()
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT to_jsonb(source)::text FROM {connection.ops.quote_name(table)} source "  # noqa: S608
                'ORDER BY to_jsonb(source)::text COLLATE "C"',
            )
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    hashed.update(row[0].encode())
                    hashed.update(b"\0")
        records[table] = hashed.hexdigest()
    return records


def existing_sequences(connection):
    excluded = ["django_migrations_id_seq", *[table + "_id_seq" for table in schema.TABLES]]
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT schemaname,sequencename,last_value FROM pg_catalog.pg_sequences "
            "WHERE schemaname='public' AND sequencename::text <> ALL(%s) ORDER BY 1,2",
            [excluded],
        )
        return cursor.fetchall()


def validate_migration_record(before, after):
    old, sequence = before
    new, ending = after
    if (
        new[: len(old)] != old
        or len(new) != len(old) + len(schema.MIGRATIONS)
        or [row[1:3] for row in new[len(old) :]] != [("pages", name) for name in schema.MIGRATIONS]
        or [row[0] for row in new[len(old) :]] != list(range(sequence + 1, sequence + 3))
        or ending != sequence + 2
    ):
        raise ValueError("Community changed migration metadata outside its two approved records")


def new_tables_inactive(connection):
    from inspinia.pages.community_models import StatementSimilaritySource

    if list(StatementSimilaritySource.objects.values_list("singleton_key", "revision")) != [(1, 0)]:
        raise ValueError("Community source must contain only its zero-revision singleton")
    populated = {
        "pages_statementsimilaritysource",
        "pages_statementsimilarityindex",
        "pages_statementsimilaritydocument",
        "pages_statementsimilarityterm",
    }
    with connection.cursor() as cursor:
        for table in sorted(schema.TABLES - populated):
            cursor.execute(f"SELECT count(*) FROM {connection.ops.quote_name(table)}")  # noqa: S608
            if cursor.fetchone()[0] != 0:
                raise ValueError("Community/report content or AI policy/jobs were unexpectedly created")


def runtime_probe(connection):
    from django.db import transaction

    from inspinia.pages.community_models import StatementSimilaritySource
    from inspinia.pages.models import ContestProblemStatement

    row = ContestProblemStatement.objects.first()
    with transaction.atomic():
        initial = StatementSimilaritySource.objects.get(pk=1).revision
        ContestProblemStatement.objects.filter(pk=row.pk).update(statement_latex="Synthetic changed statement")
        if StatementSimilaritySource.objects.get(pk=1).revision != initial + 1:
            raise ValueError("Direct statement changes did not invalidate similarity")
        ContestProblemStatement.objects.filter(pk=row.pk).update(topic="GEO")
        if StatementSimilaritySource.objects.get(pk=1).revision != initial + 1:
            raise ValueError("Unrelated metadata invalidated similarity")
        transaction.set_rollback(True)
    if StatementSimilaritySource.objects.get(pk=1).revision != initial:
        raise ValueError("The synthetic trigger probe was not rolled back")


def authenticated_routes():
    from django.db import transaction
    from django.test import RequestFactory
    from django.test import override_settings
    from django.urls import resolve

    from inspinia.users.models import User

    with transaction.atomic(), override_settings(ALLOWED_HOSTS=["testserver"]):
        user = User.objects.get(email="schema-rehearsal@example.invalid")
        User.objects.filter(pk=user.pk).update(is_approved=True)
        user.refresh_from_db()
        factory = RequestFactory()
        for url in ("/community/problems/", "/community/problems/?tab=all", "/community/problems/new/"):
            request = factory.get(url)
            request.user = user
            if resolve(request.path).func(request).status_code != HTTPStatus.OK:
                raise ValueError("Authenticated community route failed")
        transaction.set_rollback(True)


def rehearse(connection, args):
    from django.core.management import call_command
    from django.db.migrations.executor import MigrationExecutor

    if connection.pg_version != schema.POSTGRES_VERSION or connection.introspection.table_names():
        raise ValueError("Community rehearsal requires empty PostgreSQL 17.9")
    schema.validate_candidate(Path.cwd())
    if migration_sources(Path.cwd()) != migration_sources(args.active_source.resolve()):
        raise ValueError("A prior migration source differs from the active release")
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "pages"] + [
        ("pages", "0041_statement_issue_reports"),
    ]
    executor.migrate(targets)
    apps = executor.loader.project_state(targets).apps
    seed_fixture()
    seed_subscribers()
    seed_solution(apps)
    seed_shared_snapshots(apps)
    from inspinia.pages.models import ContestProblemStatement
    from inspinia.pages.models import StatementIssueReport

    statement = ContestProblemStatement.objects.get(contest_name="SCHEMA REHEARSAL")
    StatementIssueReport.objects.create(
        statement=statement,
        statement_uuid=statement.statement_uuid,
        problem_uuid=statement.problem_uuid,
        statement_label="Synthetic preserved report",
        statement_snapshot=statement.statement_latex,
        description="Synthetic statement report retained across community setup.",
    )
    before = normalize_schema_snapshot(_snapshot(connection))
    records, sequences = existing_records(connection), existing_sequences(connection)
    triggers, metadata = trigger_definitions(connection), migration_metadata(connection)
    exec(schema.MIGRATION_APPLY, {})
    metadata_after = migration_metadata(connection)
    validate_migration_record(metadata, metadata_after)
    after = normalize_schema_snapshot(_snapshot(connection))
    delta = {field: [row for row in rows if row.get("table") in schema.TABLES] for field, rows in after.items()}
    previous = {field: [row for row in rows if row.get("table") not in schema.TABLES] for field, rows in after.items()}
    if previous != before or {row["table"] for row in delta["tables"]} != schema.TABLES or delta["extensions"]:
        raise ValueError("Community changed an existing schema object")
    preserved_triggers = [
        row for row in trigger_definitions(connection) if row[2] != "ap_statement_similarity_revision"
    ]
    if preserved_triggers != triggers:
        raise ValueError("Community changed existing trigger/function definitions")
    behaviour = schema.behaviour_snapshot(connection)
    fingerprint = catalogue_schema.behaviour_fingerprint(behaviour)
    runtime_probe(connection)
    call_command("refresh_statement_similarity_index", verbosity=0)
    exec(schema.INDEX_CHECK, {})
    authenticated_routes()
    new_tables_inactive(connection)
    subprocess.run(
        [sys.executable, "-c", schema.smoke_command()],
        cwd=args.active_source,
        env={**os.environ, "PYTHONPATH": str(args.active_source.resolve())},
        check=True,
    )
    if (
        existing_records(connection) != records
        or existing_sequences(connection) != sequences
        or migration_metadata(connection) != metadata_after
        or normalize_schema_snapshot(_snapshot(connection)) != after
        or schema.behaviour_snapshot(connection) != behaviour
    ):
        raise ValueError("Community setup or compatibility smoke changed prior data/schema")
    if getattr(args, "record_delta", False):
        args.output.write_text(json.dumps({"delta": delta, "behaviour": behaviour}, sort_keys=True, indent=2) + "\n")
    else:
        if schema_state(delta)["fingerprint"] != schema.DELTA_SHA256 or fingerprint != schema.BEHAVIOUR_SHA256:
            raise ValueError("Community schema/behaviour differ from the frozen PostgreSQL rehearsal")
        args.output.write_bytes(schema.evidence_bytes(release_sha=args.release_sha, active_sha=args.active_sha))
    connection.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-source", type=Path, required=True)
    parser.add_argument("--active-sha", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record-delta", action="store_true")
    args = parser.parse_args()
    return rehearse(prepare_django(), args)


if __name__ == "__main__":
    raise SystemExit(main())
