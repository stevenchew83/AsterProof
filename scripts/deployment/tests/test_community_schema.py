"""Community maintenance remains exact, AI-off, and protected by verified recovery."""

import copy
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import catalogue_schema
from scripts.deployment import community_schema as schema
from scripts.deployment import maintenance_schema
from scripts.deployment import validate_dispatch
from scripts.deployment.migration_audit import AuditConfig
from scripts.deployment.migration_audit import MigrationAuditError
from scripts.deployment.migration_audit import collect_community_behaviour
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.tests.test_catalogue_maintenance import END
from scripts.deployment.tests.test_catalogue_maintenance import START
from scripts.deployment.tests.test_catalogue_maintenance import CatalogueBackend
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed

ROOT = Path(__file__).resolve().parents[3]


def disclosure():
    return {
        "format_version": 1,
        "kind": schema.KIND,
        "active_sha": OLD_SHA,
        "target_sha": NEW_SHA,
        "input_hashes": schema.INPUT_HASHES.copy(),
        "starting": {**START, "behaviour_fingerprint": catalogue_schema.BEHAVIOUR_SHA256},
        "expected": {**END, "behaviour_fingerprint": schema.BEHAVIOUR_SHA256},
        "recovery_policy": schema.RECOVERY_POLICY.copy(),
        "postgresql_rehearsal_sha256": hashlib.sha256(
            schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA),
        ).hexdigest(),
    }


def test_exact_disclosure_uses_existing_protected_validation():
    value = disclosure()
    assert maintenance_schema.validate_disclosure(value, target_sha=NEW_SHA) == value
    validate_dispatch.validate_schema_input(
        json.dumps(value),
        release_sha=NEW_SHA,
        migration_class="data-or-non-compatible",
        initial_adoption=False,
    )


@pytest.mark.parametrize("field", ["kind", "active_sha", "input_hashes", "recovery_policy", "expected"])
def test_modified_scope_or_recovery_is_rejected(field):
    value = disclosure()
    value[field] = "changed"
    with pytest.raises(ValueError, match="Community|community"):
        schema.validate_disclosure(value, target_sha=NEW_SHA)


@pytest.mark.parametrize("field", ["format_version", "postgres_version", *schema.FLAGS])
def test_truthy_values_are_not_rehearsal_proof(field):
    proof = schema.rehearsal_evidence(release_sha=NEW_SHA, active_sha=OLD_SHA)
    proof[field] = True if field in {"format_version", "postgres_version"} else 1
    with pytest.raises(ValueError, match="evidence"):
        schema.validate_rehearsal_evidence(proof, release_sha=NEW_SHA, active_sha=OLD_SHA)


@pytest.fixture
def initial_candidate(tmp_path):
    for name in {**schema.INPUT_HASHES, **schema.INITIALIZATION_HASHES}:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        source = ROOT / name
        if name == "inspinia/pages/community_models.py":
            # The initial 0042/0043 allowance retains its exact historical model contract.
            source = Path(__file__).parent / "fixtures/community-initial-models.txt"
        shutil.copyfile(source, target)
    return tmp_path


def test_all_migration_and_index_sources_and_packaged_proof_are_bound(initial_candidate):
    tmp_path = initial_candidate
    schema.validate_candidate(tmp_path)
    proof = tmp_path / schema.EVIDENCE_PATH
    proof.write_bytes(schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA))
    maintenance_schema.validate_build_evidence(tmp_path, disclosure())
    target = tmp_path / next(iter(schema.INITIALIZATION_HASHES))
    target.write_text("altered initialization")
    with pytest.raises(ValueError, match="frozen hash"):
        schema.validate_candidate(tmp_path)
    proof.write_text("{}")
    with pytest.raises(ValueError, match="digest"):
        schema.validate_build_evidence(tmp_path, disclosure())


def test_phase_one_models_cannot_reuse_the_initial_community_allowance():
    with pytest.raises(ValueError, match="frozen hash"):
        schema.validate_candidate(ROOT)


