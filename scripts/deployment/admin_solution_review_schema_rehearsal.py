# ruff: noqa: EM101, S102, S603, SLF001, TRY003 - Disposable schema rehearsal with fixed subprocess code.
"""Prove the two-table admin review migration on an empty PostgreSQL 17.9 database."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment import admin_solution_review_schema as schema
from scripts.deployment import evaluation_schema as preservation
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import _snapshot


def prepare_fixture(connection):
    from django.db.migrations.executor import MigrationExecutor

    if connection.introspection.table_names():
        raise ValueError("Admin review rehearsal requires an empty database")
    schema.validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "solutions"]
    targets.append(("solutions", "0013_solution_forum"))
    executor.migrate(targets)
    preservation.seed_legacy(executor, targets, connection)

    apps = executor.loader.project_state(targets).apps
    solution = apps.get_model("solutions", "ProblemSolution").objects.get(title="Synthetic preserved solution")
    apps.get_model("solutions", "SolutionForumTarget").objects.create(
        solution_id=solution.pk, revision_id=solution.current_revision_id,
        solution_version=solution.edit_version, solution_updated_at=solution.updated_at, key="a" * 64,
        snapshot={"document": {"source": solution.current_revision.body_source}},
    )
    return set(connection.introspection.table_names())


def verify_preservation(connection, tables, before):
    if set(connection.introspection.table_names()) != tables | schema.TABLES:
        raise ValueError("Admin review migration changed tables outside its approved scope")
    after = preservation.preserved_state(connection, tables)
    for key in ("rows", "columns", "constraints", "triggers", "sequences"):
        if before[key] != after[key]:
            message = f"Admin review migration changed existing {key}"
            raise ValueError(message)
    previous = before["migrations"]
    added = after["migrations"][len(previous):]
    if (
        after["migrations"][:len(previous)] != previous or len(added) != 1
        or added[0][1:3] != ("solutions", schema.MIGRATION_NAME)
        or added[0][0] != previous[-1][0] + 1
    ):
        raise ValueError("Only the approved admin review migration record may be appended")
    with connection.cursor() as cursor:
        for table in sorted(schema.TABLES):
            cursor.execute("SELECT count(*) FROM " + connection.ops.quote_name(table))  # noqa: S608
            if cursor.fetchone() != (0,):
                raise ValueError("New admin review tables must be empty")
    connection.check_constraints()


def rehearse_migration(connection):
    tables = prepare_fixture(connection)
    before = preservation.preserved_state(connection, tables)
    before_catalog = normalize_schema_snapshot(_snapshot(connection))
    exec(schema.MIGRATION_APPLY, {})
    verify_preservation(connection, tables, before)
    after = normalize_schema_snapshot(_snapshot(connection))
    prior = {field: [row for row in rows if row.get("table") not in schema.TABLES] for field, rows in after.items()}
    if prior != before_catalog:
        raise ValueError("Admin review migration changed prior catalog objects")
    delta = {field: [row for row in rows if row.get("table") in schema.TABLES] for field, rows in after.items()}
    return tables, before, after, delta


def run(args):
    os.environ.update(
        ADMIN_SOLUTION_REVIEW_ENABLED="false", ADMIN_SOLUTION_REVIEW_ENCRYPTION_KEY="",
        SOLUTION_AI_REVIEW_ENABLED="false", PROBLEM_STATEMENT_AI_REVIEW_ENABLED="false", OPENAI_API_KEY="",
    )
    connection = prepare_django()
    preservation.validate_connection(connection)
    if connection.pg_version != schema.POSTGRES_VERSION:
        raise ValueError("Authoritative admin review rehearsal requires PostgreSQL 17.9")
    tables, before, after, delta = rehearse_migration(connection)
    if schema_state(delta)["fingerprint"] != schema.DELTA_SHA256:
        raise ValueError("Admin review catalog delta differs from the reviewed fixture")
    smoke_env = {**os.environ, "PYTHONPATH": str(args.active_source.resolve())}
    subprocess.run([sys.executable, "-c", schema.smoke_command()], cwd=args.active_source, env=smoke_env, check=True)
    verify_preservation(connection, tables, before)
    if normalize_schema_snapshot(_snapshot(connection)) != after:
        raise ValueError("The active release changed catalog metadata during compatibility smoke")
    output = schema.build_evidence(source_sha=args.release_sha, active_sha=args.active_sha)
    args.output.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n")
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
