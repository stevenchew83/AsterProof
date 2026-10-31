# ruff: noqa: E402, EM101, S102, S603, TRY003
"""Rehearse pages.0040 only in the pinned, empty Actions PostgreSQL database."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment import statement_authoring_schema as schema
from scripts.deployment.newsletter_schema_rehearsal import existing_sequences
from scripts.deployment.newsletter_schema_rehearsal import migration_metadata
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.newsletter_schema_rehearsal import seed_subscribers
from scripts.deployment.onboarding_schema_rehearsal import seed_fixture
from scripts.deployment.onboarding_schema_rehearsal import seed_solution
from scripts.deployment.onboarding_schema_rehearsal import trigger_definitions
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_rehearsal import _snapshot


def existing_records(connection):
    records = {}
    for table in sorted(connection.introspection.table_names()):
        if table == "django_migrations":
            continue
        digest = hashlib.sha256()
        quoted = connection.ops.quote_name(table)
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT to_jsonb(source)::text FROM {quoted} source "  # noqa: S608 - quoted introspected fixture table
                'ORDER BY to_jsonb(source)::text COLLATE "C"',
            )
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    digest.update(row[0].encode())
                    digest.update(b"\0")
        records[table] = digest.hexdigest()
    return records


def migration_sources(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "inspinia").rglob("*")
        if path.parent.name == "migrations" and path.suffix in {".py", ".json"}
        and path.relative_to(root) != schema.MIGRATION_PATH
    }


def validate_migration_record(before, after):
    rows_before, sequence_before = before
    rows_after, sequence_after = after
    if (
        len(rows_after) != len(rows_before) + 1 or rows_after[:-1] != rows_before
        or rows_after[-1][1:3] != ("pages", schema.MIGRATION_NAME)
        or rows_after[-1][0] != sequence_before + 1 or sequence_after != sequence_before + 1
    ):
        raise ValueError("Statement-authoring changed migration metadata beyond its one frozen record")


def unknown_difficulty_roundtrip():
    from django.db import transaction

    from inspinia.pages.models import ProblemSolveRecord

    # Explicit synthetic PK prevents advancing any existing sequence. Trigger writes
    # and the probe row roll back together; no original record is changed.
    with transaction.atomic():
        problem = ProblemSolveRecord.objects.create(
            pk=2147483002, contest="C" * 128, year=2026, problem="P1", topic="", mohs=None,
            contest_year_problem="L" * 160,
        )
        problem.refresh_from_db()
        if problem.mohs is not None or problem.contest != "C" * 128 or problem.contest_year_problem != "L" * 160:
            raise ValueError("Unknown difficulty or canonical statement labels failed to round-trip")
        transaction.set_rollback(True)


def run(args):
    connection = prepare_django()
    from django.db.migrations.executor import MigrationExecutor

    if connection.pg_version != schema.POSTGRES_VERSION or connection.introspection.table_names():
        raise ValueError("Statement-authoring rehearsal requires the pinned empty PostgreSQL 17.9 database")
    schema.validate_candidate(Path.cwd())
    if migration_sources(Path.cwd()) != migration_sources(args.active_source.resolve()):
        raise ValueError("A prior migration source differs from the active release")
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "pages"] + [
        ("pages", "0039_catalogue_revision_triggers"),
    ]
    executor.migrate(targets)
    apps = executor.loader.project_state(targets).apps
    seed_fixture(apps)
    seed_subscribers()
    seed_solution(apps)
    before = normalize_schema_snapshot(_snapshot(connection))
    records, sequences = existing_records(connection), existing_sequences(connection)
    triggers, metadata = trigger_definitions(connection), migration_metadata(connection)
    exec(schema.MIGRATION_APPLY, {})
    metadata_after = migration_metadata(connection)
    validate_migration_record(metadata, metadata_after)
    after = normalize_schema_snapshot(_snapshot(connection))
    if after != schema.changed_schema(before):
        raise ValueError("PostgreSQL changed more than the three frozen statement-authoring columns")
    unknown_difficulty_roundtrip()
    subprocess.run(
        [sys.executable, "-c", schema.smoke_command()], cwd=args.active_source,
        env={**os.environ, "PYTHONPATH": str(args.active_source.resolve())}, check=True,
    )
    if (
        normalize_schema_snapshot(_snapshot(connection)) != after
        or existing_records(connection) != records or existing_sequences(connection) != sequences
        or trigger_definitions(connection) != triggers or migration_metadata(connection) != metadata_after
    ):
        raise ValueError("Statement-authoring migration or smoke changed existing records, sequences or triggers")
    behaviour = schema.catalogue_schema.behaviour_snapshot(connection)
    schema.catalogue_schema.validate_behaviour_shape(behaviour)
    if schema.catalogue_schema.behaviour_fingerprint(behaviour) != schema.catalogue_schema.BEHAVIOUR_SHA256:
        raise ValueError("Statement-authoring changed the frozen catalogue behaviour")
    args.output.write_bytes(schema.evidence_bytes(release_sha=args.release_sha, active_sha=args.active_sha))
    connection.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-source", type=Path, required=True)
    parser.add_argument("--active-sha", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
