# ruff: noqa: EM101, TRY003
from __future__ import annotations

import os
import sys
from pathlib import Path

from scripts.deployment.bootstrap import CONTRACT_PATH
from scripts.deployment.bootstrap import _authority_matches
from scripts.deployment.bootstrap import managed_service_configuration_matches
from scripts.deployment.target import TargetContract
from scripts.deployment.target import TargetContractError


def main() -> int:
    if os.geteuid() != 0:
        raise PermissionError("authority check helper must run as root")
    if len(sys.argv) != 1:
        raise ValueError("authority check helper does not accept arguments")
    if not _authority_matches(Path("/")):
        return 1
    try:
        contract = TargetContract.load(CONTRACT_PATH)
        return 0 if managed_service_configuration_matches(contract) else 1
    except (OSError, TargetContractError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
