"""Actions disclosure must admit only the already frozen profile migration."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import ranking_profile_schema as schema
from scripts.deployment import validate_dispatch

ROOT = Path(__file__).resolve().parents[3]
ACTIVE = "a" * 40
TARGET = "b" * 40


@pytest.fixture
def plan(monkeypatch):
    changes = ["A\t" + schema.MIGRATION_PATH.as_posix()]
    monkeypatch.setattr("scripts.deployment.learning_bridge.is_bridge_source", lambda root: False)
    monkeypatch.setattr(validate_dispatch, "_active_learning_bridge", lambda *args: False)
    monkeypatch.setattr(validate_dispatch.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout="\n".join(changes),
    ))
    return changes


def disclose(repository=ROOT, classification="data-or-non-compatible"):
    return validate_dispatch.build_migration_disclosure(
        repository=repository, active_sha=ACTIVE, target_sha=TARGET,
        registry_path=ROOT / "deployment/migration-classifications.yml", declared_class=classification,
    )


def test_profile_disclosure_accepts_exact_plan_and_keeps_data_class_recovery(plan):
    result = disclose()
    assert result["classification"] == "data-or-non-compatible"
    assert result["migrations"] == [{"migration": schema.MIGRATION, "classification": "data-or-non-compatible"}]


@pytest.mark.parametrize("classification", ["none", "backward-compatible-schema"])
def test_profile_disclosure_cannot_use_a_weaker_class(plan, classification):
    with pytest.raises(validate_dispatch.DispatchValidationError, match="declared migration class"):
        disclose(classification=classification)


@pytest.mark.parametrize("change", ["empty", "extra", "modified", "unclassified"])
def test_profile_disclosure_rejects_any_other_pending_source_plan(plan, change):
    if change == "empty":
        plan.clear()
    elif change == "extra":
        plan.append("A\tinspinia/solutions/migrations/0013_solution_forum.py")
    elif change == "modified":
        plan[0] = "M\t" + schema.MIGRATION_PATH.as_posix()
    else:
        plan.append("A\tinspinia/rankings/migrations/0007_unreviewed.py")
    with pytest.raises(validate_dispatch.DispatchValidationError):
        disclose()


def test_profile_disclosure_checks_actual_migration_bytes(plan, tmp_path):
    for name in (*schema.PRIOR_MIGRATIONS, schema.MIGRATION_PATH.name):
        relative = schema.MIGRATION_PATH.parent / name
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    disclose(repository=tmp_path)
    target = tmp_path / schema.MIGRATION_PATH
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(validate_dispatch.DispatchValidationError, match="migration bytes differ"):
        disclose(repository=tmp_path)
