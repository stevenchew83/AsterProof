# ruff: noqa: C901, EM101, PLR0912, PLR2004, TRY003
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.deployment import RELEASE_FORMAT_VERSION

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ManifestError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ReleaseManifest:
    repository: str
    repository_id: str
    release_sha: str
    run_id: str
    built_at: str
    target_platform: str
    python_abi: str
    files: tuple[dict[str, Any], ...]
    format_version: int = RELEASE_FORMAT_VERSION
    solution_document_reader: int = 0
    solution_image_reader: int = 0

    def validate(self) -> None:
        if self.format_version != RELEASE_FORMAT_VERSION:
            raise ManifestError("unsupported release manifest version")
        if not REPOSITORY_RE.fullmatch(self.repository):
            raise ManifestError("invalid repository identity")
        if not self.repository_id.isdigit() or self.repository_id == "0":
            raise ManifestError("invalid repository id")
        if not SHA_RE.fullmatch(self.release_sha):
            raise ManifestError("invalid release sha")
        if not self.run_id.isdigit() or self.run_id == "0":
            raise ManifestError("invalid run id")
        if not self.built_at.endswith("Z"):
            raise ManifestError("built_at must be an UTC timestamp")
        if not self.target_platform or len(self.target_platform) > 64:
            raise ManifestError("invalid target platform")
        if not re.fullmatch(r"cp3[0-9]{2}", self.python_abi):
            raise ManifestError("invalid Python ABI")

        seen: set[str] = set()
        for item in self.files:
            path = item.get("path")
            digest = item.get("sha256")
            size = item.get("size")
            if not isinstance(path, str) or not path or path in seen:
                raise ManifestError("invalid or duplicate manifest path")
            if path.startswith("/") or "\\" in path or ".." in Path(path).parts:
                raise ManifestError("unsafe manifest path")
            if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
                raise ManifestError("invalid file digest")
            if not isinstance(size, int) or size < 0:
                raise ManifestError("invalid file size")
            seen.add(path)
        if type(self.solution_document_reader) is not int or self.solution_document_reader not in {0, 1}:
            raise ManifestError("invalid solution document reader capability")
        if self.solution_document_reader:
            from scripts.deployment.solution_document_compat import reader_sources_match

            if not reader_sources_match(self.files):
                raise ManifestError("solution document reader bytes do not match the reviewed capability")
        if type(self.solution_image_reader) is not int or self.solution_image_reader not in {0, 1}:
            raise ManifestError("invalid solution image reader capability")
        if self.solution_image_reader:
            from scripts.deployment.solution_image_compat import reader_sources_match as image_sources_match

            if not image_sources_match(self.files):
                raise ManifestError("solution image reader bytes do not match the reviewed capability")

    def to_json_bytes(self) -> bytes:
        self.validate()
        payload = {
            "built_at": self.built_at,
            "files": list(self.files),
            "format_version": self.format_version,
            "python_abi": self.python_abi,
            "release_sha": self.release_sha,
            "repository": self.repository,
            "repository_id": self.repository_id,
            "run_id": self.run_id,
            "target_platform": self.target_platform,
        }
        if self.solution_document_reader:
            payload["solution_document_reader"] = self.solution_document_reader
        if self.solution_image_reader:
            payload["solution_image_reader"] = self.solution_image_reader
        return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()

    @classmethod
    def from_bytes(cls, value: bytes) -> ReleaseManifest:
        if len(value) > 2 * 1024 * 1024:
            raise ManifestError("release manifest is too large")
        try:
            data = json.loads(value)
            manifest = cls(
                format_version=data["format_version"],
                repository=data["repository"],
                repository_id=str(data["repository_id"]),
                release_sha=data["release_sha"],
                run_id=str(data["run_id"]),
                built_at=data["built_at"],
                target_platform=data["target_platform"],
                python_abi=data["python_abi"],
                files=tuple(data["files"]),
                solution_document_reader=data.get("solution_document_reader", 0),
                solution_image_reader=data.get("solution_image_reader", 0),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ManifestError("malformed release manifest") from exc
        manifest.validate()
        return manifest
