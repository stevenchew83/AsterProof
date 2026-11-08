# ruff: noqa: EM101, S102, S603, SLF001, TRY003
"""Isolated PostgreSQL 17.9 preservation proof for the disabled author review quota release."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from scripts.deployment import evaluation_schema as preservation
from scripts.deployment import self_solution_review_schema as schema
from scripts.deployment.newsletter_schema_rehearsal import migration_metadata
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import _snapshot


def seed_admin_reviews(apps):
    solution = apps.get_model("solutions", "ProblemSolution").objects.get(title="Synthetic preserved solution")
    target = apps.get_model("solutions", "SolutionForumTarget").objects.create(
        solution_id=solution.pk, revision_id=solution.current_revision_id,
        solution_version=solution.edit_version, solution_updated_at=solution.updated_at, key="a" * 64,
        snapshot={"document": {"source": solution.current_revision.body_source}},
    )
    settings = apps.get_model("solutions", "AdminSolutionReviewSettings").objects.create()
    apps.get_model("solutions", "AdminSolutionReview").objects.create(
        target=target, requested_by_id=solution.author_id, solver_id=solution.author_id,
        batch_id=uuid.uuid4(), key_version=settings.key_version, problem_label="SCHEMA REHEARSAL 2026 P1",
        model="gpt-6.1-sol", effort="medium", output_limit=4000, instructions="Synthetic review instructions.",
    )


def verify_preservation(connection, old_tables, before, recorder):
    if set(connection.introspection.table_names()) != old_tables | schema.TABLES:
        raise ValueError("author review quota migration changed tables outside its one-table allowance")
    after = preservation.preserved_state(connection, old_tables)
    if any(after[key] != before[key] for key in ("rows", "columns", "constraints", "triggers")):
        raise ValueError("author review quota migration changed prior rows, columns, constraints or triggers")
    prior_sequences = [row for row in after["sequences"] if row[1] not in schema.SEQUENCES]
    added_sequences = [row for row in after["sequences"] if row[1] in schema.SEQUENCES]
    if (
        prior_sequences != before["sequences"]
        or {row[1] for row in added_sequences} != schema.SEQUENCES
        or any(row[0] != "public" or row[2] is not None for row in added_sequences)
    ):
        raise ValueError("author review quota migration changed a prior sequence or used a new sequence")
    migrations, sequence = migration_metadata(connection)
    old_migrations, old_sequence = recorder
    if (
        migrations[:-1] != old_migrations
        or len(migrations) != len(old_migrations) + 1
        or migrations[-1][:3] != (old_sequence + 1, "solutions", schema.MIGRATION_NAME)
        or sequence != old_sequence + 1
    ):
        raise ValueError("Only the frozen author review quota migration recorder row may be appended")
    connection.check_constraints()
    with connection.cursor() as cursor:
        for table in sorted(schema.TABLES):
            cursor.execute("SELECT count(*) FROM " + connection.ops.quote_name(table))  # noqa: S608
            if cursor.fetchone() != (0,):
                raise ValueError("author review quota usage table must remain empty")


def run(args):
    os.environ.update(
        SELF_SOLUTION_REVIEW_ENABLED="false",
        ADMIN_SOLUTION_REVIEW_ENABLED="false",
        ADMIN_SOLUTION_REVIEW_ENCRYPTION_KEY="",
        OPENAI_API_KEY="",
    )
    connection = prepare_django()
    from django.db.migrations.executor import MigrationExecutor

    preservation.validate_connection(connection)
    if connection.pg_version != schema.POSTGRES_VERSION or connection.introspection.table_names():
        raise ValueError("author review quota rehearsal requires an empty disposable PostgreSQL 17.9 database")
    schema.validate_candidate(Path.cwd())
    if schema.migration_tree_sha256(args.active_source) != schema.PRIOR_MIGRATION_TREE_SHA256:
        raise ValueError("Active source has different prior migrations")
    if (args.active_source / schema.MIGRATION_PATH).exists():
        raise ValueError("Active source already has the author review quota migration")
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node != ("solutions", schema.MIGRATION_NAME)] + [
        ("solutions", "0014_admin_solution_review"),
    ]
    executor.migrate(targets)
    preservation.seed_legacy(executor, targets, connection)
    seed_admin_reviews(executor.loader.project_state(targets).apps)
    old_tables = set(connection.introspection.table_names())
    before = preservation.preserved_state(connection, old_tables)
    recorder = migration_metadata(connection)
    before_catalog = normalize_schema_snapshot(_snapshot(connection))
    exec(schema.MIGRATION_APPLY, {})
    verify_preservation(connection, old_tables, before, recorder)
    after = normalize_schema_snapshot(_snapshot(connection))
    delta = {field: [row for row in rows if row.get("table") in schema.TABLES] for field, rows in after.items()}
    existing = {field: [row for row in rows if row.get("table") not in schema.TABLES] for field, rows in after.items()}
    if existing != before_catalog:
        raise ValueError("author review quota migration changed a prior catalog object")
    discovery = getattr(args, "discover_delta", None)
    if discovery:
        discovery.write_text(json.dumps(delta, sort_keys=True, indent=2) + "\n")
        raise ValueError("Discovery only: freeze the delta, then run the strict rehearsal")
    if schema_state(delta)["fingerprint"] != schema.DELTA_SHA256:
        raise ValueError("author review quota schema differs from the frozen delta")
    subprocess.run(
        [sys.executable, "-c", schema.smoke_command()],
        cwd=args.active_source,
        env={**os.environ, "PYTHONPATH": str(args.active_source.resolve())},
        check=True,
    )
    verify_preservation(connection, old_tables, before, recorder)
    if normalize_schema_snapshot(_snapshot(connection)) != after:
        raise ValueError("Active revision smoke changed the catalog")
    evidence = schema.build_evidence(args.release_sha, args.active_sha)
    args.output.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    connection.close()
    return 0


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-source", type=Path, required=True)
    parser.add_argument("--active-sha", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--discover-delta", type=Path)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
