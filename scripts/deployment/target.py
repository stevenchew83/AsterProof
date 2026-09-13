# ruff: noqa: C901, EM101, EM102, PLR0912, PLR2004, TRY003
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TARGET_FORMAT_VERSION = 1
MARKER_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")


class TargetContractError(ValueError):
    pass


def _absolute(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/") or "\x00" in value:
        raise TargetContractError(f"{field} must be an absolute path")
    path = Path(value)
    if ".." in path.parts:
        raise TargetContractError(f"{field} cannot contain parent traversal")
    return path


@dataclass(frozen=True)
class TargetContract:
    marker: str
    repository: str
    repository_id: str
    deploy_workflow_ref: str
    rollback_workflow_ref: str
    release_root: Path
    shared_root: Path
    environment_file: Path
    media_root: Path
    service: str
    scheduler_service: str
    proxy_service: str
    app_user: str
    build_user: str
    deploy_user: str
    python_executable: Path
    tex_executable: Path
    python_abi: str
    target_platform: str
    health_url: str
    static_mode: str
    minimum_free_bytes: int
    format_version: int = TARGET_FORMAT_VERSION

    @property
    def releases_dir(self) -> Path:
        return self.release_root / "releases"

    @property
    def incoming_dir(self) -> Path:
        return self.release_root / "incoming"

    @property
    def build_dir(self) -> Path:
        return self.release_root / "build"

    @property
    def processing_dir(self) -> Path:
        return self.release_root / "processing"

    @property
    def registry_dir(self) -> Path:
        return self.release_root / "registry"

    def validate(self) -> None:
        if self.format_version != TARGET_FORMAT_VERSION:
            raise TargetContractError("unsupported target contract version")
        if not MARKER_RE.fullmatch(self.marker):
            raise TargetContractError("invalid target marker")
        if "/" not in self.repository or not self.repository_id.isdigit():
            raise TargetContractError("invalid repository identity")
        expected_deploy = f"{self.repository}/.github/workflows/production-deploy.yml@refs/heads/main"
        expected_rollback = f"{self.repository}/.github/workflows/production-rollback.yml@refs/heads/main"
        if self.deploy_workflow_ref != expected_deploy or self.rollback_workflow_ref != expected_rollback:
            raise TargetContractError("invalid authoritative workflow identity")
        services = (self.service, self.scheduler_service, self.proxy_service)
        if any(not SERVICE_RE.fullmatch(service) for service in services):
            raise TargetContractError("invalid service identity")
        for user in (self.app_user, self.build_user, self.deploy_user):
            if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
                raise TargetContractError("invalid service account")
        if len({self.app_user, self.build_user, self.deploy_user}) != 3:
            raise TargetContractError("deployment accounts must be distinct")
        if self.static_mode not in {"whitenoise", "nginx"}:
            raise TargetContractError("invalid static serving mode")
        if not self.health_url.startswith("https://"):
            raise TargetContractError("health URL must use HTTPS")
        if self.minimum_free_bytes < 512 * 1024 * 1024:
            raise TargetContractError("minimum free space is too small")
        if not re.fullmatch(r"cp3[0-9]{2}", self.python_abi):
            raise TargetContractError("invalid Python ABI")
        if not re.fullmatch(r"x86_64-manylinux_2_[0-9]{2}", self.target_platform):
            raise TargetContractError("invalid target platform")

        release = self.release_root.resolve(strict=False)
        shared = self.shared_root.resolve(strict=False)
        if release == shared or release in shared.parents or shared in release.parents:
            raise TargetContractError("release and shared roots must not overlap")
        for persistent in (self.environment_file, self.media_root):
            resolved = persistent.resolve(strict=False)
            if resolved == release or release in resolved.parents:
                raise TargetContractError("persistent state cannot live under the release root")
            if resolved != shared and shared not in resolved.parents:
                raise TargetContractError("persistent state must live under the shared root")
        if release == self.python_executable.resolve(strict=False) or release in self.python_executable.resolve(
            strict=False,
        ).parents:
            raise TargetContractError("authority Python cannot live under the release root")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetContract:
        try:
            contract = cls(
                format_version=int(data["format_version"]),
                marker=data["marker"],
                repository=data["repository"],
                repository_id=str(data["repository_id"]),
                deploy_workflow_ref=data["deploy_workflow_ref"],
                rollback_workflow_ref=data["rollback_workflow_ref"],
                release_root=_absolute(data["release_root"], "release_root"),
                shared_root=_absolute(data["shared_root"], "shared_root"),
                environment_file=_absolute(data["environment_file"], "environment_file"),
                media_root=_absolute(data["media_root"], "media_root"),
                service=data["service"],
                scheduler_service=data["scheduler_service"],
                proxy_service=data["proxy_service"],
                app_user=data["app_user"],
                build_user=data["build_user"],
                deploy_user=data["deploy_user"],
                python_executable=_absolute(data["python_executable"], "python_executable"),
                tex_executable=_absolute(data["tex_executable"], "tex_executable"),
                python_abi=data["python_abi"],
                target_platform=data["target_platform"],
                health_url=data["health_url"],
                static_mode=data["static_mode"],
                minimum_free_bytes=int(data["minimum_free_bytes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TargetContractError("malformed target contract") from exc
        contract.validate()
        return contract

    @classmethod
    def from_bytes(cls, content: bytes) -> TargetContract:
        if len(content) > 64 * 1024:
            raise TargetContractError("target contract is too large")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise TargetContractError("target contract cannot be read") from exc
        if not isinstance(data, dict):
            raise TargetContractError("target contract must be an object")
        return cls.from_dict(data)

    @classmethod
    def load(cls, path: Path) -> TargetContract:
        try:
            return cls.from_bytes(path.read_bytes())
        except OSError as exc:
            raise TargetContractError("target contract cannot be read") from exc
