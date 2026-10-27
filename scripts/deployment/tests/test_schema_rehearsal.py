# ruff: noqa: S603
"""CI rehearsal must override the application's deliberately SQLite-only test settings."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment.schema_rehearsal import REHEARSAL_DATABASE
from scripts.deployment.schema_rehearsal import REHEARSAL_URL
from scripts.deployment.schema_rehearsal import configure_rehearsal_database
from scripts.deployment.schema_rehearsal import smoke_command


def test_cold_test_settings_select_postgresql_before_connecting():
    code = """
import json
from django.conf import settings
from scripts.deployment.schema_rehearsal import configure_rehearsal_database
if settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
    raise RuntimeError('Regression fixture no longer reproduces the original CI default')
configure_rehearsal_database(settings)
print(json.dumps(settings.DATABASES['default']))
"""
    environment = {
        **os.environ,
        "GITHUB_ACTIONS": "true",
        "DATABASE_URL": REHEARSAL_URL,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DJANGO_READ_DOT_ENV_FILE": "false",
    }
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[3],
        env=environment, check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == REHEARSAL_DATABASE


@pytest.mark.parametrize(
    ("actions", "url"),
    [("false", REHEARSAL_URL), ("true", ""), ("true", "postgres://postgres@prod.invalid/example")],
)
def test_wrong_rehearsal_context_is_rejected_without_changing_settings(monkeypatch, actions, url):
    original = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "synthetic.sqlite3"}}
    settings = SimpleNamespace(DATABASES=original)
    monkeypatch.setenv("GITHUB_ACTIONS", actions)
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValueError, match="isolated"):
        configure_rehearsal_database(settings)
    assert settings.DATABASES is original


def test_active_revision_smoke_uses_the_same_explicit_database(monkeypatch):
    settings = SimpleNamespace(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3"}})
    monkeypatch.setattr("django.conf.settings", settings)
    setup = smoke_command().partition("import django")[0]
    exec(compile(setup, "<fixed-smoke-settings>", "exec"), {})  # noqa: S102 - fixed deployment smoke setup
    assert settings.DATABASES == {"default": REHEARSAL_DATABASE}
    assert settings.CONCEPT_ASSIGNMENTS_ENABLED is False
