# ruff: noqa: EM101, EM102, TRY003
"""Canonical fingerprints for trusted migration and PostgreSQL catalog snapshots."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any


class FingerprintError(ValueError):
    """Raised when an audit snapshot cannot be normalized safely."""


_ASCII_CONTROL_LIMIT = 32
_ASCII_DELETE = 127
_MIGRATION_ROW_FIELDS = 2


_SCHEMA_RECORD_FIELDS: dict[str, tuple[str, ...]] = {
    "tables": ("schema", "table", "kind"),
    "columns": (
        "schema",
        "table",
        "position",
        "column",
        "type",
        "nullable",
        "default",
        "collation",
    ),
    "constraints": ("schema", "table", "name", "type", "definition"),
    "indexes": ("schema", "table", "name", "definition"),
    "extensions": ("name", "version"),
}


def canonical_json(value: Any) -> bytes:
    """Serialize a validated value identically in CI and trusted audit code."""

    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def sha256_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _text(value: object, *, field: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise FingerprintError(f"{field} must be a string")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise FingerprintError(f"{field} must not be empty")
    if any(
        ord(character) < _ASCII_CONTROL_LIMIT or ord(character) == _ASCII_DELETE
        for character in normalized
    ):
        raise FingerprintError(f"{field} contains a control character")
    return normalized


def normalize_migration_rows(rows: Iterable[Sequence[object]]) -> list[list[str]]:
    """Normalize ``django_migrations`` app/name rows without trusting DB order."""

    normalized: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for position, row in enumerate(rows):
        if isinstance(row, (str, bytes)) or len(row) != _MIGRATION_ROW_FIELDS:
            raise FingerprintError(f"migration row {position} must contain app and name")
        item = (
            _text(row[0], field=f"migration row {position} app"),
            _text(row[1], field=f"migration row {position} name"),
        )
        if item in seen:
            raise FingerprintError(f"duplicate migration row: {item[0]}.{item[1]}")
        seen.add(item)
        normalized.append(item)
    return [list(item) for item in sorted(normalized)]


def migration_state(rows: Iterable[Sequence[object]]) -> dict[str, object]:
    normalized = normalize_migration_rows(rows)
    return {"count": len(normalized), "fingerprint": sha256_fingerprint(normalized)}


def _normalize_schema_record(category: str, position: int, raw: object) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise FingerprintError(f"{category} record {position} must be an object")
    fields = _SCHEMA_RECORD_FIELDS[category]
    if set(raw) != set(fields):
        missing = sorted(set(fields) - set(raw))
        extra = sorted(set(raw) - set(fields))
        raise FingerprintError(
            f"{category} record {position} fields mismatch; missing={missing}, extra={extra}",
        )

    result: dict[str, object] = {}
    for field in fields:
        value = raw[field]
        label = f"{category} record {position} {field}"
        if field == "position":
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise FingerprintError(f"{label} must be a positive integer")
            result[field] = value
        elif field == "nullable":
            if not isinstance(value, bool):
                raise FingerprintError(f"{label} must be a boolean")
            result[field] = value
        elif field in {"default", "collation"}:
            result[field] = _text(value, field=label, nullable=True)
        else:
            result[field] = _text(value, field=label)
    return result


def normalize_schema_snapshot(snapshot: Mapping[str, object]) -> dict[str, list[dict[str, object]]]:
    """Validate and sort the allowlisted PostgreSQL schema catalog projection."""

    if not isinstance(snapshot, Mapping):
        raise FingerprintError("schema snapshot must be an object")
    if set(snapshot) != set(_SCHEMA_RECORD_FIELDS):
        missing = sorted(set(_SCHEMA_RECORD_FIELDS) - set(snapshot))
        extra = sorted(set(snapshot) - set(_SCHEMA_RECORD_FIELDS))
        raise FingerprintError(f"schema snapshot fields mismatch; missing={missing}, extra={extra}")

    normalized: dict[str, list[dict[str, object]]] = {}
    for category in _SCHEMA_RECORD_FIELDS:
        raw_records = snapshot[category]
        if isinstance(raw_records, (str, bytes)) or not isinstance(raw_records, Sequence):
            raise FingerprintError(f"{category} must be an array")
        records = [
            _normalize_schema_record(category, position, record)
            for position, record in enumerate(raw_records)
        ]
        records.sort(key=lambda record: canonical_json(record))
        serialized = [canonical_json(record) for record in records]
        if len(serialized) != len(set(serialized)):
            raise FingerprintError(f"{category} contains duplicate records")
        normalized[category] = records
    return normalized


def schema_state(snapshot: Mapping[str, object]) -> dict[str, object]:
    normalized = normalize_schema_snapshot(snapshot)
    return {
        "counts": {category: len(records) for category, records in normalized.items()},
        "fingerprint": sha256_fingerprint(normalized),
    }
