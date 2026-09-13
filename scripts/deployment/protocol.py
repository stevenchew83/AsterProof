# ruff: noqa: EM101, PLR2004, TRY003
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from typing import BinaryIO

PROTOCOL_VERSION = "v1"
COMMANDS = {"preflight", "receive", "submit", "status"}
OPERATIONS = {"deploy", "rollback", "migration-audit"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
NUMERIC_RE = re.compile(r"^[1-9][0-9]{0,19}$")
MARKER_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
MAX_FRAME_BYTES = 64 * 1024


class ProtocolError(ValueError):
    pass


def parse_command(value: str) -> str:
    parts = value.split(" ")
    if len(parts) != 2 or parts[0] not in COMMANDS or parts[1] != PROTOCOL_VERSION:
        raise ProtocolError("unknown deployment command")
    return parts[0]


def read_frame(stream: BinaryIO, *, maximum: int = MAX_FRAME_BYTES) -> dict[str, Any]:
    length_line = stream.readline(16)
    if not length_line.endswith(b"\n") or not re.fullmatch(rb"[0-9]{1,10}\n", length_line):
        raise ProtocolError("invalid frame length")
    length = int(length_line)
    if length <= 0 or length > maximum:
        raise ProtocolError("frame exceeds configured limit")
    payload = stream.read(length)
    if len(payload) != length:
        raise ProtocolError("incomplete frame")
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ProtocolError("duplicate frame field")
            value[key] = item
        return value

    try:
        value = json.loads(payload, object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid frame payload") from exc
    if not isinstance(value, dict):
        raise ProtocolError("frame payload must be an object")
    return value


def canonical_envelope(value: dict[str, Any]) -> bytes:
    excluded = {"oidc_token"}
    return json.dumps(
        {key: item for key, item in value.items() if key not in excluded},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def envelope_audience(value: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_envelope(value)).hexdigest()
    return f"urn:asterproof:production:{digest}"


@dataclass(frozen=True)
class OperationEnvelope:
    operation: str
    run_id: str
    deployment_id: str
    workflow_sha: str
    release_sha: str
    artifact_digest: str
    target_marker: str
    migration_class: str
    oidc_token: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OperationEnvelope:
        required = {
            "operation",
            "run_id",
            "deployment_id",
            "workflow_sha",
            "release_sha",
            "artifact_digest",
            "target_marker",
            "migration_class",
            "oidc_token",
        }
        if set(data) != required:
            raise ProtocolError("operation envelope fields do not match the protocol")
        values = cls(**data)
        values.validate()
        return values

    def validate(self) -> None:
        if self.operation not in OPERATIONS:
            raise ProtocolError("invalid operation")
        if not NUMERIC_RE.fullmatch(self.run_id) or not NUMERIC_RE.fullmatch(self.deployment_id):
            raise ProtocolError("invalid GitHub operation identity")
        if (
            not SHA_RE.fullmatch(self.workflow_sha)
            or not SHA_RE.fullmatch(self.release_sha)
            or not DIGEST_RE.fullmatch(self.artifact_digest)
        ):
            raise ProtocolError("invalid release identity")
        if self.operation in {"deploy", "migration-audit"} and self.workflow_sha != self.release_sha:
            raise ProtocolError("deploy authorization must match the release SHA")
        if not MARKER_RE.fullmatch(self.target_marker):
            raise ProtocolError("invalid target marker")
        if self.migration_class not in {"none", "backward-compatible-schema", "data-or-non-compatible"}:
            raise ProtocolError("invalid migration class")
        if (
            not self.oidc_token
            or not self.oidc_token.isascii()
            or len(self.oidc_token) > 16 * 1024
            or any(character.isspace() for character in self.oidc_token)
        ):
            raise ProtocolError("invalid OIDC token")

    def public_dict(self) -> dict[str, str]:
        return {
            "artifact_digest": self.artifact_digest,
            "deployment_id": self.deployment_id,
            "migration_class": self.migration_class,
            "operation": self.operation,
            "release_sha": self.release_sha,
            "run_id": self.run_id,
            "target_marker": self.target_marker,
            "workflow_sha": self.workflow_sha,
        }
