# ruff: noqa: S603, S607
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC
from datetime import datetime
from pathlib import Path

import pytest

from scripts.deployment.validate_dispatch import DispatchValidationError
from scripts.deployment.validate_dispatch import build_migration_disclosure
from scripts.deployment.validate_dispatch import validate_adoption_input
from scripts.deployment.validate_dispatch import validate_current_main
from scripts.deployment.validate_dispatch import validate_health
from scripts.deployment.validate_dispatch import validate_preflight
from scripts.deployment.validate_dispatch import validate_ref_response
from scripts.deployment.validate_dispatch import validate_rollback_target
from scripts.deployment.validate_dispatch import validate_ssh_contract
from scripts.deployment.validate_dispatch import validate_status

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = (
    ROOT / ".github/workflows/production-deploy.yml",
    ROOT / ".github/workflows/production-rollback.yml",
)
SHA = "a" * 40
DIGEST = "b" * 64
ARTIFACT_SIZE = 4096


def test_dispatch_requires_manual_current_main_exact_sha() -> None:
    validate_current_main(event="workflow_dispatch", ref="refs/heads/main", checked_out_sha=SHA, requested_sha=SHA)
    invalid = (
        {"event": "push", "ref": "refs/heads/main", "checked_out_sha": SHA, "requested_sha": SHA},
        {"event": "workflow_dispatch", "ref": "refs/heads/topic", "checked_out_sha": SHA, "requested_sha": SHA},
        {"event": "workflow_dispatch", "ref": "refs/heads/main", "checked_out_sha": SHA, "requested_sha": "A" * 40},
        {"event": "workflow_dispatch", "ref": "refs/heads/main", "checked_out_sha": SHA, "requested_sha": "c" * 40},
    )
    for request in invalid:
        with pytest.raises(DispatchValidationError):
            validate_current_main(**request)


def test_post_approval_main_response_must_still_match() -> None:
    response = {"ref": "refs/heads/main", "object": {"type": "commit", "sha": SHA}}
    validate_ref_response(expected_sha=SHA, response=response)
    response["object"]["sha"] = "c" * 40
    with pytest.raises(DispatchValidationError, match="main moved"):
        validate_ref_response(expected_sha=SHA, response=response)


def test_initial_adoption_requires_exact_legacy_sha_and_routine_rejects_it() -> None:
    validate_adoption_input(initial_adoption=True, legacy_sha="c" * 40)
    with pytest.raises(DispatchValidationError, match="exact legacy SHA"):
        validate_adoption_input(initial_adoption=True, legacy_sha="")
    with pytest.raises(DispatchValidationError, match="only for initial adoption"):
        validate_adoption_input(initial_adoption=False, legacy_sha="c" * 40)


def test_health_evidence_is_exact_and_records_activation_time() -> None:
    now = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
    payload = {
        "schema_version": 1,
        "status": "ok",
        "process_commit_sha": SHA,
        "artifact_sha256": DIGEST,
        "state_fingerprint": "c" * 64,
        "recorded_at": "2026-09-01T00:59:00Z",
    }
    assert validate_health(payload, now=now)["active_sha"] == SHA
    payload["recorded_at"] = "2026-08-30T00:00:00Z"
    assert validate_health(payload, now=now)["recorded_at"] == "2026-08-30T00:00:00Z"
    payload["recorded_at"] = "2026-09-01T01:02:00Z"
    with pytest.raises(DispatchValidationError, match="future"):
        validate_health(payload, now=now)


def test_ssh_contract_requires_one_pinned_host_key(tmp_path: Path) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("prod.example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest\n", encoding="utf-8")
    validate_ssh_contract(
        host="prod.example",
        port="22",
        user="asterproof_deploy",
        marker="asterproof-prod",
        known_hosts=known_hosts,
    )
    known_hosts.write_text(known_hosts.read_text() * 2, encoding="utf-8")
    with pytest.raises(DispatchValidationError, match="exactly one"):
        validate_ssh_contract(
            host="prod.example",
            port="22",
            user="asterproof_deploy",
            marker="asterproof-prod",
            known_hosts=known_hosts,
        )


