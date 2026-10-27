# ruff: noqa: C901, EM101, TRY003, TRY301, S603, PLR0912, PLR0913, PLR0915, T201
"""One root-authorized encrypted backup and isolated local restore per deployment.

Source credentials stay inside the existing unprivileged application session.
Only metadata crosses the helper boundary; dump bytes remain on the host.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from scripts.deployment.migration_audit import AuditConfig
from scripts.deployment.migration_audit import _run_query
from scripts.deployment.migration_audit import collect_audit
from scripts.deployment.migration_audit import collect_identity
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import POSTGRES_VERSION
from scripts.deployment.schema_rehearsal import _snapshot

AUTHORITY = Path("/usr/local/libexec/asterproof-authority")
AUDIT_CONFIG = Path("/etc/asterproof/migration-audit.json")
AUTHORITY_MANIFEST = Path("/etc/asterproof/authority-manifest.json")
MAX_SOURCE_BYTES = 1024 * 1024 * 1024
MAX_METADATA_BYTES = 256 * 1024
MAX_AGE_SECONDS = 1800
KEY_BYTES = 32
PRESERVED_TABLES = frozenset({
    "users_user", "pages_userproblemcompletion", "pages_problemconceptassignment", "pages_conceptassignmentstate",
    "pages_problemsolverecord", "pages_contestproblemstatement", "pages_techniquebenchmark",
    "pages_statementtopictechnique", "pages_problemtopictechnique",
})
RESTORE_PORT = 55439
RESTORE_DATABASE = "asterproof_restore"
META_SQL = """SELECT json_build_object(
 'database',current_database(),'server_version',current_setting('server_version_num')::int,
 'database_bytes',pg_database_size(current_database()),'locale',d.datcollate,
 'encoding',pg_encoding_to_char(d.encoding),'provider',d.datlocprovider,
 'collation_version',d.datcollversion,
 'extensions',(SELECT json_object_agg(extname,extversion) FROM pg_extension))
 FROM pg_database d WHERE d.datname=current_database()"""
TABLES_SQL = """SELECT n.nspname,c.relname,
 coalesce((SELECT array_agg(a.attname::text ORDER BY u.ord)
 FROM pg_index i CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY u(attnum,ord)
 JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=u.attnum
 WHERE i.indrelid=c.oid AND i.indisprimary),ARRAY[]::text[])
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
 AND c.relkind IN ('r','p') ORDER BY 1,2"""
SEQUENCES_SQL = """SELECT n.nspname,c.relname FROM pg_class c
 JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND c.relkind='S' ORDER BY 1,2"""


class RecoveryError(RuntimeError):
    """Normalized codes only: never interpolate database records or credentials."""


def _sha(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise RecoveryError("recovery_run_id_invalid")
    return value


def _write_private_json(path, value):
    atomic_write_json(path, value)
    path.chmod(0o600)


def _private_file(path):
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_nlink != 1
        or metadata.st_mode & 0o077
    ):
        raise RecoveryError("recovery_file_not_root_private")


def _root_directory(path, *, private=True):
    if not path.exists():
        path.mkdir(mode=0o700 if private else 0o711)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & (0o077 if private else 0o022):
        raise RecoveryError("recovery_directory_unsafe")


def validate_source_metadata(meta):
    if (
        meta.get("server_version") != POSTGRES_VERSION
        or meta.get("encoding") != "UTF8"
        or meta.get("locale") not in {"en_US.UTF-8", "en_US.utf8"}
        or meta.get("provider") != "c"
        or meta.get("extensions") != {"plpgsql": "1.0"}
        or type(meta.get("database_bytes")) is not int
        or not 0 < meta["database_bytes"] <= MAX_SOURCE_BYTES
    ):
        raise RecoveryError("recovery_source_metadata_outside_reviewed_scope")


def preflight_recovery(contract):
    """Check prerequisites while traffic is still served; do not create a backup."""
    from scripts.deployment.postgres_runtime import program_path
    from scripts.deployment.postgres_runtime import validate_installed_runtime

    authority = json.loads(AUTHORITY_MANIFEST.read_text())
    runtime = validate_installed_runtime(expected_source_sha=authority["source_sha"])
    config = AuditConfig.load(AUDIT_CONFIG)
    identity = collect_identity(config)
    if identity["database_identity_hash"] != config.expected_database_identity_hash:
        raise RecoveryError("recovery_database_identity_mismatch")
    rows = list(csv.reader(io.StringIO(_run_query(config, META_SQL))))
    if len(rows) != 1 or len(rows[0]) != 1:
        raise RecoveryError("recovery_metadata_invalid")
    meta = json.loads(rows[0][0])
    validate_source_metadata(meta)
    if shutil.disk_usage(contract.release_root).free < contract.minimum_free_bytes + 2 * meta["database_bytes"]:
        raise RecoveryError("recovery_storage_reserve_insufficient")
    accounts = [
        pwd.getpwnam(n).pw_uid for n in (contract.app_user, contract.build_user, contract.deploy_user, config.os_user)
    ]
    if len(set(accounts)) != len(accounts) or 0 in accounts:
        raise RecoveryError("recovery_accounts_not_isolated")
    for name in ("pg_dump", "pg_restore", "postgres"):
        result = subprocess.run(
            ["/usr/sbin/runuser", "--user", config.os_user, "--", str(program_path(name)), "--version"],
            check=True,
            capture_output=True,
            timeout=15,
        )
        if b"17.9" not in result.stdout:
            raise RecoveryError("recovery_runtime_version_mismatch")
    return {**meta, **identity, "runtime_source_sha": runtime["source_sha"]}


def _set_readonly(cursor):
    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    cursor.execute("SET LOCAL statement_timeout='120s'")
    cursor.execute("SET LOCAL lock_timeout='2s'")
    cursor.execute("SET LOCAL idle_in_transaction_session_timeout='900s'")
    cursor.execute("SET LOCAL timezone='UTC'")
    cursor.execute("SET LOCAL DateStyle='ISO, YMD'")
    cursor.execute("SET LOCAL extra_float_digits=3")
    cursor.execute("SET LOCAL bytea_output='hex'")


def _copy_digest(connection, query):
    digest, count = hashlib.sha256(), 0
    with connection.cursor() as cursor, cursor.copy(query) as copied:
        for block in copied:
            data = bytes(block)
            digest.update(data)
            count += data.count(b"\n")
    return {"rows": count, "sha256": digest.hexdigest()}


def capture_manifest(connection, *, preserved_only=False):
    """Hash bounded streams of all user tables/sequences/large objects, never log rows."""
    from psycopg import sql

    with connection.cursor() as cursor:
        cursor.execute(TABLES_SQL)
        tables = cursor.fetchall()
        cursor.execute(SEQUENCES_SQL)
        sequences = cursor.fetchall()
    if len(tables) > 256 or len(sequences) > 256:  # noqa: PLR2004
        raise RecoveryError("recovery_schema_scope_too_large")
    result = {"tables": [], "sequences": [], "schema_fingerprint": None}
    if not preserved_only:
        result["schema_fingerprint"] = schema_state(_snapshot(connection))["fingerprint"]
    for schema, table, _keys in tables:
        if preserved_only and (schema != "public" or table not in PRESERVED_TABLES):
            continue
        # C ordering makes the integrity digest independent of libc collation versions.
        query = sql.SQL(
            'COPY (SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text COLLATE "C") TO STDOUT',
        ).format(
            sql.Identifier(schema, table),
        )
        result["tables"].append({"schema": schema, "table": table, **_copy_digest(connection, query)})
    if preserved_only:
        if {r["table"] for r in result["tables"]} != PRESERVED_TABLES:
            raise RecoveryError("recovery_original_tables_missing")
        return result
    for schema, sequence in sequences:
        query = sql.SQL("COPY (SELECT last_value,is_called FROM {}) TO STDOUT").format(
            sql.Identifier(schema, sequence),
        )
        result["sequences"].append({"schema": schema, "sequence": sequence, **_copy_digest(connection, query)})
    result["large_objects"] = _copy_digest(
        connection,
        "COPY (SELECT oid,encode(lo_get(oid),'hex') FROM pg_largeobject_metadata ORDER BY oid) TO STDOUT",
    )
    return result


def _assert_no_other_clients(connection, audit_role):
    # Refresh this connection's statistics snapshot; the exported MVCC data snapshot stays unchanged.
    for _attempt in range(10):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND pid<>pg_backend_pid() AND backend_type='client backend' AND usename<>%s", [audit_role],
            )
            if cursor.fetchone()[0] == 0:
                return
        time.sleep(0.1)
    raise RecoveryError("recovery_unexpected_database_clients")


def _source_cli(args):
    """Unprivileged active-application process; exported snapshot remains open through pg_dump."""
    if os.geteuid() == 0:
        raise RecoveryError("recovery_source_must_be_unprivileged")
    import django

    django.setup()
    from django.db import connection

    from scripts.deployment.postgres_runtime import program_path

    connection.ensure_connection()
    raw = connection.connection
    with raw.transaction():
        with raw.cursor() as cursor:
            _set_readonly(cursor)
            cursor.execute(
                "SELECT current_database(),current_user,coalesce(current_setting('cluster_name',true),''),"
                "coalesce(inet_server_addr()::text,''),inet_server_port()::text",
            )
            identity = list(cursor.fetchone())
            identity[1] = args.audit_role
            if _sha(identity) != args.identity:
                raise RecoveryError("recovery_source_identity_mismatch")
            cursor.execute(META_SQL)
            meta = cursor.fetchone()[0]
            validate_source_metadata(meta)
            _assert_no_other_clients(raw, args.audit_role)
            manifest = capture_manifest(raw, preserved_only=args.action == "verify")
            if args.action == "verify":
                print(json.dumps({"tables": manifest["tables"]}), flush=True)
                return
            cursor.execute("SELECT pg_export_snapshot()")
            snapshot = cursor.fetchone()[0]
        if not re.fullmatch(r"[0-9A-Fa-f-]+", snapshot):
            raise RecoveryError("recovery_snapshot_id_invalid")
        header = {"source": meta, "manifest": manifest, "snapshot": snapshot}
        encoded = canonical_json(header) + b"\n"
        if len(encoded) > MAX_METADATA_BYTES:
            raise RecoveryError("recovery_manifest_too_large")
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        params = connection.get_connection_params()
        environment = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "PGOPTIONS": "-c lock_timeout=2s -c statement_timeout=120s",
        }
        for key in ("host", "port", "dbname", "user", "password", "sslmode", "sslrootcert", "sslcert", "sslkey"):
            if params.get(key) is not None:
                environment["PG" + key.upper().replace("DBNAME", "DATABASE")] = str(params[key])
        result = subprocess.run(
            [
                str(program_path("pg_dump")),
                "--format=custom",
                "--compress=6",
                "--no-owner",
                "--no-privileges",
                "--lock-wait-timeout=2s",
                "--no-password",
                "--snapshot=" + snapshot,
            ],
            env=environment,
            stdout=sys.stdout.buffer,
            stderr=subprocess.PIPE,
            timeout=600,
            check=False,
        )
        if result.returncode:
            raise RecoveryError("recovery_pg_dump_failed")
        _assert_no_other_clients(raw, args.audit_role)


def _restore_cli(args):
    if os.geteuid() == 0:
        raise RecoveryError("recovery_restore_must_be_unprivileged")
    import psycopg

    from scripts.deployment.postgres_runtime import program_path

    scratch = args.scratch.resolve(strict=True)
    expected = json.loads((scratch / "expected.json").read_text())
    data, socket = scratch / "data", scratch / "socket"
    socket.mkdir(mode=0o700)
    log = (scratch / "restore-private.log").open("xb")

    def run(name, parameters):
        result = subprocess.run(
            [str(program_path(name)), *parameters], stdout=log, stderr=log, timeout=600, check=False,
        )
        if result.returncode:
            raise RecoveryError("recovery_isolated_restore_command_failed")

    connect = ["--host=" + str(socket), "--port=" + str(RESTORE_PORT), "--username=" + RESTORE_DATABASE]
    started = False
    try:
        run(
            "initdb",
            [
                "-D",
                str(data),
                "--username=" + RESTORE_DATABASE,
                "--encoding=UTF8",
                "--locale=en_US.utf8",
                "--auth=trust",
            ],
        )
        options = (
            f"-h '' -k {socket} -p {RESTORE_PORT} -c shared_buffers=8MB -c work_mem=2MB "
            "-c maintenance_work_mem=16MB -c max_connections=5 -c autovacuum=off -c jit=off -c wal_buffers=1MB "
            "-c max_wal_size=128MB -c min_wal_size=32MB -c max_parallel_workers=0"
        )
        run("pg_ctl", ["-D", str(data), "-w", "start", "-l", str(scratch / "postgres-private.log"), "-o", options])
        started = True
        run("createdb", [*connect, RESTORE_DATABASE])
        run(
            "pg_restore",
            [
                *connect,
                "--dbname=" + RESTORE_DATABASE,
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--no-tablespaces",
                str(scratch / "dump.pgdump"),
            ],
        )
        with (
            psycopg.connect(
                host=str(socket), port=RESTORE_PORT, user=RESTORE_DATABASE, dbname=RESTORE_DATABASE, autocommit=True,
            ) as connection,
            connection.transaction(),
            connection.cursor() as cursor,
        ):
            _set_readonly(cursor)
            actual = capture_manifest(connection)
            cursor.execute("SELECT datcollversion FROM pg_database WHERE datname=current_database()")
            collation_version = cursor.fetchone()[0]
        if actual != expected["manifest"]:
            (scratch / "manifest-difference.json").write_bytes(canonical_json({
                "expected": expected["manifest"], "actual": actual,
            }))
            raise RecoveryError("recovery_restored_data_or_schema_mismatch")
        print(
            json.dumps(
                {
                    "manifest_sha256": _sha(actual),
                    "database": RESTORE_DATABASE,
                    "port": RESTORE_PORT,
                    "isolated": True,
                    "collation_version": collation_version,
                },
            ),
            flush=True,
        )
    finally:
        if started:
            run("pg_ctl", ["-D", str(data), "-w", "stop", "-m", "fast"])
        log.close()


def _unit_command(contract, run_id, action, active_sha, config, *, scratch=None):
    active = contract.releases_dir / active_sha
    command = [
        "/usr/bin/systemd-run",
        "--quiet",
        "--wait",
        "--collect",
        "--pipe",
        "--service-type=exec",
        f"--unit=asterproof-recovery-{action}-{run_id}",
        f"--uid={contract.app_user if action in {'source', 'verify'} else config.os_user}",
        "--property=NoNewPrivileges=yes",
        "--property=ProtectSystem=strict",
        "--property=ProtectHome=yes",
        "--property=PrivateTmp=yes",
        "--property=ProtectControlGroups=yes",
        "--property=MemoryMax=256M",
        "--property=RuntimeMaxSec=1200",
        "--property=UMask=0077",
        "--property=WorkingDirectory=/",
        f"--setenv=PYTHONPATH={AUTHORITY}:{active}",
    ]
    if action in {"source", "verify"}:
        command += [
            f"--property=EnvironmentFile={contract.environment_file}",
            "--setenv=DJANGO_READ_DOT_ENV_FILE=false",
            "--setenv=DJANGO_SETTINGS_MODULE=config.settings.production",
        ]
    else:
        command += [
            "--property=PrivateNetwork=yes",
            "--property=RestrictAddressFamilies=AF_UNIX",
            f"--property=ReadWritePaths={scratch}",
        ]
    command += [str(active / ".venv/bin/python"), "-m", "scripts.deployment.database_recovery", action]
    if action in {"source", "verify"}:
        command += ["--identity", config.expected_database_identity_hash, "--audit-role", config.expected_role]
    else:
        command += ["--scratch", str(scratch)]
    return command


class _PrefixStream:
    def __init__(self, prefix, source):
        self.prefix, self.source = prefix, source

    def read(self, size):
        prefix, self.prefix = self.prefix, b""
        return prefix + self.source.read(size - len(prefix))


def create_verified_backup(contract, run_id, active_sha, starting_state_fingerprint):
    from scripts.deployment.recovery_crypto import decrypt_archive
    from scripts.deployment.recovery_crypto import encrypt_stream

    if os.geteuid() != 0:
        raise RecoveryError("recovery_root_authority_required")
    _run_id(run_id)
    meta = preflight_recovery(contract)
    config = AuditConfig.load(AUDIT_CONFIG)
    audit_before = collect_audit(config)
    if audit_before["state_fingerprint"] != starting_state_fingerprint:
        raise RecoveryError("recovery_starting_schema_drift")
    root = contract.registry_dir / "recovery"
    keys = contract.registry_dir / "recovery-keys"
    _root_directory(root)
    _root_directory(keys)
    directory = root / run_id
    directory.mkdir(mode=0o700)  # Existing means ambiguous/prior operation: reconcile, never overwrite.
    aad = {
        "run_id": run_id,
        "database_identity_hash": config.expected_database_identity_hash,
        "source_active_sha": active_sha,
        "source_state_fingerprint": starting_state_fingerprint,
    }
    _write_private_json(
        directory / "plan.json", {**aad, "stage": "started", "created_at": datetime.now(UTC).isoformat()},
    )
    archive, key = directory / "database.pgdump.gcm", keys / (run_id + ".key")
    with (directory / "source-private.stderr").open("xb") as error_log:
        process = subprocess.Popen(
            _unit_command(contract, run_id, "source", active_sha, config),
            stdout=subprocess.PIPE,
            stderr=error_log,
        )
        try:
            header = process.stdout.readline(MAX_METADATA_BYTES + 1)
            if not header.endswith(b"\n") or len(header) > MAX_METADATA_BYTES:
                raise RecoveryError("recovery_source_header_invalid")
            source = json.loads(header)
            validate_source_metadata(source["source"])
            if source["manifest"]["schema_fingerprint"] != audit_before["schema_fingerprint"]:
                raise RecoveryError("recovery_source_schema_drift")
            prefix = process.stdout.read(5)
            if prefix != b"PGDMP":
                raise RecoveryError("recovery_dump_format_invalid")
            encryption = encrypt_stream(_PrefixStream(prefix, process.stdout), archive, key, canonical_json(aad))
            if process.wait(timeout=900):
                raise RecoveryError("recovery_source_failed")
        finally:
            if process.poll() is None:
                subprocess.run(
                    ["/usr/bin/systemctl", "stop", f"asterproof-recovery-source-{run_id}.service"],
                    check=True,
                    timeout=30,
                )
                process.wait(timeout=30)
    completed = datetime.now(UTC)
    restore_root = contract.release_root / "recovery-restore"
    _root_directory(restore_root, private=False)
    scratch = restore_root / run_id
    scratch.mkdir(mode=0o700)
    audit = pwd.getpwnam(config.os_user)
    os.chown(scratch, audit.pw_uid, audit.pw_gid)
    if (
        shutil.disk_usage(contract.release_root).free
        < contract.minimum_free_bytes + encryption["plaintext_bytes"] + 2 * meta["database_bytes"]
    ):
        raise RecoveryError("recovery_restore_reserve_insufficient")
    plaintext = scratch / "dump.pgdump"
    decrypt_archive(archive, plaintext, key, canonical_json(aad), encryption["plaintext_sha256"])
    expected = scratch / "expected.json"
    expected.write_bytes(canonical_json(source))
    for path in (plaintext, expected):
        path.chmod(0o400)
        os.chown(path, audit.pw_uid, audit.pw_gid)
    try:
        result = subprocess.run(
            _unit_command(contract, run_id, "restore", active_sha, config, scratch=scratch),
            capture_output=True, timeout=1200, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        subprocess.run(
            ["/usr/bin/systemctl", "stop", f"asterproof-recovery-restore-{run_id}.service"],
            check=True, timeout=30,
        )
        os.chown(scratch, 0, 0)
        scratch.chmod(0o700)
        raise RecoveryError("recovery_isolated_restore_timeout") from exc
    if result.returncode:
        os.chown(scratch, 0, 0)
        scratch.chmod(0o700)
        raise RecoveryError("recovery_isolated_restore_failed")
    restored = json.loads(result.stdout)
    expected_digest = _sha(source["manifest"])
    if restored.get("manifest_sha256") != expected_digest or restored.get("isolated") is not True:
        raise RecoveryError("recovery_isolated_integrity_mismatch")
    verified = datetime.now(UTC)
    receipt = {
        "format_version": 1,
        **aad,
        "backup_id": run_id,
        "archive_sha256": encryption["ciphertext_sha256"],
        "archive_plaintext_sha256": encryption["plaintext_sha256"],
        "key_sha256": _hash_file(key),
        "archive_bytes": encryption["ciphertext_bytes"],
        "database_bytes": meta["database_bytes"],
        "table_manifest_sha256": expected_digest,
        "restore_manifest_sha256": restored["manifest_sha256"],
        "backup_completed_at": completed.isoformat(),
        "restore_verified_at": verified.isoformat(),
        "expires_at": (verified + timedelta(seconds=MAX_AGE_SECONDS)).isoformat(),
        "isolated": True,
        "encrypted": True,
        "rpo_seconds": 0,
        "source_collation_version": source["source"]["collation_version"],
        "restore_collation_version": restored["collation_version"],
        "restore_database": RESTORE_DATABASE,
        "restore_target": "local-private-unix-cluster",
        "scope": "same-host database-only operational recovery; not off-host disaster recovery",
    }
    _write_private_json(directory / "manifest.json", source["manifest"])
    _write_private_json(directory / "receipt.json", receipt)
    # The only plaintext copy is this owned disposable cluster; preserve encrypted backup/key.
    if scratch.parent != restore_root or scratch.is_symlink():
        raise RecoveryError("recovery_cleanup_path_invalid")
    shutil.rmtree(scratch)
    return validate_saved_recovery(contract, run_id, active_sha, starting_state_fingerprint)


def validate_saved_recovery(contract, run_id, active_sha, starting_state_fingerprint):
    _run_id(run_id)
    directory = contract.registry_dir / "recovery" / run_id
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o077:
        raise RecoveryError("recovery_receipt_directory_unsafe")
    receipt_path, archive = directory / "receipt.json", directory / "database.pgdump.gcm"
    key = contract.registry_dir / "recovery-keys" / (run_id + ".key")
    for path in (receipt_path, archive, key, directory / "manifest.json"):
        _private_file(path)
    receipt = json.loads(receipt_path.read_text())
    if (
        type(receipt.get("format_version")) is not int or receipt.get("format_version") != 1
        or key.stat().st_size != KEY_BYTES
        or _hash_file(key) != receipt.get("key_sha256")
    ):
        raise RecoveryError("recovery_key_or_receipt_invalid")
    config = AuditConfig.load(AUDIT_CONFIG)
    now = datetime.now(UTC)
    expected = {
        "run_id": run_id,
        "backup_id": run_id,
        "source_active_sha": active_sha,
        "source_state_fingerprint": starting_state_fingerprint,
        "database_identity_hash": config.expected_database_identity_hash,
    }
    if any(receipt.get(k) != v for k, v in expected.items()):
        raise RecoveryError("recovery_receipt_identity_mismatch")
    try:
        completed = datetime.fromisoformat(receipt["backup_completed_at"])
        verified = datetime.fromisoformat(receipt["restore_verified_at"])
        expires = datetime.fromisoformat(receipt["expires_at"])
        if any(value.tzinfo is None for value in (completed, verified, expires)):
            raise ValueError
    except (KeyError, ValueError, TypeError) as exc:
        raise RecoveryError("recovery_receipt_timestamps_invalid") from exc
    if not completed <= verified <= now < expires or (now - completed).total_seconds() > MAX_AGE_SECONDS:
        raise RecoveryError("recovery_receipt_stale")
    if (
        receipt.get("isolated") is not True or receipt.get("encrypted") is not True
        or type(receipt.get("rpo_seconds")) is not int or receipt.get("rpo_seconds") != 0
    ):
        raise RecoveryError("recovery_receipt_policy_mismatch")
    digest = _sha(json.loads((directory / "manifest.json").read_text()))
    if digest != receipt.get("table_manifest_sha256") or digest != receipt.get("restore_manifest_sha256"):
        raise RecoveryError("recovery_receipt_integrity_mismatch")
    if _hash_file(archive) != receipt.get("archive_sha256") or archive.stat().st_size != receipt.get("archive_bytes"):
        raise RecoveryError("recovery_archive_integrity_mismatch")
    return receipt


def verify_preserved_records(contract, run_id, active_sha):
    """After migration, compare the original identities/records to the verified recovery point."""
    _run_id(run_id)
    directory = contract.registry_dir / "recovery" / run_id
    manifest_path = directory / "manifest.json"
    _private_file(manifest_path)
    before = json.loads(manifest_path.read_text())
    expected = [r for r in before["tables"] if r["schema"] == "public" and r["table"] in PRESERVED_TABLES]
    if {r["table"] for r in expected} != PRESERVED_TABLES:
        raise RecoveryError("recovery_preservation_baseline_missing")
    config = AuditConfig.load(AUDIT_CONFIG)
    result = subprocess.run(
        _unit_command(contract, run_id, "verify", active_sha, config),
        capture_output=True, timeout=600, check=False,
    )
    if result.returncode or json.loads(result.stdout).get("tables") != expected:
        raise RecoveryError("recovery_existing_records_changed")
    return {"verified": True, "tables": len(expected), "manifest_sha256": _sha(expected)}


def smoke_recovery():
    """Production-data-free Actions proof of the actual source protocol and isolated restore."""
    from scripts.deployment.schema_rehearsal import REHEARSAL_URL

    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("DATABASE_URL") != REHEARSAL_URL:
        raise RecoveryError("recovery_smoke_requires_isolated_actions_service")
    import psycopg

    from scripts.deployment.recovery_crypto import decrypt_archive
    from scripts.deployment.recovery_crypto import encrypt_stream

    with psycopg.connect(REHEARSAL_URL, autocommit=True) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(),current_user,coalesce(current_setting('cluster_name',true),''),"
            "coalesce(inet_server_addr()::text,''),inet_server_port()::text",
        )
        identity = _sha(list(cursor.fetchone()))
    with tempfile.TemporaryDirectory(prefix="asterproof-recovery-smoke-") as temporary:
        directory = Path(temporary)
        scratch = directory / "restore"
        scratch.mkdir(mode=0o700)
        archive, key = directory / "archive.gcm", directory / "key"
        code = (
            "from django.conf import settings\n"
            "from scripts.deployment.schema_rehearsal import configure_rehearsal_database\n"
            "configure_rehearsal_database(settings)\n"
            "from scripts.deployment.database_recovery import _source_cli\n"
            "from types import SimpleNamespace\nimport sys\n"
            "_source_cli(SimpleNamespace(identity=sys.argv[1],audit_role='postgres',action='source'))\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code, identity], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        header = process.stdout.readline(MAX_METADATA_BYTES + 1)
        source = json.loads(header)
        prefix = process.stdout.read(5)
        if prefix != b"PGDMP":
            raise RecoveryError("recovery_smoke_source_protocol_failed")
        encrypted = encrypt_stream(_PrefixStream(prefix, process.stdout), archive, key, b"isolated-actions-fixture")
        if process.wait(timeout=120):
            raise RecoveryError("recovery_smoke_dump_failed")
        decrypt_archive(
            archive, scratch / "dump.pgdump", key, b"isolated-actions-fixture", encrypted["plaintext_sha256"],
        )
        (scratch / "expected.json").write_bytes(canonical_json({"manifest": source["manifest"]}))
        try:
            _restore_cli(SimpleNamespace(scratch=scratch))
        except RecoveryError:
            # Only this fixed Actions fixture may emit diagnostics; no production data is involved.
            for filename in ("restore-private.log", "postgres-private.log", "manifest-difference.json"):
                path = scratch / filename
                if path.is_file():
                    print(
                        "Synthetic fixture diagnostic " + filename + ": " + path.read_text()[-8000:], file=sys.stderr,
                    )
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("source", "restore", "verify", "smoke"))
    parser.add_argument("--identity")
    parser.add_argument("--audit-role")
    parser.add_argument("--scratch", type=Path)
    args = parser.parse_args()
    try:
        if args.action in {"source", "verify"}:
            _source_cli(args)
        elif args.action == "restore":
            _restore_cli(args)
        else:
            smoke_recovery()
    except RecoveryError as exc:
        print(str(exc), file=sys.stderr)  # Fixed normalized codes, never server exception text.
        return 1
    except Exception as exc:  # noqa: BLE001 - server exception text may contain private data or credentials.
        print("recovery_subprocess_failed_" + type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
