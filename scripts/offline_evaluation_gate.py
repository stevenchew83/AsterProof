"""Container-only pytest gate: configure disposable targets before Django is imported."""

from __future__ import annotations

import argparse
import json
import os
import socket
import time
from pathlib import Path

from scripts.offline_evaluation import CONCURRENCY_TARGETS
from scripts.offline_evaluation import IsolationError
from scripts.offline_evaluation import validate_target


def verify_environment(environment: dict[str, str], *, scratch: Path = Path("/scratch")) -> str:
    required = {
        "ASTERPROOF_OFFLINE_EVALUATION": "1", "ASTERPROOF_OFFLINE_TEST_GATE": "1",
        "DJANGO_SETTINGS_MODULE": "config.settings.test", "DJANGO_READ_DOT_ENV_FILE": "false",
        "DJANGO_MEDIA_ROOT": "/scratch/media", "SOLUTION_AI_REVIEW_ENABLED": "false",
        "SOLUTION_AI_EXECUTION_MODE": "offline",
    }
    if any(environment.get(key) != value for key, value in required.items()):
        message = "Offline execution requires explicit test settings, scratch media, disabled AI and offline mode."
        raise IsolationError(message)
    mode = environment.get("ASTERPROOF_OFFLINE_ISOLATION_MODE")
    if mode not in {"none", "postgres"}:
        message = "An explicit container isolation mode is required."
        raise IsolationError(message)
    credential_keys = ("OPENAI", "AWS_", "AZURE_", "GOOGLE_APPLICATION_CREDENTIALS", "ANTHROPIC", "DATABASE_URL")
    if any(value and key.startswith(credential_keys) for key, value in environment.items()):
        message = "The isolated test environment must not contain provider, cloud or inherited database credentials."
        raise IsolationError(message)
    if not scratch.is_dir() or scratch.is_symlink() or scratch.resolve() != scratch:
        message = "The disposable scratch mount is unavailable or resolves outside its explicit path."
        raise IsolationError(message)
    return mode


def verify_blocked_connections() -> None:
    """Supplement Docker network enforcement with direct TCP probes; no HTTP/provider request is made."""
    for address in ("1.1.1.1", "8.8.8.8"):
        try:
            connection = socket.create_connection((address, 443), timeout=0.5)
        except OSError:
            continue
        connection.close()
        message = "Outbound TCP connectivity is available; offline isolation failed."
        raise IsolationError(message)


def configure_settings(mode: str):
    # Import only after environment validation, before pytest-django can initialize the application.
    from config.settings import test as settings

    settings.MEDIA_ROOT = "/scratch/media"
    settings.SOLUTION_AI_REVIEW_ENABLED = False
    settings.SOLUTION_AI_EXECUTION_MODE = "offline"
    settings.OPENAI_API_KEY = ""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "/scratch/offline.sqlite3"}}
    if mode == "postgres":
        settings.DATABASES = {"default": {
            "ENGINE": "django.db.backends.postgresql", "HOST": "offline-db", "PORT": "5432",
            "NAME": "asterproof_offline", "USER": "postgres", "PASSWORD": "",
            "TEST": {"NAME": "test_asterproof_offline"},
        }}
    Path(settings.MEDIA_ROOT).mkdir(exist_ok=True)
    return settings


def verify_settings(settings, mode: str) -> None:
    expected = {
        "none": {"ENGINE": "django.db.backends.sqlite3", "NAME": "/scratch/offline.sqlite3"},
        "postgres": {
            "ENGINE": "django.db.backends.postgresql", "HOST": "offline-db", "PORT": "5432",
            "NAME": "asterproof_offline", "USER": "postgres", "PASSWORD": "",
            "TEST": {"NAME": "test_asterproof_offline"},
        },
    }
    if (
        {"default": expected[mode]} != settings.DATABASES
        or str(settings.MEDIA_ROOT) != "/scratch/media"
        or settings.SOLUTION_AI_REVIEW_ENABLED is not False
        or settings.SOLUTION_AI_EXECUTION_MODE != "offline"
        or settings.OPENAI_API_KEY
    ):
        message = "Only the explicit disposable database/media and disabled provider configuration are permitted."
        raise IsolationError(message)


def wait_for_database(settings) -> None:
    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
        return
    import psycopg

    deadline = time.monotonic() + 30
    while True:
        try:
            connection = "host=offline-db port=5432 dbname=asterproof_offline user=postgres connect_timeout=1"
            with psycopg.connect(connection) as database, database.cursor() as cursor:
                cursor.execute("SHOW server_version_num")
                if cursor.fetchone() != ("170009",):
                    message = "Concurrency evidence requires the pinned PostgreSQL 17.9 instance."
                    raise IsolationError(message)
                return
        except psycopg.OperationalError:
            if time.monotonic() >= deadline:
                message = "The disposable PostgreSQL instance did not become ready within 30 seconds."
                raise IsolationError(message) from None
            time.sleep(0.25)


def pytest_addoption(parser):
    parser.addoption("--offline-evaluation-gate", action="store_true", help="Require the isolated offline bootstrap.")


def pytest_configure(config):
    # Loading this module through -p bypasses main(), so cannot claim isolation.
    import pytest

    message = "Use python -m scripts.offline_evaluation; directly loading the plugin does not verify isolation."
    raise pytest.UsageError(message)


class BootstrapPlugin:
    def __init__(self, *, postgres: bool = False):
        self.postgres = postgres
        self.passed = set()

    def pytest_addoption(self, parser):
        pytest_addoption(parser)

    def pytest_configure(self, config):
        import pytest

        if not config.getoption("--offline-evaluation-gate"):
            message = "The verified offline bootstrap gate must be explicitly selected."
            raise pytest.UsageError(message)
        config.addinivalue_line(
            "markers", "offline_evaluation: executed through the verified container test bootstrap",
        )

    def pytest_collection_modifyitems(self, items):
        import pytest

        for item in items:
            item.add_marker(pytest.mark.offline_evaluation)

    def pytest_runtest_logreport(self, report):
        if report.when == "call" and report.passed:
            self.passed.add(report.nodeid)

    def pytest_sessionfinish(self, session):
        if self.postgres and not set(CONCURRENCY_TARGETS).issubset(self.passed):
            session.exitstatus = 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("none", "postgres"), required=True)
    parser.add_argument("targets", nargs="+")
    arguments = parser.parse_args(argv)
    mode = verify_environment(dict(os.environ))
    if arguments.mode != mode or not Path("/.dockerenv").is_file():
        message = "The isolated bootstrap must run inside its requested Docker container."
        raise IsolationError(message)
    targets = [validate_target(value) for value in arguments.targets]
    verify_blocked_connections()
    settings = configure_settings(mode)
    verify_settings(settings, mode)
    wait_for_database(settings)
    import pytest

    print(json.dumps({"offline_isolation_mode": mode, "outbound_tcp_probes": "blocked",  # noqa: T201
                      "provider_calls": "disabled", "evidence_origin": "deterministic_fixture"}))
    return pytest.main([
        "--offline-evaluation-gate", "--create-db", "-p", "no:cacheprovider", *targets,
    ], plugins=[BootstrapPlugin(postgres=mode == "postgres")])


if __name__ == "__main__":
    raise SystemExit(main())
