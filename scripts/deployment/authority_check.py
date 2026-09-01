# ruff: noqa: EM101, TRY003
from __future__ import annotations

import os
import sys
from pathlib import Path

from scripts.deployment.bootstrap import _authority_matches


def main() -> int:
    if os.geteuid() != 0:
        raise PermissionError("authority check helper must run as root")
    if len(sys.argv) != 1:
        raise ValueError("authority check helper does not accept arguments")
    return 0 if _authority_matches(Path("/")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
