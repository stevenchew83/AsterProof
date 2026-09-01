from __future__ import annotations

import json

import pytest

from scripts.deployment.migration_plan import CLASS_COMPATIBLE
from scripts.deployment.migration_plan import CLASS_NON_COMPATIBLE
from scripts.deployment.migration_plan import CLASS_NONE
from scripts.deployment.migration_plan import MigrationPlanError
from scripts.deployment.migration_plan import build_disclosure
from scripts.deployment.migration_plan import load_registry
from scripts.deployment.migration_plan import serialize_disclosure
from scripts.deployment.migration_plan import validate_production_audit

ACTIVE_SHA = "a" * 40
TARGET_SHA = "b" * 40
EMPTY_STATE = {
    "database_identity_hash": "f" * 64,
    "role": "asterproof_audit",
    "migration": {"count": 0, "fingerprint": "0" * 64},
    "schema": {
        "counts": {"tables": 0, "columns": 0, "constraints": 0, "indexes": 0, "extensions": 0},
        "fingerprint": "1" * 64,
    },
}


def _entry(classification: str) -> dict[str, object]:
    compatible = classification == CLASS_COMPATIBLE
    return {
        "classification": classification,
        "recovery_required": not compatible,
        "code_rollback_permitted": compatible,
        "data_preconditions": [],
        "rationale": "Reviewed migration behavior.",
    }


def _operation(name: str, *operations: str) -> dict[str, object]:
    return {"app": "pages", "name": name, "backwards": False, "operations": list(operations)}


def test_noop_plan_is_canonical_and_needs_no_registry_entry() -> None:
    disclosure = build_disclosure(
        active_sha=ACTIVE_SHA,
        target_sha=TARGET_SHA,
        operations=[],
        registry={},
        starting_state=EMPTY_STATE,
        expected_state=EMPTY_STATE,
    )

    assert disclosure["classification"] == CLASS_NONE
    assert disclosure["recovery_required"] is False
    assert disclosure["code_rollback_permitted"] is True
    assert serialize_disclosure(disclosure) == serialize_disclosure(disclosure)


def test_compatible_plan_requires_matching_smoke_evidence() -> None:
    operations = [_operation("0036_add_safe_field", "AddField")]
    registry = {"pages.0036_add_safe_field": _entry(CLASS_COMPATIBLE)}

    with pytest.raises(MigrationPlanError, match="smoke evidence"):
        build_disclosure(
            active_sha=ACTIVE_SHA,
            target_sha=TARGET_SHA,
            operations=operations,
            registry=registry,
            starting_state=EMPTY_STATE,
            expected_state=EMPTY_STATE,
        )

    disclosure = build_disclosure(
        active_sha=ACTIVE_SHA,
        target_sha=TARGET_SHA,
        operations=operations,
        registry=registry,
        starting_state=EMPTY_STATE,
        expected_state=EMPTY_STATE,
        compatibility_evidence={
            "suite": "active-revision-schema-contract",
            "passed": True,
            "active_sha": ACTIVE_SHA,
            "target_sha": TARGET_SHA,
        },
    )
    assert disclosure["classification"] == CLASS_COMPATIBLE
    assert disclosure["code_rollback_permitted"] is True


@pytest.mark.parametrize("operation", ["RunPython", "RunSQL", "RemoveField", "DeleteModel"])
def test_risky_operation_requires_non_compatible_classification(operation: str) -> None:
    migration_id = "pages.0036_risky"
    with pytest.raises(MigrationPlanError, match="must be data-or-non-compatible"):
        build_disclosure(
            active_sha=ACTIVE_SHA,
            target_sha=TARGET_SHA,
            operations=[_operation("0036_risky", operation)],
            registry={migration_id: _entry(CLASS_COMPATIBLE)},
            starting_state=EMPTY_STATE,
            expected_state=EMPTY_STATE,
            compatibility_evidence={
                "suite": "active-revision-schema-contract",
                "passed": True,
                "active_sha": ACTIVE_SHA,
                "target_sha": TARGET_SHA,
            },
        )


