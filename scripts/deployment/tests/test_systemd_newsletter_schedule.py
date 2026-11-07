# ruff: noqa: S603, T201, PLR2004
"""Verify maintenance isolation on synthetic units on an ephemeral Actions host."""

import os
import re
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment.newsletter_schedule import REVIEW_SERVICE
from scripts.deployment.newsletter_schedule import REVIEW_TIMER
from scripts.deployment.newsletter_schedule import SERVICE
from scripts.deployment.newsletter_schedule import TIMER
from scripts.deployment.newsletter_schedule import render_units

pytestmark = pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") != "true" or os.geteuid() != 0,
    reason="Root on an ephemeral Actions host only; never production units",
)



def _pool_ready(unit):
    journal = subprocess.run(
        ["/usr/bin/journalctl", "-u", unit, "-o", "cat", "-n", "12", "--no-pager"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    return "review-pool-ready" in journal.stdout


@pytest.mark.parametrize(("kind", "service_name", "timer_name"), [
    ("newsletter", SERVICE, TIMER),
    ("admin-reviews", REVIEW_SERVICE, REVIEW_TIMER),
])
def test_worker_cannot_start_drained_app_and_stops_with_app(tmp_path, kind, service_name, timer_name):
    run_id = os.environ["GITHUB_RUN_ID"]
    assert re.fullmatch(r"[1-9][0-9]{0,19}", run_id)
    app_user = os.environ["SUDO_USER"]
    assert app_user != "root"
    assert re.fullmatch(r"[a-z_][a-z0-9_-]*", app_user)
    prefix = f"asterproof-ci-{kind}-{run_id}"
    app, job, timer = (prefix + suffix for suffix in ("-app.service", ".service", ".timer"))
    units = render_units(SimpleNamespace(
        service=app, app_user=app_user,
        release_root=Path("/srv/asterproof-ci"), environment_file=Path("/dev/null"),
    ), admin_reviews=kind == "admin-reviews")
    # Keep the real dependency/sandbox/resource settings; substitute only the
    # synthetic executable/path. No application environment or data is used.
    executable = "/bin/sleep 600"
    if kind == "admin-reviews":
        executable = (
            '/usr/bin/python3 -c "import os, time; from concurrent.futures import ProcessPoolExecutor; '
            "from multiprocessing import get_context; pool = ProcessPoolExecutor(max_workers=6, "
            "mp_context=get_context('spawn')); assert pool.submit(os.getpid).result(timeout=10) != os.getpid(); "
            'print(\'review-pool-ready\', flush=True); time.sleep(600)"'
        )
    service = re.sub(r"^ExecStart=.*$", f"ExecStart={executable}", units[service_name], flags=re.MULTILINE)
    service = re.sub(r"^WorkingDirectory=.*$", "WorkingDirectory=/", service, flags=re.MULTILINE)
    definitions = {
        app: f"[Service]\nType=simple\nUser={app_user}\nExecStart=/bin/sleep 600\nTimeoutStopSec=10s\n",
        job: service,
        timer: units[timer_name].replace(service_name, job),
    }
    created = []

    def systemctl(*args, check=True):
        return subprocess.run(["/usr/bin/systemctl", *args], check=check, capture_output=True, text=True, timeout=20)

    def pid(unit):
        return systemctl("show", unit, "--property=MainPID", "--value").stdout.strip()

    try:
        for name, text in definitions.items():
            path = Path("/run/systemd/system") / name
            with path.open("x") as stream:
                stream.write(text)
            created.append(path)
        subprocess.run(["/usr/bin/systemd-analyze", "verify", "--man=no", *map(str, created)], check=True, timeout=20)
        systemctl("daemon-reload")
        assert systemctl("start", job, check=False).returncode != 0
        assert pid(app) == "0"
        assert pid(job) == "0"
        systemctl("start", app)
        systemctl("start", "--no-block", job)
        for _ in range(80):
            if pid(job) not in {"", "0"} and (kind != "admin-reviews" or _pool_ready(job)):
                break
            time.sleep(0.1)
        else:
            pytest.fail("Synthetic worker did not start")
        systemctl("stop", app)
        assert pid(app) == "0"
        assert pid(job) == "0"
        systemctl("start", app)
        assert pid(job) == "0", "Starting the app must not launch heavy maintenance"
        systemctl("restart", app)
        assert pid(job) == "0", "Restarting the app must not launch an inactive worker"
    finally:
        if created:
            systemctl("stop", *(p.name for p in created), check=False)
            systemctl("reset-failed", *(p.name for p in created), check=False)
            for path in created:
                path.unlink()
            systemctl("daemon-reload")