def test_rollback_target_must_be_distinct_immediate_eligible_candidate() -> None:
    release = {
        "artifact_digest": DIGEST,
        "migration_class": "none",
        "release_sha": "c" * 40,
        "rollback_eligible": True,
        "state": "active",
    }
    response = {
        "adoption": None,
        "ok": True,
        "checks": {"marker": "asterproof-prod"},
        "active_release": {**release, "release_sha": SHA},
        "rollback_candidate": release,
    }
    assert validate_rollback_target(expected_marker="asterproof-prod", response=response) == {
        "rollback_sha": "c" * 40,
        "rollback_digest": DIGEST,
    }
    response["rollback_candidate"]["rollback_eligible"] = False
    with pytest.raises(DispatchValidationError, match="not rollback eligible"):
        validate_rollback_target(expected_marker="asterproof-prod", response=response)


def test_deploy_preflight_reconciles_public_active_release() -> None:
    response = {
        "adoption": None,
        "ok": True,
        "checks": {
            "authority_integrity": True,
            "environment_external": True,
            "free_space": True,
            "marker": "asterproof-prod",
            "media_external": True,
            "operations_resolved": True,
            "release_root": True,
            "repository_id": "12345",
            "service": "asterproof.service",
        },
        "active_release": {"release_sha": SHA, "artifact_digest": DIGEST},
        "rollback_candidate": None,
    }
    validate_preflight(
        expected_marker="asterproof-prod",
        expected_repository_id="12345",
        expected_active_sha=SHA,
        expected_active_digest=DIGEST,
        response=response,
    )
    response["active_release"]["release_sha"] = "c" * 40
    with pytest.raises(DispatchValidationError, match="changed after disclosure"):
        validate_preflight(
            expected_marker="asterproof-prod",
            expected_repository_id="12345",
            expected_active_sha=SHA,
            expected_active_digest=DIGEST,
            response=response,
        )


def test_initial_adoption_preflight_requires_authorized_server_record() -> None:
    response = {
        "adoption": {
            "authorized_at": "2026-09-01T00:00:00Z",
            "legacy_sha": "c" * 40,
            "repository": "owner/AsterProof",
            "state": "authorized",
            "state_fingerprint": "d" * 64,
            "target_marker": "asterproof-prod",
        },
        "ok": True,
        "checks": {
            "authority_integrity": True,
            "environment_external": True,
            "free_space": True,
            "marker": "asterproof-prod",
            "media_external": True,
            "operations_resolved": True,
            "release_root": True,
            "repository_id": "12345",
            "service": "asterproof.service",
        },
        "active_release": None,
        "rollback_candidate": None,
    }

    validate_preflight(
        expected_marker="asterproof-prod",
        expected_repository_id="12345",
        expected_active_sha="",
        expected_active_digest="",
        response=response,
        expected_legacy_sha="c" * 40,
        initial_adoption=True,
    )
    response["adoption"] = None
    with pytest.raises(DispatchValidationError, match="adoption evidence"):
        validate_preflight(
            expected_marker="asterproof-prod",
            expected_repository_id="12345",
            expected_active_sha="",
            expected_active_digest="",
            response=response,
            expected_legacy_sha="c" * 40,
            initial_adoption=True,
        )


def test_status_contract_includes_workflow_and_release_identity() -> None:
    response = {
        "artifact_digest": DIGEST,
        "deployment_id": "123",
        "error_code": None,
        "migration_class": "none",
        "operation": "rollback",
        "release_sha": "c" * 40,
        "run_id": "123",
        "state": "rolled_back",
        "target_marker": "asterproof-prod",
        "updated_at": "2026-09-01T00:00:00Z",
        "workflow_sha": SHA,
    }
    validate_status(expected_marker="asterproof-prod", response=response)
    response.pop("workflow_sha")
    with pytest.raises(DispatchValidationError, match="invalid fields"):
        validate_status(expected_marker="asterproof-prod", response=response)


def test_receive_frame_binds_workflow_sha_and_artifact_size() -> None:
    command = [
        sys.executable,
        "-m",
        "scripts.deployment.validate_dispatch",
        "frame",
        "--operation",
        "deploy",
        "--run-id",
        "123",
        "--deployment-id",
        "123",
        "--workflow-sha",
        SHA,
        "--release-sha",
        SHA,
        "--artifact-digest",
        DIGEST,
        "--target-marker",
        "asterproof-prod",
        "--migration-class",
        "none",
        "--artifact-size",
        str(ARTIFACT_SIZE),
    ]
    environment = {**os.environ, "ASTERPROOF_OIDC_TOKEN": "header.payload.signature"}
    framed = subprocess.run(command, cwd=ROOT, env=environment, check=True, capture_output=True).stdout
    length, payload = framed.split(b"\n", 1)
    assert int(length) == len(payload)
    value = json.loads(payload)
    assert value["workflow_sha"] == SHA
    assert value["artifact_size"] == ARTIFACT_SIZE


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=repository, check=True, capture_output=True, text=True,
    ).stdout.strip()


