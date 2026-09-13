# ruff: noqa: EM101, EM102, TRY003
"""Build and validate fail-closed migration disclosures.

The candidate Django migration plan is produced against a disposable CI database.
Production should only compare the resulting canonical fingerprints using trusted,
bootstrap-installed audit code.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts.deployment.schema_fingerprint import canonical_json

CLASS_NONE = "none"
CLASS_COMPATIBLE = "backward-compatible-schema"
CLASS_NON_COMPATIBLE = "data-or-non-compatible"
CLASSIFICATIONS = (CLASS_NONE, CLASS_COMPATIBLE, CLASS_NON_COMPATIBLE)
_CLASS_RANK = {value: rank for rank, value in enumerate(CLASSIFICATIONS)}
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MIGRATION_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z0-9_]+$")
_DANGEROUS_OPERATIONS = {"DeleteModel", "RemoveField", "RunPython", "RunSQL"}
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_PRECONDITION_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SCHEMA_CATEGORIES = {"tables", "columns", "constraints", "indexes", "extensions"}
_REGISTRY_FIELDS = {
    "classification",
    "recovery_required",
    "code_rollback_permitted",
    "data_preconditions",
    "rationale",
}


class MigrationPlanError(ValueError):
    """Raised when a migration disclosure is incomplete or inconsistent."""


def _sha(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise MigrationPlanError(f"{field} must be a 40-character lowercase hexadecimal SHA")
    return value


def load_registry(path: str | Path) -> dict[str, dict[str, object]]:  # noqa: C901, PLR0912
    """Load the JSON-compatible YAML registry without adding a YAML parser to production."""

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MigrationPlanError(f"cannot load migration registry: {error}") from error
    if not isinstance(raw, dict) or set(raw) != {"format_version", "baseline_sha", "migrations"}:
        raise MigrationPlanError("registry must contain only format_version, baseline_sha, and migrations")
    if raw["format_version"] != 1:
        raise MigrationPlanError("unsupported migration registry format_version")
    baseline_sha = raw["baseline_sha"]
    if baseline_sha is not None:
        _sha(baseline_sha, field="baseline_sha")
    migrations = raw["migrations"]
    if not isinstance(migrations, dict):
        raise MigrationPlanError("registry migrations must be an object")

    result: dict[str, dict[str, object]] = {}
    for migration_id, entry in migrations.items():
        if not isinstance(migration_id, str) or _MIGRATION_RE.fullmatch(migration_id) is None:
            raise MigrationPlanError(f"invalid migration identifier: {migration_id!r}")
        if not isinstance(entry, dict) or set(entry) != _REGISTRY_FIELDS:
            raise MigrationPlanError(f"invalid fields for migration {migration_id}")
        classification = entry["classification"]
        if classification not in {CLASS_COMPATIBLE, CLASS_NON_COMPATIBLE}:
            raise MigrationPlanError(f"invalid classification for migration {migration_id}")
        if not isinstance(entry["recovery_required"], bool):
            raise MigrationPlanError(f"recovery_required must be boolean for migration {migration_id}")
        if not isinstance(entry["code_rollback_permitted"], bool):
            raise MigrationPlanError(f"code_rollback_permitted must be boolean for migration {migration_id}")
        preconditions = entry["data_preconditions"]
        if (
            not isinstance(preconditions, list)
            or any(not isinstance(item, str) or _PRECONDITION_RE.fullmatch(item) is None for item in preconditions)
            or len(preconditions) != len(set(preconditions))
        ):
            raise MigrationPlanError(f"invalid data_preconditions for migration {migration_id}")
        rationale = entry["rationale"]
        if not isinstance(rationale, str) or not rationale.strip():
            raise MigrationPlanError(f"rationale must not be empty for migration {migration_id}")
        if classification == CLASS_COMPATIBLE and (
            entry["recovery_required"] or not entry["code_rollback_permitted"]
        ):
            raise MigrationPlanError(f"compatible migration {migration_id} must remain rollback eligible")
        if classification == CLASS_NON_COMPATIBLE and (
            not entry["recovery_required"] or entry["code_rollback_permitted"]
        ):
            raise MigrationPlanError(
                f"non-compatible migration {migration_id} must require recovery and disable code rollback",
            )
        result[migration_id] = {
            **entry,
            "data_preconditions": sorted(preconditions),
            "rationale": rationale.strip(),
        }
    return result


def _normalize_audit_state(raw: Mapping[str, object], *, field: str) -> dict[str, object]:
    required = {"database_identity_hash", "role", "migration", "schema"}
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise MigrationPlanError(f"{field} has invalid fields")
    identity = raw["database_identity_hash"]
    if not isinstance(identity, str) or _FINGERPRINT_RE.fullmatch(identity) is None:
        raise MigrationPlanError(f"{field} database_identity_hash is invalid")
    role = raw["role"]
    if not isinstance(role, str) or _PRECONDITION_RE.fullmatch(role) is None:
        raise MigrationPlanError(f"{field} role is invalid")
    migration = raw["migration"]
    if not isinstance(migration, Mapping) or set(migration) != {"count", "fingerprint"}:
        raise MigrationPlanError(f"{field} migration state is invalid")
    if (
        not isinstance(migration["count"], int)
        or isinstance(migration["count"], bool)
        or migration["count"] < 0
        or not isinstance(migration["fingerprint"], str)
        or _FINGERPRINT_RE.fullmatch(migration["fingerprint"]) is None
    ):
        raise MigrationPlanError(f"{field} migration state is invalid")
    schema = raw["schema"]
    if not isinstance(schema, Mapping) or set(schema) != {"counts", "fingerprint"}:
        raise MigrationPlanError(f"{field} schema state is invalid")
    counts = schema["counts"]
    if (
        not isinstance(counts, Mapping)
        or set(counts) != _SCHEMA_CATEGORIES
        or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts.values())
        or not isinstance(schema["fingerprint"], str)
        or _FINGERPRINT_RE.fullmatch(schema["fingerprint"]) is None
    ):
        raise MigrationPlanError(f"{field} schema state is invalid")
    return {
        "database_identity_hash": identity,
        "role": role,
        "migration": dict(migration),
        "schema": {"counts": dict(counts), "fingerprint": schema["fingerprint"]},
    }


def normalize_plan(operations: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Normalize an already ordered Django executor plan without reordering it."""

    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for position, raw in enumerate(operations):
        if not isinstance(raw, Mapping) or set(raw) != {"app", "name", "backwards", "operations"}:
            raise MigrationPlanError(f"plan item {position} has invalid fields")
        app = raw["app"]
        name = raw["name"]
        migration_id = f"{app}.{name}"
        if not isinstance(app, str) or not isinstance(name, str) or _MIGRATION_RE.fullmatch(migration_id) is None:
            raise MigrationPlanError(f"plan item {position} has invalid migration identity")
        if migration_id in seen:
            raise MigrationPlanError(f"duplicate migration in plan: {migration_id}")
        seen.add(migration_id)
        if raw["backwards"] is not False:
            raise MigrationPlanError("production disclosures may only contain forward migrations")
        operation_names = raw["operations"]
        if (
            isinstance(operation_names, (str, bytes))
            or not isinstance(operation_names, Sequence)
            or not operation_names
            or any(not isinstance(name, str) or not name for name in operation_names)
        ):
            raise MigrationPlanError(f"plan item {migration_id} must list operation class names")
        result.append(
            {
                "migration": migration_id,
                "operations": list(operation_names),
            },
        )
    return result


