# ruff: noqa: E402, EM101, S102, S603, TRY003
"""Rehearse only the frozen evaluation migration and the active application on disposable PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment import evaluation_schema as preservation
from scripts.deployment import solution_evaluation_schema as schema
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import _snapshot


def run(args):
    os.environ.update(OPENAI_API_KEY="", SOLUTION_AI_REVIEW_ENABLED="false",
                      PROBLEM_STATEMENT_AI_REVIEW_ENABLED="false", SOLUTION_AI_EXECUTION_MODE="offline")
    connection = prepare_django()
    from django.conf import settings
    from django.db.migrations.executor import MigrationExecutor

    settings.SOLUTION_AI_REVIEW_ENABLED = False
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = False
    settings.SOLUTION_AI_EXECUTION_MODE = "offline"
    settings.OPENAI_API_KEY = ""
    preservation.validate_connection(connection)
    if connection.pg_version != schema.POSTGRES_VERSION or connection.introspection.table_names():
        raise ValueError("Evaluation rehearsal requires empty disposable PostgreSQL 17.9")
    schema.validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "solutions"] + [
        ("solutions", preservation.BASELINE_NAME),
    ]
    executor.migrate(targets)
    preservation.seed_legacy(executor, targets, connection)
    old_tables = set(connection.introspection.table_names())
    before = preservation.preserved_state(connection, old_tables)
    before_catalog = normalize_schema_snapshot(_snapshot(connection))
    exec(schema.MIGRATION_APPLY, {})
    preservation.verify_preservation(connection, old_tables, before)
    after = normalize_schema_snapshot(_snapshot(connection))
    delta = {field: [row for row in rows if row.get("table") in schema.TABLES]
             for field, rows in after.items()}
    previous = {field: [row for row in rows if row.get("table") not in schema.TABLES]
                for field, rows in after.items()}
    if previous != before_catalog or {row["table"] for row in delta["tables"]} != schema.TABLES:
        raise ValueError("Evaluation migration changed objects outside its frozen nineteen tables")
    if schema_state(delta)["fingerprint"] != schema.DELTA_SHA256:
        raise ValueError("Evaluation schema delta differs from its frozen PostgreSQL fixture")
    metadata_after = preservation.preserved_state(connection, old_tables)["migrations"]
    smoke_env = {**os.environ, "PYTHONPATH": str(args.active_source.resolve())}
    subprocess.run([sys.executable, "-c", schema.smoke_command()], cwd=args.active_source, env=smoke_env, check=True)
    preservation.verify_preservation(connection, old_tables, before)
    if (normalize_schema_snapshot(_snapshot(connection)) != after
            or preservation.preserved_state(connection, old_tables)["migrations"] != metadata_after):
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
