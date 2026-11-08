"""The exact profile migration requires recovery and preserves every original record."""
# ruff: noqa: ARG002, EM101, PLR2004, SLF001, TRY003

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.deployment import learning_schema
from scripts.deployment import maintenance_schema
from scripts.deployment import ranking_profile_preservation as preservation
from scripts.deployment import ranking_profile_schema as schema
from scripts.deployment.database_recovery import RecoveryError
from scripts.deployment.migration_plan import load_registry
from scripts.deployment.operation_worker import OperationError
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.protocol import OperationEnvelope
from scripts.deployment.protocol import ProtocolError
from scripts.deployment.protocol import envelope_audience
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.tests.test_catalogue_maintenance import CatalogueBackend
from scripts.deployment.tests.test_concept_schema import END
from scripts.deployment.tests.test_concept_schema import START
from scripts.deployment.tests.test_learning_schema import copy_candidate
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed
from scripts.deployment.tests.test_protocol import _envelope

ROOT = Path(__file__).resolve().parents[3]


def disclosure():
    return {
        "format_version": 1, "kind": schema.KIND, "migration": schema.MIGRATION,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "active_sha": OLD_SHA, "target_sha": NEW_SHA, "starting": START.copy(), "expected": END.copy(),
        "recovery_policy": schema.RECOVERY_POLICY.copy(),
        "compatibility_smoke_sha256": schema.COMPATIBILITY_SMOKE_SHA256,
        "postgresql_rehearsal_sha256": hashlib.sha256(
            schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA),
        ).hexdigest(),
    }


def test_exact_profile_sources_delta_and_recovery_classification_are_frozen():
    schema.validate_candidate(ROOT)
    delta = json.loads((ROOT / "scripts/deployment/tests/fixtures/ranking-profile-schema-delta.json").read_text())
    assert schema_state(delta)["fingerprint"] == schema.DELTA_SHA256
    assert {row["table"] for row in delta["tables"]} == schema.TABLES
    assert {"rankings_resultprofile", "rankings_resultclaim"} == schema.TABLES
    assert not delta["extensions"]
    entry = load_registry(ROOT / "deployment/migration-classifications.yml")[schema.MIGRATION]
    assert entry["classification"] == "data-or-non-compatible"
    assert entry["recovery_required"] is True
    assert entry["code_rollback_permitted"] is False


@pytest.mark.parametrize("patch", [
    {"migration": "rankings.0007_unknown"}, {"migration_file_sha256": "0" * 64},
    {"kind": "other"}, {"recovery_policy": {"rpo_seconds": 1}}, {"format_version": True},
    {"compatibility_smoke_sha256": "0" * 64}, {"postgresql_rehearsal_sha256": "0" * 64},
])
def test_profile_disclosure_rejects_unreviewed_scope_or_weakened_recovery(patch):
    with pytest.raises(ValueError, match="scope|recovery|disclosure|smoke|digest"):
        maintenance_schema.validate_disclosure({**disclosure(), **patch}, target_sha=NEW_SHA)


def test_profile_disclosure_is_oidc_bound_and_cannot_be_used_for_code_rollback():
    value = disclosure()
    assert maintenance_schema.validate_disclosure(value, target_sha=NEW_SHA) == value
    raw = _envelope(release_sha=NEW_SHA, workflow_sha=NEW_SHA, migration_class="data-or-non-compatible")
    raw["schema_disclosure"] = value
    first = OperationEnvelope.from_dict(raw)
    changed = copy.deepcopy(raw)
    changed["schema_disclosure"]["expected"]["schema_fingerprint"] = "7" * 64
    second = OperationEnvelope.from_dict(changed)
    assert envelope_audience(first.public_dict()) != envelope_audience(second.public_dict())
    for patch in ({"operation": "rollback"}, {"migration_class": "none"},
                  {"migration_class": "backward-compatible-schema"}):
        with pytest.raises(ProtocolError):
            OperationEnvelope.from_dict({**raw, **patch})