def test_migration_disclosure_is_registry_derived(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "tests@example.invalid")
    _git(repository, "config", "user.name", "Tests")
    (repository / "README").write_text("baseline\n")
    _git(repository, "add", "README")
    _git(repository, "commit", "-m", "baseline")
    active_sha = _git(repository, "rev-parse", "HEAD")
    migrations = repository / "inspinia/pages/migrations"
    migrations.mkdir(parents=True)
    (migrations / "0001_add_flag.py").write_text("# migration\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "migration")
    target_sha = _git(repository, "rev-parse", "HEAD")
    registry = tmp_path / "registry.yml"
    registry.write_text(
        json.dumps(
            {
                "format_version": 1,
                "baseline_sha": active_sha,
                "migrations": {
                    "pages.0001_add_flag": {
                        "classification": "backward-compatible-schema",
                        "recovery_required": False,
                        "code_rollback_permitted": True,
                        "data_preconditions": [],
                        "rationale": "Additive nullable state.",
                    },
                },
            },
        ),
    )
    result = build_migration_disclosure(
        repository=repository,
        active_sha=active_sha,
        target_sha=target_sha,
        registry_path=registry,
        declared_class="backward-compatible-schema",
    )
    assert result["classification"] == "backward-compatible-schema"
    with pytest.raises(DispatchValidationError, match="does not match"):
        build_migration_disclosure(
            repository=repository,
            active_sha=active_sha,
            target_sha=target_sha,
            registry_path=registry,
            declared_class="none",
        )


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_workflows_share_bounded_non_cancelling_concurrency(workflow: Path) -> None:
    text = workflow.read_text()
    assert "group: asterproof-production" in text
    assert "cancel-in-progress: false" in text
    assert "queue: max" in text
    assert "seq 1 300" in text


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_workflow_actions_are_pinned_to_full_commit_shas(workflow: Path) -> None:
    uses = re.findall(r"^\s*uses:\s*([^\s#]+)", workflow.read_text(), flags=re.MULTILINE)
    assert uses
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", value) for value in uses)


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_only_protected_job_receives_production_secrets(workflow: Path) -> None:
    text = workflow.read_text()
    assert text.count("\n    environment:\n      name: production\n") == 1
    environment_position = text.index("\n    environment:\n      name: production\n")
    for match in re.finditer(r"\$\{\{\s*secrets\.", text):
        assert match.start() > environment_position


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_workflow_uses_strict_transport_and_envelope_bound_oidc(workflow: Path) -> None:
    text = workflow.read_text()
    assert "ssh-keyscan" not in text
    assert "StrictHostKeyChecking yes" in text
    assert "ClearAllForwardings yes" in text
    assert '--target-marker "$TARGET_MARKER"' in text
    assert "scripts.deployment.validate_dispatch audience" in text
    assert "ACTIONS_ID_TOKEN_REQUEST_URL" in text
    assert "--oidc-token" not in text


def test_deploy_workflow_revalidates_main_before_any_ssh_secret_reference() -> None:
    text = WORKFLOWS[0].read_text()
    revalidation = text.index("- name: Revalidate current main after approval")
    first_secret = text.index("${{ secrets.")
    assert revalidation < first_secret
    assert "actions/attest-build-provenance@96278af6caaf10aea03fd8d33a09a777ca52d62f" in text
    assert "gh attestation verify" in text
    assert "migration-disclosure" in text


def test_initial_adoption_is_explicit_and_revalidated_after_environment_approval() -> None:
    text = WORKFLOWS[0].read_text()

    assert "initial_adoption:" in text
    assert "if: ${{ !inputs.initial_adoption }}" in text
    assert "initial_legacy_sha:" in text
    assert '--active-sha "$ACTIVE_SHA"' in text
    assert "adoption_arg=(--initial-adoption)" in text
    assert text.index("environment:\n      name: production") < text.index("adoption_arg=(--initial-adoption)")


def test_rollback_uses_current_trusted_client_and_server_selected_previous_release() -> None:
    text = WORKFLOWS[1].read_text()
    assert "ref: ${{ github.sha }}" in text
    assert "ROLLBACK_IMMEDIATE_PREVIOUS" in text
    assert "--operation rollback" in text
    assert "receive v1" not in text
    assert "immediate previous eligible release only" in text
