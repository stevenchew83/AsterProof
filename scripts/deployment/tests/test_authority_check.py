from __future__ import annotations

import sys

from scripts.deployment.authority_check import main


def test_authority_check_returns_only_integrity_status(monkeypatch) -> None:
    monkeypatch.setattr("scripts.deployment.authority_check.os.geteuid", lambda: 0)
    monkeypatch.setattr("scripts.deployment.authority_check._authority_matches", lambda _root: True)
    monkeypatch.setattr("scripts.deployment.authority_check.TargetContract.load", lambda _path: object())
    monkeypatch.setattr(
        "scripts.deployment.authority_check.managed_service_configuration_matches", lambda _contract: True,
    )
    monkeypatch.setattr(sys, "argv", ["asterproof-authority-check"])

    assert main() == 0

    monkeypatch.setattr(
        "scripts.deployment.authority_check.managed_service_configuration_matches", lambda _contract: False,
    )
    assert main() == 1

    monkeypatch.setattr("scripts.deployment.authority_check._authority_matches", lambda _root: False)
    assert main() == 1