class ProfileBackend(CatalogueBackend):
    def ensure_ranking_profile_reader(self, contract, release, *, required=False):
        return None

    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        (destination / schema.EVIDENCE_PATH).write_bytes(schema.evidence_bytes(
            release_sha=NEW_SHA, active_sha=OLD_SHA,
        ))

    def schema_audit(self, contract):
        result = {**(START if self.stage == "starting" else END), "server_version_num": schema.POSTGRES_VERSION}
        if self.failure == self.stage:
            result["schema_fingerprint"] = "0" * 64
        return result

    def check_ranking_profile_schema(self, contract, release):
        if self.failure == "candidate":
            raise ValueError("Changed profile migration")

    def migrate_ranking_profile_schema(self, contract, release):
        self.events.append("migrate")
        self.stage = "expected"
        if self.failure == "migration":
            raise OperationError("profile_migration_failed")

    def verify_ranking_profile_records(self, contract, run_id, active_sha):
        self.events.append("preserve")
        if self.failure == "preserve":
            raise OperationError("ranking_profile_original_records_changed")

    def catalogue_audit(self, contract):
        pytest.fail("A profile migration must not require or alter catalogue behaviour")

    def refresh_catalogue(self, contract, release):
        pytest.fail("A profile migration must not refresh existing derived records")

    def verify_catalogue_records(self, contract, run_id, active_sha):
        pytest.fail("The profile migration must compare every original table, including ranking records")


def seed_request(contract):
    _seed(contract, migration_class="data-or-non-compatible")
    path = contract.registry_dir / "requests/42.json"
    value = read_json(path)
    value["schema_disclosure"] = disclosure()
    atomic_write_json(path, value)


def test_profile_activation_requires_verified_backup_and_complete_preservation(tmp_path):
    contract = _contract(tmp_path)
    seed_request(contract)
    backend = ProfileBackend()
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "active", (result["error_code"], backend.events)
    assert backend.events == ["preflight", "drain", "backup", "verify_recovery", "migrate", "preserve",
                              "activate", "health", "resume"]
    assert read_json(contract.registry_dir / f"releases/{NEW_SHA}.json")["rollback_eligible"] is False
    assert run_operation(contract, "42", backend=backend) == result


@pytest.mark.parametrize("failure", ["starting", "candidate", "preflight", "backup", "receipt", "migration",
                                     "expected", "preserve", "activation"])
def test_profile_failures_never_bypass_recovery_or_activate_early(tmp_path, failure):
    contract = _contract(tmp_path)
    seed_request(contract)
    backend = ProfileBackend(failure=failure)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == ("failed" if failure in {"starting", "candidate", "preflight"} else "recovery_required")
    if failure not in {"activation"}:
        assert "activate" not in backend.events


def manifests():
    tables = [
        {"schema": "public", "table": name, "rows": 1, "sha256": "1" * 64}
        for name in ("django_migrations", "rankings_student", "rankings_studentresult",
                     "rankings_rankingcorrectionreceipt", "rankings_rankingcorrectionitem")
    ]
    before = {"tables": tables, "sequences": [
        {"schema": "public", "sequence": "django_migrations_id_seq", "rows": 1, "sha256": "2" * 64},
    ], "large_objects": {"rows": 0, "sha256": preservation.EMPTY_TABLE_DIGEST}}
    after = copy.deepcopy(before)
    after.update(migration_rows=1, ai_review_disabled=True)
    after["tables"] += [{"schema": "public", "table": name, "rows": 0,
                         "sha256": preservation.EMPTY_TABLE_DIGEST} for name in sorted(schema.TABLES)]
    after["sequences"] += [
        {"schema": key[0], "sequence": key[1], "rows": 1, "sha256": preservation.EMPTY_SEQUENCE_DIGEST}
        for key in sorted(preservation.NEW_SEQUENCES)
    ]
    return before, after


def test_all_original_tables_sequences_and_empty_new_metadata_are_compared():
    before, after = manifests()
    assert preservation.compare_preserved(before, after)["verified"] is True
    for field, index, patch in [("tables", 1, {"sha256": "7" * 64}),
                                ("tables", -1, {"rows": 1}), ("sequences", 0, {"sha256": "7" * 64}),
                                ("sequences", -1, {"sha256": "7" * 64})]:
        changed = copy.deepcopy(after)
        changed[field][index].update(patch)
        with pytest.raises(RecoveryError, match="ranking_profile_preservation"):
            preservation.compare_preserved(before, changed)
    for patch in ({"migration_rows": 2}, {"migration_rows": True}, {"ai_review_disabled": False}):
        with pytest.raises(RecoveryError, match="ranking_profile_preservation"):
            preservation.compare_preserved(before, {**after, **patch})


def test_learning_history_still_rejects_later_profile_migration(tmp_path):
    copy_candidate(tmp_path)
    learning_schema.validate_candidate(tmp_path)
    path = tmp_path / schema.MIGRATION_PATH
    path.write_bytes((ROOT / schema.MIGRATION_PATH).read_bytes())
    with pytest.raises(learning_schema.LearningSchemaError, match="Historical migration"):
        learning_schema.validate_candidate(tmp_path)
