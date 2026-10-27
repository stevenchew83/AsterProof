"""Prepare fixed rendering caches without executing a user request."""

import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from django.template import TemplateSyntaxError
from django.utils.translation import get_language
from django.utils.translation import override

from config.startup import prepare_first_request

ROOT = Path(__file__).resolve().parents[2]


def test_disabled_preparation_leaves_caches_untouched(settings):
    settings.PREPARE_FIRST_REQUEST = False
    with patch("config.startup.reverse") as routes, patch("config.startup.get_template") as templates:
        prepare_first_request()
    routes.assert_not_called()
    templates.assert_not_called()


def test_fresh_wsgi_prepares_without_database_cache_rendering_or_spreadsheets():
    code = """
import importlib.abc
import sys
from contextlib import ExitStack
from unittest.mock import patch

class RejectSpreadsheetEngines(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pandas', 'numpy', 'openpyxl'}:
            raise AssertionError('Spreadsheet import: ' + fullname)

sys.meta_path.insert(0, RejectSpreadsheetEngines())
import django
django.setup()
from django.conf import settings
from django.core.cache import cache
settings.PREPARE_FIRST_REQUEST = True
settings.LANGUAGE_CODE = 'en-us'
from django.utils.translation import get_language
before = get_language()
with ExitStack() as stack:
    stack.enter_context(patch('django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection',
                             side_effect=AssertionError('Startup accessed database')))
    stack.enter_context(patch('django.template.base.Template.render',
                             side_effect=AssertionError('Startup rendered context')))
    for method in ('get', 'set', 'add', 'get_many', 'touch', 'delete', 'clear'):
        stack.enter_context(patch.object(cache, method, side_effect=AssertionError('Startup accessed cache')))
    from config.wsgi import application
    assert callable(application)
assert get_language() == before
from config.startup import FIRST_REQUEST_TEMPLATES
from django.template.loader import get_template
with patch('django.template.base.Template.compile_nodelist', side_effect=AssertionError('Template was not prepared')):
    for name in FIRST_REQUEST_TEMPLATES:
        assert get_template(name).template is get_template(name).template
print('safe startup verified')
"""
    result = subprocess.run(  # noqa: S603 - fixed program in a local isolated interpreter.
        [sys.executable, "-B", "-c", code],
        cwd=ROOT,
        env={
            **{k: os.environ[k] for k in ("PATH", "SYSTEMROOT") if k in os.environ},
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "DJANGO_READ_DOT_ENV_FILE": "False",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert result.stdout.strip() == "safe startup verified"


def test_failed_preparation_restores_language_and_does_not_report_ready(settings, caplog):
    settings.PREPARE_FIRST_REQUEST = True
    settings.LANGUAGE_CODE = "en-us"
    caplog.set_level(logging.INFO, logger="config.startup")
    with override("fr"):
        with (
            patch("config.startup.get_template", side_effect=TemplateSyntaxError("invalid template")),
            pytest.raises(TemplateSyntaxError),
        ):
            prepare_first_request()
        assert get_language() == "fr"
    assert not any("startup_prepared" in entry.message for entry in caplog.records)


def test_missing_static_manifest_entry_fails_preparation(settings, tmp_path, caplog):
    settings.PREPARE_FIRST_REQUEST = True
    settings.DEBUG = False
    settings.STATIC_ROOT = tmp_path
    settings.STORAGES = {
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    caplog.set_level(logging.INFO, logger="config.startup")
    with pytest.raises(ValueError, match="Missing staticfiles manifest entry"):
        prepare_first_request()
    assert not any("startup_prepared" in entry.message for entry in caplog.records)
