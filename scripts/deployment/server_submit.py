# ruff: noqa: EM101, S603, T201, TRY003
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC
from datetime import datetime
from pathlib import Path

from scripts.deployment.protocol import OperationEnvelope
from scripts.deployment.protocol import read_frame
from scripts.deployment.server_gate import DEFAULT_CONTRACT
from scripts.deployment.server_gate import validate_authorization
from scripts.deployment.target import TargetContract


def _atomic_write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def accept_request(contract: TargetContract, frame: dict[str, object]) -> dict[str, object]:
    envelope = OperationEnvelope.from_dict(frame)
    claims = validate_authorization(contract, envelope)
    requests = contract.registry_dir / "requests"
    operations = contract.registry_dir / "operations"
    replay = contract.registry_dir / "oidc-jti"
    request_path = requests / f"{envelope.run_id}.json"
    operation_path = operations / f"{envelope.run_id}.json"
    jti_path = replay / str(claims["jti"])
    for directory in (requests, operations, replay):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        jti_path.touch(mode=0o600, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError("OIDC authorization has already been used") from exc

    public = envelope.public_dict()
    request = public | {"workflow_ref": claims["workflow_ref"]}
    if request_path.exists():
        existing = json.loads(request_path.read_text())
        if existing != request:
            raise ValueError("run id already belongs to another request")
    else:
        _atomic_write(request_path, request)
    if operation_path.exists():
        existing_state = json.loads(operation_path.read_text())
        if existing_state.get("state") != "verified":
            return {"run_id": envelope.run_id, "state": existing_state.get("state", "unknown")}
    state = public | {
        "error_code": None,
        "state": "verified",
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    _atomic_write(operation_path, state)
    subprocess.run(
        ["/usr/bin/systemctl", "start", f"asterproof-deploy-operation@{envelope.run_id}.service"],
        check=True,
    )
    return {"run_id": envelope.run_id, "state": "submitted"}


def main() -> int:
    if os.geteuid() != 0:
        raise PermissionError("submit helper must run as root")
    if len(sys.argv) != 1:
        raise ValueError("submit helper does not accept arguments")
    result = accept_request(TargetContract.load(DEFAULT_CONTRACT), read_frame(sys.stdin.buffer))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
