# ruff: noqa: EM101, PLR0913, PLR2004, S310, S603, TC001, TRY003
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from scripts.deployment.release_manifest import ReleaseManifest
from scripts.deployment.release_state import ReleaseStateError
from scripts.deployment.release_state import atomic_symlink
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import safe_release_path
from scripts.deployment.release_state import utc_now
from scripts.deployment.target import TargetContract


def activate_release(contract: TargetContract, release_sha: str) -> str | None:
    target = safe_release_path(contract.releases_dir, release_sha)
    if not target.is_dir():
        raise ReleaseStateError("candidate release is missing")
    current = contract.release_root / "current"
    previous = contract.release_root / "previous"
    prior_sha: str | None = None
    if current.is_symlink():
        prior = current.resolve(strict=True)
        if prior.parent != contract.releases_dir.resolve(strict=True):
            raise ReleaseStateError("current release link escapes release root")
        prior_sha = prior.name
        atomic_symlink(previous, prior, allowed_root=contract.releases_dir)
    atomic_symlink(current, target, allowed_root=contract.releases_dir)
    return prior_sha


def restore_previous(contract: TargetContract) -> str:
    current = contract.release_root / "current"
    previous = contract.release_root / "previous"
    if not previous.is_symlink() or not current.is_symlink():
        raise ReleaseStateError("previous release is unavailable")
    target = previous.resolve(strict=True)
    prior = current.resolve(strict=True)
    if prior.parent != contract.releases_dir.resolve(strict=True):
        raise ReleaseStateError("current release link escapes release root")
    atomic_symlink(current, target, allowed_root=contract.releases_dir)
    atomic_symlink(previous, prior, allowed_root=contract.releases_dir)
    return target.name


def write_runtime_state(
    release: Path,
    *,
    release_sha: str,
    artifact_digest: str,
    state_fingerprint: str,
) -> None:
    path = release / "runtime-release-state.json"
    atomic_write_json(
        path,
        {
            "artifact_sha256": artifact_digest,
            "state_fingerprint": state_fingerprint,
            "process_commit_sha": release_sha,
            "recorded_at": utc_now(),
            "schema_version": 1,
            "status": "ok",
        },
    )
    path.chmod(0o644)


def restart_service(contract: TargetContract) -> None:
    subprocess.run(["/usr/bin/systemctl", "restart", contract.service], check=True)
    subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", contract.service], check=True)


def _same_https_origin(expected_url: str, actual_url: str) -> bool:
    expected = urllib.parse.urlsplit(expected_url)
    actual = urllib.parse.urlsplit(actual_url)
    return expected.scheme == actual.scheme == "https" and expected.netloc == actual.netloc


def health_check(contract: TargetContract, release_sha: str, artifact_digest: str) -> dict[str, Any]:
    request = urllib.request.Request(
        contract.health_url,
        headers={"Accept": "application/json", "Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise ReleaseStateError("health endpoint returned an unexpected status")
        if not _same_https_origin(contract.health_url, response.geturl()):
            raise ReleaseStateError("health endpoint redirected outside the configured HTTPS origin")
        payload = response.read(64 * 1024 + 1)
    if len(payload) > 64 * 1024:
        raise ReleaseStateError("health response is too large")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ReleaseStateError("health response is malformed") from exc
    if value.get("process_commit_sha") != release_sha or value.get("artifact_sha256") != artifact_digest:
        raise ReleaseStateError("health response release identity mismatch")
    return value


def verify_static_assets(contract: TargetContract, release_sha: str) -> None:
    release = safe_release_path(contract.releases_dir, release_sha).resolve(strict=True)
    manifest = ReleaseManifest.from_bytes((release / "release-metadata.json").read_bytes())
    selected: dict[str, dict[str, Any]] = {}
    for item in manifest.files:
        path = str(item["path"])
        if not path.startswith("staticfiles/"):
            continue
        suffix = Path(path).suffix
        if suffix in {".css", ".js"} and suffix not in selected:
            selected[suffix] = item
    if set(selected) != {".css", ".js"}:
        raise ReleaseStateError("release manifest lacks representative static assets")
    origin = urllib.parse.urlsplit(contract.health_url)
    base_url = urllib.parse.urlunsplit((origin.scheme, origin.netloc, "/", "", ""))
    for item in selected.values():
        relative = str(item["path"]).removeprefix("staticfiles/")
        url = urllib.parse.urljoin(base_url, f"static/{relative}")
        request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200 or not _same_https_origin(contract.health_url, response.geturl()):
                raise ReleaseStateError("static asset response is invalid")
            payload = response.read(int(item["size"]) + 1)
        if len(payload) != item["size"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise ReleaseStateError("static asset bytes do not match the release manifest")


def verify_service_processes(contract: TargetContract, release_sha: str) -> dict[int, int]:
    result = subprocess.run(
        ["/usr/bin/systemctl", "show", contract.service, "--property=ControlGroup", "--value"],
        check=True,
        capture_output=True,
        text=True,
    )
    control_group = result.stdout.strip()
    if not control_group.startswith("/") or ".." in Path(control_group).parts:
        raise ReleaseStateError("service control group is invalid")
    process_file = Path("/sys/fs/cgroup") / control_group.lstrip("/") / "cgroup.procs"
    process_ids = [int(value) for value in process_file.read_text().splitlines() if value]
    if not process_ids:
        raise ReleaseStateError("service has no running processes")
    expected = safe_release_path(contract.releases_dir, release_sha).resolve(strict=True)
    evidence: dict[int, int] = {}
    for process_id in process_ids:
        working_directory = Path(f"/proc/{process_id}/cwd").readlink().resolve(strict=True)
        if working_directory != expected and expected not in working_directory.parents:
            raise ReleaseStateError("service process is outside the active release")
        executable = Path(f"/proc/{process_id}/exe").readlink().resolve(strict=True)
        if executable != expected and expected not in executable.parents:
            raise ReleaseStateError("service process executable is outside the active release")
        stat_fields = Path(f"/proc/{process_id}/stat").read_text().rsplit(")", 1)[1].split()
        start_time = int(stat_fields[19])
        evidence[process_id] = start_time
    return evidence


def verify_release(
    contract: TargetContract,
    release_sha: str,
    artifact_digest: str,
    *,
    stabilization_seconds: int = 10,
) -> dict[str, Any]:
    initial_processes = verify_service_processes(contract, release_sha)
    health_check(contract, release_sha, artifact_digest)
    verify_static_assets(contract, release_sha)
    time.sleep(stabilization_seconds)
    if verify_service_processes(contract, release_sha) != initial_processes:
        raise ReleaseStateError("service process set changed during stabilization")
    health = health_check(contract, release_sha, artifact_digest)
    verify_static_assets(contract, release_sha)
    return health
