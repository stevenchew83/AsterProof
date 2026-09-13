from __future__ import annotations

import pytest

from scripts.deployment.schema_fingerprint import FingerprintError
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state

EXPECTED_MIGRATION_COUNT = 2


def _snapshot() -> dict[str, list[dict[str, object]]]:
    return {
        "tables": [{"schema": "public", "table": "pages_record", "kind": "r"}],
        "columns": [
            {
                "schema": "public",
                "table": "pages_record",
                "position": 1,
                "column": "id",
                "type": "bigint",
                "nullable": False,
                "default": None,
                "collation": None,
            },
        ],
        "constraints": [],
        "indexes": [],
        "extensions": [{"name": "plpgsql", "version": "1.0"}],
    }


def test_migration_fingerprint_is_order_independent_and_counts_rows() -> None:
    first = migration_state([("pages", "0002_second"), ("pages", "0001_initial")])
    second = migration_state([("pages", "0001_initial"), ("pages", "0002_second")])

    assert first == second
    assert first["count"] == EXPECTED_MIGRATION_COUNT


def test_migration_fingerprint_rejects_duplicates() -> None:
    with pytest.raises(FingerprintError, match="duplicate migration"):
        migration_state([("pages", "0001_initial"), ("pages", "0001_initial")])


def test_schema_fingerprint_is_order_independent() -> None:
    snapshot = _snapshot()
    snapshot["tables"].append({"schema": "public", "table": "users_user", "kind": "r"})
    reversed_snapshot = {key: list(reversed(value)) for key, value in snapshot.items()}

    assert schema_state(snapshot) == schema_state(reversed_snapshot)


@pytest.mark.parametrize("field", ["unknown", "missing"])
def test_schema_snapshot_rejects_field_drift(field: str) -> None:
    snapshot = _snapshot()
    if field == "unknown":
        snapshot["tables"][0]["owner"] = "postgres"
    else:
        del snapshot["columns"][0]["type"]

    with pytest.raises(FingerprintError, match="fields mismatch"):
        normalize_schema_snapshot(snapshot)


def test_schema_snapshot_rejects_control_characters() -> None:
    snapshot = _snapshot()
    snapshot["indexes"].append(
        {
            "schema": "public",
            "table": "pages_record",
            "name": "bad\nindex",
            "definition": "CREATE INDEX bad ON pages_record (id)",
        },
    )

    with pytest.raises(FingerprintError, match="control character"):
        schema_state(snapshot)
