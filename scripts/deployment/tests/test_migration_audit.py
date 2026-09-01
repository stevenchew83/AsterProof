from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.deployment.migration_audit import AuditConfig
from scripts.deployment.migration_audit import MigrationAuditError
from scripts.deployment.migration_audit import collect_audit
from scripts.deployment.migration_audit import collect_identity
from scripts.deployment.schema_fingerprint import canonical_json


@dataclass
class Result:
    stdout: str


def test_collect_audit_uses_fixed_read_only_queries_and_fingerprints() -> None:
    identity = ["asterproof", "asterproof_catalog", "prod", "10.0.0.1", "5432"]
    outputs = iter(
        [
            ",".join(identity) + "\n",
            "pages,0001_initial\n",
            "public,table,r\n",
            "public,table,1,id,bigint,f,,\n",
            "public,table,table_pkey,p,PRIMARY KEY (id)\n",
            "public,table,table_pkey,CREATE UNIQUE INDEX table_pkey ON public.table USING btree (id)\n",
            "plpgsql,1.0\n",
        ],
    )
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> Result:
        commands.append(command)
        return Result(next(outputs))

    config = AuditConfig(
        os_user="asterproof_audit",
        pg_service="asterproof_audit",
        pg_service_file=Path("/etc/asterproof/pg_service.conf"),
        expected_role="asterproof_catalog",
        expected_database_identity_hash=hashlib.sha256(canonical_json(identity)).hexdigest(),
    )

    result = collect_audit(config, runner=runner)

    assert result["state"]["migration"]["count"] == 1
    assert len(result["state_fingerprint"]) == len("0" * 64)
    assert all("BEGIN READ ONLY" in command[-1] for command in commands)
    assert all(command[:4] == ["/usr/sbin/runuser", "--user", "asterproof_audit", "--"] for command in commands)


def test_collect_audit_rejects_wrong_database_identity() -> None:
    config = AuditConfig(
        os_user="asterproof_audit",
        pg_service="asterproof_audit",
        pg_service_file=Path("/etc/asterproof/pg_service.conf"),
        expected_role="asterproof_catalog",
        expected_database_identity_hash="0" * 64,
    )

    with pytest.raises(MigrationAuditError, match="identity"):
        collect_audit(
            config,
            runner=lambda *_args, **_kwargs: Result("asterproof,asterproof_catalog,prod,10.0.0.1,5432\n"),
        )


def test_identity_discovery_validates_role_without_trusting_placeholder_hash() -> None:
    config = AuditConfig(
        os_user="asterproof_audit",
        pg_service="asterproof_audit",
        pg_service_file=Path("/etc/asterproof/pg_service.conf"),
        expected_role="asterproof_catalog",
        expected_database_identity_hash="0" * 64,
    )

    result = collect_identity(
        config,
        runner=lambda *_args, **_kwargs: Result("asterproof,asterproof_catalog,prod,10.0.0.1,5432\n"),
    )

    assert result["role"] == "asterproof_catalog"
    assert result["database_identity_hash"] != config.expected_database_identity_hash
