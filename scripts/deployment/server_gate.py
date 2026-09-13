# ruff: noqa: EM101, PLR0912, S603, S607, T201, TRY003
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from scripts.deployment.oidc import GitHubOIDCValidator
from scripts.deployment.oidc import OIDCPolicy
from scripts.deployment.protocol import DIGEST_RE
from scripts.deployment.protocol import NUMERIC_RE
from scripts.deployment.protocol import OperationEnvelope
from scripts.deployment.protocol import ProtocolError
from scripts.deployment.protocol import parse_command
from scripts.deployment.protocol import read_frame
from scripts.deployment.release_manifest import sha256_file
from scripts.deployment.release_state import ReleaseStateError
from scripts.deployment.release_state import read_json
from scripts.deployment.release_state import release_sha_from_link
from scripts.deployment.target import TargetContract

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_CONTRACT = Path("/etc/asterproof/deployment-target.json")
AUTHORITY_CHECK_HELPER = Path("/usr/local/libexec/asterproof-authority-check")
SUBMIT_HELPER = Path("/usr/local/libexec/asterproof-deploy-submit")
STATUS_FIELDS = {
    "artifact_digest",
    "deployment_id",
    "error_code",
    "migration_class",
    "operation",
    "release_sha",
    "run_id",
    "state",
    "target_marker",
    "updated_at",
    "workflow_sha",
}


def _workflow_ref(contract: TargetContract, operation: str) -> str:
    return contract.rollback_workflow_ref if operation == "rollback" else contract.deploy_workflow_ref


def validate_authorization(contract: TargetContract, envelope: OperationEnvelope) -> dict[str, Any]:
    validator = GitHubOIDCValidator(
        OIDCPolicy(
            repository=contract.repository,
            repository_id=contract.repository_id,
            workflow_ref=_workflow_ref(contract, envelope.operation),
            target_marker=contract.marker,
        ),
    )
    return validator.validate(envelope.oidc_token, envelope)


