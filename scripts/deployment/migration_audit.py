# ruff: noqa: EM101, PLR0913, S603, T201, TRY003
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import schema_state

DEFAULT_CONFIG = Path("/etc/asterproof/migration-audit.json")
PSQL = Path("/usr/bin/psql")
RUNUSER = Path("/usr/sbin/runuser")
NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,63}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class MigrationAuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditConfig:
    os_user: str
    pg_service: str
    pg_service_file: Path
    expected_role: str
    expected_database_identity_hash: str

    @classmethod
    def from_bytes(cls, content: bytes) -> AuditConfig:
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise MigrationAuditError("migration audit configuration cannot be read") from exc
        required = {
            "format_version",
            "os_user",
            "pg_service",
            "pg_service_file",
            "expected_role",
            "expected_database_identity_hash",
        }
        if not isinstance(value, dict) or set(value) != required or value["format_version"] != 1:
            raise MigrationAuditError("migration audit configuration is malformed")
        service_file = Path(str(value["pg_service_file"]))
        names = (value["os_user"], value["pg_service"], value["expected_role"])
        if any(not isinstance(item, str) or not NAME_RE.fullmatch(item) for item in names):
            raise MigrationAuditError("migration audit identity is invalid")
        if not service_file.is_absolute() or ".." in service_file.parts:
            raise MigrationAuditError("migration audit service file is invalid")
        identity = value["expected_database_identity_hash"]
        if not isinstance(identity, str) or not DIGEST_RE.fullmatch(identity):
            raise MigrationAuditError("migration audit database identity is invalid")
        return cls(
            os_user=value["os_user"],
            pg_service=value["pg_service"],
            pg_service_file=service_file,
            expected_role=value["expected_role"],
            expected_database_identity_hash=identity,
        )

    @classmethod
    def load(cls, path: Path) -> AuditConfig:
        try:
            return cls.from_bytes(path.read_bytes())
        except OSError as exc:
            raise MigrationAuditError("migration audit configuration cannot be read") from exc


IDENTITY_SQL = """
SELECT current_database(), current_user,
       coalesce(current_setting('cluster_name', true), ''),
       coalesce(inet_server_addr()::text, ''), inet_server_port()::text
"""
MIGRATIONS_SQL = "SELECT app, name FROM django_migrations ORDER BY app, name"
SCHEMA_SQL = {
    "tables": """
        SELECT n.nspname, c.relname, c.relkind
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m') ORDER BY 1,2,3
    """,
    "columns": """
        SELECT n.nspname,c.relname,a.attnum,a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),
               NOT a.attnotnull,pg_catalog.pg_get_expr(d.adbin,d.adrelid),coll.collname
        FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        LEFT JOIN pg_catalog.pg_collation coll ON coll.oid=a.attcollation AND a.attcollation<>0
        WHERE n.nspname='public' AND c.relkind IN ('r','p') AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY 1,2,3
    """,
    "constraints": """
        SELECT n.nspname,c.relname,k.conname,k.contype,pg_catalog.pg_get_constraintdef(k.oid,true)
        FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' ORDER BY 1,2,3
    """,
    "indexes": """
        SELECT schemaname,tablename,indexname,indexdef FROM pg_catalog.pg_indexes
        WHERE schemaname='public' ORDER BY 1,2,3
    """,
    "extensions": "SELECT extname,extversion FROM pg_catalog.pg_extension ORDER BY 1",
}


def _parse_csv(output: str, width: int) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(output)))
    if any(len(row) != width for row in rows):
        raise MigrationAuditError("migration audit query returned an unexpected shape")
    return rows


def _run_query(config: AuditConfig, sql: str, *, runner: Any = subprocess.run) -> str:
    wrapped = (
        "BEGIN READ ONLY; SET LOCAL statement_timeout='10s'; "
        f"COPY ({sql}) TO STDOUT WITH (FORMAT csv); ROLLBACK;"
    )
    result = runner(
        [
            str(RUNUSER),
            "--user",
            config.os_user,
            "--",
            str(PSQL),
            "--no-psqlrc",
            "--quiet",
            "--set=ON_ERROR_STOP=1",
            "--dbname",
            f"service={config.pg_service}",
            "--command",
            wrapped,
        ],
        check=True,
        capture_output=True,
        text=True,
        env={"PGSERVICEFILE": str(config.pg_service_file)},
    )
    return result.stdout


def collect_identity(config: AuditConfig, *, runner: Any = subprocess.run) -> dict[str, str]:
    identity_rows = _parse_csv(_run_query(config, IDENTITY_SQL, runner=runner), 5)
    if len(identity_rows) != 1 or identity_rows[0][1] != config.expected_role:
        raise MigrationAuditError("migration audit database role mismatch")
    return {
        "database_identity_hash": hashlib.sha256(canonical_json(identity_rows[0])).hexdigest(),
        "role": config.expected_role,
    }


def collect_audit(config: AuditConfig, *, runner: Any = subprocess.run) -> dict[str, Any]:
    identity = collect_identity(config, runner=runner)
    identity_hash = identity["database_identity_hash"]
    if identity_hash != config.expected_database_identity_hash:
        raise MigrationAuditError("migration audit database identity mismatch")
    migrations = migration_state(_parse_csv(_run_query(config, MIGRATIONS_SQL, runner=runner), 2))

    snapshot: dict[str, list[dict[str, object]]] = {}
    field_names = {
        "tables": ("schema", "table", "kind"),
        "columns": ("schema", "table", "position", "column", "type", "nullable", "default", "collation"),
        "constraints": ("schema", "table", "name", "type", "definition"),
        "indexes": ("schema", "table", "name", "definition"),
        "extensions": ("name", "version"),
    }
    for category, sql in SCHEMA_SQL.items():
        fields = field_names[category]
        records: list[dict[str, object]] = []
        for row in _parse_csv(_run_query(config, sql, runner=runner), len(fields)):
            record: dict[str, object] = dict(zip(fields, row, strict=True))
            if category == "columns":
                record["position"] = int(str(record["position"]))
                record["nullable"] = str(record["nullable"]).lower() == "t"
                for nullable in ("default", "collation"):
                    record[nullable] = record[nullable] or None
            records.append(record)
        snapshot[category] = records
    schema = schema_state(snapshot)
    state = {
        "database_identity_hash": identity_hash,
        "migration": migrations,
        "role": config.expected_role,
        "schema": schema,
    }
    return {
        "format_version": 1,
        "migration_fingerprint": migrations["fingerprint"],
        "schema_fingerprint": schema["fingerprint"],
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "state": state,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("fingerprint", "identity"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--contract", type=Path)
    args = parser.parse_args()
    del args.contract
    config = AuditConfig.load(args.config)
    value = collect_identity(config) if args.command == "identity" else collect_audit(config)
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
