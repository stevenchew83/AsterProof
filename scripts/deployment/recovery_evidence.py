"""Validate read-only evidence after separately authorized operator recovery."""

# ruff: noqa: EM101, PLR0913, TRY003
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from scripts.deployment.protocol import DIGEST_RE
from scripts.deployment.protocol import NUMERIC_RE
from scripts.deployment.protocol import SHA_RE
from scripts.deployment.release_manifest import sha256_file
from scripts.deployment.release_state import read_json
from scripts.deployment.validate_dispatch import validate_health
from scripts.deployment.validate_dispatch import validate_preflight
from scripts.deployment.validate_dispatch import validate_status


def validate_artifact(
    *,
    archive: Path,
    envelope: dict[str, Any],
    run: dict[str, Any],
    artifact: dict[str, Any],
    repository: str,
    repository_id: str,
    release_sha: str,
    digest: str,
    run_id: str,
    artifact_id: str,
) -> None:
    if not SHA_RE.fullmatch(release_sha) or not DIGEST_RE.fullmatch(digest):
        raise ValueError("invalid recovery artifact identity")
    if not NUMERIC_RE.fullmatch(run_id) or not NUMERIC_RE.fullmatch(artifact_id):
        raise ValueError("invalid recovery run or artifact ID")
    if (
        str(run.get("id")) != run_id
        or run.get("head_sha") != release_sha
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or run.get("path") != ".github/workflows/production-deploy.yml"
        or run.get("status") != "completed"
        or run.get("repository", {}).get("full_name") != repository
        or str(artifact.get("id")) != artifact_id
        or artifact.get("expired") is not False
        or str(artifact.get("workflow_run", {}).get("id")) != run_id
        or artifact.get("workflow_run", {}).get("head_sha") != release_sha
        or str(artifact.get("workflow_run", {}).get("repository_id")) != repository_id
        or artifact.get("name") != f"production-release-{release_sha}"
        or envelope.get("release_sha") != release_sha
        or envelope.get("repository") != repository
        or envelope.get("repository_id") != repository_id
        or envelope.get("run_id") != run_id
        or envelope.get("archive_sha256") != digest
        or envelope.get("archive_size") != archive.stat().st_size
        or sha256_file(archive) != digest
    ):
        raise ValueError("original deployment artifact evidence does not match")


def validate_reconciliation(
    *,
    health: dict[str, Any],
    preflight: dict[str, Any],
    status: dict[str, Any],
    marker: str,
    repository_id: str,
    release_sha: str,
    digest: str,
    fingerprint: str,
    run_id: str,
) -> None:
    if not DIGEST_RE.fullmatch(fingerprint):
        raise ValueError("invalid recovery state fingerprint")
    observed = validate_health(health)
    if (
        observed["active_sha"] != release_sha
        or observed["active_digest"] != digest
        or health["state_fingerprint"] != fingerprint
    ):
        raise ValueError("public health differs from the recovered artifact or state")
    validate_preflight(
        expected_marker=marker,
        expected_repository_id=repository_id,
        expected_active_sha=release_sha,
        expected_active_digest=digest,
        response=preflight,
    )
    active = preflight["active_release"]
    if active.get("state") != "active" or active.get("migration_class") != "none" or preflight["adoption"] is not None:
        raise ValueError("recovered release or adoption state is incomplete")
    validate_status(expected_marker=marker, response=status)
    if (
        status["state"] != "active"
        or status["operation"] != "deploy"
        or status["migration_class"] != "none"
        or status["release_sha"] != release_sha
        or status["workflow_sha"] != release_sha
        or status["artifact_digest"] != digest
        or status["run_id"] != run_id
        or status["deployment_id"] != run_id
    ):
        raise ValueError("original deployment operation has not been reconciled")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("artifact", "reconciliation"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--fingerprint", required=True)
    args = parser.parse_args()
    if args.action == "artifact":
        validate_artifact(
            archive=args.directory / "asterproof-release.tar",
            envelope=read_json(args.directory / "release-envelope.json"),
            run=read_json(args.directory / "original-run.json"),
            artifact=read_json(args.directory / "original-artifact.json"),
            repository=args.repository,
            repository_id=args.repository_id,
            release_sha=args.release_sha,
            digest=args.digest,
            run_id=args.run_id,
            artifact_id=args.artifact_id,
        )
    else:
        validate_reconciliation(
            health=read_json(args.directory / "health.json"),
            preflight=read_json(args.directory / "preflight.json"),
            status=read_json(args.directory / "status.json"),
            marker=args.marker,
            repository_id=args.repository_id,
            release_sha=args.release_sha,
            digest=args.digest,
            fingerprint=args.fingerprint,
            run_id=args.run_id,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