def build_disclosure(  # noqa: C901, PLR0913
    *,
    active_sha: str,
    target_sha: str,
    operations: Sequence[Mapping[str, object]],
    registry: Mapping[str, Mapping[str, object]],
    starting_state: Mapping[str, object],
    expected_state: Mapping[str, object],
    compatibility_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    active_sha = _sha(active_sha, field="active_sha")
    target_sha = _sha(target_sha, field="target_sha")
    plan = normalize_plan(operations)
    entries: list[dict[str, object]] = []
    for item in plan:
        migration_id = item["migration"]
        entry = registry.get(migration_id)
        if entry is None:
            raise MigrationPlanError(f"unclassified migration: {migration_id}")
        classification = entry.get("classification")
        if classification not in {CLASS_COMPATIBLE, CLASS_NON_COMPATIBLE}:
            raise MigrationPlanError(f"invalid classification for migration {migration_id}")
        dangerous = _DANGEROUS_OPERATIONS.intersection(item["operations"])
        if dangerous and classification != CLASS_NON_COMPATIBLE:
            names = ", ".join(sorted(dangerous))
            raise MigrationPlanError(f"{migration_id} uses {names} and must be data-or-non-compatible")
        entries.append({**item, **entry})

    release_class = max(
        (entry["classification"] for entry in entries),
        key=lambda value: _CLASS_RANK[value],
        default=CLASS_NONE,
    )
    normalized_starting_state = _normalize_audit_state(starting_state, field="starting_state")
    normalized_expected_state = _normalize_audit_state(expected_state, field="expected_state")
    if (
        normalized_starting_state["database_identity_hash"]
        != normalized_expected_state["database_identity_hash"]
        or normalized_starting_state["role"] != normalized_expected_state["role"]
    ):
        raise MigrationPlanError("starting and expected audit identity must match")
    evidence = compatibility_evidence
    if release_class == CLASS_COMPATIBLE:
        if not isinstance(evidence, Mapping) or evidence.get("passed") is not True:
            raise MigrationPlanError("compatible migrations require passing active-revision smoke evidence")
        if set(evidence) != {"suite", "passed", "active_sha", "target_sha"}:
            raise MigrationPlanError("compatibility evidence has invalid fields")
        if evidence["active_sha"] != active_sha or evidence["target_sha"] != target_sha:
            raise MigrationPlanError("compatibility evidence SHA mismatch")
    elif evidence is not None:
        raise MigrationPlanError("compatibility evidence is only valid for compatible-schema plans")

    disclosure = {
        "format_version": 1,
        "active_sha": active_sha,
        "target_sha": target_sha,
        "classification": release_class,
        "recovery_required": any(bool(entry["recovery_required"]) for entry in entries),
        "code_rollback_permitted": all(bool(entry["code_rollback_permitted"]) for entry in entries),
        "starting_state": normalized_starting_state,
        "expected_state": normalized_expected_state,
        "plan": entries,
        "data_preconditions": sorted(
            {precondition for entry in entries for precondition in entry["data_preconditions"]},
        ),
        "compatibility_evidence": dict(evidence) if evidence is not None else None,
    }
    # Fail before emitting if a caller supplied a non-serializable or ambiguous value.
    canonical_json(disclosure)
    return disclosure


def serialize_disclosure(disclosure: Mapping[str, object]) -> bytes:
    return canonical_json(disclosure) + b"\n"


def validate_production_audit(
    disclosure: Mapping[str, object],
    audit: Mapping[str, object],
) -> None:
    """Require trusted production evidence to exactly match the disclosed start."""

    if not isinstance(disclosure, Mapping) or "starting_state" not in disclosure:
        raise MigrationPlanError("disclosure has no starting_state")
    expected = _normalize_audit_state(disclosure["starting_state"], field="starting_state")
    if not isinstance(audit, Mapping) or set(audit) != {"format_version", "state", "preconditions"}:
        raise MigrationPlanError("production audit has invalid fields")
    if audit["format_version"] != 1:
        raise MigrationPlanError("production audit format_version is invalid")
    actual = _normalize_audit_state(audit["state"], field="production audit state")
    if actual != expected:
        raise MigrationPlanError("production audit state does not match disclosure")
    required = disclosure.get("data_preconditions")
    results = audit["preconditions"]
    if (
        not isinstance(required, list)
        or not isinstance(results, Mapping)
        or set(results) != set(required)
        or any(value is not True for value in results.values())
    ):
        raise MigrationPlanError("production data preconditions did not pass exactly")


def django_executor_plan(executor: Any, targets: Sequence[tuple[str, str]]) -> list[dict[str, object]]:
    """Convert Django's CI-only MigrationExecutor plan into the trusted input shape."""

    result: list[dict[str, object]] = []
    for migration, backwards in executor.migration_plan(targets):
        result.append(
            {
                "app": migration.app_label,
                "name": migration.name,
                "backwards": backwards,
                "operations": [type(operation).__name__ for operation in migration.operations],
            },
        )
    return result


def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate a migration registry or canonicalize a disclosure")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--disclosure-input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    registry = load_registry(args.registry)
    if args.disclosure_input is None:
        sys.stdout.write(f"validated {len(registry)} migration classifications\n")
        return 0
    if args.output is None:
        parser.error("--output is required with --disclosure-input")
    raw = json.loads(args.disclosure_input.read_text(encoding="utf-8"))
    disclosure = build_disclosure(registry=registry, **raw)
    args.output.write_bytes(serialize_disclosure(disclosure))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
