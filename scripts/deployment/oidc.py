# ruff: noqa: C901, EM101, EM102, PLR0912, PLR2004, S310, TC003, TRY003, TRY301
from __future__ import annotations

import base64
import json
import re
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

from scripts.deployment.protocol import OperationEnvelope
from scripts.deployment.protocol import envelope_audience

GITHUB_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_CONFIGURATION_URL = f"{GITHUB_ISSUER}/.well-known/openid-configuration"


class OIDCValidationError(ValueError):
    pass


def _decode_segment(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise OIDCValidationError("malformed OIDC token encoding") from exc


def fetch_json(url: str, *, timeout: float = 5.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise OIDCValidationError("OIDC provider returned an unexpected response")
            payload = response.read(1024 * 1024 + 1)
    except OIDCValidationError:
        raise
    except OSError as exc:
        raise OIDCValidationError("OIDC provider is unavailable") from exc
    if len(payload) > 1024 * 1024:
        raise OIDCValidationError("OIDC provider response is too large")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise OIDCValidationError("OIDC provider response is malformed") from exc
    if not isinstance(value, dict):
        raise OIDCValidationError("OIDC provider response must be an object")
    return value


@dataclass(frozen=True)
class OIDCPolicy:
    repository: str
    repository_id: str
    workflow_ref: str
    target_marker: str
    environment: str = "production"
    ref: str = "refs/heads/main"
    issuer: str = GITHUB_ISSUER
    clock_skew_seconds: int = 30


class GitHubOIDCValidator:
    def __init__(
        self,
        policy: OIDCPolicy,
        *,
        json_fetcher: Callable[[str], dict[str, Any]] = fetch_json,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.policy = policy
        self.json_fetcher = json_fetcher
        self.now = now

    def validate(self, token: str, envelope: OperationEnvelope) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise OIDCValidationError("malformed OIDC token")
        try:
            header = json.loads(_decode_segment(parts[0]))
            claims = json.loads(_decode_segment(parts[1]))
        except json.JSONDecodeError as exc:
            raise OIDCValidationError("malformed OIDC token payload") from exc
        if not isinstance(header, dict) or not isinstance(claims, dict):
            raise OIDCValidationError("OIDC token payload must be an object")
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise OIDCValidationError("OIDC token uses an unsupported signing key")

        configuration = self.json_fetcher(GITHUB_CONFIGURATION_URL)
        if configuration.get("issuer") != self.policy.issuer:
            raise OIDCValidationError("OIDC discovery issuer mismatch")
        jwks_uri = configuration.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri.startswith(f"{self.policy.issuer}/"):
            raise OIDCValidationError("OIDC discovery keys URL mismatch")
        keys = self.json_fetcher(jwks_uri).get("keys")
        if not isinstance(keys, list):
            raise OIDCValidationError("OIDC key set is malformed")
        key = next((item for item in keys if isinstance(item, dict) and item.get("kid") == header["kid"]), None)
        if key is None or key.get("kty") != "RSA" or key.get("alg") not in {None, "RS256"}:
            raise OIDCValidationError("OIDC signing key is not trusted")
        try:
            modulus = int.from_bytes(_decode_segment(key["n"]), "big")
            exponent = int.from_bytes(_decode_segment(key["e"]), "big")
            public_key = RSAPublicNumbers(exponent, modulus).public_key()
            public_key.verify(
                _decode_segment(parts[2]),
                f"{parts[0]}.{parts[1]}".encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, KeyError, TypeError, ValueError) as exc:
            raise OIDCValidationError("OIDC signature validation failed") from exc

        self._validate_claims(claims, envelope)
        return claims

    def _validate_claims(self, claims: dict[str, Any], envelope: OperationEnvelope) -> None:
        now = int(self.now())
        skew = self.policy.clock_skew_seconds
        required_times = (claims.get("iat"), claims.get("nbf"), claims.get("exp"))
        if not all(isinstance(item, int) for item in required_times):
            raise OIDCValidationError("OIDC token time claims are missing")
        issued_at, not_before, expires = required_times
        if issued_at > now + skew or not_before > now + skew or expires < now - skew or expires - issued_at > 600:
            raise OIDCValidationError("OIDC token is outside its validity window")

        expected = {
            "iss": self.policy.issuer,
            "aud": envelope_audience(envelope.public_dict()),
            "repository": self.policy.repository,
            "repository_id": self.policy.repository_id,
            "environment": self.policy.environment,
            "ref": self.policy.ref,
            "workflow_ref": self.policy.workflow_ref,
            "run_id": envelope.run_id,
            "sha": envelope.workflow_sha,
        }
        for field, value in expected.items():
            claim = claims.get(field)
            if field == "aud" and isinstance(claim, list):
                if value not in claim:
                    raise OIDCValidationError("OIDC audience does not authorize the request")
            elif str(claim) != value:
                raise OIDCValidationError(f"OIDC claim mismatch: {field}")
        subject = f"repo:{self.policy.repository}:environment:{self.policy.environment}"
        if claims.get("sub") != subject:
            raise OIDCValidationError("OIDC subject does not authorize production")
        if claims.get("event_name") != "workflow_dispatch":
            raise OIDCValidationError("OIDC event is not an approved deployment event")
        if not isinstance(claims.get("jti"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", claims["jti"]):
            raise OIDCValidationError("OIDC replay identity is missing")
        if envelope.target_marker != self.policy.target_marker:
            raise OIDCValidationError("target marker is not authorized")
