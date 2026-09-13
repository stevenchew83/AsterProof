# ruff: noqa: S603, S607, TC003
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.deployment.archive_safety import safe_extract
from scripts.deployment.build_release import build_release


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "manage.py").write_text("print('ok')\n")
    (root / ".env").write_text("not tracked\n")
    _git(root, "add", "manage.py")
    _git(root, "commit", "-qm", "initial")
    return root, _git(root, "rev-parse", "HEAD")


def test_build_release_is_deterministic_and_excludes_untracked_secrets(tmp_path: Path) -> None:
    root, release_sha = _repository(tmp_path)
    static_root = tmp_path / "staticfiles"
    wheelhouse = tmp_path / "wheelhouse"
    static_root.mkdir()
    wheelhouse.mkdir()
    (static_root / "app.css").write_text("body{}\n")
    (wheelhouse / "example-1-py3-none-any.whl").write_bytes(b"wheel")
    outputs = [tmp_path / "one.tar", tmp_path / "two.tar"]

    envelopes = [
        build_release(
            repository_root=root,
            static_root=static_root,
            wheelhouse=wheelhouse,
            output=output,
            repository="owner/AsterProof",
            repository_id="123",
            release_sha=release_sha,
            run_id="42",
            target_platform="manylinux2014_x86_64",
            python_abi="cp312",
            built_at="2026-09-01T00:00:00Z",
            source_date_epoch=1_700_000_000,
        )
        for output in outputs
    ]

    assert envelopes[0]["archive_sha256"] == envelopes[1]["archive_sha256"]
    extracted = tmp_path / "extracted"
    manifest = safe_extract(outputs[0], extracted, expected_digest=str(envelopes[0]["archive_sha256"]))
    assert manifest.release_sha == release_sha
    assert not (extracted / ".env").exists()
    assert (extracted / "staticfiles/app.css").is_file()
    assert (extracted / "wheelhouse/example-1-py3-none-any.whl").is_file()


def test_build_release_rejects_dirty_tracked_source(tmp_path: Path) -> None:
    root, release_sha = _repository(tmp_path)
    (root / "manage.py").write_text("changed\n")
    static_root = tmp_path / "staticfiles"
    wheelhouse = tmp_path / "wheelhouse"
    static_root.mkdir()
    wheelhouse.mkdir()

    with pytest.raises(ValueError, match="tracked worktree"):
        build_release(
            repository_root=root,
            static_root=static_root,
            wheelhouse=wheelhouse,
            output=tmp_path / "release.tar",
            repository="owner/AsterProof",
            repository_id="123",
            release_sha=release_sha,
            run_id="42",
            target_platform="manylinux2014_x86_64",
            python_abi="cp312",
            built_at="2026-09-01T00:00:00Z",
            source_date_epoch=1_700_000_000,
        )
