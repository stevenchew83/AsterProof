"""Run the editor transport, clipboard and restricted mathematical configuration."""

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.ci_checks import select_checks


@pytest.mark.parametrize("path", [
    "inspinia/static/js/learning-editor.js",
    "inspinia/static/js/learning-math.js",
    "inspinia/static/js/math-document-editor.js",
    "inspinia/static/js/solution-document-editor.js",
    "gulpfile.js",
])
def test_shared_editor_changes_select_both_editor_contracts(path):
    checks = select_checks([path])
    assert checks["javascript"]
    assert {
        "scripts/tests/test_learning_editor_js.py",
        "scripts/tests/test_solution_document_js.py",
    } <= set(checks["tests"])


def test_learning_javascript_contracts():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for mathematical editor contracts")
    directory = Path(__file__).resolve().parent
    suites = [str(directory / name) for name in ("learning_editor.test.cjs", "learning_math.test.cjs")]
    result = subprocess.run(  # noqa: S603 - Fixed repository suites and discovered Node executable.
        [node, "--test", *suites], cwd=directory.parents[1], capture_output=True, text=True,
        check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
