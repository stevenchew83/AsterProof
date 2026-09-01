# ruff: noqa: S108, TC003
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.deployment.release_state import ReleaseStateError
from scripts.deployment.release_state import atomic_symlink
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import protected_release_shas
from scripts.deployment.release_state import release_sha_from_link
from scripts.deployment.release_state import transition


def test_atomic_state_transition_and_invalid_replay(tmp_path: Path) -> None:
    state = tmp_path / "operation.json"
    atomic_write_json(state, {"state": "verified"})

    result = transition(state, "prepared")

    assert result["state"] == "prepared"
    assert json.loads(state.read_text())["state"] == "prepared"
    with pytest.raises(ReleaseStateError, match="invalid"):
        transition(state, "active")


def test_atomic_symlink_and_release_link_reject_escape(tmp_path: Path) -> None:
    releases = tmp_path / "releases"
    release = releases / ("a" * 40)
    release.mkdir(parents=True)
    link = tmp_path / "current"

    atomic_symlink(link, release, allowed_root=releases)

    assert release_sha_from_link(link, releases_dir=releases) == "a" * 40
    outside = tmp_path / "outside"
    outside.mkdir()
    link.unlink()
    link.symlink_to(outside)
    with pytest.raises(ReleaseStateError, match="escapes"):
        release_sha_from_link(link, releases_dir=releases)


def test_protected_releases_include_links_and_in_progress_operations(tmp_path: Path) -> None:
    releases = tmp_path / "releases"
    first = releases / ("a" * 40)
    second = releases / ("b" * 40)
    first.mkdir(parents=True)
    second.mkdir()
    atomic_symlink(tmp_path / "current", first, allowed_root=releases)
    operations = tmp_path / "registry/operations"
    atomic_write_json(operations / "42.json", {"release_sha": "b" * 40, "state": "prepared"})

    assert protected_release_shas(tmp_path, operations) == {"a" * 40, "b" * 40}
