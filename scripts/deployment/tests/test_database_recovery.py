# ruff: noqa: SLF001, PLR2004, EM101, TRY003
"""Recovery receipts reject wrong targets, damaged keys and unverified data."""
from __future__ import annotations

import io
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import database_recovery as recovery
from scripts.deployment.recovery_crypto import encrypt_stream


class RootPath:
    """Model root ownership for the non-root local test runner."""
    def __init__(self, path):
        self.path = path

    def __truediv__(self, value):
        return RootPath(self.path / value)

    def lstat(self):
        value = self.path.lstat()
        return SimpleNamespace(st_uid=0, st_mode=value.st_mode, st_nlink=value.st_nlink)

    def __getattr__(self, name):
        return getattr(self.path, name)


@pytest.fixture
def receipt(tmp_path, monkeypatch):
    registry = tmp_path / "registry"
    directory, keys = registry / "recovery/42", registry / "recovery-keys"
    directory.mkdir(parents=True, mode=0o700)
    keys.mkdir(mode=0o700)
    archive, key = directory / "database.pgdump.gcm", keys / "42.key"
    encryption = encrypt_stream(io.BytesIO(b"PGDMPsynthetic backup"), archive, key, b"synthetic")
    now = datetime.now(UTC)
    manifest = {"tables": [{"table": "users_user", "rows": 3, "sha256": "f" * 64}]}
    value = {
        "format_version": 1, "run_id": "42", "backup_id": "42", "source_active_sha": "a" * 40,
        "source_state_fingerprint": "c" * 64, "database_identity_hash": "b" * 64,
        "archive_sha256": encryption["ciphertext_sha256"], "archive_bytes": encryption["ciphertext_bytes"],
        "key_sha256": recovery._hash_file(key), "table_manifest_sha256": recovery._sha(manifest),
        "restore_manifest_sha256": recovery._sha(manifest), "isolated": True, "encrypted": True, "rpo_seconds": 0,
        "backup_completed_at": (now - timedelta(seconds=20)).isoformat(),
        "restore_verified_at": (now - timedelta(seconds=5)).isoformat(),
        "expires_at": (now + timedelta(seconds=1700)).isoformat(),
    }
    for name, contents in (("manifest.json", manifest), ("receipt.json", value)):
        recovery._write_private_json(directory / name, contents)
    monkeypatch.setattr(
        recovery.AuditConfig, "load", lambda _path: SimpleNamespace(expected_database_identity_hash="b" * 64),
    )
    return SimpleNamespace(contract=SimpleNamespace(registry_dir=RootPath(registry)), directory=directory,
                           archive=archive, key=key, value=value)


def validate(fixture):
    return recovery.validate_saved_recovery(fixture.contract, "42", "a" * 40, "c" * 64)


def test_private_atomic_receipt_and_matching_backup_are_accepted(receipt):
    assert validate(receipt)["backup_id"] == "42"
    assert (receipt.directory / "receipt.json").stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [("run_id", "43"), ("database_identity_hash", "0" * 64), ("source_active_sha", "d" * 40),
     ("source_state_fingerprint", "e" * 64), ("isolated", 1), ("encrypted", False), ("rpo_seconds", False),
     ("format_version", True), ("restore_manifest_sha256", "0" * 64),
     ("backup_completed_at", "2000-01-01T00:00:00+00:00"), ("expires_at", "2000-01-01T00:00:00+00:00"),
     ("restore_verified_at", "2026-01-01T00:00:00")],
)
def test_invalid_recovery_receipt_is_rejected(receipt, field, value):
    receipt.value[field] = value
    recovery._write_private_json(receipt.directory / "receipt.json", receipt.value)
    with pytest.raises(recovery.RecoveryError, match="recovery_"):
        validate(receipt)


@pytest.mark.parametrize("which", ["archive", "key", "manifest", "public", "symlink", "hardlink"])
def test_corrupt_or_exposed_recovery_material_is_rejected(receipt, which):
    if which == "archive":
        receipt.archive.write_bytes(b"corrupt")
    elif which == "key":
        receipt.key.write_bytes(b"x" * 32)
    elif which == "manifest":
        (receipt.directory / "manifest.json").write_text("{}")
    elif which == "public":
        receipt.key.chmod(0o644)
    elif which == "symlink":
        receipt.archive.unlink()
        receipt.archive.symlink_to(receipt.key)
    else:
        (receipt.directory / "another-key").hardlink_to(receipt.key)
    with pytest.raises(recovery.RecoveryError, match="recovery_"):
        validate(receipt)