def test_expected_catalog_preserves_starting_schema_and_requires_reporting():
    snapshot = {
        "tables": [{"schema": "public", "table": "pages_statementissuereport", "kind": "r"}],
        "columns": [],
        "constraints": [],
        "indexes": [],
        "extensions": [],
    }
    migrations = [["pages", "0041_statement_issue_reports"]]
    state = {
        "database_identity_hash": "a" * 64,
        "role": "asterproof_catalog",
        "schema": schema_state(snapshot),
        "migration": migration_state(migrations),
    }
    start = {
        "server_version_num": schema.POSTGRES_VERSION,
        "state": state,
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "catalog_snapshot": snapshot,
        "migration_rows": migrations,
        "behaviour_fingerprint": catalogue_schema.BEHAVIOUR_SHA256,
    }
    original = copy.deepcopy(start)
    delta = json.loads((ROOT / schema.DELTA_PATH).read_text())
    expected = schema.expected_catalog_audit(start, delta)
    assert original == start
    assert expected["behaviour_fingerprint"] == schema.BEHAVIOUR_SHA256
    assert (
        expected["migration_fingerprint"]
        == migration_state(
            [
                *migrations,
                *[["pages", name] for name in schema.MIGRATIONS],
            ],
        )["fingerprint"]
    )
    delta["columns"][0]["nullable"] = not delta["columns"][0]["nullable"]
    with pytest.raises(ValueError, match="delta"):
        schema.expected_catalog_audit(start, delta)
    start["migration_rows"] = []
    with pytest.raises(ValueError, match="reporting"):
        schema.expected_catalog_audit(start, json.loads((ROOT / schema.DELTA_PATH).read_text()))


class CommunityBackend(CatalogueBackend):
    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        (destination / schema.EVIDENCE_PATH).write_bytes(
            schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA),
        )

    def community_audit(self, contract):
        result = super().catalogue_audit(contract)
        if self.failure != self.stage:
            result["behaviour_fingerprint"] = (
                catalogue_schema.BEHAVIOUR_SHA256 if self.stage == "starting" else schema.BEHAVIOUR_SHA256
            )
        return result

    def check_community_schema(self, contract, release):
        return super().check_catalogue_schema(contract, release)

    def migrate_community_schema(self, contract, release):
        return super().migrate_catalogue_schema(contract, release)

    def initialize_community_index(self, contract, release):
        return super().refresh_catalogue(contract, release)

    def check_catalogue_schema(self, contract, release):
        pytest.fail("Community must not use the catalogue migration plan")

    def migrate_catalogue_schema(self, contract, release):
        pytest.fail("Community must not use the catalogue migration plan")


def request(contract):
    _seed(contract, migration_class="data-or-non-compatible")
    path = contract.registry_dir / "requests/42.json"
    value = read_json(path)
    value["schema_disclosure"] = disclosure()
    atomic_write_json(path, value)


def test_worker_requires_verified_restore_and_index_before_activation(tmp_path):
    contract = _contract(tmp_path)
    request(contract)
    backend = CommunityBackend()
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "active"
    assert backend.events == [
        "preflight",
        "drain",
        "backup",
        "verify_recovery",
        "migrate",
        "refresh",
        "preserve",
        "activate",
        "health",
        "resume",
    ]
    assert read_json(contract.registry_dir / f"releases/{NEW_SHA}.json")["rollback_eligible"] is False
    assert run_operation(contract, "42", backend=backend) == result


@pytest.mark.parametrize(
    "failure",
    ["drain", "backup", "receipt", "migration", "expected", "refresh", "preserve", "activation", "resume"],
)
def test_post_drain_failure_is_reconciled_without_retry_or_rollback(tmp_path, failure):
    contract = _contract(tmp_path)
    request(contract)
    backend = CommunityBackend(failure)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "recovery_required"
    events = backend.events.copy()
    assert run_operation(contract, "42", backend=backend) == result
    assert backend.events == events


