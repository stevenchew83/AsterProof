# ruff: noqa: EM101, PLR2004, TRY003
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

NON_TERMINAL_STATES = {"receiving", "verified", "prepared", "migrating", "activating"}
TERMINAL_STATES = {"active", "rolled_back", "failed", "recovery_required"}
ALL_STATES = NON_TERMINAL_STATES | TERMINAL_STATES
TRANSITIONS = {
    "receiving": {"verified", "failed"},
    "verified": {"prepared", "activating", "failed"},
    "prepared": {"migrating", "activating", "failed"},
    "migrating": {"activating", "recovery_required"},
    "activating": {"active", "rolled_back", "recovery_required"},
    "active": set(),
    "rolled_back": set(),
    "failed": set(),
    "recovery_required": set(),
}


class ReleaseStateError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
        path.chmod(0o644)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseStateError("release state cannot be read") from exc
    if not isinstance(value, dict):
        raise ReleaseStateError("release state must be an object")
    return value


def transition(path: Path, target_state: str, *, error_code: str | None = None) -> dict[str, Any]:
    current = read_json(path)
    current_state = current.get("state")
    if current_state not in ALL_STATES or target_state not in ALL_STATES:
        raise ReleaseStateError("unknown release state")
    if target_state not in TRANSITIONS[current_state]:
        raise ReleaseStateError("invalid release state transition")
    current["state"] = target_state
    current["error_code"] = error_code
    current["updated_at"] = utc_now()
    atomic_write_json(path, current)
    return current


def safe_release_path(releases_dir: Path, release_sha: str) -> Path:
    if len(release_sha) != 40 or any(character not in "0123456789abcdef" for character in release_sha):
        raise ReleaseStateError("invalid release SHA")
    path = releases_dir / release_sha
    resolved_root = releases_dir.resolve(strict=False)
    resolved = path.resolve(strict=False)
    if resolved.parent != resolved_root:
        raise ReleaseStateError("release path escapes release root")
    return path


def atomic_symlink(link: Path, target: Path, *, allowed_root: Path) -> None:
    resolved_root = allowed_root.resolve(strict=True)
    resolved_target = target.resolve(strict=True)
    if resolved_target.parent != resolved_root or not resolved_target.is_dir():
        raise ReleaseStateError("symlink target is not a release")
    relative = Path("releases") / resolved_target.name
    temporary = link.with_name(f".{link.name}.next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(relative)
    temporary.replace(link)


def release_sha_from_link(link: Path, *, releases_dir: Path) -> str | None:
    if not link.is_symlink():
        return None
    target = link.resolve(strict=True)
    if target.parent != releases_dir.resolve(strict=True) or not target.is_dir():
        raise ReleaseStateError("release link escapes release root")
    return target.name


def protected_release_shas(release_root: Path, operations_dir: Path) -> set[str]:
    protected: set[str] = set()
    for name in ("current", "previous"):
        link = release_root / name
        if link.is_symlink():
            target = link.resolve(strict=False)
            if target.parent == (release_root / "releases").resolve(strict=False):
                protected.add(target.name)
    if operations_dir.is_dir():
        for path in operations_dir.glob("*.json"):
            try:
                operation = read_json(path)
            except ReleaseStateError:
                continue
            if operation.get("state") in NON_TERMINAL_STATES and isinstance(operation.get("release_sha"), str):
                protected.add(operation["release_sha"])
    return protected
