# ruff: noqa: EM101, S102, S603, TRY003
"""Rehearse the exact AI review take-down allowance on disposable PostgreSQL 17.9."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from django.utils import timezone

from scripts.deployment import admin_review_takedown_schema as schema
from scripts.deployment import evaluation_schema as preservation
from scripts.deployment.newsletter_schema_rehearsal import migration_metadata
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import _snapshot
from scripts.deployment.self_solution_review_schema_rehearsal import seed_admin_reviews


def verify_preservation(  # noqa: PLR0913 - Keep the independent preservation checks explicit.
    connection, old_tables, before, old_review, legacy_reviews, before_catalog, recorder,
):
    after = normalize_schema_snapshot(_snapshot(connection))
    delta = {field: [row for row in rows if row not in before_catalog[field]] for field, rows in after.items()}
    if (
        schema_state(delta)["fingerprint"] != schema.DELTA_SHA256
        or any(row not in after[field] for field, rows in before_catalog.items() for row in rows)
        or old_tables != set(connection.introspection.table_names())
    ):
        raise ValueError("PostgreSQL catalog differs from the frozen review take-down delta")
    observed = preservation.preserved_state(connection, old_tables - {schema.TABLE})
    if any(observed[key] != before[key] for key in ("rows", "columns", "constraints", "sequences", "triggers")):
        raise ValueError("Migration changed previously stored records or database objects")
    if legacy_reviews.values().get() != old_review:
        raise ValueError("Migration changed the existing published review")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM solutions_adminsolutionreview "
            "WHERE taken_down_at IS NOT NULL OR taken_down_by_id IS NOT NULL",
        )
        if cursor.fetchone() != (0,):
            raise ValueError("New take-down metadata must be null for existing reviews")
    (old_rows, old_sequence), (new_rows, new_sequence) = recorder, migration_metadata(connection)
    if (
        new_rows[:-1] != old_rows or len(new_rows) != len(old_rows) + 1
        or new_rows[-1][:3] != (old_sequence + 1, "solutions", schema.MIGRATION_NAME)
        or new_sequence != old_sequence + 1
    ):
        raise ValueError("Only the expected take-down migration recorder row may be appended")
    connection.check_constraints()


def run(args):
    connection = prepare_django()
    from django.db.migrations.executor import MigrationExecutor

    preservation.validate_connection(connection)
    if connection.pg_version != schema.POSTGRES_VERSION or connection.introspection.table_names():
        raise ValueError("Review take-down rehearsal requires an empty PostgreSQL 17.9 database")
    schema.validate_candidate(Path.cwd())
    if (args.active_source / schema.MIGRATION_PATH).exists() or (
        schema.migration_tree_sha256(args.active_source) != schema.PRIOR_MIGRATION_TREE_SHA256
    ):
        raise ValueError("Active source differs from the required migration baseline")
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "solutions"] + [schema.PREVIOUS]
    executor.migrate(targets)
    preservation.seed_legacy(executor, targets, connection)
    apps = executor.loader.project_state(targets).apps
    seed_admin_reviews(apps)
    legacy_reviews = apps.get_model("solutions", "AdminSolutionReview").objects
    legacy_reviews.update(
        status="completed", score=0, feedback="Preserved synthetic review feedback.",
        published_at=timezone.now(), notification="pending",
    )
    old_review = legacy_reviews.values().get()
    old_tables = set(connection.introspection.table_names())
    before = preservation.preserved_state(connection, old_tables - {schema.TABLE})
    before_catalog = normalize_schema_snapshot(_snapshot(connection))
    recorder = migration_metadata(connection)
    exec(schema.MIGRATION_APPLY, {})
    verify_preservation(connection, old_tables, before, old_review, legacy_reviews, before_catalog, recorder)
    subprocess.run(
        [sys.executable, "-c", schema.SMOKE_COMMAND],
        cwd=args.active_source,
        env={**os.environ, "PYTHONPATH": str(args.active_source.resolve())},
        check=True,
    )
    verify_preservation(connection, old_tables, before, old_review, legacy_reviews, before_catalog, recorder)
    args.output.write_bytes(schema.evidence_bytes(args.release_sha, args.active_sha))
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
