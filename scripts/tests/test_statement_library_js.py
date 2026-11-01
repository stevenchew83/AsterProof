"""Verify library start buttons and completion rendering for newly uploaded statements."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_statement_library_interactions():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the statement library interaction checks")
    result = subprocess.run(  # noqa: S603 - fixed repository test and discovered Node executable
        [node, "--test", str(Path(__file__).with_name("statement_library.test.cjs"))],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
