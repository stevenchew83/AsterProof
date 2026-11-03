"""The reader bridge permits one exact deferred plan without changing the schema."""

import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import learning_bridge as bridge
from scripts.deployment import learning_schema
from scripts.deployment.operation_worker import OperationError
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.tests.test_learning_schema import disclosure
from scripts.deployment.tests.test_learning_worker import write_real_reader_fixture
from scripts.deployment.tests.test_operation_worker import FINGERPRINT
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import FakeBackend
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed

ROOT = Path(__file__).resolve().parents[3]
BRIDGE_PRODUCTION = Path(__file__).parent / "fixtures/learning-bridge-production.py.txt"


def write_bridge(release):
    write_real_reader_fixture(release)
    for source in (ROOT / "inspinia").glob("**/migrations/*"):
        # This fixture predates the later forum and ranking schemas.
        if (
            source.is_file() and source.suffix in {".py", ".json"}
            and source not in {
                ROOT / "inspinia/solutions/migrations/0013_solution_forum.py",
                ROOT / "inspinia/rankings/migrations/0005_ranking_analysis_review.py",
                ROOT / "inspinia/rankings/migrations/0006_student_achievement_profiles.py",
            }
        ):
            target = release / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    source = BRIDGE_PRODUCTION
    target = release / bridge.PRODUCTION_SETTINGS
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    metadata = release / "release-metadata.json"
    value = json.loads(metadata.read_bytes())
    value["files"].append(
        {
            "path": bridge.PRODUCTION_SETTINGS,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "size": source.stat().st_size,
        },
    )
    metadata.write_text(json.dumps(value))


def test_frozen_bridge_settings_fixture_matches_reviewed_hash():
    assert hashlib.sha256(BRIDGE_PRODUCTION.read_bytes()).hexdigest() == bridge.PRODUCTION_SHA256


@pytest.fixture
def candidate(tmp_path):
    release = tmp_path / NEW_SHA
    release.mkdir()
    write_bridge(release)
    return release


def test_bridge_requires_exact_production_reader_migrations_and_manifest(candidate):
    assert bridge.is_bridge_source(candidate)
    assert bridge.has_bridge_marker(candidate)
    bridge.validate_bridge_source(candidate)
    bridge.validate_bridge_candidate(candidate)


@pytest.mark.parametrize("part", ["production", "reader", "migration", "historical", "manifest"])
def test_changed_bridge_bytes_or_manifest_are_rejected(candidate, part):
    relative = {
        "production": bridge.PRODUCTION_SETTINGS,
        "reader": "inspinia/learning/publication.py",
        "migration": next(iter(learning_schema.MIGRATION_FILES)),
        "historical": "inspinia/solutions/migrations/0001_initial.py",
    }.get(part)
    if relative:
        path = candidate / relative
        path.write_bytes(path.read_bytes() + b"\n# Unreviewed modification\n")
    else:
        path = candidate / "release-metadata.json"
        value = json.loads(path.read_bytes())
        value["learning_reader"] = 0
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="(?i)bridge|learning|production"):
        bridge.validate_bridge_candidate(candidate)


def test_normal_production_false_marker_is_not_a_bridge(tmp_path):
    target = tmp_path / bridge.PRODUCTION_SETTINGS
    target.parent.mkdir(parents=True)
    target.write_text("LEARNING_READER_BRIDGE = False\n# LEARNING_READER_BRIDGE = True\n")
    assert not bridge.has_bridge_marker(tmp_path)
    assert not bridge.is_bridge_source(tmp_path)


class BridgeBackend(FakeBackend):
    def __init__(self, *, installed=False, malformed=False, pending=True, fail_target=False):
        super().__init__(fail_target=fail_target)
        self.installed = installed
        self.malformed = malformed
        self.pending = pending
        self.trace = []

    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        write_bridge(destination)
        if self.malformed:
            target = destination / bridge.PRODUCTION_SETTINGS
            target.write_bytes(target.read_bytes() + b"\nLEARNING_MODULE_ENABLED = True\n")

    def learning_reader_required(self, contract):
        return self.installed

    def check_learning_bridge(self, contract, release):
        bridge.validate_bridge_candidate(release)
        self.trace.append("readonly_exact_plan")

    def candidate_migrations_applied(self, contract, release):
        self.trace.append("ordinary_migration_check")
        if self.pending:
            message = "unapplied_migrations"
            raise OperationError(message)


def test_verified_bridge_can_activate_before_schema_without_any_migration(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract)
    backend = BridgeBackend()
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "active"
    assert backend.trace == ["readonly_exact_plan"]
    assert (contract.release_root / "current").resolve().name == NEW_SHA
    assert read_json(contract.registry_dir / f"releases/{NEW_SHA}.json")["migration_class"] == "none"