def test_non_compatible_plan_requires_recovery_and_disables_rollback() -> None:
    entry = _entry(CLASS_NON_COMPATIBLE)
    entry["data_preconditions"] = ["completion_rows_are_unique"]
    disclosure = build_disclosure(
        active_sha=ACTIVE_SHA,
        target_sha=TARGET_SHA,
        operations=[_operation("0036_backfill", "RunPython")],
        registry={"pages.0036_backfill": entry},
        starting_state=EMPTY_STATE,
        expected_state=EMPTY_STATE,
    )

    assert disclosure["classification"] == CLASS_NON_COMPATIBLE
    assert disclosure["recovery_required"] is True
    assert disclosure["code_rollback_permitted"] is False
    assert disclosure["data_preconditions"] == ["completion_rows_are_unique"]

    validate_production_audit(
        disclosure,
        {
            "format_version": 1,
            "state": EMPTY_STATE,
            "preconditions": {"completion_rows_are_unique": True},
        },
    )


def test_production_audit_rejects_drift_and_failed_precondition() -> None:
    entry = _entry(CLASS_NON_COMPATIBLE)
    entry["data_preconditions"] = ["completion_rows_are_unique"]
    disclosure = build_disclosure(
        active_sha=ACTIVE_SHA,
        target_sha=TARGET_SHA,
        operations=[_operation("0036_backfill", "RunPython")],
        registry={"pages.0036_backfill": entry},
        starting_state=EMPTY_STATE,
        expected_state=EMPTY_STATE,
    )
    drifted_state = {**EMPTY_STATE, "database_identity_hash": "e" * 64}
    with pytest.raises(MigrationPlanError, match="does not match"):
        validate_production_audit(
            disclosure,
            {
                "format_version": 1,
                "state": drifted_state,
                "preconditions": {"completion_rows_are_unique": True},
            },
        )
    with pytest.raises(MigrationPlanError, match="preconditions"):
        validate_production_audit(
            disclosure,
            {
                "format_version": 1,
                "state": EMPTY_STATE,
                "preconditions": {"completion_rows_are_unique": False},
            },
        )


def test_missing_registry_entry_fails_closed() -> None:
    with pytest.raises(MigrationPlanError, match="unclassified migration"):
        build_disclosure(
            active_sha=ACTIVE_SHA,
            target_sha=TARGET_SHA,
            operations=[_operation("0036_new", "AddField")],
            registry={},
            starting_state=EMPTY_STATE,
            expected_state=EMPTY_STATE,
        )


def test_plan_order_is_preserved_and_contributes_to_output() -> None:
    operations = [
        _operation("0036_first", "AddField"),
        _operation("0037_second", "AddIndex"),
    ]
    registry = {
        "pages.0036_first": _entry(CLASS_NON_COMPATIBLE),
        "pages.0037_second": _entry(CLASS_NON_COMPATIBLE),
    }
    disclosure = build_disclosure(
        active_sha=ACTIVE_SHA,
        target_sha=TARGET_SHA,
        operations=operations,
        registry=registry,
        starting_state=EMPTY_STATE,
        expected_state=EMPTY_STATE,
    )

    assert [item["migration"] for item in disclosure["plan"]] == ["pages.0036_first", "pages.0037_second"]


def test_registry_is_json_compatible_yaml_and_rejects_unknown_fields(tmp_path) -> None:
    registry_path = tmp_path / "classifications.yml"
    registry_path.write_text(
        json.dumps({"format_version": 1, "baseline_sha": None, "migrations": {}}),
        encoding="utf-8",
    )
    assert load_registry(registry_path) == {}

    registry_path.write_text(
        json.dumps({"format_version": 1, "baseline_sha": None, "migrations": {}, "unsafe": True}),
        encoding="utf-8",
    )
    with pytest.raises(MigrationPlanError, match="must contain only"):
        load_registry(registry_path)


def test_invalid_sha_and_reverse_plan_are_rejected() -> None:
    with pytest.raises(MigrationPlanError, match="active_sha"):
        build_disclosure(
            active_sha="main",
            target_sha=TARGET_SHA,
            operations=[],
            registry={},
            starting_state=EMPTY_STATE,
            expected_state=EMPTY_STATE,
        )

    reverse = _operation("0036_reverse", "RemoveField")
    reverse["backwards"] = True
    with pytest.raises(MigrationPlanError, match="forward migrations"):
        build_disclosure(
            active_sha=ACTIVE_SHA,
            target_sha=TARGET_SHA,
            operations=[reverse],
            registry={"pages.0036_reverse": _entry(CLASS_NON_COMPATIBLE)},
            starting_state=EMPTY_STATE,
            expected_state=EMPTY_STATE,
        )
