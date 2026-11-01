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


def test_learning_bundle_uses_its_own_rehearsal_with_shared_arguments(monkeypatch, tmp_path):
    from scripts.deployment import learning_schema
    from scripts.deployment import learning_schema_rehearsal
    from scripts.deployment import schema_rehearsal

    seen = []
    args = SimpleNamespace(
        active_source=tmp_path, active_sha="a" * 40, release_sha="b" * 40, output=tmp_path / "evidence.json",
    )
    monkeypatch.setattr(schema_rehearsal, "_arguments", lambda: args)
    monkeypatch.setenv("SCHEMA_DISCLOSURE", json.dumps({"migration": learning_schema.MIGRATION}))
    monkeypatch.setattr(learning_schema_rehearsal, "run", lambda value: seen.append(value) or 0)
    monkeypatch.setattr(
        schema_rehearsal, "configure_rehearsal_database", lambda settings: pytest.fail("Generic fallback"),
    )
    assert schema_rehearsal.main() == 0
    assert seen == [args]


@pytest.mark.parametrize(
    ("migration", "module"),
    [
        ("solutions.0011_problem_evaluation_packages", "assessment_prototype_schema_rehearsal"),
        ("pages.0044_learning_page_activity", "learning_activity_schema_rehearsal"),
        ("solutions.0010_offline_evaluation_contract", "solution_evaluation_schema_rehearsal"),
        (
            "solutions.0009_problemsolution_edit_version_solutionreviewpolicy_and_more",
            "solution_document_schema_rehearsal",
        ),
    ],
)
def test_learning_dispatch_preserves_existing_literal_rehearsal_targets(migration, module):
    import importlib

    from scripts.deployment.schema_rehearsal import _approved_rehearsal

    existing = importlib.import_module("scripts.deployment." + module)
    assert _approved_rehearsal(migration) is existing.run


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
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[3],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
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
