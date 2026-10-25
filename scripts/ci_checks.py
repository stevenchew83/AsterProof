"""Select bounded PR checks; production deployment still verifies the full release."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = {"pages", "problemsets", "rankings", "solutions", "training", "users"}
# These apps consume the shared problem identity and statement/solution helpers.
DEPENDENTS = {"pages": {"problemsets", "solutions"}, "solutions": {"problemsets"}}
CORE_TESTS = {"config/tests", "inspinia/users/tests"}
DEPENDENCY_FILES = {"pyproject.toml", "uv.lock"}
STATIC_FILES = {"package.json", "package-lock.json", "gulpfile.js", "scripts/build_and_collectstatic.sh"}


def documentation_only(path: str) -> bool:
    file = Path(path)
    return file.name == "AGENTS.md" or (
        file.suffix in {".md", ".rst"}
        and (len(file.parts) == 1 or file.parts[0] in {"docs", ".github"})
    )


def select_checks(paths: list[str]) -> dict:
    changed = [path for path in paths if not documentation_only(path)]
    apps: set[str] = set()
    tests = set(CORE_TESTS) if changed else set()
    static = locks = workflows = False
    for path in changed:
        if path in DEPENDENCY_FILES or path.startswith("requirements/"):
            apps.update(APPS)
            tests.add("scripts")
            locks = static = True
        elif path.startswith(".github/workflows/"):
            tests.add("scripts")
            workflows = True
        elif path.startswith(("scripts/", "deployment/")):
            tests.add("scripts")
            static |= path in STATIC_FILES
            locks |= path == "scripts/deployment/check_production_lock.py"
        elif path in STATIC_FILES or path.startswith("inspinia/static/"):
            static = True
        elif path.startswith("config/") or path == "manage.py":
            apps.update(APPS)
            static = True
        elif path.startswith("inspinia/"):
            app = path.removeprefix("inspinia/templates/").removeprefix("inspinia/").split("/", 1)[0]
            apps.update({app} if app in APPS else APPS)
        else:
            # New/shared paths get broad checks until their ownership is known.
            apps.update(APPS)
            tests.add("scripts")
            static = locks = workflows = True

    if "users" in apps:
        apps.update(APPS)
    for app in tuple(apps):
        apps.update(DEPENDENTS.get(app, set()))
    tests.update(f"inspinia/{app}" for app in apps if app != "users")
    return {
        "runtime": bool(changed),
        "workflows": workflows,
        "static": static,
        "locks": locks,
        "tests": sorted(tests),
    }


def changed_paths(base: str, *, root: Path = ROOT) -> list[str]:
    if re.fullmatch(r"[0-9a-f]{40}", base) is None:
        msg = "CI requires an exact PR base SHA"
        raise ValueError(msg)
    result = subprocess.run(  # noqa: S603
        ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD", "--"],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [path for path in result.stdout.split("\0") if path]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    checks = select_checks(changed_paths(args.base))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            for name, value in checks.items():
                stream.write(f"{name}={json.dumps(value)}\n")
    print(json.dumps(checks, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
