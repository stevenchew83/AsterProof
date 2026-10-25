"""Reject new application lint findings while allowing the recorded legacy baseline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "deployment/application-lint-baseline.json"


def finding_keys(findings: list[dict], root: Path) -> Counter[str]:
    keys = []
    for finding in findings:
        path = Path(finding["filename"]).resolve()
        relative = path.relative_to(root.resolve()).as_posix()
        line = path.read_text().splitlines()[finding["location"]["row"] - 1].strip()
        keys.append(json.dumps([relative, finding["code"], finding["message"], line], separators=(",", ":")))
    return Counter(keys)


def check_baseline(current: Counter[str], baseline: dict) -> Counter[str]:
    if baseline.get("format_version") != 1 or not isinstance(baseline.get("findings"), dict):
        msg = "Application lint baseline has an unsupported format"
        raise ValueError(msg)
    allowed = baseline["findings"]
    if any(not isinstance(key, str) or type(count) is not int or count < 1 for key, count in allowed.items()):
        msg = "Application lint baseline contains invalid findings"
        raise ValueError(msg)
    return current - Counter(allowed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args()
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "ruff", "check", "inspinia", "--output-format=json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        sys.stderr.write(result.stderr)
        return result.returncode
    findings = json.loads(result.stdout)
    new = check_baseline(finding_keys(findings, ROOT), json.loads(args.baseline.read_text()))
    if new:
        for key, count in sorted(new.items()):
            filename, code, message, source_line = json.loads(key)
            print(f"{filename}: {code} {message} ({count} new)\n  {source_line}")  # noqa: T201
        return 1
    print(f"Application lint: no new findings ({len(findings)} recorded legacy findings remain).")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
