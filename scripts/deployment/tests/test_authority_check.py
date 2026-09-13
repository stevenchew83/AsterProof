from __future__ import annotations

import sys

from scripts.deployment.authority_check import main


def test_authority_check_returns_only_integrity_status(monkeypatch) -> None:
    monkeypatch.setattr("scripts.deployment.authority_check.os.geteuid", lambda: 0)
    monkeypatch.setattr("scripts.deployment.authority_check._authority_matches", lambda _root: True)
    monkeypatch.setattr(sys, "argv", ["asterproof-authority-check"])

    assert main() == 0

    monkeypatch.setattr("scripts.deployment.authority_check._authority_matches", lambda _root: False)
    assert main() == 1
