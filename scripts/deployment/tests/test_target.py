# ruff: noqa: S108, TC003
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.deployment.target import TargetContract
from scripts.deployment.target import TargetContractError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _contract(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "format_version": 1,
        "marker": "asterproof-production",
        "repository": "owner/AsterProof",
        "repository_id": "123",
        "deploy_workflow_ref": "owner/AsterProof/.github/workflows/production-deploy.yml@refs/heads/main",
        "rollback_workflow_ref": "owner/AsterProof/.github/workflows/production-rollback.yml@refs/heads/main",
        "release_root": "/srv/asterproof",
        "shared_root": "/var/lib/asterproof",
        "environment_file": "/var/lib/asterproof/environment",
        "media_root": "/var/lib/asterproof/media",
        "service": "asterproof.service",
        "app_user": "asterproof",
        "build_user": "asterproof_build",
        "deploy_user": "asterproof_deploy",
        "python_executable": "/usr/bin/python3.12",
        "python_abi": "cp312",
        "proxy_service": "nginx.service",
        "scheduler_service": "asterproof-catalog.service",
        "target_platform": "x86_64-manylinux_2_28",
        "tex_executable": "/usr/bin/latexmk",
        "health_url": "https://example.com/healthz/",
        "static_mode": "whitenoise",
        "minimum_free_bytes": 2_147_483_648,
    }
    value.update(overrides)
    return value


def test_target_contract_derives_bounded_release_paths() -> None:
    contract = TargetContract.from_dict(_contract())

    assert contract.releases_dir == Path("/srv/asterproof/releases")
    assert contract.incoming_dir == Path("/srv/asterproof/incoming")


def test_checked_in_production_target_is_valid() -> None:
    contract = TargetContract.load(REPOSITORY_ROOT / "deployment/production-target.json")

    assert contract.repository == "stevenchew83/AsterProof"
    assert contract.repository_id == "1165803960"
    assert contract.marker == "asterproof-production"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("media_root", "/srv/asterproof/media"),
        ("environment_file", "/tmp/environment"),
        ("shared_root", "/srv/asterproof/shared"),
        ("service", "gunicorn.service;reboot"),
        ("deploy_workflow_ref", "owner/AsterProof/.github/workflows/other.yml@refs/heads/main"),
        ("health_url", "http://example.com/healthz/"),
        ("minimum_free_bytes", 1),
    ],
)
def test_target_contract_rejects_unsafe_boundaries(field: str, value: object) -> None:
    with pytest.raises(TargetContractError):
        TargetContract.from_dict(_contract(**{field: value}))
