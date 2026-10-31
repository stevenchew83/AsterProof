# ruff: noqa: E402, EM101, S102, S603, TRY003
"""Prove only one first-login preference column in the pinned empty Actions database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment import onboarding_schema as schema
from scripts.deployment.newsletter_schema_rehearsal import existing_sequences
from scripts.deployment.newsletter_schema_rehearsal import migration_metadata
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.newsletter_schema_rehearsal import seed_subscribers
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import _snapshot


def existing_records(connection):
    """Compare every prior column value, excluding only the one addition."""
    records = {}
    for table in sorted(connection.introspection.table_names()):
        if table == "django_migrations":
            continue
        digest = hashlib.sha256()
        quoted = connection.ops.quote_name(table)
        expression = "to_jsonb(source)"
        if table == schema.TABLE:
            expression += " - ARRAY['solution_guide_status']::text[]"
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT ({expression})::text FROM {quoted} source "  # noqa: S608 - fixed expression, quoted introspected table
                f'ORDER BY ({expression})::text COLLATE "C"',
            )
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    digest.update(row[0].encode())
                    digest.update(b"\0")
        records[table] = digest.hexdigest()
    return records


def trigger_definitions(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT n.nspname,c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid),pg_get_functiondef(p.oid) "
            "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid "
            "WHERE NOT t.tgisinternal AND n.nspname='public' ORDER BY 1,2,3",
        )
        return cursor.fetchall()


def validate_migration_record(before, after):
    rows_before, sequence_before = before
    rows_after, sequence_after = after
    if (
        len(rows_after) != len(rows_before) + 1
        or rows_after[:-1] != rows_before
        or rows_after[-1][1:3] != ("users", schema.MIGRATION_NAME)
        or rows_after[-1][0] != sequence_before + 1
        or sequence_after != sequence_before + 1
    ):
        raise ValueError("Onboarding rehearsal changed migration metadata beyond its one frozen record")


def seed_solution(apps):
    from inspinia.pages.models import ProblemSolveRecord

    # Use the historical model: candidate runtime fields do not exist yet.
    solution = apps.get_model("solutions", "ProblemSolution").objects.create(
        author_id=apps.get_model("users", "User").objects.get(email="schema-rehearsal@example.invalid").pk,
        problem_id=ProblemSolveRecord.objects.get(contest="SCHEMA REHEARSAL").pk,
        title="Synthetic preserved solution",
        summary="Synthetic preserved summary.",
        status="draft",
    )
    apps.get_model("solutions", "ProblemSolutionBlock").objects.create(
        solution_id=solution.pk,
        position=1,
        body_source="Synthetic preserved proof.",
    )


def existing_users_not_enrolled(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*), bool_and(solution_guide_status='not_enrolled') FROM users_user")
        count, all_legacy = cursor.fetchone()
        return count > 0 and all_legacy is True


def new_accounts_enrolled():
    from django.db import transaction

    from inspinia.users.models import User

    with transaction.atomic():
        user = User.objects.create(pk=2147483001, email="new-code-signup@schema-rehearsal.example.invalid")
        user.refresh_from_db()
        if user.solution_guide_status != User.SolutionGuideStatus.ACTIVE:
            raise ValueError("New accounts do not receive the first-login guide")
        transaction.set_rollback(True)


def seed_fixture(apps):
    from inspinia.pages.models import ContestProblemStatement
    from inspinia.pages.models import ProblemSolveRecord
    from inspinia.pages.models import StatementTopicTechnique
    from inspinia.pages.models import UserProblemCompletion

    user = apps.get_model("users", "User").objects.create(
        email="schema-rehearsal@example.invalid",
        name="Synthetic existing learner",
        is_approved=True,
    )
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
    UserProblemCompletion.objects.create(user_id=user.pk, problem=problem, statement=statement)


def run(args):
    connection = prepare_django()
    from django.db.migrations.executor import MigrationExecutor

    if connection.pg_version != schema.POSTGRES_VERSION:
        raise ValueError("Onboarding rehearsal requires the pinned PostgreSQL 17.9 runtime")
    if connection.introspection.table_names():
        raise ValueError("Onboarding rehearsal database must be empty")
    schema.validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "users"] + [
        ("users", "0008_useraccesssettings"),
    ]
    executor.migrate(targets)
    seed_fixture(executor.loader.project_state(targets).apps)
    seed_subscribers()
    seed_solution(executor.loader.project_state(targets).apps)
    before = normalize_schema_snapshot(_snapshot(connection))
    records = existing_records(connection)
    sequences = existing_sequences(connection)
    triggers = trigger_definitions(connection)
    metadata_before = migration_metadata(connection)
    exec(schema.MIGRATION_APPLY, {})
    new_accounts_enrolled()
    metadata_after = migration_metadata(connection)
    validate_migration_record(metadata_before, metadata_after)
    after = normalize_schema_snapshot(_snapshot(connection))
    delta = {field: [] for field in before}
    delta["columns"] = [
        row for row in after["columns"] if row["table"] == schema.TABLE and row["column"] in schema.COLUMNS
    ]
    previous = {field: list(rows) for field, rows in after.items()}
    previous["columns"] = [row for row in after["columns"] if row not in delta["columns"]]
    if {row["column"] for row in delta["columns"]} != schema.COLUMNS:
        raise ValueError("Onboarding rehearsal did not add the one frozen column")
    if (
        previous != before
        or existing_records(connection) != records
        or existing_sequences(connection) != sequences
        or trigger_definitions(connection) != triggers
        or not existing_users_not_enrolled(connection)
    ):
        raise ValueError("Onboarding migration changed existing schema, records, sequences, triggers, or defaults")
    fingerprint = schema_state(delta)["fingerprint"]
    if not getattr(args, "record_delta", False) and fingerprint != schema.DELTA_SHA256:
        detail = json.dumps(delta, sort_keys=True)
        message = f"Onboarding schema delta differs from the frozen fixture: {fingerprint}; {detail}"
        raise ValueError(message)
    smoke_env = {**os.environ, "PYTHONPATH": str(args.active_source.resolve())}
    subprocess.run([sys.executable, "-c", schema.smoke_command()], cwd=args.active_source, env=smoke_env, check=True)
    if (
        normalize_schema_snapshot(_snapshot(connection)) != after
        or existing_records(connection) != records
        or existing_sequences(connection) != sequences
        or migration_metadata(connection) != metadata_after
        or trigger_definitions(connection) != triggers
        or not existing_users_not_enrolled(connection)
    ):
        raise ValueError("Active-revision smoke changed existing schema, records, sequences, or triggers")
    if getattr(args, "record_delta", False):
        output = delta  # Discovery only; this is not accepted as deployable build evidence.
    else:
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
            "existing_users_not_enrolled": True,
            "new_accounts_enrolled": True,
            "existing_trigger_definitions_unchanged": True,
        }
    args.output.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n")
    print("Onboarding PostgreSQL delta:", fingerprint)  # noqa: T201
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
