# ruff: noqa: EM101, TRY003, S603, SLF001, T201
"""Read-only, exact record preservation for the frozen community-proof migration.

Only digest/count metadata crosses the unprivileged application boundary. The
verified recovery manifest remains root-private, and existing recovery paths are
not modified by this additional, narrowly scoped comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys

from scripts.deployment import database_recovery as recovery
from scripts.deployment.migration_audit import NAME_RE
from scripts.deployment.migration_audit import AuditConfig
from scripts.deployment.schema_fingerprint import canonical_json

MODULE = "scripts.deployment.community_proof_preservation"
MIGRATION = "0045_community_proof_library"
NEW_COLUMNS = ("embargo_until", "legacy_member_visible", "public_hint", "solution_known")
# This is the physical field order created by the frozen pages.0042 migration.
COMMUNITY_COLUMNS = (
    "id",
    "title",
    "statement_latex",
    "topic",
    "mohs",
    "topic_tags",
    "core_ideas",
    "rationale",
    "pitfalls",
    "source_kind",
    "source_details",
    "source_url",
    "contest_name",
    "contest_year",
    "problem_code",
    "solution_outline",
    "status",
    "version",
    "similarity_snapshot",
    "reviewed_at",
    "review_notes",
    "created_at",
    "updated_at",
    "author_id",
    "reviewed_by_id",
)
TABLES = frozenset(
    "pages_" + name
    for name in (
        "communityattempt",
        "communitycontentreport",
        "communityprivateasset",
        "communityproblemrevision",
        "communitysolution",
        "communitysolutionasset",
        "communitysolutionrevision",
        "moderationevent",
        "problempublication",
    )
)
NEW_SEQUENCE = ("public", "pages_problempublication_id_seq")
MIGRATION_SEQUENCE = ("public", "django_migrations_id_seq")
EMPTY_TABLE_DIGEST = hashlib.sha256(b"").hexdigest()
EMPTY_SEQUENCE_DIGEST = hashlib.sha256(b"1\tf\n").hexdigest()
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
MAX_OBJECTS = 256
MAX_PG_NAME_BYTES = 63
IDENTITY_COLUMNS = 5
COLUMN_SQL = """SELECT attname FROM pg_catalog.pg_attribute
 WHERE attrelid='public.pages_communityproblem'::regclass
 AND attnum>0 AND NOT attisdropped ORDER BY attnum"""
DEFAULTS_SQL = """SELECT count(*) FROM public.pages_communityproblem
 WHERE legacy_member_visible IS DISTINCT FROM true
 OR solution_known IS DISTINCT FROM false OR public_hint IS DISTINCT FROM ''
 OR embargo_until IS NOT NULL"""
MIGRATION_DELTA_SQL = """SELECT count(*),
 coalesce(bool_and(id=(SELECT last_value FROM public.django_migrations_id_seq)),false),
 (SELECT is_called AND last_value>1 FROM public.django_migrations_id_seq)
 FROM public.django_migrations
 WHERE app='pages' AND name='0045_community_proof_library'"""
SOURCE_IDENTITY_SQL = """SELECT current_database(),current_user,
 coalesce(current_setting('cluster_name',true),''),
 coalesce(inet_server_addr()::text,''),inet_server_port()::text"""


def _fail(suffix):
    raise recovery.RecoveryError("community_proof_preservation_" + suffix)


def _digest_record(record, name=None):
    expected = {"rows", "sha256"} | ({"schema", name} if name else set())
    if (
        not isinstance(record, dict)
        or set(record) != expected
        or type(record.get("rows")) is not int
        or record["rows"] < 0
        or not isinstance(record.get("sha256"), str)
        or not DIGEST_RE.fullmatch(record["sha256"])
    ):
        _fail("metadata_invalid")
    if name and any(
        not isinstance(record.get(key), str)
        or not record[key]
        or len(record[key].encode()) > MAX_PG_NAME_BYTES
        or "\x00" in record[key]
        for key in ("schema", name)
    ):
        _fail("metadata_invalid")


def _record_map(records, name):
    if not isinstance(records, list) or len(records) > MAX_OBJECTS:
        _fail("metadata_invalid")
    result = {}
    for record in records:
        _digest_record(record, name)
        key = (record["schema"], record[name])
        if key in result:
            _fail("metadata_invalid")
        result[key] = record
    return result


def _baseline_maps(before):
    if not isinstance(before, dict):
        _fail("baseline_invalid")
    tables = _record_map(before.get("tables"), "table")
    sequences = _record_map(before.get("sequences"), "sequence")
    _digest_record(before.get("large_objects"))
    required = {("public", "pages_communityproblem"), ("public", "django_migrations")}
    if not required <= tables.keys() or MIGRATION_SEQUENCE not in sequences:
        _fail("baseline_invalid")
    if any(("public", table) in tables for table in TABLES) or NEW_SEQUENCE in sequences:
        _fail("baseline_already_migrated")
    try:
        columns = sorted(
            (
                row
                for row in before["schema_snapshot"]["columns"]
                if row["schema"] == "public" and row["table"] == "pages_communityproblem"
            ),
            key=lambda row: row["position"],
        )
        names = tuple(row["column"] for row in columns)
    except (KeyError, TypeError):
        _fail("baseline_invalid")
    if names != COMMUNITY_COLUMNS:
        _fail("baseline_columns_invalid")
    return tables, sequences


def _check_delta_metadata(after):
    if type(after["migration_rows"]) is not int or after["migration_rows"] != 1:
        _fail("migration_delta_invalid")
    if type(after["legacy_default_violations"]) is not int or after["legacy_default_violations"] != 0:
        _fail("legacy_defaults_changed")
    if after["ai_review_disabled"] is not True:
        _fail("ai_review_not_disabled")


def compare_preserved(before, after):
    """Compare full old records with only the two exact, frozen projections."""
    old_tables, old_sequences = _baseline_maps(before)
    expected_keys = {
        "tables",
        "sequences",
        "large_objects",
        "migration_rows",
        "legacy_default_violations",
        "ai_review_disabled",
    }
    if not isinstance(after, dict) or set(after) != expected_keys:
        _fail("metadata_invalid")
    tables = _record_map(after["tables"], "table")
    sequences = _record_map(after["sequences"], "sequence")
    _digest_record(after["large_objects"])
    if tables.keys() != old_tables.keys() | {("public", table) for table in TABLES}:
        _fail("table_set_changed")
    if sequences.keys() != old_sequences.keys() | {NEW_SEQUENCE}:
        _fail("sequence_set_changed")
    if any(tables[key] != value for key, value in old_tables.items()):
        _fail("existing_records_changed")
    if any(sequences[key] != value for key, value in old_sequences.items()):
        _fail("existing_sequences_changed")
    if any(
        tables[("public", table)]["rows"] != 0 or tables[("public", table)]["sha256"] != EMPTY_TABLE_DIGEST
        for table in TABLES
    ):
        _fail("new_tables_not_empty")
    if sequences[NEW_SEQUENCE] != {
        "schema": NEW_SEQUENCE[0],
        "sequence": NEW_SEQUENCE[1],
        "rows": 1,
        "sha256": EMPTY_SEQUENCE_DIGEST,
    }:
        _fail("new_sequence_used")
    if after["large_objects"] != before["large_objects"]:
        _fail("large_objects_changed")
    _check_delta_metadata(after)
    retained = {
        "tables": [old_tables[key] for key in sorted(old_tables)],
        "sequences": [old_sequences[key] for key in sorted(old_sequences)],
        "large_objects": before["large_objects"],
    }
    return {
        "verified": True,
        "tables": len(old_tables),
        "sequences": len(old_sequences),
        "manifest_sha256": recovery._sha(retained),
    }


def _private_json(path):
    recovery._private_file(path)
    if path.stat().st_size > recovery.MAX_METADATA_BYTES:
        _fail("metadata_too_large")
    try:
        return json.loads(path.read_bytes())
    except (ValueError, UnicodeError):
        _fail("metadata_invalid")


def _command(contract, run_id, active_sha, config, *, capture_module):
    command = recovery._unit_command(contract, run_id, "verify", active_sha, config)
    module = "scripts.deployment.database_recovery"
    if command.count(module) != 1:
        _fail("command_shape_invalid")
    index = command.index(module)
    if index < 1 or command[index - 1] != "-m" or command[index + 1 : index + 2] != ["verify"]:
        _fail("command_shape_invalid")
    command[index] = capture_module
    return command


def verify_preserved_records(contract, run_id, active_sha):
    """Root compares the child's bounded metadata to the verified private backup."""
    return _verify_preserved_records(
        contract, run_id, active_sha, capture_module=MODULE, validate_baseline=_baseline_maps,
        compare=compare_preserved,
    )