@pytest.mark.parametrize("failure", ["starting", "candidate", "preflight"])
def test_invalid_preflight_never_drains(tmp_path, failure):
    contract = _contract(tmp_path)
    request(contract)
    backend = CommunityBackend(failure)
    assert run_operation(contract, "42", backend=backend)["state"] == "failed"
    assert "drain" not in backend.events


def test_backend_commands_keep_ai_off_and_initialization_bounded(monkeypatch, initial_candidate):
    calls = []
    monkeypatch.setattr(WorkerBackend, "_run_candidate", lambda *args, **kwargs: calls.append((args, kwargs)))
    backend = WorkerBackend()
    backend.check_community_schema(None, initial_candidate)
    backend.migrate_community_schema(None, initial_candidate)
    backend.initialize_community_index(None, initial_candidate)
    assert calls[0][0][-1] == ["shell", "--command", schema.PLAN_CHECK]
    assert "PROBLEM_STATEMENT_AI_REVIEW_ENABLED" in schema.PLAN_CHECK
    assert calls[1][1] == {"migration": True}
    assert calls[2][0][-1] == ["refresh_statement_similarity_index"]
    assert calls[2][1] == {"runtime_seconds": 600}
    assert calls[3][0][-1] == ["shell", "--command", schema.INDEX_CHECK]
    assert calls[3][1] == {"runtime_seconds": 60}


def test_dispatch_admits_only_two_exact_migrations(monkeypatch, initial_candidate):
    # This fixture models an ordinary maintenance source, not the reader bridge.
    monkeypatch.setattr("scripts.deployment.learning_bridge.is_bridge_source", lambda root: False)
    monkeypatch.setattr(validate_dispatch, "_active_learning_bridge", lambda *args: False)
    changes = ["A\t" + path for path in schema.INPUT_HASHES]
    monkeypatch.setattr(
        validate_dispatch.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout="\n".join(changes)),
    )
    args = {
        "repository": initial_candidate,
        "active_sha": OLD_SHA,
        "target_sha": NEW_SHA,
        "registry_path": ROOT / "deployment/migration-classifications.yml",
        "declared_class": "data-or-non-compatible",
    }
    result = validate_dispatch.build_migration_disclosure(**args)
    assert len(result["migrations"]) == len(schema.MIGRATIONS)
    changes.append("A\tinspinia/pages/migrations/0041_statement_issue_reports.py")
    with pytest.raises(validate_dispatch.DispatchValidationError, match="exact frozen"):
        validate_dispatch.build_migration_disclosure(**args)


def test_community_audit_is_identity_bound_fixed_metadata_only():
    identity = ["asterproof", "asterproof_catalog", "prod", "10.0.0.1", "5432"]
    config = AuditConfig(
        os_user="asterproof_audit",
        pg_service="asterproof_audit",
        pg_service_file=Path("/etc/asterproof/pg_service.conf"),
        expected_role="asterproof_catalog",
        expected_database_identity_hash=hashlib.sha256(canonical_json(identity)).hexdigest(),
    )
    outputs = iter([",".join(identity) + "\n", "", ""])
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(stdout=next(outputs))

    assert collect_community_behaviour(config, runner=runner)["metadata"] == {"functions": [], "triggers": []}
    assert all("BEGIN READ ONLY" in cmd[-1] and "statement_timeout='10s'" in cmd[-1] for cmd in commands)
    assert "asterproof_statement_similarity_revision" in commands[1][-1]
    assert "ap_statement_similarity_revision" in commands[2][-1]
    with pytest.raises(MigrationAuditError, match="identity"):
        collect_community_behaviour(
            config,
            runner=lambda *a, **kw: SimpleNamespace(
                stdout="otherdb,asterproof_catalog,prod,10.0.0.1,5432\n",
            ),
        )