class RefuseCandidateBackend(BridgeBackend):
    def candidate_check(self, contract, release):
        pytest.fail("An ineligible bridge must stop before candidate execution")

    def activate(self, contract, release_sha):
        pytest.fail("An ineligible bridge must never activate")


@pytest.mark.parametrize("eligible", [False, None, 1, "true"])
def test_bridge_requires_explicitly_eligible_real_baseline(tmp_path, eligible):
    contract = _contract(tmp_path)
    _seed(contract)
    baseline_path = contract.registry_dir / f"releases/{OLD_SHA}.json"
    baseline = read_json(baseline_path) | {"rollback_eligible": eligible}
    atomic_write_json(baseline_path, baseline)
    backend = RefuseCandidateBackend()

    result = run_operation(contract, "42", backend=backend)

    assert result["state"] == "failed"
    assert result["error_code"] == "learning_bridge_eligible_baseline_required"
    assert not backend.trace
    assert (contract.release_root / "current").resolve().name == OLD_SHA
    assert read_json(baseline_path) == baseline
    assert not (contract.registry_dir / f"releases/{NEW_SHA}.json").exists()


def test_bridge_cannot_use_legacy_adoption_without_real_recovery_baseline(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract)
    (contract.release_root / "current").unlink()
    adoption_path = contract.registry_dir / "adoption.json"
    adoption = {
        "authorized_at": "2026-09-01T00:00:00Z",
        "legacy_sha": OLD_SHA,
        "legacy_source_root": "/srv/legacy-asterproof",
        "state_fingerprint": FINGERPRINT,
        "repository": contract.repository,
        "state": "authorized",
        "target_marker": contract.marker,
    }
    atomic_write_json(adoption_path, adoption)
    backend = RefuseCandidateBackend()

    result = run_operation(contract, "42", backend=backend)

    assert result["state"] == "failed"
    assert result["error_code"] == "learning_bridge_eligible_baseline_required"
    assert not backend.trace
    assert not (contract.release_root / "current").exists()
    assert read_json(adoption_path) == adoption


def test_nonbridge_none_keeps_existing_ineligible_baseline_behavior(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract)
    baseline_path = contract.registry_dir / f"releases/{OLD_SHA}.json"
    atomic_write_json(baseline_path, read_json(baseline_path) | {"rollback_eligible": False})

    result = run_operation(contract, "42", backend=FakeBackend())

    assert result["state"] == "active"
    assert (contract.release_root / "current").resolve().name == NEW_SHA
    assert read_json(baseline_path)["rollback_eligible"] is False
    assert read_json(contract.registry_dir / f"releases/{NEW_SHA}.json")["rollback_eligible"] is True


def test_bridge_retains_normal_health_failure_recovery_before_floor(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract)
    result = run_operation(contract, "42", backend=BridgeBackend(fail_target=True))
    assert result["state"] == "rolled_back"
    assert (contract.release_root / "current").resolve().name == OLD_SHA


def test_bridge_uses_ordinary_migrate_check_after_floor_is_installed(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract)
    backend = BridgeBackend(installed=True, pending=False)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "active"
    assert backend.trace == ["ordinary_migration_check"]


def test_bridge_does_not_allow_pending_migrations_after_floor_exists(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract)
    backend = BridgeBackend(installed=True, pending=True)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "failed"
    assert result["error_code"] == "unapplied_migrations"
    assert backend.trace == ["ordinary_migration_check"]


def test_malformed_bridge_cannot_enter_exception(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract)
    backend = BridgeBackend(malformed=True)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "failed"
    assert result["error_code"] == "learning_bridge_invalid"
    assert not backend.trace


def test_bridge_cannot_be_used_as_a_schema_deployment(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract, migration_class="backward-compatible-schema")
    path = contract.registry_dir / "requests/42.json"
    atomic_write_json(path, {**read_json(path), "schema_disclosure": disclosure()})
    backend = BridgeBackend()
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "failed"
    assert result["error_code"] == "learning_bridge_requires_none"
    assert not backend.trace


