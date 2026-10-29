"""Render reviewable Newsletter units; this command never installs or starts them."""

import argparse
import json
import re
from pathlib import Path

from scripts.deployment.target import TargetContract

SERVICE = "asterproof-newsletter.service"
TIMER = "asterproof-newsletter.timer"


def render_units(contract):
    values = {
        "APP_SERVICE": contract.service,
        "APP_USER": contract.app_user,
        "CURRENT": str(contract.release_root / "current"),
        "ENVIRONMENT_FILE": str(contract.environment_file),
    }
    if any(not re.fullmatch(r"[A-Za-z0-9_./-]+", value) for value in values.values()):
        message = "Unit substitutions must not contain systemd specifiers, whitespace or shell syntax."
        raise ValueError(message)
    directory = Path(__file__).resolve().parents[2] / "deployment/systemd"
    units = {}
    for name in (SERVICE, TIMER):
        text = (directory / (name + ".in")).read_text()
        for key, value in values.items():
            text = text.replace("@" + key + "@", value)
        units[name] = text
    return units


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render_units(TargetContract.load(args.contract)), indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
