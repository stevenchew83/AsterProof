# ruff: noqa: EM101, PLR2004, S603, SLF001, TRY003
"""The website allowance remains exact, hash-bound, and data-preserving."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import additive_schema
from scripts.deployment import newsletter_automation_schema as schema
from scripts.deployment.newsletter_automation_rehearsal import validate_migration_record
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.protocol import OperationEnvelope
from scripts.deployment.protocol import ProtocolError
from scripts.deployment.protocol import envelope_audience
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.tests.test_concept_schema import END
from scripts.deployment.tests.test_concept_schema import START
from scripts.deployment.tests.test_concept_schema import SchemaBackend
from scripts.deployment.tests.test_concept_schema import disclosure as concept_disclosure
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed
from scripts.deployment.tests.test_protocol import _envelope
from scripts.deployment.validate_dispatch import validate_schema_input

ROOT = Path(__file__).resolve().parents[3]


def disclosure():
    value = concept_disclosure()
    value.update(migration=schema.MIGRATION, migration_file_sha256=schema.MIGRATION_SHA256)
    value["postgresql_rehearsal_sha256"] = hashlib.sha256(evidence_bytes(build_evidence())).hexdigest()
    value["compatibility_smoke_sha256"] = schema.COMPATIBILITY_SMOKE_SHA256
    return value


def evidence_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def build_evidence():
    return {
        "format_version": 1,
        "source_sha": NEW_SHA,
        "active_sha": OLD_SHA,
        "postgres_version": schema.POSTGRES_VERSION,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "delta_sha256": schema.DELTA_SHA256,
        "existing_schema_unchanged": True,
        "source_fixture_unchanged": True,
        "active_revision_smoke_passed": True,
        "existing_records_unchanged": True,
        "existing_sequences_unchanged": True,
        "existing_subscribers_unchanged": True,
        "existing_campaigns_unchanged": True,
    }


def test_router_preserves_original_allowance_and_admits_only_exact_website_disclosure():
    for value in (concept_disclosure(), disclosure()):
        assert additive_schema.validate_disclosure(value, target_sha=NEW_SHA) == value
    value = disclosure()
    for change in ({"migration": "website.0003_other"}, {"migration_file_sha256": "0" * 64}):
        with pytest.raises(ValueError, match="outside the approved scope"):
            additive_schema.validate_disclosure({**value, **change}, target_sha=NEW_SHA)
    validate_schema_input(
        json.dumps(value),
        release_sha=NEW_SHA,
        migration_class="backward-compatible-schema",
        initial_adoption=False,
    )


def test_newsletter_schema_is_bound_to_the_oidc_request_and_cannot_be_used_for_rollback():
    raw = _envelope(release_sha=NEW_SHA, workflow_sha=NEW_SHA, migration_class="backward-compatible-schema")
    raw["schema_disclosure"] = disclosure()
    first = OperationEnvelope.from_dict(raw)
    raw = copy.deepcopy(raw)
    raw["schema_disclosure"]["expected"]["schema_fingerprint"] = "7" * 64
    assert envelope_audience(first.public_dict()) != envelope_audience(OperationEnvelope.from_dict(raw).public_dict())
    for change in ({"migration_class": "none"}, {"operation": "rollback"}, {"schema_disclosure": None}):
        with pytest.raises(ProtocolError):
            OperationEnvelope.from_dict({**raw, **change})


def test_newsletter_migration_bytes_are_frozen_and_symlinks_rejected(tmp_path):
    path = tmp_path / schema.MIGRATION_PATH
    path.parent.mkdir(parents=True)
    content = (ROOT / schema.MIGRATION_PATH).read_bytes()
    assert hashlib.sha256(content).hexdigest() == schema.MIGRATION_SHA256
    path.write_bytes(content)
    initial = tmp_path / "inspinia/website/migrations/0001_initial.py"
    initial.write_bytes((ROOT / "inspinia/website/migrations/0001_initial.py").read_bytes())
    (tmp_path / "inspinia/website/migrations/0002_newsletter_campaigns.py").write_bytes(
        (ROOT / "inspinia/website/migrations/0002_newsletter_campaigns.py").read_bytes(),
    )
    schema.validate_candidate(tmp_path)
    path.write_bytes(content + b"\n")
    with pytest.raises(schema.NewsletterAutomationSchemaError):
        schema.validate_candidate(tmp_path)
    path.unlink()
    path.symlink_to(ROOT / schema.MIGRATION_PATH)
    with pytest.raises(schema.NewsletterAutomationSchemaError):
        schema.validate_candidate(tmp_path)


@pytest.mark.parametrize(
    "field",
    [
        "existing_records_unchanged",
        "existing_sequences_unchanged",
        "existing_subscribers_unchanged",
        "existing_campaigns_unchanged",
    ],
)
@pytest.mark.parametrize("value", [False, 1, None])
def test_data_preservation_evidence_must_be_explicit_true(tmp_path, field, value):
    report = build_evidence()
    report[field] = value
    content = evidence_bytes(report)
    (tmp_path / schema.EVIDENCE_PATH).write_bytes(content)
    bound = disclosure()
    bound["postgresql_rehearsal_sha256"] = hashlib.sha256(content).hexdigest()
    with pytest.raises(schema.NewsletterAutomationSchemaError):
        schema.validate_build_evidence(tmp_path, bound)


@pytest.mark.parametrize("extra", [False, True])
def test_newsletter_plan_guard_remains_literal_under_optimized_python(monkeypatch, extra):
    operations = [type(name, (), {})() for name in ["AddField"] * 6 + ["AlterField"] + ["CreateModel"] * 4]
    migration = SimpleNamespace(app_label="website", name="0003_newsletter_automation", operations=operations)
    plan = [(migration, False)]
    if extra:
        plan.append((SimpleNamespace(app_label="users", name="unapproved", operations=operations), False))
    executor = SimpleNamespace(
        loader=SimpleNamespace(graph=SimpleNamespace(leaf_nodes=lambda: [("website", "0003_newsletter_automation")])),
        migration_plan=lambda targets: plan,
    )
    monkeypatch.setattr("django.db.migrations.executor.MigrationExecutor", lambda connection: executor)
    command = compile(schema.PLAN_CHECK, "<frozen-website-plan>", "exec", optimize=2)
    if extra:
        with pytest.raises(RuntimeError, match="Unapproved"):
            exec(command, {})  # noqa: S102 - exact fixed plan guard
    else:
        exec(command, {})  # noqa: S102 - exact fixed plan guard


class AutomationBackend(SchemaBackend):
    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        path = destination / schema.MIGRATION_PATH
        path.parent.mkdir(parents=True)
        path.write_bytes((ROOT / schema.MIGRATION_PATH).read_bytes())
        (destination / schema.EVIDENCE_PATH).write_bytes(evidence_bytes(build_evidence()))
        initial = destination / "inspinia/website/migrations/0001_initial.py"
        initial.write_bytes((ROOT / "inspinia/website/migrations/0001_initial.py").read_bytes())
        (destination / "inspinia/website/migrations/0002_newsletter_campaigns.py").write_bytes(
            (ROOT / "inspinia/website/migrations/0002_newsletter_campaigns.py").read_bytes(),
        )

    def check_newsletter_automation_schema(self, contract, release):
        if self.fail_at == "candidate":
            raise schema.NewsletterAutomationSchemaError("Invalid website candidate")
        schema.validate_candidate(release)

    def migrate_newsletter_automation_schema(self, contract, release):
        super().migrate_concept_schema(contract, release)


@pytest.mark.parametrize(
    ("failure", "state", "migrated"),
    [
        ("", "active", True),
        ("start", "failed", False),
        ("candidate", "failed", False),
        ("migration", "recovery_required", True),
        ("end", "recovery_required", True),
    ],
)
def test_newsletter_worker_uses_exact_plan_and_never_retries_failed_migrations(tmp_path, failure, state, migrated):
    contract = _contract(tmp_path)
    _seed(contract, migration_class="backward-compatible-schema")
    path = contract.registry_dir / "requests/42.json"
    request = read_json(path)
    request["schema_disclosure"] = disclosure()
    atomic_write_json(path, request)
    backend = AutomationBackend(fail_at=failure)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == state
    assert backend.migrated == migrated
    assert (contract.release_root / "current").resolve().name == (NEW_SHA if state == "active" else OLD_SHA)
    assert run_operation(contract, "42", backend=backend) == result
    if state == "active":
        assert (
            read_json(contract.registry_dir / f"releases/{OLD_SHA}.json")["state_fingerprint"]
            == END["state_fingerprint"]
        )
    else:
        assert (
            read_json(contract.registry_dir / f"releases/{OLD_SHA}.json")["state_fingerprint"]
            == START["state_fingerprint"]
        )


def test_newsletter_migration_retains_lock_and_statement_bounds(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("scripts.deployment.operation_worker.subprocess.run", lambda args, **kwargs: seen.append(args))
    WorkerBackend().migrate_newsletter_automation_schema(_contract(tmp_path), tmp_path / "candidate")
    assert "--setenv=PGOPTIONS=-c lock_timeout=2s -c statement_timeout=30s" in seen[0]
    assert seen[0][-3:] == ["shell", "--command", schema.MIGRATION_APPLY]


def test_only_the_one_new_migration_metadata_record_is_permitted():
    old = [(1, "pages", "0039_catalogue_revision_triggers", "before")]
    new = [*old, (2, "website", "0003_newsletter_automation", "after")]
    validate_migration_record((old, 1), (new, 2))
    for changed in ([*new, (3, "users", "other", "after")], [(1, "pages", "changed", "before"), new[-1]]):
        with pytest.raises(ValueError, match="beyond its one approved record"):
            validate_migration_record((old, 1), (changed, 2))
