from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from scripts.deployment.recovery_evidence import validate_artifact
from scripts.deployment.recovery_evidence import validate_reconciliation
from scripts.deployment.validate_dispatch import DispatchValidationError

SHA = "a" * 40
DIGEST = "b" * 64
FINGERPRINT = "c" * 64
ROOT = Path(__file__).resolve().parents[3]


def artifact_arguments(tmp_path):
    archive = tmp_path / "archive.tar"
    archive.write_bytes(b"original artifact")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return {
        "archive": archive,
        "envelope": {
            "archive_sha256": digest,
            "archive_size": archive.stat().st_size,
            "release_sha": SHA,
            "repository": "owner/AsterProof",
            "repository_id": "99",
            "run_id": "123",
        },
        "run": {
            "id": 123,
            "head_sha": SHA,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "path": ".github/workflows/production-deploy.yml",
            "status": "completed",
            "repository": {"full_name": "owner/AsterProof"},
        },
        "artifact": {
            "id": 456,
            "expired": False,
            "workflow_run": {"id": 123, "head_sha": SHA, "repository_id": 99},
            "name": f"production-release-{SHA}",
        },
        "repository": "owner/AsterProof",
        "repository_id": "99",
        "release_sha": SHA,
        "digest": digest,
        "run_id": "123",
        "artifact_id": "456",
    }


def test_original_artifact_must_match_run_repository_and_bytes(tmp_path):
    arguments = artifact_arguments(tmp_path)
    validate_artifact(**arguments)
    for field, key, value in (
        ("run", "head_sha", "d" * 40),
        ("run", "head_branch", "topic"),
        ("run", "event", "pull_request"),
        ("run", "path", ".github/workflows/other.yml"),
        ("run", "repository", {"full_name": "other/AsterProof"}),
        ("artifact", "workflow_run", {"id": 999, "head_sha": SHA}),
        ("artifact", "expired", True),
        ("envelope", "archive_size", 1),
    ):
        invalid = copy.deepcopy(arguments)
        invalid[field][key] = value
        with pytest.raises(ValueError, match="does not match"):
            validate_artifact(**invalid)
    arguments["archive"].write_bytes(b"modified artifact")
    with pytest.raises(ValueError, match="does not match"):
        validate_artifact(**arguments)


def reconciliation_arguments():
    return {
        "health": {
            "schema_version": 1,
            "status": "ok",
            "process_commit_sha": SHA,
            "artifact_sha256": DIGEST,
            "state_fingerprint": FINGERPRINT,
            "recorded_at": "2026-01-01T00:00:00Z",
        },
        "preflight": {
            "ok": True,
            "adoption": None,
            "rollback_candidate": None,
            "checks": {
                "authority_integrity": True,
                "environment_external": True,
                "free_space": True,
                "marker": "asterproof-prod",
                "media_external": True,
                "operations_resolved": True,
                "release_root": True,
                "repository_id": "99",
                "service": "asterproof.service",
            },
            "active_release": {
                "release_sha": SHA,
                "artifact_digest": DIGEST,
                "state": "active",
                "migration_class": "none",
                "rollback_eligible": False,
            },
        },
        "status": {
            "artifact_digest": DIGEST,
            "deployment_id": "123",
            "error_code": "operator_recovered",
            "migration_class": "none",
            "operation": "deploy",
            "release_sha": SHA,
            "run_id": "123",
            "state": "active",
            "target_marker": "asterproof-prod",
            "updated_at": "2026-01-01T00:00:00Z",
            "workflow_sha": SHA,
        },
        "marker": "asterproof-prod",
        "repository_id": "99",
        "release_sha": SHA,
        "digest": DIGEST,
        "fingerprint": FINGERPRINT,
        "run_id": "123",
    }


def test_reconciliation_allows_conservative_nonrollback_release_record():
    validate_reconciliation(**reconciliation_arguments())


@pytest.mark.parametrize(
    ("field", "key", "value"),
    [
        ("health", "artifact_sha256", "d" * 64),
        ("health", "state_fingerprint", "d" * 64),
        ("status", "state", "recovery_required"),
        ("status", "run_id", "999"),
        ("status", "operation", "rollback"),
        ("status", "workflow_sha", "d" * 40),
        ("preflight", "adoption", {"state": "authorized"}),
        ("preflight", "active_release", {"release_sha": SHA, "artifact_digest": DIGEST, "state": "prepared"}),
    ],
)
def test_reconciliation_rejects_conflicting_or_incomplete_evidence(field, key, value):
    arguments = reconciliation_arguments()
    arguments[field][key] = value
    with pytest.raises((ValueError, DispatchValidationError)):
        validate_reconciliation(**arguments)


def test_recovery_workflow_has_no_production_mutation_or_oidc_capability():
    source = (ROOT / ".github/workflows/production-reconcile.yml").read_text()
    assert "environment:\n      name: production" in source
    assert "group: asterproof-production" in source
    assert "cancel-in-progress: false" in source
    assert "queue: max" in source
    assert "gh attestation verify" in source
    assert source.index("- name: Revalidate current main after approval") < source.index("${{ secrets.")
    assert "StrictHostKeyChecking yes" in source
    assert "'preflight v1'" in source
    assert "'status v1'" in source
    for forbidden in ("id-token:", "receive v1", "submit v1", "systemctl", "ACTIONS_ID_TOKEN_REQUEST"):
        assert forbidden not in source
