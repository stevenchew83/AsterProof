# ruff: noqa: ARG002, EM101, PLR2004, S603, SLF001, TRY003
"""The approved migration is the sole schema write allowed through the deployment path."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.deployment.concept_schema import DELTA_SHA256
from scripts.deployment.concept_schema import EVIDENCE_PATH
from scripts.deployment.concept_schema import MIGRATION
from scripts.deployment.concept_schema import MIGRATION_APPLY
from scripts.deployment.concept_schema import MIGRATION_PATH
from scripts.deployment.concept_schema import MIGRATION_SHA256
from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.concept_schema import validate_build_evidence
from scripts.deployment.concept_schema import validate_candidate
from scripts.deployment.concept_schema import validate_disclosure
from scripts.deployment.operation_worker import OperationError
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.protocol import OperationEnvelope
from scripts.deployment.protocol import ProtocolError
from scripts.deployment.protocol import envelope_audience
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.tests.test_operation_worker import FINGERPRINT
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import FakeBackend
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed
from scripts.deployment.tests.test_protocol import _envelope
from scripts.deployment.validate_dispatch import DispatchValidationError
from scripts.deployment.validate_dispatch import validate_schema_input

START = {"state_fingerprint": FINGERPRINT, "schema_fingerprint": "1" * 64, "migration_fingerprint": "2" * 64}
END = {"state_fingerprint": "f" * 64, "schema_fingerprint": "3" * 64, "migration_fingerprint": "4" * 64}


def disclosure():
    return {
        "format_version": 1,
        "active_sha": OLD_SHA,
        "target_sha": NEW_SHA,
        "migration": MIGRATION,
        "migration_file_sha256": MIGRATION_SHA256,
        "starting": copy.deepcopy(START),
        "expected": copy.deepcopy(END),
        "postgresql_rehearsal_sha256": "5" * 64,
        "compatibility_smoke_sha256": "6" * 64,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("migration", "pages.0037_other"),
        ("migration_file_sha256", "0" * 64),
        ("target_sha", OLD_SHA),
        ("active_sha", NEW_SHA),
        ("unexpected", True),
        ("postgresql_rehearsal_sha256", ""),
        ("expected", START),
    ],
)
def test_disclosure_rejects_out_of_scope_or_unproven_inputs(field, value):
    report = disclosure()
    report[field] = value
    with pytest.raises(ConceptSchemaError):
        validate_disclosure(report, target_sha=NEW_SHA)


def test_protocol_binds_each_schema_fingerprint_to_the_oidc_audience():
    raw = _envelope(release_sha=NEW_SHA, workflow_sha=NEW_SHA, migration_class="backward-compatible-schema")
    raw["schema_disclosure"] = disclosure()
    first = OperationEnvelope.from_dict(raw)
    raw = copy.deepcopy(raw)
    raw["schema_disclosure"]["expected"]["schema_fingerprint"] = "7" * 64
    second = OperationEnvelope.from_dict(raw)
    assert envelope_audience(first.public_dict()) != envelope_audience(second.public_dict())
    for change in [{"schema_disclosure": None}, {"migration_class": "none"}, {"operation": "rollback"}]:
        with pytest.raises(ProtocolError):
            OperationEnvelope.from_dict({**raw, **change})
    del raw["schema_disclosure"]
    with pytest.raises(ProtocolError):
        OperationEnvelope.from_dict(raw)


def test_dispatch_blocks_adoption_and_unbound_schema_input():
    validate_schema_input(
        json.dumps(disclosure()),
        release_sha=NEW_SHA,
        migration_class="backward-compatible-schema",
        initial_adoption=False,
    )
    for value, classification, adoption in [
        ("", "backward-compatible-schema", False),
        ("{}", "none", False),
        (json.dumps(disclosure()), "backward-compatible-schema", True),
    ]:
        with pytest.raises(DispatchValidationError):
            validate_schema_input(
                value,
                release_sha=NEW_SHA,
                migration_class=classification,
                initial_adoption=adoption,
            )


def test_only_exact_migration_bytes_are_accepted(tmp_path):
    root = Path(__file__).resolve().parents[3]
    path = tmp_path / MIGRATION_PATH
    path.parent.mkdir(parents=True)
    content = (root / MIGRATION_PATH).read_bytes()
    assert hashlib.sha256(content).hexdigest() == MIGRATION_SHA256
    path.write_bytes(content)
    validate_candidate(tmp_path)
    path.write_bytes(content + b"\n")
    with pytest.raises(ConceptSchemaError):
        validate_candidate(tmp_path)
    path.unlink()
    path.symlink_to(root / MIGRATION_PATH)
    with pytest.raises(ConceptSchemaError):
        validate_candidate(tmp_path)


def build_evidence():
    return {
        "format_version": 1,
        "source_sha": NEW_SHA,
        "active_sha": OLD_SHA,
        "postgres_version": 170009,
        "migration_file_sha256": MIGRATION_SHA256,
        "delta_sha256": DELTA_SHA256,
        "existing_schema_unchanged": True,
        "source_fixture_unchanged": True,
        "active_revision_smoke_passed": True,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_sha", OLD_SHA),
        ("postgres_version", 150019),
        ("active_revision_smoke_passed", False),
        ("delta_sha256", "0" * 64),
    ],
)
def test_wrong_packaged_schema_evidence_is_rejected(tmp_path, field, value):
    report = build_evidence()
    report[field] = value
    (tmp_path / EVIDENCE_PATH).write_text(json.dumps(report))
    with pytest.raises(ConceptSchemaError):
        validate_build_evidence(tmp_path, disclosure())


class SchemaBackend(FakeBackend):
    def __init__(self, *, fail_at=""):
        super().__init__()
        self.stage = "starting"
        self.fail_at = fail_at
        self.migrated = False

    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        (destination / EVIDENCE_PATH).write_text(json.dumps(build_evidence()))

    def check_concept_schema(self, contract, release):
        if self.fail_at == "candidate":
            raise ConceptSchemaError("Changed migration or extra pending migration")

    def schema_audit(self, contract):
        audit = copy.deepcopy(START if self.stage == "starting" else END)
        audit["server_version_num"] = 170009
        if self.fail_at == "start":
            audit["schema_fingerprint"] = "8" * 64
        if self.fail_at == "end" and self.stage == "expected":
            audit["schema_fingerprint"] = "8" * 64
        return audit

    def state_fingerprint(self, contract):
        return (START if self.stage == "starting" else END)["state_fingerprint"]

    def migrate_concept_schema(self, contract, release):
        self.migrated = True
        self.stage = "expected"
        if self.fail_at == "migration":
            raise subprocess.CalledProcessError(1, ["approved-migration"])

    def restart_and_verify(self, contract, release_sha, artifact_digest):
        if self.fail_at == "activation" and release_sha == NEW_SHA:
            raise OperationError("health_failed")
        return {"state_fingerprint": END["state_fingerprint"]}


def request_with_schema(contract):
    _seed(contract, migration_class="backward-compatible-schema")
    path = contract.registry_dir / "requests/42.json"
    request = read_json(path)
    request["schema_disclosure"] = disclosure()
    atomic_write_json(path, request)


def test_exact_schema_deployment_and_terminal_replay(tmp_path):
    contract = _contract(tmp_path)
    request_with_schema(contract)
    backend = SchemaBackend()
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "active"
    assert backend.migrated
    assert (contract.release_root / "current").resolve().name == NEW_SHA
    assert (
        read_json(contract.registry_dir / f"releases/{OLD_SHA}.json")["state_fingerprint"] == END["state_fingerprint"]
    )
    assert run_operation(contract, "42", backend=backend) == result


@pytest.mark.parametrize(
    ("failure", "expected", "migrated"),
    [
        ("start", "failed", False),
        ("candidate", "failed", False),
        ("migration", "recovery_required", True),
        ("end", "recovery_required", True),
    ],
)
def test_schema_failure_never_activates_or_retries(tmp_path, failure, expected, migrated):
    contract = _contract(tmp_path)
    request_with_schema(contract)
    backend = SchemaBackend(fail_at=failure)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == expected
    assert backend.migrated == migrated
    assert (contract.release_root / "current").resolve().name == OLD_SHA
    assert (contract.releases_dir / NEW_SHA).exists() == migrated
    assert run_operation(contract, "42", backend=backend) == result


def test_schema_migration_command_has_lock_and_statement_bounds(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("scripts.deployment.operation_worker.subprocess.run", lambda args, **kwargs: seen.append(args))
    backend = WorkerBackend()
    backend.migrate_concept_schema(_contract(tmp_path), tmp_path / "candidate")
    assert "--setenv=PGOPTIONS=-c lock_timeout=2s -c statement_timeout=30s" in seen[0]
    assert seen[0][-3:] == ["shell", "--command", MIGRATION_APPLY]


@pytest.mark.parametrize("extra", [False, True])
def test_literal_plan_guard_survives_optimized_python(monkeypatch, extra):
    from types import SimpleNamespace

    from scripts.deployment.concept_schema import MIGRATION_NAME
    from scripts.deployment.concept_schema import PLAN_CHECK

    operation = type("CreateModel", (), {})()
    migration = SimpleNamespace(app_label="pages", name=MIGRATION_NAME, operations=[operation] * 4)
    plan = [(migration, False)]
    if extra:
        plan.append((SimpleNamespace(app_label="users", name="0009_unapproved", operations=[operation]), False))
    fake = SimpleNamespace(
        loader=SimpleNamespace(graph=SimpleNamespace(leaf_nodes=lambda: [("pages", MIGRATION_NAME)])),
        migration_plan=lambda targets: plan,
    )
    monkeypatch.setattr("django.db.migrations.executor.MigrationExecutor", lambda connection: fake)
    if extra:
        with pytest.raises(RuntimeError, match="Unapproved"):
            exec(compile(PLAN_CHECK, "<fixed-plan-guard>", "exec", optimize=2), {})  # noqa: S102 - fixed trusted script
    else:
        exec(compile(PLAN_CHECK, "<fixed-plan-guard>", "exec", optimize=2), {})  # noqa: S102 - fixed trusted script
