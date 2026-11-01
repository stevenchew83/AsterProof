# ruff: noqa: EM101, EM102, S102, S603, SLF001, TRY003
"""Rehearse the exact four-table prototype bundle on disposable PostgreSQL 17.9."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment import assessment_prototype_schema as schema
from scripts.deployment import evaluation_schema as preservation
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import _snapshot


def verify_preservation(connection, old_tables, before):
    if set(connection.introspection.table_names()) != old_tables | schema.TABLES:
        raise ValueError("Prototype migration changed tables outside its four-table bundle")
    after = preservation.preserved_state(connection, old_tables)
    for key in ("rows", "columns", "constraints", "triggers"):
        if before[key] != after[key]:
            raise ValueError(f"Prototype migration changed existing {key}")
    new_sequences = {"solutions_evaluationpackageapproval_id_seq", "solutions_synthetichintreveal_id_seq"}
    existing_sequences = [row for row in after["sequences"] if row[1] not in new_sequences]
    added_sequences = [row for row in after["sequences"] if row[1] in new_sequences]
    if (
        existing_sequences != before["sequences"]
        or {row[1] for row in added_sequences} != new_sequences
        or any(row[0] != "public" or row[2] is not None for row in added_sequences)
    ):
        raise ValueError("Prototype migration changed an existing sequence or used a new sequence")
    added = after["migrations"][len(before["migrations"]) :]
    if (
        after["migrations"][: len(before["migrations"])] != before["migrations"]
        or [tuple(row[1:3]) for row in added] != list(schema.MIGRATIONS)
        or [row[0] for row in added]
        != [before["migrations"][-1][0] + index for index in range(1, len(schema.MIGRATIONS) + 1)]
    ):
        raise ValueError("Only the two frozen migration recorder rows may be appended")
    connection.check_constraints()
    with connection.cursor() as cursor:
        for table in sorted(schema.TABLES):
            cursor.execute("SELECT count(*) FROM " + connection.ops.quote_name(table))  # noqa: S608
            if cursor.fetchone() != (0,):
                raise ValueError("Prototype tables must remain empty after migration")
        cursor.execute("SELECT enabled,daily_budget_micros,monthly_budget_micros FROM solutions_solutionreviewpolicy")
        if cursor.fetchall() != [(False, 0, 0)]:
            raise ValueError("AI policy must remain disabled and unfunded")


def run(args):
    os.environ.update(
        OPENAI_API_KEY="",
        SOLUTION_AI_REVIEW_ENABLED="false",
        PROBLEM_STATEMENT_AI_REVIEW_ENABLED="false",
        SOLUTION_AI_EXECUTION_MODE="offline",
    )
    connection = prepare_django()
    from django.conf import settings
    from django.db.migrations.executor import MigrationExecutor

    settings.SOLUTION_AI_REVIEW_ENABLED = False
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = False
    settings.SYNTHETIC_REVIEW_PROTOTYPE_ENABLED = False
    settings.SOLUTION_AI_EXECUTION_MODE = "offline"
    settings.OPENAI_API_KEY = ""
    preservation.validate_connection(connection)
    if connection.pg_version != schema.POSTGRES_VERSION or connection.introspection.table_names():
        raise ValueError("Prototype rehearsal requires empty disposable PostgreSQL 17.9")
    schema.validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "solutions"] + [
        ("solutions", "0010_offline_evaluation_contract"),
    ]
    executor.migrate(targets)
    preservation.seed_legacy(executor, targets, connection)
    old_tables = set(connection.introspection.table_names())
    before = preservation.preserved_state(connection, old_tables)
    before_catalog = normalize_schema_snapshot(_snapshot(connection))
    exec(schema.MIGRATION_APPLY, {})
    verify_preservation(connection, old_tables, before)
    after = normalize_schema_snapshot(_snapshot(connection))
    delta = {field: [row for row in rows if row.get("table") in schema.TABLES] for field, rows in after.items()}
    previous = {field: [row for row in rows if row.get("table") not in schema.TABLES] for field, rows in after.items()}
    if previous != before_catalog or schema_state(delta)["fingerprint"] != schema.DELTA_SHA256:
        raise ValueError("Prototype schema differs from its exact frozen PostgreSQL delta")
    metadata_after = preservation.preserved_state(connection, old_tables)["migrations"]
    smoke_env = {**os.environ, "PYTHONPATH": str(args.active_source.resolve())}
    subprocess.run([sys.executable, "-c", schema.smoke_command()], cwd=args.active_source, env=smoke_env, check=True)
    verify_preservation(connection, old_tables, before)
    if (
        normalize_schema_snapshot(_snapshot(connection)) != after
        or preservation.preserved_state(connection, old_tables)["migrations"] != metadata_after
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
        "new_evidence_tables_empty": True,
        "existing_trigger_definitions_unchanged": True,
        "ai_disabled_and_unfunded": True,
        "synthetic_prototype_disabled": True,
    }
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
