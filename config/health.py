"""Minimal process-bound production health and release identity signal."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.http import JsonResponse

RUNTIME_RELEASE_STATE_FILENAME = "runtime-release-state.json"
RUNTIME_RELEASE_STATE_SCHEMA_VERSION = 1
MAX_RUNTIME_RELEASE_STATE_BYTES = 16 * 1024

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_EXPECTED_FIELDS = {
    "schema_version",
    "status",
    "process_commit_sha",
    "artifact_sha256",
    "state_fingerprint",
    "recorded_at",
}


@dataclass(frozen=True, slots=True)
class RuntimeReleaseState:
    schema_version: int
    status: str
    process_commit_sha: str
    artifact_sha256: str
    state_fingerprint: str
    recorded_at: str

    def as_payload(self) -> dict[str, str | int]:
        return asdict(self)


class InvalidRuntimeReleaseStateError(ValueError):
    """Raised when release state is absent, unsafe, or outside its fixed schema."""


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidRuntimeReleaseStateError
        result[key] = value
    return result


def _validate_payload(payload: Any) -> RuntimeReleaseState:
    if not isinstance(payload, dict) or set(payload) != _EXPECTED_FIELDS:
        raise InvalidRuntimeReleaseStateError

    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != RUNTIME_RELEASE_STATE_SCHEMA_VERSION
    ):
        raise InvalidRuntimeReleaseStateError
    if payload["status"] != "ok":
        raise InvalidRuntimeReleaseStateError

    string_fields = (
        "process_commit_sha",
        "artifact_sha256",
        "state_fingerprint",
        "recorded_at",
    )
    if any(type(payload[field]) is not str for field in string_fields):
        raise InvalidRuntimeReleaseStateError
    if not _SHA_PATTERN.fullmatch(payload["process_commit_sha"]):
        raise InvalidRuntimeReleaseStateError
    if not _DIGEST_PATTERN.fullmatch(payload["artifact_sha256"]):
        raise InvalidRuntimeReleaseStateError
    if not _DIGEST_PATTERN.fullmatch(payload["state_fingerprint"]):
        raise InvalidRuntimeReleaseStateError
    if not _UTC_TIMESTAMP_PATTERN.fullmatch(payload["recorded_at"]):
        raise InvalidRuntimeReleaseStateError
    try:
        datetime.fromisoformat(payload["recorded_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidRuntimeReleaseStateError from exc

    return RuntimeReleaseState(**payload)


def load_runtime_release_state(release_root: Path) -> RuntimeReleaseState:
    """Read one fixed state file without following a file-level symlink."""

    try:
        resolved_root = release_root.resolve(strict=True)
        state_path = resolved_root / RUNTIME_RELEASE_STATE_FILENAME
        is_symlink = state_path.is_symlink()
    except OSError as exc:
        raise InvalidRuntimeReleaseStateError from exc
    if is_symlink:
        raise InvalidRuntimeReleaseStateError

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(state_path, flags)
        try:
            file_stat = os.fstat(descriptor)
            chunks: list[bytes] = []
            remaining = MAX_RUNTIME_RELEASE_STATE_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise InvalidRuntimeReleaseStateError from exc

    raw_payload = b"".join(chunks)
    if not stat.S_ISREG(file_stat.st_mode):
        raise InvalidRuntimeReleaseStateError
    if not 0 < file_stat.st_size <= MAX_RUNTIME_RELEASE_STATE_BYTES:
        raise InvalidRuntimeReleaseStateError
    if len(raw_payload) > MAX_RUNTIME_RELEASE_STATE_BYTES:
        raise InvalidRuntimeReleaseStateError

    try:
        payload = json.loads(
            raw_payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_fields,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidRuntimeReleaseStateError from exc
    return _validate_payload(payload)


def _load_process_runtime_release_state() -> RuntimeReleaseState | None:
    try:
        # BASE_DIR is resolved once here so later changes to a mutable `current`
        # symlink cannot change the identity reported by an existing process.
        release_root = Path(settings.BASE_DIR).resolve(strict=True)
        return load_runtime_release_state(release_root)
    except InvalidRuntimeReleaseStateError:
        return None


PROCESS_RUNTIME_RELEASE_STATE = _load_process_runtime_release_state()


@transaction.non_atomic_requests
def healthz(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        response = JsonResponse({"status": "method_not_allowed"}, status=405)
        response["Allow"] = "GET"
    elif PROCESS_RUNTIME_RELEASE_STATE is None:
        response = JsonResponse({"status": "unavailable"}, status=503)
    else:
        response = JsonResponse(PROCESS_RUNTIME_RELEASE_STATE.as_payload())

    response["Cache-Control"] = "no-store"
    return response
