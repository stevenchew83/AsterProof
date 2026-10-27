# ruff: noqa: EM101, PLR0915, PLR2004, S108, S603, SLF001, TRY003
"""Exercise private restore across root/nobody with the real production unit options."""
from __future__ import annotations

import json
import os
import pwd
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import database_recovery as recovery
from scripts.deployment.postgres_runtime import program_path
from scripts.deployment.recovery_crypto import decrypt_archive
from scripts.deployment.recovery_crypto import encrypt_stream
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_rehearsal import REHEARSAL_URL

pytestmark = pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") != "true" or os.geteuid() != 0,
    reason="Requires an ephemeral Actions runner with installed public PG runtime; never production data",
)


def test_encrypted_restore_with_private_umask_separate_uid_and_network_namespace(monkeypatch):
    import psycopg

    run_id, sha = os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_SHA"]
    assert os.environ.get("DATABASE_URL") == REHEARSAL_URL
    assert re.fullmatch(r"[1-9][0-9]{0,19}", run_id)
    assert re.fullmatch(r"[0-9a-f]{40}", sha)
    root = Path("/srv") / ("asterproof-ci-recovery-" + run_id)
    root.mkdir(mode=0o755)  # Exclusive ownership: never reuse or erase a pre-existing path.
    root.chmod(0o755)
    original_umask = os.umask(0o077)
    unit = "asterproof-recovery-restore-" + run_id + ".service"
    try:
        releases = root / "releases"
        releases.mkdir(mode=0o755)
        releases.chmod(0o755)
        active = releases / sha
        active.mkdir(mode=0o755)
        active.chmod(0o755)
        # /srv remains visible with both ProtectHome and PrivateTmp enabled.
        shutil.copytree(Path.cwd() / "scripts", active / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(Path.cwd() / ".catalogue-quality", active / ".venv", symlinks=True)
        monkeypatch.setattr(recovery, "AUTHORITY", active)
        private = root / "backup"
        private.mkdir(mode=0o700)
        archive, key = private / "database.gcm", private / "key"
        with psycopg.connect(REHEARSAL_URL, autocommit=True) as connection, connection.transaction():
            with connection.cursor() as cursor:
                recovery._set_readonly(cursor)
                expected = recovery.capture_manifest(connection)
                cursor.execute("SELECT pg_export_snapshot()")
                snapshot = cursor.fetchone()[0]
            # Native database tools always execute as an unprivileged existing user.
            process = subprocess.Popen(
                [
                    "/usr/sbin/runuser", "--user", "runner", "--", str(program_path("pg_dump")),
                    "--dbname=" + REHEARSAL_URL, "--snapshot=" + snapshot, "--format=custom",
                    "--no-owner", "--no-privileges", "--no-password",
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                encryption = encrypt_stream(process.stdout, archive, key, b"fixed-isolated-actions-fixture")
                assert process.wait(timeout=120) == 0
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
        restore_root = root / "recovery-restore"
        recovery._root_directory(restore_root, private=False)
        assert restore_root.stat().st_mode & 0o777 == 0o711
        scratch = restore_root / run_id
        scratch.mkdir(mode=0o700)
        audit = pwd.getpwnam("nobody")
        os.chown(scratch, audit.pw_uid, audit.pw_gid)
        plaintext = scratch / "dump.pgdump"
        decrypt_archive(archive, plaintext, key, b"fixed-isolated-actions-fixture", encryption["plaintext_sha256"])
        expected_path = scratch / "expected.json"
        expected_path.write_bytes(canonical_json({"manifest": expected}))
        for path in (plaintext, expected_path):
            path.chmod(0o400)
            os.chown(path, audit.pw_uid, audit.pw_gid)
        contract = SimpleNamespace(releases_dir=releases)
        config = SimpleNamespace(os_user="nobody")
        command = recovery._unit_command(contract, run_id, "restore", sha, config, scratch=scratch)
        result = subprocess.run(command, check=False, capture_output=True, timeout=180)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        restored = json.loads(result.stdout)
        assert restored["isolated"] is True
        assert restored["manifest_sha256"] == recovery._sha(expected)
        assert scratch.stat().st_uid == audit.pw_uid
        assert scratch.stat().st_mode & 0o777 == 0o700
        assert archive.stat().st_uid == 0
        assert archive.stat().st_mode & 0o077 == 0
        assert key.stat().st_mode & 0o077 == 0
    finally:
        subprocess.run(
            ["/usr/bin/systemctl", "stop", unit], check=False, capture_output=True, timeout=30,
        )
        os.umask(original_umask)
        shutil.rmtree(root)
