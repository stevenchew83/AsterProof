# ruff: noqa: SLF001, T201
"""Compare exact pre-0017 records to the verified recovery manifest."""

import argparse
import sys

from scripts.deployment import database_recovery as recovery
from scripts.deployment import multiple_solutions_schema as schema
from scripts.deployment.community_proof_preservation import DIGEST_RE
from scripts.deployment.community_proof_preservation import IDENTITY_COLUMNS
from scripts.deployment.community_proof_preservation import MAX_OBJECTS
from scripts.deployment.community_proof_preservation import MIGRATION_SEQUENCE
from scripts.deployment.community_proof_preservation import SOURCE_IDENTITY_SQL
from scripts.deployment.community_proof_preservation import _digest_record
from scripts.deployment.community_proof_preservation import _record_map
from scripts.deployment.community_proof_preservation import _verify_preserved_records
from scripts.deployment.migration_audit import NAME_RE
from scripts.deployment.schema_fingerprint import canonical_json

MODULE = "scripts.deployment.multiple_solutions_preservation"
SOLUTION_COLUMNS = (
    "id", "title", "status", "summary", "submitted_at", "published_at", "created_at", "updated_at",
    "author_id", "problem_id", "pdf_show_author", "pdf_show_date", "pdf_show_footer", "edit_version",
    "current_revision_id",
)


def _fail(reason):
    raise recovery.RecoveryError("multiple_solutions_preservation_" + reason)


def baseline_maps(before):
    if not isinstance(before, dict):
        _fail("baseline_invalid")
    tables = _record_map(before.get("tables"), "table")
    sequences = _record_map(before.get("sequences"), "sequence")
    _digest_record(before.get("large_objects"))
    if (
        ("public", schema.TABLE) not in tables or ("public", "django_migrations") not in tables
        or MIGRATION_SEQUENCE not in sequences
    ):
        _fail("baseline_invalid")
    try:
        columns = sorted(
            (item for item in before["schema_snapshot"]["columns"]
             if item["schema"] == "public" and item["table"] == schema.TABLE),
            key=lambda item: item["position"],
        )
        names = tuple(item["column"] for item in columns)
    except (KeyError, TypeError):
        _fail("baseline_columns_invalid")
    if names != SOLUTION_COLUMNS:
        _fail("baseline_columns_invalid")
    return tables, sequences


def compare_preserved(before, after):
    old_tables, old_sequences = baseline_maps(before)
    if not isinstance(after, dict) or set(after) != {
        "tables", "sequences", "large_objects", "migration_rows", "nonoriginal_solutions",
    }:
        _fail("metadata_invalid")
    if (
        type(after["migration_rows"]) is not int or after["migration_rows"] != 1
        or type(after["nonoriginal_solutions"]) is not int or after["nonoriginal_solutions"] != 0
    ):
        _fail("unexpected_rows")
    _digest_record(after["large_objects"])
    if (
        _record_map(after["tables"], "table") != old_tables
        or _record_map(after["sequences"], "sequence") != old_sequences
        or after["large_objects"] != before["large_objects"]
    ):
        _fail("original_records_changed")
    return {"verified": True, "tables": len(old_tables), "sequences": len(old_sequences)}


def verify_preserved_records(contract, run_id, active_sha):
    if active_sha != schema.ACTIVE_SHA:
        _fail("active_sha_invalid")
    return _verify_preserved_records(
        contract, run_id, active_sha, capture_module=MODULE, validate_baseline=baseline_maps,
        compare=compare_preserved,
    )


