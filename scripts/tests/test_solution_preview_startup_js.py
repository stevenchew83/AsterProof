"""Exercise actual startup events without adding a browser-test dependency."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_solution_preview_startup_contract():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the frontend startup contract")
    result = subprocess.run(  # noqa: S603 - fixed repository test and discovered Node executable
        [
            node, "--test",
            str(Path(__file__).with_name("solution_preview_startup.test.cjs")),
            str(Path(__file__).with_name("website_math.test.cjs")),
            str(Path(__file__).with_name("solution_editor_clipboard.test.cjs")),
            str(Path(__file__).with_name("solution_collections.test.cjs")),
        ],
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
