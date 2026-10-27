# ruff: noqa: EM101, PLR2004, S108, S603, SLF001, TRY003
"""Ephemeral Actions-only reproduction of stopping a real oneshot scheduler."""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json

pytestmark = pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") != "true" or os.geteuid() != 0,
    reason="Requires root on an ephemeral GitHub Actions runner; never run against production units",
)


def test_real_oneshot_sigterm_is_drained_without_relaxing_process_checks(tmp_path, monkeypatch):
    run_id = os.environ["GITHUB_RUN_ID"]
    assert re.fullmatch(r"[1-9][0-9]{0,19}", run_id)
    prefix = "asterproof-ci-drain-" + run_id
    scheduler, app = prefix + "-scheduler.service", prefix + "-app.service"
    timer = scheduler.removesuffix(".service") + ".timer"
    definitions = {
        scheduler: "[Service]\nType=oneshot\nExecStart=/bin/sleep 600\nTimeoutStopSec=10s\n",
        app: "[Service]\nType=simple\nExecStart=/bin/sleep 600\nTimeoutStopSec=10s\n",
        timer: "[Timer]\nOnActiveSec=10min\nUnit=" + scheduler + "\n",
    }
    created = []

    def systemctl(*arguments, check=True):
        return subprocess.run(
            ["/usr/bin/systemctl", *arguments], capture_output=True, text=True, check=check, timeout=20,
        )

    try:
        for unit, contents in definitions.items():
            path = Path("/run/systemd/system") / unit
            with path.open("x") as output:
                output.write(contents)
            created.append(path)
        systemctl("daemon-reload")
        systemctl("start", timer, app)
        systemctl("start", "--no-block", scheduler)
        backend = WorkerBackend()
        for _ in range(30):
            if backend._unit_properties(scheduler, "MainPID").get("MainPID") not in {None, "0", ""}:
                break
            time.sleep(0.1)
        else:
            pytest.fail("Synthetic oneshot scheduler did not start")
        writer_checks = []
        # This integration checks actual systemd stop semantics. Database identity/writer
        # observability is independently exercised by the metadata-only guard tests.
        monkeypatch.setattr(backend, "assert_database_drained", lambda: writer_checks.append(True))
        state = tmp_path / "operation.json"
        atomic_write_json(state, {"state": "draining"})
        backend.drain(SimpleNamespace(service=app, scheduler_service=scheduler), state)
        result = read_json(state)
        assert writer_checks == [True]
        assert result["maintenance_scheduler_was_active"] is True
        stopped = result["maintenance_scheduler_stop_result"]
        assert (stopped["ActiveState"], stopped["Result"], stopped["ExecMainCode"], stopped["ExecMainStatus"]) == (
            "failed", "signal", "2", "15",
        )
        assert stopped["MainPID"] == "0"
        assert stopped["ControlGroup"] == ""
    finally:
        if created:
            systemctl("stop", *(p.name for p in created), check=False)
            systemctl("reset-failed", *(p.name for p in created), check=False)
            for path in created:
                path.unlink()
            systemctl("daemon-reload")
