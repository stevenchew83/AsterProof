"""Run the recovery storage contract with Node's built-in test runner."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_solution_draft_recovery_storage_contract():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the frontend storage contract")
    result = subprocess.run(  # noqa: S603 - fixed repository test, discovered Node executable
        [node, "--test", str(Path(__file__).with_name("solution_draft_recovery.test.cjs"))],
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
