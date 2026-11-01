# ruff: noqa: EM101, PLR2004, S108, S603, SLF001, TRY003
"""Ephemeral Actions-only reproduction of stopping a real oneshot scheduler."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
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


def test_ordered_stops_finish_before_drain_advances_in_production_sandbox(tmp_path):  # noqa: PLR0915
    """Scale 90-second caller/unit grace periods to 0.9s; two ordered stops need 1.1s."""
    run_id = os.environ["GITHUB_RUN_ID"]
    assert re.fullmatch(r"[1-9][0-9]{0,19}", run_id)
    prefix = "asterproof-ci-ordered-drain-" + run_id
    scheduler, app = prefix + "-scheduler.service", prefix + "-app.service"
    timer, controller = prefix + "-scheduler.timer", prefix + "-worker.service"
    root = Path("/srv") / prefix
    root.mkdir(mode=0o700)  # Exclusive fixture; never reuse any existing host path.
    repository = Path(__file__).resolve().parents[3]
    created, support = [], []
    witness = root / "stop-witness.py"
    post_stop = "\nExecStopPost=" + str(root / ".venv/bin/python") + " -I -B " + str(witness) + " "

    def systemctl(*arguments, check=True):
        return subprocess.run(
            ["/usr/bin/systemctl", *arguments], capture_output=True, text=True, check=check, timeout=20,
        )

    definitions = {
        scheduler: "[Unit]\nAfter=" + app + "\n[Service]\nType=simple\nExecStart=/bin/sleep 600\n"
                   "ExecStop=/bin/sleep 0.55\nTimeoutStopSec=0.9s"
                   + post_stop + str(root / "scheduler-stopped") + "\n",
        app: "[Service]\nType=simple\nExecStart=/bin/sleep 600\n"
             "ExecStop=/bin/sleep 0.55\nTimeoutStopSec=0.9s" + post_stop + str(root / "app-stopped") + "\n",
        timer: "[Timer]\nOnActiveSec=10min\nUnit=" + scheduler + "\n",
    }
    try:
        shutil.copytree(repository / "scripts", root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(Path(sys.prefix), root / ".venv", symlinks=True)
        witness.write_text(
            "import sys, time\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(str(time.monotonic()))\n",
        )
        for name in ("/etc/asterproof", "/usr/local/libexec"):
            path = Path(name)
            if not path.exists():
                path.mkdir(mode=0o755)
                support.append(path)
        for unit, contents in definitions.items():
            path = Path("/run/systemd/system") / unit
            with path.open("x") as output:
                output.write(contents)
            created.append(path)
        systemctl("daemon-reload")
        systemctl("start", app, scheduler, timer)
        state, result = root / "operation.json", root / "result.json"
        atomic_write_json(state, {"state": "draining"})
        driver = root / "driver.py"
        driver.write_text(
            "import json, os, subprocess, sys, time\n"
            "from pathlib import Path\nfrom types import SimpleNamespace\n"
            f"sys.path.insert(0, {str(root)!r})\n"
            "os.environ['DJANGO_READ_DOT_ENV_FILE'] = 'false'\n"
            "from scripts.deployment import operation_worker as worker\n"
            "original_run = subprocess.run\nstop_deadlines = []\n"
            "def scaled_stop(arguments, **options):\n"
            "    if arguments[:2] == ['/usr/bin/systemctl', 'stop'] and '--no-block' not in arguments:\n"
            "        stop_deadlines.append(options['timeout'])\n"
            "        options['timeout'] = options['timeout'] / 100\n"
            "    return original_run(arguments, **options)\n"
            "worker.subprocess.run = scaled_stop\n"
            "backend = worker.WorkerBackend()\nwriters = []\n"
            "backend.assert_database_drained = lambda: writers.append(time.monotonic())\n"
            "started = time.monotonic()\nerror = None\n"
            "try:\n"
            f"    contract = SimpleNamespace(service={app!r}, scheduler_service={scheduler!r})\n"
            f"    backend.drain(contract, Path({str(state)!r}))\n"
            "except Exception as exc:\n"
            "    error = {'type': type(exc).__name__, 'code': getattr(exc, 'code', None),\n"
            "             'returncode': getattr(exc, 'returncode', None), 'timeout': getattr(exc, 'timeout', None)}\n"
            f"units = {[timer, scheduler, app, controller]!r}\n"
            "names = 'ActiveState,MainPID,ControlGroup,Result,ExecMainCode,ExecMainStatus,Job'\n"
            "states = {unit: backend._unit_properties(unit, names)\n"
            "          for unit in units}\n"
            "finished = time.monotonic()\n"
            f"Path({str(result)!r}).write_text(json.dumps({{'error': error, 'writer_checks': writers,\n"
            "    'elapsed_seconds': finished-started, 'finished_monotonic': finished,\n"
            "    'original_stop_deadlines': stop_deadlines, 'observed_units': states}, sort_keys=True))\n",
        )
        template = (repository / "deployment/systemd/asterproof-deploy-operation@.service.in").read_text()
        service = template.split("[Service]\n", 1)[1].split("[Install]", 1)[0]
        properties = [
            line.replace("@RELEASE_ROOT@", str(root)) for line in service.splitlines()
            if line and not line.startswith("#") and not line.startswith("ExecStart=")
        ]
        assert "NoNewPrivileges=yes" in properties
        assert "MemoryDenyWriteExecute=yes" in properties
        assert "ProtectControlGroups=yes" in properties
        assert "RestrictNamespaces=yes" in properties
        # Keep the production default root identity; explicit User=root changes capabilities on systemd255.
        assert not any(value.startswith(("User=", "Group=")) for value in properties)
        completed = subprocess.run(
            ["/usr/bin/systemd-run", "--wait", "--collect", "--unit=" + controller,
             *["--property=" + value for value in properties],
             str(root / ".venv/bin/python"), "-I", "-B", str(driver)],
            capture_output=True, text=True, check=False, timeout=25,
        )
        outcome = json.loads(result.read_text()) if result.exists() else {"controller_exit": completed.returncode}
        for _ in range(100):
            if all(systemctl("show", unit, "-p", "ActiveState", "--value").stdout.strip() in {"inactive", "failed"}
                   for unit in (timer, scheduler, app)):
                break
            time.sleep(0.05)
        finished = systemctl("show", app, "-p", "InactiveEnterTimestampMonotonic", "--value").stdout.strip()
        evidence = {
            **outcome, "run_id": run_id, "source_sha": os.environ.get("GITHUB_SHA"),
            "per_unit_grace_seconds": 0.9, "ordered_exec_stop_seconds": [0.55, 0.55],
            "app_finished_monotonic": int(finished or "0") / 1000000,
            "sandbox_properties": properties, "production_access": False,
            "database_guard": "synthetic callback; real SQL guard covered separately",
            "stop_witnesses": {
                name: float((root / (name + "-stopped")).read_text())
                if (root / (name + "-stopped")).exists() else None
                for name in ("app", "scheduler")
            },
        }
        evidence_root = Path(os.environ.get("RUNNER_TEMP", str(tmp_path)))
        (evidence_root / ("drain-lifecycle-" + run_id + ".json")).write_text(json.dumps(evidence, sort_keys=True))
        assert completed.returncode == 0, evidence
        assert outcome.get("error") is None, evidence
        assert len(outcome["writer_checks"]) == 1
        assert read_json(state)["maintenance_scheduler_stop_result"]["MainPID"] == "0"
        assert all(value is not None and 0 < value <= outcome["writer_checks"][0]
                   for value in evidence["stop_witnesses"].values())
        # systemd may garbage-collect inactive units and reset their timestamps.
        assert outcome["observed_units"][app]["ActiveState"] == "inactive"
        assert all(outcome["observed_units"][unit].get("MainPID", "0") == "0" for unit in (timer, scheduler, app))
        assert all(outcome["observed_units"][unit]["Job"] == "" for unit in (timer, scheduler, app))
    finally:
        if created:
            systemctl("stop", controller, *(path.name for path in created), check=False)
            systemctl("reset-failed", controller, *(path.name for path in created), check=False)
            for path in created:
                path.unlink()
            systemctl("daemon-reload")
        shutil.rmtree(root)
        for path in reversed(support):
            path.rmdir()
