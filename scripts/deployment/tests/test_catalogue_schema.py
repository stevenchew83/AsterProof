"""Frozen input validation and negative trigger/audit contract tests."""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

from scripts.deployment.catalogue_schema import BEHAVIOUR_SHA256
from scripts.deployment.catalogue_schema import DELTA_SHA256
from scripts.deployment.catalogue_schema import INPUT_HASHES
from scripts.deployment.catalogue_schema import PLAN_CHECK
from scripts.deployment.catalogue_schema import TRIGGER_TABLES
from scripts.deployment.catalogue_schema import behaviour_fingerprint
from scripts.deployment.catalogue_schema import validate_behaviour_shape
from scripts.deployment.catalogue_schema import validate_candidate
from scripts.deployment.catalogue_schema import validate_rehearsal_evidence

ROOT = Path(__file__).resolve().parents[3]


def test_reviewed_input_hashes_and_exact_operations():
    validate_candidate(ROOT)
    tree = ast.parse((ROOT / "inspinia/pages/migrations/0037_catalogue_tables.py").read_text())
    operations = [
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "migrations"
        and n.func.attr != "swappable_dependency"
    ]
    assert operations == ["CreateModel"] * 11 + ["AddConstraint"] * 3
    assert "['CreateModel']*11+['AddConstraint']*3" in PLAN_CHECK
    assert "actual != expected" in PLAN_CHECK


@pytest.mark.parametrize("name", INPUT_HASHES)
def test_changed_or_symlinked_migration_input_is_rejected(tmp_path, name):
    directory = tmp_path / "inspinia/pages/migrations"
    directory.mkdir(parents=True)
    for filename in INPUT_HASHES:
        shutil.copy2(ROOT / "inspinia/pages/migrations" / filename, directory / filename)
    (directory / name).write_bytes(b"unexpected mutation")
    with pytest.raises(ValueError, match="reviewed hash"):
        validate_candidate(tmp_path)
    (directory / name).unlink()
    (directory / name).symlink_to(ROOT / "inspinia/pages/migrations" / name)
    with pytest.raises(ValueError, match="reviewed hash"):
        validate_candidate(tmp_path)


def behaviour():
    return {
        "functions": [["public", "asterproof_catalogue_revision", "", "frozen definition", False, None]],
        "triggers": [["public", t, "ap_catalogue_" + t, "frozen definition", "O"] for t in sorted(TRIGGER_TABLES)],
    }


def test_behaviour_fingerprint_binds_definitions_and_enabled_states():
    valid = behaviour()
    validate_behaviour_shape(valid)
    changed = behaviour()
    changed["functions"][0][3] = "another definition"
    assert behaviour_fingerprint(changed) != behaviour_fingerprint(valid)
    changed = behaviour()
    changed["triggers"][0][4] = "D"
    assert behaviour_fingerprint(changed) != behaviour_fingerprint(valid)
    with pytest.raises(ValueError, match="enabled states"):
        validate_behaviour_shape(changed)


@pytest.mark.parametrize("mutation", ["missing", "extra", "security", "configuration"])
def test_unapproved_behaviour_shape_is_rejected(mutation):
    value = behaviour()
    if mutation == "missing":
        value["triggers"].pop()
    elif mutation == "extra":
        value["triggers"].append(["public", "unrelated", "ap_catalogue_unrelated", "definition", "O"])
    elif mutation == "security":
        value["functions"][0][4] = True
    else:
        value["functions"][0][5] = "search_path=untrusted"
    with pytest.raises(ValueError, match="Catalogue trigger"):
        validate_behaviour_shape(value)


def evidence():
    return {
        "format_version": 1, "source_sha": "a" * 40, "active_sha": "b" * 40,
        "postgres_version": 170009, "input_hashes": INPUT_HASHES,
        "delta_sha256": DELTA_SHA256, "behaviour_sha256": BEHAVIOUR_SHA256,
        "existing_schema_unchanged": True, "existing_records_unchanged": True,
        "active_revision_smoke_passed": True, "runtime_invalidation_passed": True,
        "trigger_uninstall_reinstall_passed": True,
    }


def test_complete_proof_is_bound_to_exact_release_and_active_revision():
    validate_rehearsal_evidence(evidence(), release_sha="a" * 40, active_sha="b" * 40)
    with pytest.raises(ValueError, match="frozen release"):
        validate_rehearsal_evidence(evidence(), release_sha="c" * 40, active_sha="b" * 40)
    with pytest.raises(ValueError, match="distinct immutable"):
        validate_rehearsal_evidence(evidence(), release_sha="a" * 40, active_sha="a" * 40)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("format_version", True), ("input_hashes", {}), ("existing_records_unchanged", 1),
        ("runtime_invalidation_passed", "true"), ("active_revision_smoke_passed", False),
        ("behaviour_sha256", "0" * 64), ("delta_sha256", "0" * 64),
    ],
)
def test_incomplete_or_modified_runtime_proof_is_rejected(field, value):
    proof = evidence()
    proof[field] = value
    with pytest.raises(ValueError, match="frozen release"):
        validate_rehearsal_evidence(proof, release_sha="a" * 40, active_sha="b" * 40)
