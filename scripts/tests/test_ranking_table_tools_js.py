"""Exercise local ranking sorting/filtering/clipboard output without dependencies."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_ranking_table_tools():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the ranking table checks")
    result = subprocess.run(  # noqa: S603 - fixed repository test and discovered Node executable
        [node, "--test", str(Path(__file__).with_name("ranking_table_tools.test.cjs"))],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
