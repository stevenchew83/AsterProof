"""Keep spreadsheet engines out of ordinary app and maintenance startup."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from inspinia.pages.topic_tags_parse import parse_topic_tags_cell

ROOT = Path(__file__).resolve().parents[2]


def test_app_routes_templates_and_maintenance_start_without_spreadsheet_engines():
    # A separate interpreter prevents other tests' imports from hiding an eager
    # dependency. Block imports instead of asserting machine-specific timings.
    code = """
import importlib.abc
import sys

class RejectSpreadsheetEngines(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pandas', 'numpy', 'openpyxl'}:
            raise AssertionError('Spreadsheet engine imported during startup: ' + fullname)

sys.meta_path.insert(0, RejectSpreadsheetEngines())
import django
django.setup()
from django.core.management import load_command_class
from django.template.loader import get_template
from django.urls import resolve

assert resolve('/dashboard/topic-tags/').view_name == 'pages:topic_tag_dashboard'
assert resolve('/dashboard/techniques/').view_name == 'pages:technique_dashboard'
for template in ('pages/topic-tag-analytics.html', 'pages/technique-progress.html'):
    get_template(template)
for command in ('recompute_technique_progress_catalog', 'refresh_concept_summaries',
                'refresh_statement_duplicate_report'):
    load_command_class('inspinia.pages', command)
print('lightweight startup verified')
"""
    result = subprocess.run(  # noqa: S603 - fixed code in an isolated test interpreter.
        [sys.executable, "-B", "-c", code],
        cwd=ROOT,
        env={
            **{key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ},
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "DJANGO_READ_DOT_ENV_FILE": "False",
            "DATABASE_URL": "sqlite:///:memory:",
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert result.stdout.strip() == "lightweight startup verified"


@pytest.mark.parametrize("value", [None, float("nan"), -float("nan")])
def test_tag_parser_preserves_empty_float_cells(value):
    assert parse_topic_tags_cell(value) == []


def test_tag_parser_preserves_literal_nan_label():
    assert parse_topic_tags_cell("NaN")[0]["technique"] == "NAN"
