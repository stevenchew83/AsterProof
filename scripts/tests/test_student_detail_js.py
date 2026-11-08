"""Run the student explorer's request-race and URL contract checks."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_student_detail_controller():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for student explorer checks")
    result = subprocess.run(  # noqa: S603 - fixed local test script and discovered Node executable
        [node, "--test", str(Path(__file__).with_name("student_detail.test.cjs"))],
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
