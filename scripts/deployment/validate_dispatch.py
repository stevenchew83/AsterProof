# ruff: noqa: C901, EM101, EM102, PLR0912, PLR0913, PLR0915, PLR2004, S106, S603, S607, T201, TRY003
"""Validate GitHub deployment workflow inputs and public release evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.deployment.migration_plan import load_registry
from scripts.deployment.protocol import DIGEST_RE
from scripts.deployment.protocol import MARKER_RE
from scripts.deployment.protocol import NUMERIC_RE
from scripts.deployment.protocol import SHA_RE
from scripts.deployment.protocol import OperationEnvelope
from scripts.deployment.protocol import envelope_audience

MAIN_REF = "refs/heads/main"
ROUTINE_MIGRATION_CLASSES = {"none", "backward-compatible-schema"}
ALL_MIGRATION_CLASSES = ROUTINE_MIGRATION_CLASSES | {"data-or-non-compatible"}
HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
MIGRATION_PATH_RE = re.compile(r"^inspinia/([a-z_][a-z0-9_]*)/migrations/([0-9][A-Za-z0-9_]*)\.py$")


class DispatchValidationError(ValueError):
    """Raised when a workflow request is not authorized by the static contract."""


def validate_current_main(*, event: str, ref: str, checked_out_sha: str, requested_sha: str) -> None:
    if event != "workflow_dispatch":
        raise DispatchValidationError("production releases require workflow_dispatch")
    if ref != MAIN_REF:
        raise DispatchValidationError("production workflows must run from refs/heads/main")
    if SHA_RE.fullmatch(requested_sha) is None:
        raise DispatchValidationError("release_sha must be 40 lowercase hexadecimal characters")
    if checked_out_sha != requested_sha:
        raise DispatchValidationError("release_sha must equal the workflow commit")


def validate_adoption_input(*, initial_adoption: bool, legacy_sha: str) -> None:
    if initial_adoption:
        if SHA_RE.fullmatch(legacy_sha) is None:
            raise DispatchValidationError("initial adoption requires the exact legacy SHA")
    elif legacy_sha:
        raise DispatchValidationError("legacy SHA is permitted only for initial adoption")


def validate_ref_response(*, expected_sha: str, response: dict[str, Any]) -> None:
    if SHA_RE.fullmatch(expected_sha) is None:
        raise DispatchValidationError("expected SHA is invalid")
    if not isinstance(response, dict) or response.get("ref") != MAIN_REF:
        raise DispatchValidationError("GitHub main ref response is invalid")
    target = response.get("object")
    if not isinstance(target, dict) or target.get("type") != "commit" or target.get("sha") != expected_sha:
        raise DispatchValidationError("main moved after workflow dispatch")


def validate_migration_class(value: str, *, routine: bool = True) -> None:
    allowed = ROUTINE_MIGRATION_CLASSES if routine else ALL_MIGRATION_CLASSES
    if value not in allowed:
        if value == "data-or-non-compatible" and routine:
            raise DispatchValidationError("data-or-non-compatible requires the maintenance deployment procedure")
        raise DispatchValidationError("unknown migration class")


def validate_ssh_contract(*, host: str, port: str, user: str, marker: str, known_hosts: Path) -> None:
    if HOST_RE.fullmatch(host) is None or ".." in host:
        raise DispatchValidationError("production SSH host is invalid")
    try:
        parsed_port = int(port)
    except ValueError as exc:
        raise DispatchValidationError("production SSH port is invalid") from exc
    if not 1 <= parsed_port <= 65535 or str(parsed_port) != port:
        raise DispatchValidationError("production SSH port is invalid")
    if USER_RE.fullmatch(user) is None:
        raise DispatchValidationError("production SSH user is invalid")
    if MARKER_RE.fullmatch(marker) is None:
        raise DispatchValidationError("production target marker is invalid")
    try:
        value = known_hosts.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DispatchValidationError("pinned known_hosts file cannot be read") from exc
    lines = [line for line in value.splitlines() if line and not line.startswith("#")]
    if len(lines) != 1 or len(lines[0]) > 8192 or "\x00" in lines[0]:
        raise DispatchValidationError("exactly one bounded production host key must be pinned")
    fields = lines[0].split()
    if len(fields) < 3 or not fields[1].startswith("ssh-"):
        raise DispatchValidationError("pinned production host key is malformed")


def validate_status(*, expected_marker: str, response: dict[str, Any]) -> None:
    required = {
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
    if not isinstance(response, dict) or set(response) != required:
        raise DispatchValidationError("server status response has invalid fields")
    if response["target_marker"] != expected_marker:
        raise DispatchValidationError("production target marker mismatch")
    if response["state"] not in {
        "receiving",
        "verified",
        "prepared",
        "migrating",
        "activating",
        "active",
        "rolled_back",
        "failed",
        "recovery_required",
    }:
        raise DispatchValidationError("server operation state is invalid")
    if SHA_RE.fullmatch(str(response["release_sha"])) is None:
        raise DispatchValidationError("server release SHA is invalid")
    if SHA_RE.fullmatch(str(response["workflow_sha"])) is None:
        raise DispatchValidationError("server workflow SHA is invalid")
    if DIGEST_RE.fullmatch(str(response["artifact_digest"])) is None:
        raise DispatchValidationError("server artifact digest is invalid")
    if NUMERIC_RE.fullmatch(str(response["run_id"])) is None or NUMERIC_RE.fullmatch(
        str(response["deployment_id"]),
    ) is None:
        raise DispatchValidationError("server operation identity is invalid")


def validate_rollback_target(*, expected_marker: str, response: dict[str, Any]) -> dict[str, str]:
    required = {"ok", "checks", "active_release", "rollback_candidate", "adoption"}
    if (
        not isinstance(response, dict)
        or set(response) != required
        or response["ok"] is not True
        or response["adoption"] is not None
    ):
        raise DispatchValidationError("rollback preflight response has invalid fields")
    checks = response["checks"]
    if not isinstance(checks, dict) or checks.get("marker") != expected_marker:
        raise DispatchValidationError("production target marker mismatch")
    active = response["active_release"]
    candidate = response["rollback_candidate"]
    release_fields = {"artifact_digest", "migration_class", "release_sha", "rollback_eligible", "state"}
    if (
        not isinstance(active, dict)
        or not isinstance(candidate, dict)
        or set(active) != release_fields
        or set(candidate) != release_fields
    ):
        raise DispatchValidationError("rollback release evidence has invalid fields")
    if candidate["rollback_eligible"] is not True:
        raise DispatchValidationError("immediate previous release is not rollback eligible")
    if SHA_RE.fullmatch(str(active["release_sha"])) is None or SHA_RE.fullmatch(str(candidate["release_sha"])) is None:
        raise DispatchValidationError("rollback target SHA is invalid")
    if active["release_sha"] == candidate["release_sha"]:
        raise DispatchValidationError("rollback target must differ from the active release")
    if DIGEST_RE.fullmatch(str(candidate["artifact_digest"])) is None:
        raise DispatchValidationError("rollback target digest is invalid")
    return {"rollback_sha": candidate["release_sha"], "rollback_digest": candidate["artifact_digest"]}


def validate_preflight(
    *,
    expected_marker: str,
    expected_repository_id: str,
    expected_active_sha: str,
    expected_active_digest: str,
    response: dict[str, Any],
    expected_legacy_sha: str = "",
    initial_adoption: bool = False,
) -> None:
    required = {"ok", "checks", "active_release", "rollback_candidate", "adoption"}
    if not isinstance(response, dict) or set(response) != required or response["ok"] is not True:
        raise DispatchValidationError("production preflight did not pass")
    checks = response["checks"]
    required_checks = {
        "authority_integrity",
        "environment_external",
        "free_space",
        "marker",
        "media_external",
        "operations_resolved",
        "release_root",
        "repository_id",
        "service",
    }
    if not isinstance(checks, dict) or set(checks) != required_checks:
        raise DispatchValidationError("production preflight checks have invalid fields")
    safety_checks = (
        "authority_integrity",
        "environment_external",
        "free_space",
        "media_external",
        "operations_resolved",
        "release_root",
    )
    if any(checks[field] is not True for field in safety_checks):
        raise DispatchValidationError("production preflight safety check failed")
    if checks["marker"] != expected_marker or str(checks["repository_id"]) != expected_repository_id:
        raise DispatchValidationError("production preflight identity mismatch")
    active = response["active_release"]
    if initial_adoption:
        adoption = response["adoption"]
        adoption_fields = {
            "authorized_at",
            "legacy_sha",
            "repository",
            "state",
            "state_fingerprint",
            "target_marker",
        }
        if active is not None:
            raise DispatchValidationError("initial adoption requires no managed active release")
        if (
            not isinstance(adoption, dict)
            or set(adoption) != adoption_fields
            or adoption.get("state") != "authorized"
            or adoption.get("target_marker") != expected_marker
            or adoption.get("legacy_sha") != expected_legacy_sha
            or SHA_RE.fullmatch(str(adoption.get("legacy_sha", ""))) is None
            or DIGEST_RE.fullmatch(str(adoption.get("state_fingerprint", ""))) is None
        ):
            raise DispatchValidationError("initial adoption evidence is invalid")
        return
    if not isinstance(active, dict):
        raise DispatchValidationError("production active release is missing")
    if active.get("release_sha") != expected_active_sha or active.get("artifact_digest") != expected_active_digest:
        raise DispatchValidationError("production active release changed after disclosure")


def validate_health(response: dict[str, Any], *, now: datetime | None = None) -> dict[str, str]:
    required = {
        "schema_version",
        "status",
        "process_commit_sha",
        "artifact_sha256",
        "state_fingerprint",
        "recorded_at",
    }
    if not isinstance(response, dict) or set(response) != required:
        raise DispatchValidationError("public release state has invalid fields")
    if response["schema_version"] != 1 or response["status"] != "ok":
        raise DispatchValidationError("public release state is unavailable")
    if SHA_RE.fullmatch(str(response["process_commit_sha"])) is None:
        raise DispatchValidationError("public release SHA is invalid")
    for field in ("artifact_sha256", "state_fingerprint"):
        if DIGEST_RE.fullmatch(str(response[field])) is None:
            raise DispatchValidationError(f"public release {field} is invalid")
    try:
        recorded_at = datetime.strptime(str(response["recorded_at"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise DispatchValidationError("public release timestamp is invalid") from exc
    current = now or datetime.now(tz=UTC)
    if (current - recorded_at).total_seconds() < -60:
        raise DispatchValidationError("public release timestamp is in the future")
    return {
        "active_sha": response["process_commit_sha"],
        "active_digest": response["artifact_sha256"],
        "state_fingerprint": response["state_fingerprint"],
        "recorded_at": response["recorded_at"],
    }


def build_migration_disclosure(
    *, repository: Path, active_sha: str, target_sha: str, registry_path: Path, declared_class: str,
) -> dict[str, Any]:
    if SHA_RE.fullmatch(active_sha) is None or SHA_RE.fullmatch(target_sha) is None:
        raise DispatchValidationError("migration disclosure SHA is invalid")
    validate_migration_class(declared_class)
    try:
        changed = subprocess.run(
            ["git", "diff", "--name-status", "--find-renames=0", f"{active_sha}..{target_sha}", "--", "inspinia"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except subprocess.CalledProcessError as exc:
        raise DispatchValidationError("active release is not available for migration disclosure") from exc
    registry = load_registry(registry_path)
    migrations: list[dict[str, str]] = []
    for line in changed:
        status, separator, path = line.partition("\t")
        match = MIGRATION_PATH_RE.fullmatch(path)
        if not match or path.endswith("/__init__.py"):
            continue
        if status != "A" or not separator:
            raise DispatchValidationError("existing migration files must not be changed or deleted")
        migration_id = f"{match.group(1)}.{match.group(2)}"
        entry = registry.get(migration_id)
        if entry is None:
            raise DispatchValidationError(f"migration is not classified: {migration_id}")
        migrations.append({"migration": migration_id, "classification": str(entry["classification"])})
    derived = "none"
    if any(item["classification"] == "data-or-non-compatible" for item in migrations):
        derived = "data-or-non-compatible"
    elif migrations:
        derived = "backward-compatible-schema"
    if derived != declared_class:
        raise DispatchValidationError("declared migration class does not match the reviewed registry")
    return {
        "format_version": 1,
        "active_sha": active_sha,
        "target_sha": target_sha,
        "classification": derived,
        "migrations": migrations,
    }


def _json_file(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 1024 * 1024:
        raise DispatchValidationError("JSON evidence is too large")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DispatchValidationError("JSON evidence is malformed") from exc
    if not isinstance(value, dict):
        raise DispatchValidationError("JSON evidence must be an object")
    return value


def _operation_from_args(args: argparse.Namespace) -> OperationEnvelope:
    token = args.oidc_token
    if token is None:
        token = os.environ.get("ASTERPROOF_OIDC_TOKEN", "")
    return OperationEnvelope.from_dict(
        {
            "operation": args.operation,
            "run_id": args.run_id,
            "deployment_id": args.deployment_id,
            "workflow_sha": args.workflow_sha,
            "release_sha": args.release_sha,
            "artifact_digest": args.artifact_digest,
            "target_marker": args.target_marker,
            "migration_class": args.migration_class,
            "oidc_token": token,
        },
    )


def _add_envelope_arguments(parser: argparse.ArgumentParser, *, token: bool) -> None:
    parser.add_argument("--operation", required=True, choices=("deploy", "rollback", "migration-audit"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument("--target-marker", required=True)
    parser.add_argument("--migration-class", required=True, choices=sorted(ALL_MIGRATION_CLASSES))
    if token:
        parser.add_argument("--oidc-token")
    else:
        parser.set_defaults(oidc_token="audience-placeholder")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    dispatch = subparsers.add_parser("dispatch")
    dispatch.add_argument("--event", required=True)
    dispatch.add_argument("--ref", required=True)
    dispatch.add_argument("--checked-out-sha", required=True)
    dispatch.add_argument("--release-sha", required=True)
    dispatch.add_argument("--migration-class", required=True)
    dispatch.add_argument("--initial-adoption", action="store_true")
    dispatch.add_argument("--initial-legacy-sha", default="")

    main_ref = subparsers.add_parser("main-ref")
    main_ref.add_argument("--expected-sha", required=True)
    main_ref.add_argument("--response", type=Path, required=True)

    ssh = subparsers.add_parser("ssh-contract")
    ssh.add_argument("--host", required=True)
    ssh.add_argument("--port", required=True)
    ssh.add_argument("--user", required=True)
    ssh.add_argument("--target-marker", required=True)
    ssh.add_argument("--known-hosts", type=Path, required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--target-marker", required=True)
    status.add_argument("--response", type=Path, required=True)

    rollback_target = subparsers.add_parser("rollback-target")
    rollback_target.add_argument("--target-marker", required=True)
    rollback_target.add_argument("--response", type=Path, required=True)
    rollback_target.add_argument("--output", type=Path, required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--target-marker", required=True)
    preflight.add_argument("--repository-id", required=True)
    preflight.add_argument("--active-sha", required=True)
    preflight.add_argument("--active-digest", required=True)
    preflight.add_argument("--initial-adoption", action="store_true")
    preflight.add_argument("--expected-legacy-sha", default="")
    preflight.add_argument("--response", type=Path, required=True)

    health = subparsers.add_parser("health")
    health.add_argument("--response", type=Path, required=True)
    health.add_argument("--output", type=Path)

    disclosure = subparsers.add_parser("migration-disclosure")
    disclosure.add_argument("--repository", type=Path, default=Path.cwd())
    disclosure.add_argument("--active-sha", required=True)
    disclosure.add_argument("--target-sha", required=True)
    disclosure.add_argument("--registry", type=Path, required=True)
    disclosure.add_argument("--declared-class", required=True)
    disclosure.add_argument("--output", type=Path, required=True)

    audience = subparsers.add_parser("audience")
    _add_envelope_arguments(audience, token=False)

    frame = subparsers.add_parser("frame")
    _add_envelope_arguments(frame, token=True)
    frame.add_argument("--artifact-size", type=int)

    status_frame = subparsers.add_parser("status-frame")
    status_frame.add_argument("--run-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "dispatch":
        validate_current_main(
            event=args.event,
            ref=args.ref,
            checked_out_sha=args.checked_out_sha,
            requested_sha=args.release_sha,
        )
        validate_migration_class(args.migration_class)
        validate_adoption_input(
            initial_adoption=args.initial_adoption,
            legacy_sha=args.initial_legacy_sha,
        )
    elif args.command == "main-ref":
        validate_ref_response(expected_sha=args.expected_sha, response=_json_file(args.response))
    elif args.command == "ssh-contract":
        validate_ssh_contract(
            host=args.host,
            port=args.port,
            user=args.user,
            marker=args.target_marker,
            known_hosts=args.known_hosts,
        )
    elif args.command == "status":
        validate_status(expected_marker=args.target_marker, response=_json_file(args.response))
    elif args.command == "rollback-target":
        value = validate_rollback_target(
            expected_marker=args.target_marker,
            response=_json_file(args.response),
        )
        args.output.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    elif args.command == "preflight":
        validate_preflight(
            expected_marker=args.target_marker,
            expected_repository_id=args.repository_id,
            expected_active_sha=args.active_sha,
            expected_active_digest=args.active_digest,
            expected_legacy_sha=args.expected_legacy_sha,
            response=_json_file(args.response),
            initial_adoption=args.initial_adoption,
        )
    elif args.command == "health":
        evidence = validate_health(_json_file(args.response))
        serialized = json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n"
        if args.output is None:
            sys.stdout.write(serialized)
        else:
            args.output.write_text(serialized, encoding="utf-8")
    elif args.command == "migration-disclosure":
        disclosure = build_migration_disclosure(
            repository=args.repository,
            active_sha=args.active_sha,
            target_sha=args.target_sha,
            registry_path=args.registry,
            declared_class=args.declared_class,
        )
        args.output.write_text(json.dumps(disclosure, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    elif args.command == "audience":
        envelope = _operation_from_args(args)
        print(envelope_audience(envelope.public_dict()))
    elif args.command == "frame":
        envelope = _operation_from_args(args)
        value: dict[str, object] = {**envelope.public_dict(), "oidc_token": envelope.oidc_token}
        if args.artifact_size is not None:
            if args.operation != "deploy" or args.artifact_size <= 0:
                raise DispatchValidationError("artifact_size is invalid for this request")
            value["artifact_size"] = args.artifact_size
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        sys.stdout.buffer.write(f"{len(payload)}\n".encode() + payload)
    elif args.command == "status-frame":
        if NUMERIC_RE.fullmatch(args.run_id) is None:
            raise DispatchValidationError("status run_id is invalid")
        payload = json.dumps({"run_id": args.run_id}, separators=(",", ":")).encode()
        sys.stdout.buffer.write(f"{len(payload)}\n".encode() + payload)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DispatchValidationError as error:
        print(f"deployment dispatch rejected: {error}", file=sys.stderr)
        raise SystemExit(2) from error
