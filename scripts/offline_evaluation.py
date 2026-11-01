"""Run prepared offline evaluation tests in disposable, isolated local containers."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path

POSTGRES_IMAGE = (
    "postgres:17.9-bookworm@sha256:"
    "47f917f7409eacd22fc5dfb1dee634e1b55cf0c01d1a7eb701be2227a03e0641"
)
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
IMAGE_ENVIRONMENT = frozenset(
    {
        "PATH", "LANG", "LC_ALL", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256", "PYTHONUNBUFFERED",
        "PYTHONDONTWRITEBYTECODE", "PIP_DISABLE_PIP_VERSION_CHECK", "PIP_NO_CACHE_DIR",
        "PYTHON_PIP_VERSION", "PYTHON_GET_PIP_URL", "PYTHON_GET_PIP_SHA256", "PYTHON_SETUPTOOLS_VERSION",
    },
)
EXCLUDED_PARTS = frozenset({".git", ".aws", ".ssh", ".docker", ".kube", ".codex", ".venv", "node_modules"})
EXCLUDED_PARTS |= {".ci-quality", ".release-quality", ".context", "venv", "ENV", ".tox", ".pytest_cache"}
EXCLUDED_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db"})
DEFAULT_TARGETS = (
    "inspinia/solutions/test_coach_evaluation.py",
    "inspinia/solutions/test_reviews.py",
)
CONCURRENCY_TARGETS = (
    "inspinia/solutions/test_solution_editor.py::test_concurrent_first_document_saves_have_one_winner",
    "inspinia/solutions/test_reviews.py::test_postgres_concurrent_requests_reserve_once",
    "inspinia/solutions/test_reviews.py::test_postgres_competing_workers_dispatch_once",
    "inspinia/solutions/test_evaluation_concurrency.py::test_postgres_duplicate_hint_reveal_records_one_event",
    "inspinia/solutions/test_evaluation_concurrency.py::test_postgres_freeze_racing_with_withdrawal_preserves_invalidity",
    "inspinia/solutions/test_evaluation_concurrency.py::test_postgres_final_aggregate_is_delivered_once_across_actors",
    "inspinia/solutions/test_evaluation_concurrency.py::test_postgres_revocation_serializes_with_judgment",
    "inspinia/solutions/test_evaluation_concurrency.py::test_postgres_protocol_freeze_and_import_limits_are_atomic",
)
MIN_TIMEOUT = 30
MAX_TIMEOUT = 1800


class IsolationError(RuntimeError):
    """A required isolation property could not be established."""


def validate_image_id(value: str) -> str:
    if not IMAGE_ID.fullmatch(value):
        message = "Use a locally prepared immutable image ID: sha256 followed by 64 lowercase hex digits."
        raise IsolationError(message)
    return value


def validate_target(value: str) -> str:
    parts = value.split("::")
    path = Path(parts[0])
    allowed_prefix = parts[0].startswith(("inspinia/solutions/", "scripts/tests/", "scripts/deployment/tests/"))
    if (
        not allowed_prefix or path.is_absolute() or ".." in path.parts
        or path.suffix != ".py" or not (path.name.startswith("test_") or path.name == "tests.py")
        or any(not re.fullmatch(r"[A-Za-z0-9_]+", node) for node in parts[1:])
    ):
        message = "Select an explicit solution or scripts test module, optionally followed by a test name."
        raise IsolationError(message)
    return value


def safe_source_path(value: str) -> bool:
    path = Path(value)
    return (
        not path.is_absolute() and ".." not in path.parts
        and not any(part in EXCLUDED_PARTS or part.startswith(".env") for part in path.parts)
        and path.suffix.lower() not in EXCLUDED_SUFFIXES
    )


class LocalDocker:
    """Use the default local daemon without inherited Docker credentials or remote endpoints."""

    def __init__(self, config: Path):
        executable = shutil.which("docker")
        if not executable:
            message = "Docker CLI is unavailable; container isolation has not been verified."
            raise IsolationError(message)
        self.prefix = [executable, "--config", str(config)]
        self.environment = {"PATH": os.environ.get("PATH", ""), "DOCKER_CONFIG": str(config)}

    def run(self, arguments: list[str], *, timeout: int = 60, capture: bool = True) -> str:
        try:
            result = subprocess.run(  # noqa: S603 - fixed executable and validated argument lists, no shell
                [*self.prefix, *arguments], check=True, timeout=timeout,
                env=self.environment, text=True, capture_output=capture,
            )
        except (OSError, subprocess.SubprocessError) as error:
            message = f"Local Docker operation failed ({arguments[0]}). Isolation acceptance is incomplete."
            raise IsolationError(message) from error
        return result.stdout if capture else ""


def verify_prepared_image(docker: LocalDocker, image_id: str) -> None:
    rows = json.loads(docker.run(["image", "inspect", validate_image_id(image_id)]))
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("Id") != image_id:
        message = "Docker did not resolve the exact prepared dependency image."
        raise IsolationError(message)
    config = rows[0].get("Config") or {}
    if config.get("Volumes"):
        message = "Prepared dependency images must not declare persistent or anonymous volumes."
        raise IsolationError(message)
    if (config.get("Labels") or {}).get("io.asterproof.offline-dependencies") != "true":
        message = "The prepared image must carry io.asterproof.offline-dependencies=true."
        raise IsolationError(message)
    if any(entry.partition("=")[0] not in IMAGE_ENVIRONMENT for entry in config.get("Env") or []):
        message = "Prepared images must not embed application, credential or provider environment variables."
        raise IsolationError(message)


def snapshot_source(root: Path, destination: Path) -> None:
    """Copy Git-visible regular source files; never mount the checkout or its private files."""
    git = shutil.which("git")
    if not git:
        message = "Git is required to select the safe source snapshot."
        raise IsolationError(message)
    result = subprocess.run(  # noqa: S603 - fixed read-only Git command, no shell
        [git, "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True, capture_output=True,
    )
    destination.mkdir(mode=0o755)
    destination.chmod(0o755)
    for relative in result.stdout.decode().split("\0"):
        if not relative or not safe_source_path(relative):
            continue
        source = root / relative
        if not source.exists() or not stat.S_ISREG(source.lstat().st_mode):
            continue
        # A symlink in any parent directory must not turn a source path into a private mount.
        if source.resolve() != root.resolve() / relative:
            message = "Source snapshot refuses paths traversing symlinks."
            raise IsolationError(message)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        shutil.copyfile(source, target)
        target.chmod(0o644)
    for directory in destination.rglob("*"):
        if directory.is_dir():
            directory.chmod(0o755)


def runner_arguments(  # noqa: PLR0913 - explicit bounded container inputs
    *, image_id: str, source: Path, name: str, network: str, postgres: bool, targets: list[str],
) -> list[str]:
    mode = "postgres" if postgres else "none"
    arguments = [
        "run", "--pull=never", "--name", name, "--network", network,
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=128", "--memory=1g", "--cpus=2", "--user=65534:65534",
        "--tmpfs", "/scratch:rw,nosuid,nodev,mode=1777,size=512m",
        "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777,size=128m",  # noqa: S108 - private container tmpfs
        "--mount", f"type=bind,src={source},dst=/workspace,readonly",
        "--workdir", "/workspace", "--entrypoint", "/usr/local/bin/python",
    ]
    environment = {
        "ASTERPROOF_OFFLINE_EVALUATION": "1", "ASTERPROOF_OFFLINE_TEST_GATE": "1",
        "ASTERPROOF_OFFLINE_ISOLATION_MODE": mode,
        "DJANGO_SETTINGS_MODULE": "config.settings.test", "DJANGO_READ_DOT_ENV_FILE": "false",
        "DJANGO_MEDIA_ROOT": "/scratch/media", "SOLUTION_AI_REVIEW_ENABLED": "false",
        "SOLUTION_AI_EXECUTION_MODE": "offline", "OPENAI_API_KEY": "",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
    }
    for key, value in environment.items():
        arguments.extend(["--env", f"{key}={value}"])
    arguments.extend([image_id, "-m", "scripts.offline_evaluation_gate", "--mode", mode, *targets])
    return arguments


def execute(image_id: str, targets: list[str], *, postgres: bool = False, timeout: int = 900) -> None:
    image_id = validate_image_id(image_id)
    targets = [validate_target(target) for target in targets]
    if not MIN_TIMEOUT <= timeout <= MAX_TIMEOUT:
        message = "The isolation timeout must be between 30 and 1800 seconds."
        raise IsolationError(message)
    root = Path(__file__).resolve().parents[1]
    prefix = f"asterproof-offline-{uuid.uuid4().hex}"
    runner, database, network = f"{prefix}-tests", f"{prefix}-db", f"{prefix}-net"
    with tempfile.TemporaryDirectory(prefix="asterproof-offline-") as temporary:
        scratch = Path(temporary)
        config = scratch / "docker-config"
        config.mkdir()
        docker = LocalDocker(config)
        verify_prepared_image(docker, image_id)
        source = scratch / "source"
        snapshot_source(root, source)
        for target in targets:
            if not (source / target.split("::")[0]).is_file():
                message = "Every selected test module must exist in the safe source snapshot."
                raise IsolationError(message)
        resources = []
        try:
            if postgres:
                docker.run(["image", "inspect", POSTGRES_IMAGE])
                resources.append(["network", "rm", network])
                docker.run(["network", "create", "--internal", network])
                description = json.loads(docker.run(["network", "inspect", network]))
                if len(description) != 1 or description[0].get("Internal") is not True:
                    message = "Disposable PostgreSQL tests require a verified internal-only network."
                    raise IsolationError(message)
                resources.append(["rm", "--force", database])
                docker.run([
                    "run", "--detach", "--pull=never", "--name", database,
                    "--network", network, "--network-alias", "offline-db", "--memory=768m", "--cpus=2",
                    "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,nodev,size=512m",
                    "--env", "POSTGRES_DB=asterproof_offline", "--env", "POSTGRES_USER=postgres",
                    "--env", "POSTGRES_HOST_AUTH_METHOD=trust", POSTGRES_IMAGE,
                ])
                targets = list(dict.fromkeys([*CONCURRENCY_TARGETS, *targets]))
            resources.append(["rm", "--force", runner])
            print(json.dumps({  # noqa: T201 - evidence is deliberately emitted to the CI log
                "dependency_image_id": image_id, "isolation_mode": "postgres" if postgres else "none",
                "evidence_origin": "deterministic_fixture", "test_targets": targets,
            }), flush=True)
            docker.run(runner_arguments(
                image_id=image_id, source=source, name=runner,
                network=network if postgres else "none", postgres=postgres, targets=targets,
            ), timeout=timeout, capture=False)
        finally:
            # Names are generated for this invocation; no existing workload is selected.
            cleanup_failures = []
            for arguments in reversed(resources):
                try:
                    docker.run(arguments)
                except IsolationError:
                    cleanup_failures.append(arguments[-1])
            if cleanup_failures:
                message = f"Disposable resources require local cleanup: {', '.join(cleanup_failures)}"
                raise IsolationError(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Prepared local dependency image ID, sha256:<64 hex>.")
    parser.add_argument("--postgres", action="store_true", help="Use a disposable internal-only PostgreSQL network.")
    parser.add_argument("--test-target", action="append", help="Explicit test module or module::test_name.")
    parser.add_argument("--timeout", type=int, default=900)
    arguments = parser.parse_args(argv)
    try:
        execute(arguments.image, arguments.test_target or list(DEFAULT_TARGETS), postgres=arguments.postgres,
                timeout=arguments.timeout)
    except (IsolationError, subprocess.SubprocessError, ValueError) as error:
        parser.exit(2, f"Offline evaluation not verified: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
