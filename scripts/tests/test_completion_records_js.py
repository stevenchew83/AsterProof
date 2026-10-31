"""Verify completion table renderers and responsive search without a browser dependency."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_completion_record_renderers():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the completion table renderer checks")
    result = subprocess.run(  # noqa: S603 - fixed repository test and discovered Node executable
        [node, "--test", str(Path(__file__).with_name("completion_records.test.cjs"))],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
