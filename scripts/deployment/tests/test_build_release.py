# ruff: noqa: S603, S607, TC003
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.deployment.archive_safety import safe_extract
from scripts.deployment.build_release import build_release

WORKFLOW = Path(__file__).resolve().parents[3] / ".github/workflows/production-deploy.yml"


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


def test_production_static_build_preserves_the_release_checkout(tmp_path: Path) -> None:
    root, _ = _repository(tmp_path)
    (root / "scripts").mkdir()
    builder = root / "scripts/build_and_collectstatic.sh"
    builder.write_text(
        "#!/bin/bash\n"
        "set -eu\n"
        "test ! -e .env\n"
        "printf 'rebuilt\\n' > app.css\n"
        "mkdir staticfiles\n"
        "cp app.css staticfiles/app.css\n",
    )
    builder.chmod(0o755)
    (root / "app.css").write_text("committed\n")
    _git(root, "add", "scripts/build_and_collectstatic.sh", "app.css")
    _git(root, "commit", "-qm", "track asset and builder")
    sha = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain", "--untracked-files=all")

    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["build"]["steps"]
    static_step = next(step for step in steps if step.get("id") == "static")
    manifest_step = next(step for step in steps if step["name"] == "Verify static manifest and representative assets")
    release_step = next(step for step in steps if step.get("id") == "release")
    runner_temp = tmp_path / "runner temp"
    runner_temp.mkdir()
    output = runner_temp / "outputs"
    subprocess.run(
        ["/bin/bash", "-eo", "pipefail", "-c", static_step["run"]],
        cwd=root,
        env={**os.environ, "RELEASE_SHA": sha, "RUNNER_TEMP": str(runner_temp), "GITHUB_OUTPUT": str(output)},
        check=True,
    )

    static_root = runner_temp / "asterproof-static-build" / "staticfiles"
    assert output.read_text() == f"root={static_root}\n"
    assert (static_root / "app.css").read_text() == "rebuilt\n"
    assert (root / "app.css").read_text() == "committed\n"
    assert _git(root, "status", "--porcelain", "--untracked-files=all") == status
    assert manifest_step["env"]["RELEASE_STATIC_ROOT"] == release_step["env"]["RELEASE_STATIC_ROOT"] == (
        "${{ steps.static.outputs.root }}"
    )
    assert '--static-root "$RELEASE_STATIC_ROOT"' in release_step["run"]


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


def test_schema_proof_is_bound_into_the_immutable_archive(tmp_path):
    root, release_sha = _repository(tmp_path)
    static_root, wheelhouse = tmp_path / "static", tmp_path / "wheels"
    static_root.mkdir()
    wheelhouse.mkdir()
    proof = tmp_path / "schema-proof.json"
    proof.write_text('{"synthetic_schema_proof":true}\n')
    output = tmp_path / "release.tar"
    receipt = build_release(
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
        built_at="2026-10-27T00:00:00Z",
        source_date_epoch=1_700_000_000,
        schema_evidence=proof,
    )
    extracted = tmp_path / "extracted"
    manifest = safe_extract(output, extracted, expected_digest=receipt["archive_sha256"])
    assert (extracted / "deployment-schema-evidence.json").read_bytes() == proof.read_bytes()
    assert any(row["path"] == "deployment-schema-evidence.json" for row in manifest.files)


def test_private_postgres_runtime_is_an_attested_regular_file_only(tmp_path):
    root, release_sha = _repository(tmp_path)
    static_root, wheelhouse = tmp_path / "static", tmp_path / "wheels"
    static_root.mkdir()
    wheelhouse.mkdir()
    runtime = tmp_path / "postgres-runtime.tar"
    runtime.write_bytes(b"synthetic runtime archive; installer validates its internal manifest")
    arguments = {
        "repository_root": root, "static_root": static_root, "wheelhouse": wheelhouse,
        "output": tmp_path / "release.tar", "repository": "owner/AsterProof", "repository_id": "123",
        "release_sha": release_sha, "run_id": "42", "target_platform": "x86_64-manylinux_2_28",
        "python_abi": "cp312", "built_at": "2026-10-27T00:00:00Z", "source_date_epoch": 1700000000,
        "recovery_runtime": runtime,
    }
    receipt = build_release(**arguments)
    extracted = tmp_path / "extracted"
    manifest = safe_extract(arguments["output"], extracted, expected_digest=receipt["archive_sha256"])
    assert (extracted / "deployment-postgres-runtime.tar").read_bytes() == runtime.read_bytes()
    assert any(row["path"] == "deployment-postgres-runtime.tar" for row in manifest.files)
    link = tmp_path / "runtime-link.tar"
    link.symlink_to(runtime)
    with pytest.raises(ValueError, match="invalid recovery runtime"):
        build_release(**{**arguments, "recovery_runtime": link})