def test_bridge_check_runs_as_application_identity_with_read_only_database_defaults(candidate, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("scripts.deployment.operation_worker.subprocess.run", lambda args, **kwargs: seen.append(args))
    WorkerBackend().check_learning_bridge(_contract(tmp_path), candidate)
    assert "--uid=asterproof" in seen[0]
    assert (
        "--setenv=PGOPTIONS=-c default_transaction_read_only=on -c lock_timeout=2s -c statement_timeout=30s" in seen[0]
    )
    assert "--property=RuntimeMaxSec=60s" in seen[0]
    prefix = seen[0].index("/usr/bin/env")
    assert seen[0][prefix:prefix + 3] == [
        "/usr/bin/env", "DJANGO_READ_DOT_ENV_FILE=False",
        "PGOPTIONS=-c default_transaction_read_only=on -c lock_timeout=2s -c statement_timeout=30s",
    ]
    assert seen[0][-3:] == ["shell", "--command", bridge.PLAN_CHECK]


@pytest.mark.parametrize("defect", [None, "extra", "flags", "floor", "settings", "backwards", "operations"])
def test_readonly_plan_accepts_only_exact_four_pending_migrations(monkeypatch, defect):  # noqa: C901 - Plan matrix.
    from django.db import transaction

    statements = []
    settings = SimpleNamespace(
        SETTINGS_MODULE="config.settings.production",
        LEARNING_READER_BRIDGE=True,
        LEARNING_MODULE_ENABLED=False,
        LEARNING_CONTRIBUTIONS_ENABLED=False,
        LEARNING_PUBLICATION_ENABLED=False,
    )
    if defect == "flags":
        settings.LEARNING_PUBLICATION_ENABLED = True
    if defect == "settings":
        settings.SETTINGS_MODULE = "config.settings.test"
    plan = [
        (
            SimpleNamespace(
                app_label=app, name=name, operations=[type(operation, (), {})() for operation in operations],
            ),
            False,
        )
        for (app, name), operations in zip(
            learning_schema.MIGRATIONS, learning_schema.OPERATION_SEQUENCES, strict=True,
        )
    ]
    if defect == "extra":
        plan.append((SimpleNamespace(app_label="users", name="unapproved", operations=[]), False))
    if defect == "backwards":
        plan[0] = (plan[0][0], True)
    if defect == "operations":
        plan[0][0].operations = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            statements.append(statement)

        def fetchone(self):
            return (defect == "floor",)

    connection = SimpleNamespace(vendor="postgresql", pg_version=170009, cursor=Cursor)
    executor = SimpleNamespace(
        loader=SimpleNamespace(graph=SimpleNamespace(leaf_nodes=list)), migration_plan=lambda targets: plan,
    )
    monkeypatch.setattr("django.conf.settings", settings)
    monkeypatch.setattr("django.db.connection", connection)
    monkeypatch.setattr(transaction, "atomic", nullcontext)
    monkeypatch.setattr("django.db.migrations.executor.MigrationExecutor", lambda connection: executor)
    command = compile(bridge.PLAN_CHECK, "<read-only-learning-bridge>", "exec")
    if defect:
        with pytest.raises(RuntimeError):
            exec(command, {})  # noqa: S102 - Trusted fixed read-only plan proof.
    else:
        exec(command, {})  # noqa: S102 - Trusted fixed read-only plan proof.
        assert statements[0] == "SET TRANSACTION READ ONLY"
        assert all(statement.startswith(("SET ", "SELECT ")) for statement in statements)


def test_nonbridge_none_release_keeps_strict_pending_migration_check(tmp_path):
    class NormalPendingBackend(BridgeBackend):
        def prepare(self, contract, request, destination):
            super().prepare(contract, request, destination)
            target = destination / bridge.PRODUCTION_SETTINGS
            target.write_text("LEARNING_READER_BRIDGE = False\n")

    contract = _contract(tmp_path)
    _seed(contract)
    backend = NormalPendingBackend()
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "failed"
    assert result["error_code"] == "unapplied_migrations"
    assert backend.trace == ["ordinary_migration_check"]


def test_none_bridge_rejects_a_schema_disclosure_before_preparation(tmp_path):
    contract = _contract(tmp_path)
    _seed(contract)
    path = contract.registry_dir / "requests/42.json"
    atomic_write_json(path, {**read_json(path), "schema_disclosure": disclosure()})
    backend = BridgeBackend()
    with pytest.raises(OperationError, match="request_invalid"):
        run_operation(contract, "42", backend=backend)
    assert not backend.prepared


def test_failed_readonly_bridge_plan_never_activates_or_migrates(tmp_path):
    import subprocess

    class FailedPlanBackend(BridgeBackend):
        def check_learning_bridge(self, contract, release):
            raise subprocess.CalledProcessError(1, ["read-only-learning-plan"])

    contract = _contract(tmp_path)
    _seed(contract)
    result = run_operation(contract, "42", backend=FailedPlanBackend())
    assert result["state"] == "failed"
    assert result["error_code"] == "operation_failed"
    assert (contract.release_root / "current").resolve().name == OLD_SHA
