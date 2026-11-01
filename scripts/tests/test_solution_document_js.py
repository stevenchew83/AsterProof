"""Run the actual editor, safe preview, recovery, and AI UI contracts in CI."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_solution_document_javascript_contracts():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the solution document contracts")
    directory = Path(__file__).resolve().parent
    suites = (
        "solution_document_core.test.cjs", "solution_document_preview.test.cjs",
        "solution_document_recovery.test.cjs", "solution_ai_review.test.cjs",
    )
    result = subprocess.run(  # noqa: S603 - Fixed repository suites and discovered Node executable.
        [node, "--test", *(str(directory / suite) for suite in suites)],
        cwd=directory.parents[1], capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
