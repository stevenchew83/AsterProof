from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts" / "deployment" / "check_production_lock.py"
SPEC = importlib.util.spec_from_file_location("check_production_lock", MODULE_PATH)
assert SPEC
assert SPEC.loader
lock_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lock_check)


def _fixture_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    requirements = tmp_path / "requirements"
    requirements.mkdir()
    base = requirements / "base.txt"
    base.write_text("bleach==6.3.0\nmarkdown==3.10.2\n", encoding="utf-8")
    source = requirements / "production.txt"
    source.write_text("-r base.txt\ngunicorn==23.0.0\n", encoding="utf-8")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "fixture"\nversion = "0.1.0"\n'
        'dependencies = ["bleach==6.3.0", "markdown==3.10.2"]\n',
        encoding="utf-8",
    )
    lock = requirements / "production.lock"
    lock.write_text(
        f"{lock_check.SOURCE_HEADER}{lock_check.requirements_digest(source)}\n"
        "bleach==6.3.0 \\\n"
        "    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "gunicorn==23.0.0 \\\n"
        "    --hash=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
        "markdown==3.10.2 \\\n"
        "    --hash=sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\n",
        encoding="utf-8",
    )
    return source, lock, pyproject


def test_repository_production_lock_is_current_and_hashed():
    lock_check.validate_lock(
        REPO_ROOT / "requirements" / "production.txt",
        REPO_ROOT / "requirements" / "production.lock",
        REPO_ROOT / "pyproject.toml",
    )


def test_valid_hash_lock_passes(tmp_path):
    source, lock, pyproject = _fixture_repo(tmp_path)

    lock_check.validate_lock(source, lock, pyproject)


def test_changed_requirement_makes_lock_stale(tmp_path):
    source, lock, pyproject = _fixture_repo(tmp_path)
    source.write_text("-r base.txt\ngunicorn==23.0.1\n", encoding="utf-8")

    with pytest.raises(lock_check.LockError, match="stale"):
        lock_check.validate_lock(source, lock, pyproject)


def test_missing_hash_fails(tmp_path):
    source, lock, pyproject = _fixture_repo(tmp_path)
    lock.write_text(
        f"{lock_check.SOURCE_HEADER}{lock_check.requirements_digest(source)}\nbleach==6.3.0\n",
        encoding="utf-8",
    )

    with pytest.raises(lock_check.LockError, match="no sha256 hash"):
        lock_check.validate_lock(source, lock, pyproject)


def test_malformed_hash_fails(tmp_path):
    source, lock, pyproject = _fixture_repo(tmp_path)
    lock.write_text(lock.read_text(encoding="utf-8").replace("a" * 64, "a" * 63), encoding="utf-8")

    with pytest.raises(lock_check.LockError, match="invalid sha256"):
        lock_check.validate_lock(source, lock, pyproject)


def test_pyproject_overlap_drift_fails(tmp_path):
    source, lock, pyproject = _fixture_repo(tmp_path)
    pyproject.write_text(
        '[project]\nname = "fixture"\nversion = "0.1.0"\n'
        'dependencies = ["bleach>=6.3.0", "markdown==3.10.2"]\n',
        encoding="utf-8",
    )

    with pytest.raises(lock_check.LockError, match="drift for bleach"):
        lock_check.validate_lock(source, lock, pyproject)


def test_regeneration_is_stable_when_resolver_output_is_stable(tmp_path, monkeypatch):
    source, lock, _ = _fixture_repo(tmp_path)

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output-file") + 1])
        output.write_text(
            "bleach==6.3.0 \\\n"
            "    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(lock_check.subprocess, "run", fake_run)

    first = lock_check.render_lock(source, lock, upgrade=False)
    second = lock_check.render_lock(source, lock, upgrade=False)

    assert first == second
    assert lock_check.SOURCE_HEADER in first


def test_resolution_check_does_not_seed_itself_from_existing_lock(tmp_path, monkeypatch):
    source, lock, _ = _fixture_repo(tmp_path)
    lock.write_text(lock.read_text(encoding="utf-8").replace("gunicorn==23.0.0", "gunicorn==99.0.0"))

    def fake_render(requested_source, existing_lock, *, upgrade):
        assert requested_source == source
        assert existing_lock is None
        assert upgrade is False
        return "clean resolver output\n"

    monkeypatch.setattr(lock_check, "render_lock", fake_render)

    with pytest.raises(lock_check.LockError, match="clean deterministic resolution"):
        lock_check.validate_resolved_lock(source, lock)


def test_static_build_requires_explicit_environment_python():
    script = (REPO_ROOT / "scripts" / "build_and_collectstatic.sh").read_text(encoding="utf-8")

    assert "ASTERPROOF_PYTHON:?" in script
    assert '"$PYTHON_BIN" manage.py collectstatic --noinput' in script
    assert "uv run python manage.py collectstatic" not in script


def test_static_build_fails_before_npm_without_selected_python():
    environment = os.environ.copy()
    environment.pop("ASTERPROOF_PYTHON", None)

    result = subprocess.run(  # noqa: S603
        ["/bin/bash", str(REPO_ROOT / "scripts" / "build_and_collectstatic.sh")],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Set ASTERPROOF_PYTHON" in result.stderr
    assert "npm" not in result.stdout


def test_oidc_crypto_runtime_is_explicit_in_production_authority():
    requirements = lock_check.direct_requirements(REPO_ROOT / "requirements" / "production.txt")

    assert requirements["cryptography"] == ("==", "44.0.3")


def test_ci_uses_pinned_actions_and_offline_runtime_install():
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    git_sha_length = 40

    action_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]
    assert action_lines
    assert all("@" in line and len(line.rsplit("@", 1)[1].split()[0]) == git_sha_length for line in action_lines)
    assert "pip wheel --require-hashes" in workflow
    assert "pip install --no-index --require-hashes" in workflow
    assert "import django, gunicorn, psycopg, bleach, markdown, cryptography" in workflow
    assert "config.settings.staticfiles" in workflow
    assert "staticfiles/staticfiles.json" in workflow
    assert "ACTIONLINT_LINUX_AMD64_SHA256" in workflow
    assert '"$RUNNER_TEMP/actionlint"' in workflow