def preflight(
    contract: TargetContract,
    *,
    authority_matches: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    authority_matches = authority_matches or _installed_authority_matches
    usage = shutil.disk_usage(contract.release_root)
    checks = {
        "authority_integrity": authority_matches(),
        "environment_external": contract.release_root.resolve(strict=False)
        not in contract.environment_file.resolve(strict=False).parents,
        "free_space": usage.free >= contract.minimum_free_bytes,
        "marker": contract.marker,
        "media_external": contract.release_root.resolve(strict=False)
        not in contract.media_root.resolve(strict=False).parents,
        "operations_resolved": _operations_resolved(contract),
        "release_root": contract.release_root.is_dir(),
        "repository_id": contract.repository_id,
        "service": contract.service,
    }
    result: dict[str, Any] = {
        "checks": checks,
        "ok": all(value is True or isinstance(value, str) for value in checks.values()),
    }
    result.update(_release_evidence(contract))
    result["adoption"] = _adoption_evidence(contract)
    return result


def _installed_authority_matches() -> bool:
    result = subprocess.run(
        ["/usr/bin/sudo", str(AUTHORITY_CHECK_HELPER)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _operations_resolved(contract: TargetContract) -> bool:
    operations = contract.registry_dir / "operations"
    if not operations.is_dir():
        return True
    for path in operations.glob("*.json"):
        try:
            state = read_json(path).get("state")
        except ReleaseStateError:
            return False
        if state not in {"active", "failed", "rolled_back"}:
            return False
    return True


def _adoption_evidence(contract: TargetContract) -> dict[str, Any] | None:
    try:
        record = read_json(contract.registry_dir / "adoption.json")
    except (OSError, ReleaseStateError):
        return None
    required = {
        "authorized_at",
        "legacy_sha",
        "legacy_source_root",
        "repository",
        "state",
        "state_fingerprint",
        "target_marker",
    }
    if (
        set(record) != required
        or record.get("state") != "authorized"
        or record.get("repository") != contract.repository
        or record.get("target_marker") != contract.marker
        or not Path(str(record.get("legacy_source_root", ""))).is_absolute()
        or ".." in Path(str(record.get("legacy_source_root", ""))).parts
        or re.fullmatch(r"[0-9a-f]{40}", str(record.get("legacy_sha", ""))) is None
        or not DIGEST_RE.fullmatch(str(record.get("state_fingerprint", "")))
    ):
        return None
    public_fields = required - {"legacy_source_root"}
    return {key: record[key] for key in sorted(public_fields)}


def _release_evidence(contract: TargetContract) -> dict[str, Any]:
    evidence: dict[str, Any] = {"active_release": None, "rollback_candidate": None}
    for link_name, field in (("current", "active_release"), ("previous", "rollback_candidate")):
        try:
            release_sha = release_sha_from_link(
                contract.release_root / link_name,
                releases_dir=contract.releases_dir,
            )
            if release_sha is None:
                continue
            record = read_json(contract.registry_dir / "releases" / f"{release_sha}.json")
            digest = str(record.get("artifact_digest", ""))
            if record.get("release_sha") != release_sha or not DIGEST_RE.fullmatch(digest):
                continue
            evidence[field] = {
                "artifact_digest": digest,
                "migration_class": record.get("migration_class"),
                "release_sha": release_sha,
                "rollback_eligible": bool(record.get("rollback_eligible")),
                "state": record.get("state"),
            }
        except (OSError, ReleaseStateError):
            continue
    return evidence


def receive(contract: TargetContract, stream: Any) -> dict[str, Any]:
    frame = read_frame(stream)
    artifact_size = frame.pop("artifact_size", None)
    envelope = OperationEnvelope.from_dict(frame)
    if envelope.operation != "deploy" or not isinstance(artifact_size, int) or artifact_size <= 0:
        raise ProtocolError("invalid receive request")
    if artifact_size > shutil.disk_usage(contract.release_root).free - contract.minimum_free_bytes:
        raise ProtocolError("insufficient free space for artifact")
    validate_authorization(contract, envelope)
    contract.incoming_dir.mkdir(mode=0o730, parents=True, exist_ok=True)
    destination = contract.incoming_dir / f"{envelope.run_id}-{envelope.release_sha}.tar"
    if destination.exists():
        if destination.stat().st_size == artifact_size and sha256_file(destination) == envelope.artifact_digest:
            return {
                "artifact_digest": envelope.artifact_digest,
                "release_sha": envelope.release_sha,
                "status": "already_received",
            }
        raise ProtocolError("artifact identity already exists with different contents")

    fd, temporary_name = tempfile.mkstemp(prefix=".receive-", dir=contract.incoming_dir)
    temporary = Path(temporary_name)
    digest_ok = False
    try:
        remaining = artifact_size
        with os.fdopen(fd, "wb") as output:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ProtocolError("artifact stream ended early")
                output.write(chunk)
                remaining -= len(chunk)
            output.flush()
            os.fsync(output.fileno())
        digest_ok = sha256_file(temporary) == envelope.artifact_digest
        if not digest_ok:
            raise ProtocolError("artifact digest mismatch")
        temporary.replace(destination)
    finally:
        if not digest_ok:
            temporary.unlink(missing_ok=True)
    return {"artifact_digest": envelope.artifact_digest, "release_sha": envelope.release_sha, "status": "received"}


def status(contract: TargetContract, stream: Any) -> dict[str, Any]:
    frame = read_frame(stream)
    if set(frame) != {"run_id"} or not isinstance(frame["run_id"], str) or not NUMERIC_RE.fullmatch(frame["run_id"]):
        raise ProtocolError("invalid status request")
    path = contract.registry_dir / "operations" / f"{frame['run_id']}.json"
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return {"run_id": frame["run_id"], "state": "unknown"}
    if not isinstance(value, dict):
        raise ProtocolError("operation status is malformed")
    return {key: value[key] for key in sorted(STATUS_FIELDS & set(value))}


def submit(stream: Any) -> dict[str, Any]:
    frame = read_frame(stream)
    encoded = json.dumps(frame, sort_keys=True, separators=(",", ":")).encode()
    framed = f"{len(encoded)}\n".encode() + encoded
    result = subprocess.run(
        ["/usr/bin/sudo", str(SUBMIT_HELPER)],
        input=framed,
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise ProtocolError("deployment submit helper rejected the request")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProtocolError("deployment submit helper returned invalid status") from exc
    if not isinstance(value, dict):
        raise ProtocolError("deployment submit status must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    contract = TargetContract.load(args.contract)
    command = parse_command(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
    if command == "preflight":
        result = preflight(contract)
    elif command == "receive":
        result = receive(contract, sys.stdin.buffer)
    elif command == "submit":
        result = submit(sys.stdin.buffer)
    else:
        result = status(contract, sys.stdin.buffer)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
