"""Verify chart rendering, date controls, and clipboard interactions for view analytics."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_page_view_analytics_interactions():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the view analytics interaction checks")
    result = subprocess.run(  # noqa: S603 - fixed repository test and discovered Node executable
        [
            node,
            "--test",
            str(Path(__file__).with_name("page_view_analytics.test.cjs")),
            str(Path(__file__).with_name("page_view_charts.test.cjs")),
            str(Path(__file__).with_name("learning_activity.test.cjs")),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