def _verify_preserved_records(  # noqa: PLR0913 - The caller fixes the trusted capture and comparison scope.
    contract, run_id, active_sha, *, capture_module, validate_baseline, compare,
):
    if os.geteuid() != 0:
        _fail("root_required")
    recovery._run_id(run_id)
    if not isinstance(active_sha, str) or not SHA_RE.fullmatch(active_sha):
        _fail("active_sha_invalid")
    directory = contract.registry_dir / "recovery" / run_id
    mode = directory.lstat()
    if not stat.S_ISDIR(mode.st_mode) or mode.st_uid != 0 or mode.st_mode & 0o077:
        _fail("recovery_directory_unsafe")
    before = _private_json(directory / "manifest.json")
    validate_baseline(before)
    config = AuditConfig.load(recovery.AUDIT_CONFIG)
    receipt = _private_json(directory / "receipt.json")
    digest = recovery._sha(before)
    expected = {
        "format_version": 1,
        "run_id": run_id,
        "backup_id": run_id,
        "source_active_sha": active_sha,
        "database_identity_hash": config.expected_database_identity_hash,
        "table_manifest_sha256": digest,
        "restore_manifest_sha256": digest,
        "isolated": True,
        "encrypted": True,
        "rpo_seconds": 0,
    }
    if not isinstance(receipt, dict) or any(
        type(receipt.get(key)) is not type(value) or receipt.get(key) != value for key, value in expected.items()
    ):
        _fail("unverified_baseline")
    try:
        result = subprocess.run(
            _command(contract, run_id, active_sha, config, capture_module=capture_module),
            capture_output=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _fail("source_timeout")
    if result.returncode:
        _fail("source_failed")
    if len(result.stdout) > recovery.MAX_METADATA_BYTES:
        _fail("metadata_too_large")
    try:
        after = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        _fail("metadata_invalid")
    return compare(before, after)


def capture_preservation(connection):
    """Fixed read-only COPY projections; row bytes never leave this process."""
    from psycopg import sql

    with connection.cursor() as cursor:
        cursor.execute(recovery.TABLES_SQL)
        tables = cursor.fetchall()
        cursor.execute(recovery.SEQUENCES_SQL)
        sequences = cursor.fetchall()
        cursor.execute(COLUMN_SQL)
        columns = tuple(row[0] for row in cursor.fetchall())
        cursor.execute(DEFAULTS_SQL)
        violations = cursor.fetchone()[0]
        cursor.execute(MIGRATION_DELTA_SQL)
        count, row_matches_sequence, sequence_called = cursor.fetchone()
    if len(tables) > MAX_OBJECTS or len(sequences) > MAX_OBJECTS:
        _fail("schema_scope_too_large")
    if columns != COMMUNITY_COLUMNS + NEW_COLUMNS:
        _fail("columns_invalid")
    if type(violations) is not int or violations != 0:
        _fail("legacy_defaults_changed")
    if type(count) is not int or count != 1 or row_matches_sequence is not True or sequence_called is not True:
        _fail("migration_delta_invalid")
    result = {"tables": [], "sequences": [], "migration_rows": count, "legacy_default_violations": violations}
    for schema, table, _keys in tables:
        source = sql.Identifier(schema, table)
        if (schema, table) == ("public", "pages_communityproblem"):
            source = sql.SQL("(SELECT {} FROM {})").format(
                sql.SQL(",").join(sql.Identifier(column) for column in COMMUNITY_COLUMNS),
                source,
            )
        condition = sql.SQL("")
        if (schema, table) == ("public", "django_migrations"):
            condition = sql.SQL("WHERE NOT (app='pages' AND name='0045_community_proof_library')")
        query = sql.SQL(
            'COPY (SELECT row_to_json(t)::text FROM {} t {} ORDER BY row_to_json(t)::text COLLATE "C") TO STDOUT',
        ).format(source, condition)
        result["tables"].append({"schema": schema, "table": table, **recovery._copy_digest(connection, query)})
    for schema, sequence in sequences:
        projection = (
            "last_value - 1 AS last_value,true AS is_called"
            if (schema, sequence) == MIGRATION_SEQUENCE
            else "last_value,is_called"
        )
        query = sql.SQL("COPY (SELECT {} FROM {}) TO STDOUT").format(
            sql.SQL(projection),
            sql.Identifier(schema, sequence),
        )
        result["sequences"].append(
            {
                "schema": schema,
                "sequence": sequence,
                **recovery._copy_digest(connection, query),
            },
        )
    result["large_objects"] = recovery._copy_digest(
        connection,
        "COPY (SELECT oid,encode(lo_get(oid),'hex') FROM pg_largeobject_metadata ORDER BY oid) TO STDOUT",
    )
    return result


def _source_cli(args):
    if os.geteuid() == 0:
        _fail("source_must_be_unprivileged")
    if (
        args.action != "verify"
        or not isinstance(args.identity, str)
        or not DIGEST_RE.fullmatch(args.identity)
        or not isinstance(args.audit_role, str)
        or not NAME_RE.fullmatch(args.audit_role)
    ):
        _fail("identity_arguments_invalid")
    import django

    django.setup()
    from django.conf import settings
    from django.db import connection

    if any(
        getattr(settings, name, False) is not False
        for name in (
            "PROBLEM_STATEMENT_AI_REVIEW_ENABLED",
            "SOLUTION_AI_REVIEW_ENABLED",
        )
    ):
        _fail("ai_review_not_disabled")
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
        result = {**capture_preservation(raw), "ai_review_disabled": True}
        recovery._assert_no_other_clients(raw, args.audit_role)
        encoded = canonical_json(result) + b"\n"
        if len(encoded) > recovery.MAX_METADATA_BYTES:
            _fail("metadata_too_large")
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("action", choices=("verify",))
    parser.add_argument("--identity", required=True)
    parser.add_argument("--audit-role", required=True)
    args = parser.parse_args(argv)
    try:
        _source_cli(args)
    except recovery.RecoveryError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001 - never emit database exception text or credentials.
        print("community_proof_preservation_subprocess_failed_" + type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
