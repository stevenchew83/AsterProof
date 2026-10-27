# ruff: noqa: S603, T201
"""Install only the separately authorized nightly duplicate-report schedule.

Run from reviewed immutable source after the matching application release is
active. This does not install deployment authority or alter existing units.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SERVICE = "asterproof-duplicate-report.service"
TIMER = "asterproof-duplicate-report.timer"


def render_units(contract):
    current = contract.release_root / "current"
    for value in (str(current), str(contract.environment_file)):
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
            message = "Unit paths must not contain systemd specifiers or whitespace."
            raise ValueError(message)
    return {
        SERVICE: f"""[Unit]
Description=AsterProof nightly duplicate-statement report
Requisite={contract.service}
After={contract.service}

[Service]
Type=oneshot
User={contract.app_user}
WorkingDirectory={current}
EnvironmentFile={contract.environment_file}
ExecStart={current}/.venv/bin/python manage.py refresh_statement_duplicate_report --force
Nice=15
CPUWeight=10
IOWeight=10
MemoryHigh=160M
MemoryMax=192M
TimeoutStartSec=25min
TimeoutStopSec=20s
KillMode=control-group
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
""",
        TIMER: f"""[Unit]
Description=Run AsterProof duplicate analysis at 02:00 MYT

[Timer]
OnCalendar=*-*-* 02:00:00 Asia/Kuala_Lumpur
AccuracySec=1min
Persistent=false
Unit={SERVICE}

[Install]
WantedBy=timers.target
""",
    }


def check_destinations(directory, units):
    for name, text in units.items():
        path = directory / name
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_text() != text)):
            message = f"Refusing to replace an existing different unit: {name}"
            raise ValueError(message)
        if path.exists() and (path.stat().st_uid != 0 or path.stat().st_mode & 0o022):
            message = f"Existing unit ownership/mode is unsafe: {name}"
            raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--install", action="store_true", help="Install and enable the timer; never run analysis now.")
    args = parser.parse_args()
    if __package__:
        parser.error("Execute the reviewed installer as a standalone file or stdin, not a release package module.")
    if os.geteuid() != 0 or not re.fullmatch(r"[0-9a-f]{40}", args.release_sha):
        parser.error("Root and an exact release SHA are required.")
    # Import the pre-existing protected target validator, never release code as root.
    sys.path.insert(0, "/usr/local/libexec/asterproof-authority")
    from scripts.deployment.target import TargetContract

    contract = TargetContract.load(Path("/etc/asterproof/deployment-target.json"))
    if contract.marker != "asterproof-production" or contract.repository != "stevenchew83/AsterProof":
        parser.error("Unexpected production target.")
    current = contract.release_root / "current"
    record = json.loads((contract.registry_dir / "releases" / f"{args.release_sha}.json").read_text())
    if (
        current.resolve().name != args.release_sha
        or record["state"] != "active"
        or record["release_sha"] != args.release_sha
        or not (current / "inspinia/pages/management/commands/refresh_statement_duplicate_report.py").is_file()
    ):
        parser.error("The exact matching application release must already be active.")
    subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", contract.service], check=True, timeout=10)
    units = render_units(contract)
    directory = Path("/etc/systemd/system")
    check_destinations(directory, units)
    with tempfile.TemporaryDirectory(prefix="asterproof-duplicate-units-", dir="/run") as temporary:
        paths = []
        for name, text in units.items():
            path = Path(temporary) / name
            path.write_text(text)
            paths.append(str(path))
        subprocess.run(["/usr/bin/systemd-analyze", "verify", "--man=no", *paths], check=True, timeout=20)
        if args.install:
            check_destinations(directory, units)
            if current.resolve().name != args.release_sha:
                parser.error("Active release changed during preparation.")
            for name, text in units.items():
                path = directory / name
                if not path.exists():
                    with path.open("x") as stream:
                        stream.write(text)
                    path.chmod(0o644)
            subprocess.run(["/usr/bin/systemctl", "daemon-reload"], check=True, timeout=20)
            # Preserve the already-published hourly cache until the first night.
            # This one-time bounded command renews cache TTLs, not source analysis.
            subprocess.run([
                "/usr/bin/systemd-run", f"--unit=asterproof-duplicate-retain-{args.release_sha[:12]}",
                "--wait", "--collect", "--pipe", "--property=Type=oneshot",
                f"--property=User={contract.app_user}", f"--property=WorkingDirectory={current}",
                f"--property=EnvironmentFile={contract.environment_file}",
                "--property=Nice=15", "--property=IOWeight=10", "--property=MemoryHigh=160M",
                "--property=MemoryMax=192M", "--property=TimeoutStartSec=90s",
                "--property=NoNewPrivileges=true", "--property=PrivateTmp=true",
                "--property=ProtectSystem=strict", "--property=ProtectHome=true",
                str(current / ".venv/bin/python"), "manage.py",
                "refresh_statement_duplicate_report", "--retain-current",
            ], check=True, timeout=100)
            subprocess.run(["/usr/bin/systemctl", "enable", "--now", TIMER], check=True, timeout=20)
            subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", TIMER], check=True, timeout=10)
    print(json.dumps({
        "release_sha": args.release_sha,
        "installed": args.install,
        "schedule": "02:00 Asia/Kuala_Lumpur; no catch-up run",
        "unit_sha256": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in units.items()},
    }, sort_keys=True))


if __name__ == "__main__":
    main()
