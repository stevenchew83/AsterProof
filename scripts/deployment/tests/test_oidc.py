# ruff: noqa: PLR0913
from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import rsa

from scripts.deployment.oidc import GITHUB_CONFIGURATION_URL
from scripts.deployment.oidc import GitHubOIDCValidator
from scripts.deployment.oidc import OIDCPolicy
from scripts.deployment.oidc import OIDCValidationError
from scripts.deployment.protocol import OperationEnvelope
from scripts.deployment.protocol import envelope_audience


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _envelope() -> OperationEnvelope:
    return OperationEnvelope.from_dict(
        {
            "operation": "deploy",
            "run_id": "123",
            "deployment_id": "456",
            "workflow_sha": "a" * 40,
            "release_sha": "a" * 40,
            "artifact_digest": "b" * 64,
            "target_marker": "asterproof-production",
            "migration_class": "none",
            "oidc_token": "placeholder",
        },
    )


def _token(private_key: rsa.RSAPrivateKey, claims: dict[str, object]) -> str:
    header = _encode(json.dumps({"alg": "RS256", "kid": "key-1", "typ": "JWT"}).encode())
    payload = _encode(json.dumps(claims).encode())
    signature = private_key.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_encode(signature)}"


def _validator(
    private_key: rsa.RSAPrivateKey,
    *,
    now: int,
) -> GitHubOIDCValidator:
    public = private_key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "alg": "RS256",
                "e": _encode(public.e.to_bytes((public.e.bit_length() + 7) // 8, "big")),
                "kid": "key-1",
                "kty": "RSA",
                "n": _encode(public.n.to_bytes((public.n.bit_length() + 7) // 8, "big")),
            },
        ],
    }

    def fetch(url: str) -> dict[str, object]:
        if url == GITHUB_CONFIGURATION_URL:
            return {"issuer": "https://token.actions.githubusercontent.com", "jwks_uri": "https://token.actions.githubusercontent.com/.well-known/jwks"}
        return jwks

    return GitHubOIDCValidator(
        OIDCPolicy(
            repository="owner/AsterProof",
            repository_id="789",
            workflow_ref="owner/AsterProof/.github/workflows/production-deploy.yml@refs/heads/main",
            target_marker="asterproof-production",
        ),
        json_fetcher=fetch,
        now=lambda: now,
    )


def _claims(envelope: OperationEnvelope, now: int) -> dict[str, object]:
    return {
        "aud": envelope_audience(envelope.public_dict()),
        "environment": "production",
        "event_name": "workflow_dispatch",
        "exp": now + 300,
        "iat": now,
        "iss": "https://token.actions.githubusercontent.com",
        "jti": "unique-token-id",
        "nbf": now - 1,
        "ref": "refs/heads/main",
        "repository": "owner/AsterProof",
        "repository_id": "789",
        "run_id": "123",
        "sha": envelope.workflow_sha,
        "sub": "repo:owner/AsterProof:environment:production",
        "workflow_ref": "owner/AsterProof/.github/workflows/production-deploy.yml@refs/heads/main",
    }


def test_oidc_validator_accepts_bound_production_job() -> None:
    now = int(time.time())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    envelope = _envelope()

    claims = _validator(key, now=now).validate(_token(key, _claims(envelope, now)), envelope)

    assert claims["jti"] == "unique-token-id"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("environment", "staging"),
        ("event_name", "pull_request"),
        ("repository_id", "999"),
        ("run_id", "124"),
        ("sha", "c" * 40),
    ],
)
def test_oidc_validator_rejects_claim_mismatch(field: str, value: object) -> None:
    now = int(time.time())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    envelope = _envelope()
    claims = _claims(envelope, now)
    claims[field] = value

    with pytest.raises(OIDCValidationError):
        _validator(key, now=now).validate(_token(key, claims), envelope)


def test_oidc_validator_rejects_envelope_replay() -> None:
    now = int(time.time())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    first = _envelope()
    token = _token(key, _claims(first, now))
    second_data = first.public_dict() | {
        "oidc_token": "placeholder",
        "release_sha": "c" * 40,
        "workflow_sha": "c" * 40,
    }
    second = OperationEnvelope.from_dict(second_data)

    with pytest.raises(OIDCValidationError):
        _validator(key, now=now).validate(token, second)
