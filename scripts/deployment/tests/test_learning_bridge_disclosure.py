# ruff: noqa: S603 -- Fixed Git commands operate only on each synthetic temporary repository.
"""Real Git transitions disclose the exact deferred bridge plan without hiding migrations."""

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import community_proof_schema
from scripts.deployment import learning_bridge
from scripts.deployment import learning_schema
from scripts.deployment.validate_dispatch import DispatchValidationError
from scripts.deployment.validate_dispatch import build_migration_disclosure

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "deployment/migration-classifications.yml"
NORMAL_PRODUCTION = b"LEARNING_READER_BRIDGE = False\n"
BRIDGE_PRODUCTION = Path(__file__).parent / "fixtures/learning-bridge-production.py.txt"
UNRELATED = "inspinia/users/migrations/0009_user_solution_guide_status.py"


@pytest.fixture
def history(tmp_path, monkeypatch):
    def git(*arguments):
        return subprocess.run(
            ["/usr/bin/git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *arguments],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def write(relative, content):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def commit(message):
        git("add", "--all")
        git("commit", "--quiet", "-m", message)
        return git("rev-parse", "HEAD")

    def add_learning():
        for relative in learning_schema.MIGRATION_FILES:
            write(relative, (ROOT / relative).read_bytes())

    bridge_bytes = BRIDGE_PRODUCTION.read_bytes()
    assert hashlib.sha256(bridge_bytes).hexdigest() == learning_bridge.PRODUCTION_SHA256
    git("init", "--quiet")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Synthetic bridge fixture")
    write(learning_bridge.PRODUCTION_SETTINGS, NORMAL_PRODUCTION)
    baseline = commit("Synthetic old baseline")
    calls = {"bridge": [], "schema": []}
    # Full historical-migration/28-reader byte validation is independently covered. These
    # captures retain real Git history and real static production-hash detection.
    monkeypatch.setattr(learning_bridge, "validate_bridge_source", lambda path: calls["bridge"].append(path))
    monkeypatch.setattr(learning_schema, "validate_candidate", lambda path: calls["schema"].append(path))
    return SimpleNamespace(
        root=tmp_path,
        git=git,
        write=write,
        commit=commit,
        add_learning=add_learning,
        baseline=baseline,
        bridge_bytes=bridge_bytes,
        calls=calls,
    )


def learning_plan():
    return sorted(
        [
            {"migration": f"{app}.{name}", "classification": "backward-compatible-schema"}
            for app, name in learning_schema.MIGRATIONS
        ],
        key=lambda row: row["migration"],
    )


def disclose(history, active, target, classification):
    return build_migration_disclosure(
        repository=history.root,
        active_sha=active,
        target_sha=target,
        registry_path=REGISTRY,
        declared_class=classification,
    )


def commit_bridge(history):
    history.add_learning()
    history.write(learning_bridge.PRODUCTION_SETTINGS, history.bridge_bytes)
    return history.commit("Synthetic exact hard-off bridge")


def test_first_bridge_truthfully_reports_all_four_deferred_migrations_without_ddl(history):
    bridge_sha = commit_bridge(history)
    result = disclose(history, history.baseline, bridge_sha, "none")
    assert result == {
        "format_version": 1,
        "active_sha": history.baseline,
        "target_sha": bridge_sha,
        "classification": "none",
        "migrations": learning_plan(),
        "learning_reader_preparation": {"deferred_migrations": learning_plan(), "database_changes": False},
    }
    assert history.calls == {"bridge": [history.root], "schema": []}


def test_successor_synthesizes_the_four_pending_migrations_despite_no_migration_file_diff(history):
    bridge_sha = commit_bridge(history)
    history.write(learning_bridge.PRODUCTION_SETTINGS, NORMAL_PRODUCTION)
    target = history.commit("Synthetic normal successor")
    assert history.git("diff", "--name-only", f"{bridge_sha}..{target}", "--", "inspinia") == ""
    result = disclose(history, bridge_sha, target, "backward-compatible-schema")
    assert result == {
        "format_version": 1,
        "active_sha": bridge_sha,
        "target_sha": target,
        "classification": "backward-compatible-schema",
        "migrations": learning_plan(),
        "learning_reader_successor": True,
    }
    assert history.calls == {"bridge": [], "schema": [history.root]}


def test_community_qualification_bridge_and_successor_keep_separate_exact_plans(history, monkeypatch):
    proof_validated = []
    monkeypatch.setattr(community_proof_schema, "validate_candidate", proof_validated.append)
    for relative in community_proof_schema.INPUT_HASHES:
        history.write(relative, (ROOT / relative).read_bytes())
    community_sha = history.commit("Synthetic Community proof release")
    proof = disclose(history, history.baseline, community_sha, "data-or-non-compatible")
    assert proof["migrations"] == [
        {"migration": "pages.0045_community_proof_library", "classification": "data-or-non-compatible"},
    ]
    assert "learning_reader_preparation" not in proof
    assert proof_validated == [history.root]
    assert history.calls == {"bridge": [], "schema": []}

    history.write("docs/synthetic-qualification.md", b"Synthetic no-schema baseline qualification.\n")
    qualification_sha = history.commit("Synthetic source-identical documentation qualification")
    qualification = disclose(history, community_sha, qualification_sha, "none")
    assert qualification["classification"] == "none"
    assert qualification["migrations"] == []
    assert history.git("diff", "--name-only", f"{community_sha}..{qualification_sha}") == (
        "docs/synthetic-qualification.md"
    )

    bridge_sha = commit_bridge(history)
    preparation = disclose(history, qualification_sha, bridge_sha, "none")
    assert preparation["migrations"] == learning_plan()
    assert preparation["learning_reader_preparation"] == {
        "deferred_migrations": learning_plan(), "database_changes": False,
    }

    history.write(learning_bridge.PRODUCTION_SETTINGS, NORMAL_PRODUCTION)
    successor_sha = history.commit("Synthetic Training schema successor after Community")
    successor = disclose(history, bridge_sha, successor_sha, "backward-compatible-schema")
    assert successor["migrations"] == learning_plan()
    assert successor["learning_reader_successor"] is True
    assert proof_validated == [history.root]
    assert history.calls == {"bridge": [history.root], "schema": [history.root]}


def test_bridge_cannot_defer_the_community_proof_migration(history, monkeypatch):
    proof_validated = []
    monkeypatch.setattr(community_proof_schema, "validate_candidate", proof_validated.append)
    for relative in community_proof_schema.INPUT_HASHES:
        history.write(relative, (ROOT / relative).read_bytes())
    bridge_sha = commit_bridge(history)

    with pytest.raises(DispatchValidationError, match="exact four migrations"):
        disclose(history, history.baseline, bridge_sha, "none")

    assert proof_validated == []
    assert history.calls == {"bridge": [], "schema": []}


@pytest.mark.parametrize("include_learning", [False, True])
def test_first_bridge_rejects_unrelated_or_mixed_classified_migrations(history, include_learning):
    if include_learning:
        history.add_learning()
    history.write(UNRELATED, b"# Synthetic unrelated, already-classified migration.\n")
    history.write(learning_bridge.PRODUCTION_SETTINGS, history.bridge_bytes)
    target = history.commit("Synthetic invalid bridge migration set")
    with pytest.raises(DispatchValidationError, match="exact four migrations"):
        disclose(history, history.baseline, target, "none")
    assert history.calls == {"bridge": [], "schema": []}


def test_successor_rejects_another_classified_migration(history):
    bridge_sha = commit_bridge(history)
    history.write(learning_bridge.PRODUCTION_SETTINGS, NORMAL_PRODUCTION)
    history.write(UNRELATED, b"# Synthetic unrelated, already-classified migration.\n")
    target = history.commit("Synthetic mixed successor")
    with pytest.raises(DispatchValidationError, match="cannot introduce another migration"):
        disclose(history, bridge_sha, target, "backward-compatible-schema")
    assert history.calls == {"bridge": [], "schema": []}


def test_successor_cannot_edit_a_deliberately_deferred_migration(history):
    bridge_sha = commit_bridge(history)
    history.write(learning_bridge.PRODUCTION_SETTINGS, NORMAL_PRODUCTION)
    relative = next(iter(learning_schema.MIGRATION_FILES))
    history.write(relative, (ROOT / relative).read_bytes() + b"\n# Changed deferred migration.\n")
    target = history.commit("Synthetic changed historical migration")
    with pytest.raises(DispatchValidationError, match="must not be changed or deleted"):
        disclose(history, bridge_sha, target, "backward-compatible-schema")


def test_a_marker_with_wrong_production_hash_cannot_gain_the_none_exception(history):
    history.add_learning()
    history.write(learning_bridge.PRODUCTION_SETTINGS, history.bridge_bytes + b"\n# Hash differs.\n")
    target = history.commit("Synthetic malformed bridge source")
    assert learning_bridge.has_bridge_marker(history.root)
    assert not learning_bridge.is_bridge_source(history.root)
    with pytest.raises(DispatchValidationError, match="does not match"):
        disclose(history, history.baseline, target, "none")
    assert history.calls == {"bridge": [], "schema": []}


def test_a_malformed_historical_bridge_does_not_synthesize_the_successor_plan(history):
    history.add_learning()
    history.write(learning_bridge.PRODUCTION_SETTINGS, history.bridge_bytes + b"\n# Not the reviewed bridge.\n")
    malformed_sha = history.commit("Synthetic malformed historical bridge")
    history.write(learning_bridge.PRODUCTION_SETTINGS, NORMAL_PRODUCTION)
    target = history.commit("Synthetic successor of an unverified bridge")
    assert history.git("diff", "--name-only", f"{malformed_sha}..{target}", "--", "inspinia") == ""
    with pytest.raises(DispatchValidationError, match="does not match"):
        disclose(history, malformed_sha, target, "backward-compatible-schema")
    assert history.calls == {"bridge": [], "schema": []}


@pytest.mark.parametrize("classification", ["backward-compatible-schema", "data-or-non-compatible"])
def test_bridge_rejects_a_schema_migration_class(history, classification):
    target = commit_bridge(history)
    with pytest.raises(DispatchValidationError, match="exact four migrations"):
        disclose(history, history.baseline, target, classification)
    assert history.calls == {"bridge": [], "schema": []}


def test_normal_source_with_none_does_not_gain_the_successor_schema_exception(history):
    bridge_sha = commit_bridge(history)
    history.write(learning_bridge.PRODUCTION_SETTINGS, NORMAL_PRODUCTION)
    target = history.commit("Synthetic normal source with wrong declared class")
    result = disclose(history, bridge_sha, target, "none")
    # No schema exception is granted: runtime pending-plan enforcement must reject
    # an ordinary none deployment while those four DB migrations are unapplied.
    assert result["classification"] == "none"
    assert result["migrations"] == []
    assert "learning_reader_successor" not in result
    assert history.calls == {"bridge": [], "schema": []}
