# ruff: noqa: EM101, EM102, T201, TRY003, TRY301
"""Generate and validate AsterProof's hashed production dependency lock."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

PYTHON_VERSION = "3.12"
TARGET_PLATFORM = "x86_64-manylinux_2_28"
SOURCE_HEADER = "# asterproof-requirements-sha256: "
LOCK_ENTRY_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^ ;\\]+)")
SOURCE_ENTRY_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?\s*(==|>=)\s*([^ ;#]+)")
HASH_TOKEN_RE = re.compile(r"--hash=sha256:([^\s\\]+)")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class LockError(ValueError):
    """A production lock contract violation."""


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_files(source: Path) -> list[Path]:
    """Return the source and its recursively included local requirement files."""
    discovered: list[Path] = []
    visiting: set[Path] = set()

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in visiting:
            raise LockError(f"cyclic requirements include: {path}")
        if path in discovered:
            return
        if not path.is_file():
            raise LockError(f"missing requirements input: {path}")
        visiting.add(path)
        discovered.append(path)
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith(("-r ", "--requirement ")):
                include = line.split(maxsplit=1)[1]
                visit(path.parent / include)
        visiting.remove(path)

    visit(source)
    return discovered


def requirements_digest(source: Path) -> str:
    digest = hashlib.sha256()
    root = source.resolve().parent.parent
    for path in sorted(requirement_files(source)):
        try:
            label = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise LockError(f"requirements include escapes repository: {path}") from exc
        digest.update(label.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def direct_requirements(source: Path) -> dict[str, tuple[str, str]]:
    parsed: dict[str, tuple[str, str]] = {}
    for path in requirement_files(source):
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            match = SOURCE_ENTRY_RE.match(raw_line.strip())
            if match:
                parsed[normalize_name(match.group(1))] = (match.group(2), match.group(3))
    return parsed


def project_requirements(pyproject: Path) -> dict[str, tuple[str, str]]:
    document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    parsed: dict[str, tuple[str, str]] = {}
    for value in document.get("project", {}).get("dependencies", []):
        match = SOURCE_ENTRY_RE.match(value)
        if not match:
            raise LockError(f"unsupported pyproject dependency declaration: {value}")
        parsed[normalize_name(match.group(1))] = (match.group(2), match.group(3))
    return parsed


def validate_overlap(source: Path, pyproject: Path) -> None:
    authority = direct_requirements(source)
    for name, project_spec in project_requirements(pyproject).items():
        authority_spec = authority.get(name)
        if authority_spec is None:
            raise LockError(f"pyproject dependency is absent from production requirements: {name}")
        if project_spec != authority_spec:
            raise LockError(
                f"pyproject/production requirement drift for {name}: "
                f"pyproject {project_spec[0]}{project_spec[1]}, "
                f"production {authority_spec[0]}{authority_spec[1]}",
            )


def validate_locked_entries(lines: list[str]) -> None:
    entries = 0
    current_entry: str | None = None
    current_has_hash = False
    for line in [*lines, "sentinel"]:
        for digest in HASH_TOKEN_RE.findall(line):
            if SHA256_RE.fullmatch(digest) is None:
                raise LockError(f"invalid sha256 hash in production lock: {digest}")
        match = LOCK_ENTRY_RE.match(line)
        if match:
            if current_entry is not None and not current_has_hash:
                raise LockError(f"locked requirement has no sha256 hash: {current_entry}")
            current_entry = normalize_name(match.group(1))
            current_has_hash = "--hash=sha256:" in line
            entries += 1
        elif current_entry is not None and line.startswith("    --hash=sha256:"):
            current_has_hash = True
    if entries == 0:
        raise LockError("production lock contains no pinned requirements")
    if current_entry is not None and not current_has_hash:
        raise LockError(f"locked requirement has no sha256 hash: {current_entry}")


def validate_lock(source: Path, lock: Path, pyproject: Path) -> None:
    if not lock.is_file():
        raise LockError(f"missing production lock: {lock}")
    validate_overlap(source, pyproject)
    lines = lock.read_text(encoding="utf-8").splitlines()
    expected_header = SOURCE_HEADER + requirements_digest(source)
    if expected_header not in lines[:8]:
        raise LockError("production lock is stale; regenerate it with --write")
    validate_locked_entries(lines)


def validate_resolved_lock(source: Path, lock: Path) -> None:
    """Re-resolve from source so altered transitive pins cannot validate themselves."""
    expected = render_lock(source, None, upgrade=False)
    if lock.read_text(encoding="utf-8") != expected:
        raise LockError("production lock differs from a clean deterministic resolution")


def render_lock(source: Path, existing_lock: Path | None, *, upgrade: bool) -> str:
    with tempfile.TemporaryDirectory(prefix="asterproof-lock-") as temp_dir:
        output = Path(temp_dir) / "production.lock"
        if existing_lock and existing_lock.is_file() and not upgrade:
            output.write_bytes(existing_lock.read_bytes())
        command = [
            "uv",
            "pip",
            "compile",
            str(source),
            "--generate-hashes",
            "--python-version",
            PYTHON_VERSION,
            "--python-platform",
            TARGET_PLATFORM,
            "--no-header",
            "--output-file",
            str(output),
        ]
        if upgrade:
            command.append("--upgrade")
        environment = os.environ.copy()
        environment.setdefault("UV_CACHE_DIR", str(Path(temp_dir) / "uv-cache"))
        subprocess.run(command, check=True, env=environment, stdout=subprocess.DEVNULL)  # noqa: S603
        body = output.read_text(encoding="utf-8")
    header = (
        "# Generated by scripts/deployment/check_production_lock.py --write\n"
        f"# Python {PYTHON_VERSION}; target {TARGET_PLATFORM}\n"
        f"{SOURCE_HEADER}{requirements_digest(source)}\n"
    )
    return header + body


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--write", action="store_true", help="regenerate the lock, preserving versions")
    parser.add_argument("--upgrade", action="store_true", help="regenerate and allow dependency upgrades")
    parser.add_argument(
        "--verify-resolution",
        action="store_true",
        help="resolve from source and require a byte-identical lock",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    source = root / "requirements" / "production.txt"
    lock = root / "requirements" / "production.lock"
    pyproject = root / "pyproject.toml"
    try:
        if args.upgrade and not args.write:
            raise LockError("--upgrade requires --write")
        if args.write and args.verify_resolution:
            raise LockError("--verify-resolution cannot be combined with --write")
        validate_overlap(source, pyproject)
        if args.write:
            rendered = render_lock(source, lock, upgrade=args.upgrade)
            lock.write_text(rendered, encoding="utf-8")
        validate_lock(source, lock, pyproject)
        if args.verify_resolution:
            validate_resolved_lock(source, lock)
    except (LockError, OSError, subprocess.CalledProcessError, tomllib.TOMLDecodeError) as exc:
        print(f"production lock check failed: {exc}", file=sys.stderr)
        return 1
    print("production lock is current, hashed, and aligned with pyproject.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
