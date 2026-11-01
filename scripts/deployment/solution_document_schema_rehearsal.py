# ruff: noqa: E402, EM101, S102, S603, PLR2004, TRY003
"""Rehearse the exact additive document/review schema in isolated PostgreSQL 17.9."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment import solution_document_schema as schema
from scripts.deployment.newsletter_schema_rehearsal import existing_sequences as all_sequences
from scripts.deployment.newsletter_schema_rehearsal import migration_metadata
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.newsletter_schema_rehearsal import seed_fixture
from scripts.deployment.newsletter_schema_rehearsal import seed_subscribers
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import sha256_fingerprint
from scripts.deployment.schema_rehearsal import _snapshot
from scripts.deployment.solution_collections_schema_rehearsal import seed_shared_snapshots
from scripts.deployment.solution_collections_schema_rehearsal import seed_solution
from scripts.deployment.solution_collections_schema_rehearsal import trigger_definitions


def existing_records(connection):
    """Hash prior values, excluding only the two additive document columns."""
    records = {}
    for table in sorted(connection.introspection.table_names()):
        if table == "django_migrations" or table in schema.TABLES:
            continue
        expression = "to_jsonb(source)"
        if table == schema.TABLE:
            expression += " - ARRAY['edit_version','current_revision_id']::text[]"
        digest = hashlib.sha256()
        with connection.cursor() as cursor:
            quoted = connection.ops.quote_name(table)
            cursor.execute(
                f"SELECT ({expression})::text FROM {quoted} source "  # noqa: S608 - fixed expression and quoted table
                f'ORDER BY ({expression})::text COLLATE "C"',
            )
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    digest.update(row[0].encode())
                    digest.update(b"\0")
        records[table] = digest.hexdigest()
    return records


def validate_migration_record(before, after):
    rows_before, sequence_before = before
    rows_after, sequence_after = after
    if (
        len(rows_after) != len(rows_before) + 1
        or rows_after[:-1] != rows_before
        or rows_after[-1][1:3] != ("solutions", schema.MIGRATION_NAME)
        or rows_after[-1][0] != sequence_before + 1
        or sequence_after != sequence_before + 1
    ):
        raise ValueError("Document rehearsal changed migration metadata beyond its one approved record")


def seed_collections(apps):
    """Populate historical collections, order, anchors, and active/stopped generations."""
    shares = apps.get_model("solutions", "SolutionPublicShare")
    collection_model = apps.get_model("solutions", "SolutionCollection")
    entry_model = apps.get_model("solutions", "SolutionCollectionEntry")
    active = shares.objects.get(is_active=True)
    stopped = shares.objects.get(is_active=False)
    collection = collection_model.objects.create(
        owner_id=active.solution.author_id, title="Synthetic preserved personal collection",
        introduction="Synthetic preserved introduction.",
    )
    for position, share in enumerate((stopped, active), start=1):
        entry_model.objects.create(collection=collection, share=share, position=position, share_token=share.token)
    collection_model.objects.create(
        owner_id=active.solution.author_id, title="Synthetic stopped collection", is_active=False,
    )


def existing_sequences(connection):
    return [row for row in all_sequences(connection) if row[1] != "solutions_solutionreviewpolicy_id_seq"]


def document_schema_defaults_safe(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*),bool_and(edit_version=0 AND current_revision_id IS NULL) "
            "FROM solutions_problemsolution",
        )
        count, valid = cursor.fetchone()
        if not count or valid is not True:
            return False
        for table in sorted(schema.TABLES):
            cursor.execute(
                f"SELECT EXISTS (SELECT 1 FROM {connection.ops.quote_name(table)})",  # noqa: S608 - Frozen table names.
            )
            if cursor.fetchone()[0]:
                return False
        cursor.execute("SELECT last_value FROM pg_catalog.pg_sequences WHERE schemaname='public' "
                       "AND sequencename='solutions_solutionreviewpolicy_id_seq'")
        return cursor.fetchone() == (None,)


def validate_alteration_shape(delta):
    removed, added = delta["removed"], delta["added"]
    if any(removed.values()) or added["extensions"]:
        raise ValueError("Document migration removed existing objects or added extensions")
    if {row["table"] for row in added["tables"]} != schema.TABLES:
        raise ValueError("Document migration must add exactly its three tables")
    columns = [row for row in added["columns"] if row["table"] == schema.TABLE]
    if {row["column"] for row in columns} != schema.COLUMNS or len(columns) != 2:
        raise ValueError("Document migration must add exactly its two solution columns")
    version = next(row for row in columns if row["column"] == "edit_version")
    pointer = next(row for row in columns if row["column"] == "current_revision_id")
    if version["nullable"] or version["default"] != "0" or not pointer["nullable"]:
        raise ValueError("Document version/pointer defaults differ from the compatible plan")
    allowed = schema.TABLES | {schema.TABLE}
    if any(row["table"] not in allowed for group in ("columns", "constraints", "indexes") for row in added[group]):
        raise ValueError("Document schema changed an unrelated table")


def rehearse(connection, args):
    from django.db.migrations.executor import MigrationExecutor

    if connection.pg_version != schema.POSTGRES_VERSION:
        raise ValueError("Document rehearsal requires the pinned PostgreSQL 17.9 runtime")
    if connection.introspection.table_names():
        raise ValueError("Document rehearsal database must be empty")
    schema.validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "solutions"] + [
        ("solutions", "0008_solutioncollection_kind_and_nullable_owner"),
    ]
    executor.migrate(targets)
    apps = executor.loader.project_state(targets).apps
    seed_fixture()
    seed_subscribers()
    seed_solution(apps)
    seed_shared_snapshots(apps)
    seed_collections(apps)
    before = normalize_schema_snapshot(_snapshot(connection))
    records = existing_records(connection)
    sequences = existing_sequences(connection)
    triggers = trigger_definitions(connection)
    metadata_before = migration_metadata(connection)
    exec(schema.MIGRATION_APPLY, {})
    metadata_after = migration_metadata(connection)
    validate_migration_record(metadata_before, metadata_after)
    after = normalize_schema_snapshot(_snapshot(connection))
    delta = schema.schema_delta(before, after)
    validate_alteration_shape(delta)
    fingerprint = sha256_fingerprint(delta)
    if not getattr(args, "record_delta", False) and schema.apply_delta(before, delta) != after:
        raise ValueError("Document migration differs from its frozen alteration")
    if (
        existing_records(connection) != records
        or existing_sequences(connection) != sequences
        or trigger_definitions(connection) != triggers
        or not document_schema_defaults_safe(connection)
    ):
        raise ValueError(
            "Document migration changed existing rows, order, anchors, sharing, counters, sequences, or triggers",
        )
    if not getattr(args, "skip_active_smoke", False):
        smoke_env = {**os.environ, "PYTHONPATH": str(args.active_source.resolve())}
        subprocess.run(
            [sys.executable, "-c", schema.smoke_command()], cwd=args.active_source, env=smoke_env, check=True,
        )
    elif not getattr(args, "record_delta", False):
        raise ValueError("Deployable evidence requires the independently checked active revision smoke")
    if (
        normalize_schema_snapshot(_snapshot(connection)) != after
        or existing_records(connection) != records
        or existing_sequences(connection) != sequences
        or migration_metadata(connection) != metadata_after
        or trigger_definitions(connection) != triggers
        or not document_schema_defaults_safe(connection)
    ):
        raise ValueError("Old-code compatibility smoke changed preserved fixture/schema state")
    output = delta if getattr(args, "record_delta", False) else {
        "format_version": 1,
        "source_sha": args.release_sha,
        "active_sha": args.active_sha,
        "postgres_version": connection.pg_version,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "delta_sha256": schema.DELTA_SHA256,
        "only_approved_schema_changed": True,
        "source_fixture_unchanged": True,
        "active_revision_smoke_passed": True,
        "existing_records_unchanged": True,
        "existing_sequences_unchanged": True,
        "document_schema_defaults_safe": True,
        "existing_trigger_definitions_unchanged": True,
    }
    args.output.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n")
    print("Document PostgreSQL alteration:", fingerprint)  # noqa: T201
    connection.close()
    return 0


def run(args):
    return rehearse(prepare_django(), args)


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
