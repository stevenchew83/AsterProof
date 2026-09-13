from __future__ import annotations

import io

import pytest

from scripts.deployment.protocol import OperationEnvelope
from scripts.deployment.protocol import ProtocolError
from scripts.deployment.protocol import envelope_audience
from scripts.deployment.protocol import parse_command
from scripts.deployment.protocol import read_frame


def _envelope(**overrides: str) -> dict[str, str]:
    value = {
        "operation": "deploy",
        "run_id": "123",
        "deployment_id": "456",
        "workflow_sha": "a" * 40,
        "release_sha": "a" * 40,
        "artifact_digest": "b" * 64,
        "target_marker": "asterproof-production",
        "migration_class": "none",
        "oidc_token": "header.payload.signature",
    }
    value.update(overrides)
    return value


def test_protocol_parses_fixed_command_and_frame() -> None:
    payload = b'{"status":"ok"}'

    assert parse_command("preflight v1") == "preflight"
    assert read_frame(io.BytesIO(f"{len(payload)}\n".encode() + payload)) == {"status": "ok"}


@pytest.mark.parametrize("command", ["", "bash", "preflight", "preflight v2", "status v1 extra"])
def test_protocol_rejects_unknown_commands(command: str) -> None:
    with pytest.raises(ProtocolError):
        parse_command(command)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation", "shell"),
        ("run_id", "-1"),
        ("deployment_id", "1/2"),
        ("release_sha", "main"),
        ("workflow_sha", "main"),
        ("artifact_digest", "b" * 63),
        ("target_marker", "../../prod"),
        ("migration_class", "safe"),
        ("oidc_token", "token\nvalue"),
    ],
)
def test_operation_envelope_rejects_untrusted_fields(field: str, value: str) -> None:
    with pytest.raises(ProtocolError):
        OperationEnvelope.from_dict(_envelope(**{field: value}))


def test_audience_is_bound_to_every_public_operation_field() -> None:
    first = OperationEnvelope.from_dict(_envelope())
    second = OperationEnvelope.from_dict(_envelope(release_sha="c" * 40, workflow_sha="c" * 40))

    assert envelope_audience(first.public_dict()) != envelope_audience(second.public_dict())
    assert "oidc_token" not in first.public_dict()


def test_rollback_binds_workflow_and_target_shas_separately() -> None:
    envelope = OperationEnvelope.from_dict(
        _envelope(operation="rollback", workflow_sha="c" * 40, release_sha="a" * 40),
    )

    assert envelope.workflow_sha == "c" * 40
    assert envelope.release_sha == "a" * 40


def test_deploy_rejects_workflow_sha_that_differs_from_release() -> None:
    with pytest.raises(ProtocolError):
        OperationEnvelope.from_dict(_envelope(workflow_sha="c" * 40))