def capture_preservation(connection):
    """Stream local read-only COPY digests with only the frozen 0017 changes projected out."""
    from psycopg import sql

    with connection.cursor() as cursor:
        cursor.execute(recovery.TABLES_SQL)
        tables = cursor.fetchall()
        cursor.execute(recovery.SEQUENCES_SQL)
        sequences = cursor.fetchall()
        cursor.execute(
            "SELECT attname FROM pg_catalog.pg_attribute "
            "WHERE attrelid='public.solutions_problemsolution'::regclass "
            "AND attnum>0 AND NOT attisdropped ORDER BY attnum",
        )
        columns = tuple(row[0] for row in cursor.fetchall())
        cursor.execute("SELECT count(*) FROM public.solutions_problemsolution WHERE additional_draft_key IS NOT NULL")
        nonoriginal_solutions = cursor.fetchone()[0]
        cursor.execute(
            "SELECT count(*), coalesce(bool_and(id=(SELECT last_value FROM public.django_migrations_id_seq)),false), "
            "(SELECT is_called AND last_value>1 FROM public.django_migrations_id_seq) "
            "FROM public.django_migrations WHERE app=%s AND name=%s",
            schema.MIGRATION_NODE,
        )
        migration_rows, matches_sequence, sequence_called = cursor.fetchone()
    if len(tables) > MAX_OBJECTS or len(sequences) > MAX_OBJECTS:
        _fail("schema_scope_too_large")
    if columns != (*SOLUTION_COLUMNS, schema.NEW_COLUMN):
        _fail("columns_invalid")
    if (
        nonoriginal_solutions != 0 or migration_rows != 1
        or matches_sequence is not True or sequence_called is not True
    ):
        _fail("unexpected_rows")
    result = {
        "tables": [], "sequences": [], "migration_rows": migration_rows,
        "nonoriginal_solutions": nonoriginal_solutions,
    }
    for namespace, table, _keys in tables:
        source = sql.Identifier(namespace, table)
        if (namespace, table) == ("public", schema.TABLE):
            source = sql.SQL("(SELECT {} FROM {})").format(
                sql.SQL(",").join(sql.Identifier(column) for column in SOLUTION_COLUMNS),
                source,
            )
        condition = sql.SQL("")
        if (namespace, table) == ("public", "django_migrations"):
            condition = sql.SQL("WHERE NOT (app={} AND name={})").format(
                *map(sql.Literal, schema.MIGRATION_NODE),
            )
        query = sql.SQL(
            'COPY (SELECT row_to_json(t)::text FROM {} t {} '
            'ORDER BY row_to_json(t)::text COLLATE "C") TO STDOUT',
        ).format(source, condition)
        result["tables"].append({"schema": namespace, "table": table, **recovery._copy_digest(connection, query)})
    for namespace, sequence in sequences:
        projection = "last_value,is_called"
        if (namespace, sequence) == MIGRATION_SEQUENCE:
            projection = "last_value - 1 AS last_value,true AS is_called"
        query = sql.SQL("COPY (SELECT {} FROM {}) TO STDOUT").format(sql.SQL(projection), sql.Identifier(
            namespace, sequence,
        ))
        result["sequences"].append(
            {"schema": namespace, "sequence": sequence, **recovery._copy_digest(connection, query)},
        )
    result["large_objects"] = recovery._copy_digest(
        connection,
        "COPY (SELECT oid,encode(lo_get(oid),'hex') FROM pg_largeobject_metadata ORDER BY oid) TO STDOUT",
    )
    return result


def _source_cli(args):
    import os

    if os.geteuid() == 0 or not DIGEST_RE.fullmatch(args.identity) or not NAME_RE.fullmatch(args.audit_role):
        _fail("source_identity_arguments_invalid")
    import django

    django.setup()
    from django.db import connection

    if connection.vendor != "postgresql":
        _fail("source_backend_invalid")
    connection.ensure_connection()
    raw = connection.connection
    with raw.transaction():
        with raw.cursor() as cursor:
            recovery._set_readonly(cursor)
            cursor.execute(SOURCE_IDENTITY_SQL)
            identity = list(cursor.fetchone())
            if len(identity) != IDENTITY_COLUMNS:
                _fail("source_identity_mismatch")
            identity[1] = args.audit_role
            if recovery._sha(identity) != args.identity:
                _fail("source_identity_mismatch")
            cursor.execute(recovery.META_SQL)
            recovery.validate_source_metadata(cursor.fetchone()[0])
        recovery._assert_no_other_clients(raw, args.audit_role)
        result = capture_preservation(raw)
        recovery._assert_no_other_clients(raw, args.audit_role)
        encoded = canonical_json(result) + b"\n"
        if len(encoded) > recovery.MAX_METADATA_BYTES:
            _fail("metadata_too_large")
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("action", choices=("verify",))
    parser.add_argument("--identity", required=True)
    parser.add_argument("--audit-role", required=True)
    try:
        _source_cli(parser.parse_args())
    except recovery.RecoveryError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001 - Never print database exception text.
        print("multiple_solutions_preservation_failed_" + type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