def test_source_scope_and_isolation_commands_are_bounded():
    good = {"server_version": 170009, "encoding": "UTF8", "locale": "en_US.UTF-8", "provider": "c",
            "extensions": {"plpgsql": "1.0"}, "database_bytes": 478181043}
    recovery.validate_source_metadata(good)
    with pytest.raises(recovery.RecoveryError, match="scope"):
        recovery.validate_source_metadata({**good, "extensions": {"unreviewed": "1"}})
    with pytest.raises(recovery.RecoveryError, match="scope"):
        recovery.validate_source_metadata({**good, "database_bytes": 2 * 1024**3})
    contract = SimpleNamespace(
        releases_dir=Path("/safe/releases"), app_user="asterproof", environment_file="/safe/env",
    )
    config = SimpleNamespace(os_user="asterproof_audit", expected_database_identity_hash="b" * 64,
                             expected_role="asterproof_catalog")
    restore = recovery._unit_command(contract, "42", "restore", "a" * 40, config, scratch="/safe/restore/42")
    assert "--property=PrivateNetwork=yes" in restore
    assert "--property=RestrictAddressFamilies=AF_UNIX" in restore
    assert "--uid=asterproof_audit" in restore
    assert not any("EnvironmentFile=" in argument for argument in restore)
    assert "--property=ReadWritePaths=/safe/restore/42" in restore
    source = recovery._unit_command(contract, "42", "source", "a" * 40, config)
    assert "--uid=asterproof" in source
    assert "--property=EnvironmentFile=/safe/env" in source


def test_smoke_is_never_a_generic_database_command(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    monkeypatch.setenv("DATABASE_URL", "postgres://production.invalid/database")
    with pytest.raises(recovery.RecoveryError, match="isolated_actions"):
        recovery.smoke_recovery()


def test_dump_schema_compares_visible_order_without_obsolete_physical_slots():
    before = {"columns": [
        {"schema": "public", "table": "example", "position": 1, "column": "id", "type": "bigint"},
        {"schema": "public", "table": "example", "position": 3, "column": "note", "type": "text"},
    ]}
    restored = {"columns": [{**row, "position": n} for n, row in enumerate(before["columns"], 1)]}
    assert recovery.logical_backup_schema(before) == recovery.logical_backup_schema(restored)
    assert before["columns"][1]["position"] == 3
    changed_type = {"columns": [dict(row) for row in restored["columns"]]}
    changed_type["columns"][1]["type"] = "integer"
    assert recovery.logical_backup_schema(before) != recovery.logical_backup_schema(changed_type)
    changed_order = {"columns": [dict(row) for row in restored["columns"]]}
    changed_order["columns"][0]["column"] = "note"
    changed_order["columns"][1]["column"] = "id"
    assert recovery.logical_backup_schema(before) != recovery.logical_backup_schema(changed_order)


@pytest.mark.parametrize(("original", "restored"), recovery.PG17_INDEX_REPARSE_EQUIVALENTS.items())
def test_only_exact_known_pg17_index_cast_reparsing_is_equivalent(original, restored):
    def snapshot(definition):
        return {"columns": [], "indexes": [{"definition": definition}]}
    assert recovery.logical_backup_schema(snapshot(original)) == recovery.logical_backup_schema(snapshot(restored))
    for change in (
        original.replace("CREATE UNIQUE INDEX", "CREATE INDEX"),
        original.replace(" ON public.", " ON other_schema."),
        original.replace("::text[]", "::varchar[]"),
        original.replace("'totp'", "'changed'").replace("'material_completion'", "'changed'"),
        original.replace("USING btree", "USING hash"),
    ):
        assert recovery.logical_backup_schema(snapshot(change)) != recovery.logical_backup_schema(snapshot(restored))
    assert snapshot(original)["indexes"][0]["definition"] == original
