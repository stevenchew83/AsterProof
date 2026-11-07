"""Render reviewable AsterProof scheduler units; this command never installs or starts them."""

import argparse
import json
import re
from pathlib import Path

from scripts.deployment.target import TargetContract

SERVICE = "asterproof-newsletter.service"
TIMER = "asterproof-newsletter.timer"
REVIEW_SERVICE = "asterproof-admin-solution-reviews.service"
REVIEW_TIMER = "asterproof-admin-solution-reviews.timer"


def render_units(contract, *, admin_reviews=False):
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
    for name in ((REVIEW_SERVICE, REVIEW_TIMER) if admin_reviews else (SERVICE, TIMER)):
        text = (directory / (name + ".in")).read_text()
        for key, value in values.items():
            text = text.replace("@" + key + "@", value)
        units[name] = text
    return units


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--admin-solution-reviews", action="store_true")
    args = parser.parse_args()
    units = render_units(TargetContract.load(args.contract), admin_reviews=args.admin_solution_reviews)
    print(json.dumps(units, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
