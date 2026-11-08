"""The proof-library maintenance path preserves recovery and has no initialization side effects."""
# ruff: noqa: ARG002, EM101, TRY003

import ast
import hashlib
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from uuid import UUID

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.test import override_settings
from django.urls import path
from django.urls import resolve

from scripts.deployment import community_proof_schema as schema
from scripts.deployment import community_schema
from scripts.deployment import validate_dispatch
from scripts.deployment.learning_bridge import PRODUCTION_SETTINGS
from scripts.deployment.operation_worker import OperationError
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.tests.test_catalogue_maintenance import END
from scripts.deployment.tests.test_catalogue_maintenance import START
from scripts.deployment.tests.test_catalogue_maintenance import CatalogueBackend
from scripts.deployment.tests.test_learning_bridge import write_bridge
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def synthetic_delta(monkeypatch):
    # Exercise worker state transitions independently of the actual PG17 catalog fixture.
    monkeypatch.setattr(schema, "DELTA_SHA256", "f" * 64)


def disclosure():
    return {
        "format_version": 1,
        "kind": schema.KIND,
        "active_sha": OLD_SHA,
        "target_sha": NEW_SHA,
        "input_hashes": schema.INPUT_HASHES.copy(),
        "starting": {**START, "behaviour_fingerprint": community_schema.BEHAVIOUR_SHA256},
        "expected": {**END, "behaviour_fingerprint": community_schema.BEHAVIOUR_SHA256},
        "recovery_policy": schema.RECOVERY_POLICY.copy(),
        "postgresql_rehearsal_sha256": hashlib.sha256(
            schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA),
        ).hexdigest(),
    }


class ProofBackend(CatalogueBackend):
    def prepare(self, contract, request, destination):
        super().prepare(contract, request, destination)
        (destination / schema.EVIDENCE_PATH).write_bytes(
            schema.evidence_bytes(release_sha=NEW_SHA, active_sha=OLD_SHA),
        )

    def community_audit(self, contract):
        result = super().catalogue_audit(contract)
        if self.failure != self.stage:
            result["behaviour_fingerprint"] = community_schema.BEHAVIOUR_SHA256
        return result

    def check_community_proof_schema(self, contract, release):
        return super().check_catalogue_schema(contract, release)

    def migrate_community_proof_schema(self, contract, release):
        return super().migrate_catalogue_schema(contract, release)

    def check_community_proof_ai_disabled(self, contract, release):
        self.events.append("ai_off")
        if self.failure == "ai_off":
            raise OperationError("ai_enabled")

    def verify_community_proof_records(self, contract, run_id, active_sha):
        return super().verify_catalogue_records(contract, run_id, active_sha)

    def verify_catalogue_records(self, contract, run_id, active_sha):
        pytest.fail("The proof library must use its Community-specific record preservation")

    def check_catalogue_schema(self, contract, release):
        pytest.fail("The proof library must not use the catalogue migration plan")

    def migrate_catalogue_schema(self, contract, release):
        pytest.fail("The proof library must not use the catalogue migration plan")

    def refresh_catalogue(self, contract, release):
        pytest.fail("The proof library migration must not refresh existing derived data")

    def initialize_community_index(self, contract, release):
        pytest.fail("The proof library migration must not initialize or refresh the existing index")


def seed_request(contract):
    _seed(contract, migration_class="data-or-non-compatible")
    path = contract.registry_dir / "requests/42.json"
    value = read_json(path)
    value["schema_disclosure"] = disclosure()
    atomic_write_json(path, value)


def test_recovery_and_preservation_precede_activation_without_index_or_catalogue_writes(tmp_path):
    contract = _contract(tmp_path)
    seed_request(contract)
    backend = ProofBackend()
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "active"
    assert backend.events == [
        "preflight", "drain", "backup", "verify_recovery", "migrate", "ai_off", "preserve",
        "activate", "health", "resume",
    ]
    assert read_json(contract.registry_dir / f"releases/{NEW_SHA}.json")["rollback_eligible"] is False
    assert run_operation(contract, "42", backend=backend) == result


@pytest.mark.parametrize("failure", ["starting", "candidate", "preflight"])
def test_invalid_proof_preflight_never_drains_the_serving_application(tmp_path, failure):
    contract = _contract(tmp_path)
    seed_request(contract)
    backend = ProofBackend(failure)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "failed"
    assert "drain" not in backend.events


@pytest.mark.parametrize(
    "failure", ["drain", "backup", "receipt", "migration", "expected", "ai_off", "preserve", "activation", "resume"],
)
def test_proof_failure_after_drain_requires_reconciliation_without_retry_or_rollback(tmp_path, failure):
    contract = _contract(tmp_path)
    seed_request(contract)
    backend = ProofBackend(failure)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "recovery_required"
    before = backend.events.copy()
    assert run_operation(contract, "42", backend=backend) == result
    assert backend.events == before


def test_backend_uses_only_the_frozen_plan_and_bounded_ai_off_read(monkeypatch):
    calls, validated = [], []
    monkeypatch.setattr(schema, "validate_candidate", validated.append)
    monkeypatch.setattr(WorkerBackend, "_run_candidate", lambda *args, **kwargs: calls.append((args, kwargs)))
    backend = WorkerBackend()
    backend.check_community_proof_schema(None, ROOT)
    backend.migrate_community_proof_schema(None, ROOT)
    backend.check_community_proof_ai_disabled(None, ROOT)
    assert validated == [ROOT]
    assert calls[0][0][-1] == ["shell", "--command", schema.PLAN_CHECK]
    assert calls[1][0][-1] == ["shell", "--command", schema.MIGRATION_APPLY]
    assert calls[1][1] == {"migration": True}
    assert calls[2][0][-1] == ["shell", "--command", schema.AI_OFF_CHECK]
    assert calls[2][1] == {"runtime_seconds": 60}


def test_dispatch_requires_only_the_one_frozen_proof_migration(tmp_path, monkeypatch):
    changes = ["A\t" + path for path in schema.INPUT_HASHES]
    validated = []
    monkeypatch.setattr(schema, "validate_candidate", validated.append)
    settings = tmp_path / PRODUCTION_SETTINGS
    settings.parent.mkdir(parents=True)
    settings.write_bytes(b"LEARNING_READER_BRIDGE = False\n")

    def git_result(arguments, **kwargs):
        if arguments[:2] == ["git", "diff"]:
            return SimpleNamespace(stdout="\n".join(changes))
        assert arguments[:2] == ["git", "show"]
        return SimpleNamespace(stdout=settings.read_bytes(), returncode=0)

    monkeypatch.setattr(
        validate_dispatch.subprocess, "run", git_result,
    )
    args = {
        "repository": tmp_path, "active_sha": OLD_SHA, "target_sha": NEW_SHA,
        "registry_path": ROOT / "deployment/migration-classifications.yml", "declared_class": "data-or-non-compatible",
    }
    result = validate_dispatch.build_migration_disclosure(**args)
    assert result["migrations"] == [
        {"migration": "pages.0045_community_proof_library", "classification": "data-or-non-compatible"},
    ]
    assert validated == [tmp_path]
    changes.append("A\tinspinia/pages/migrations/0044_learning_page_activity.py")
    with pytest.raises(validate_dispatch.DispatchValidationError, match="exact frozen"):
        validate_dispatch.build_migration_disclosure(**args)


def test_proof_migration_cannot_run_through_a_learning_bridge(tmp_path):
    class ProofBridgeBackend(ProofBackend):
        def prepare(self, contract, request, destination):
            super().prepare(contract, request, destination)
            write_bridge(destination)

    contract = _contract(tmp_path)
    seed_request(contract)
    backend = ProofBridgeBackend()

    result = run_operation(contract, "42", backend=backend)

    assert result["state"] == "failed"
    assert result["error_code"] == "learning_bridge_requires_none"
    assert backend.events == []
    assert (contract.release_root / "current").resolve().name == OLD_SHA


def test_generated_compatibility_reader_passes_resolved_problem_id_to_detail_views():
    urls = ModuleType("community_proof_compatibility_test_urls")
    visited = []
    user = object()

    def listing(request):
        assert request.user is user
        visited.append(request.path)
        return HttpResponse()

    def detail(request, problem_id):
        assert request.user is user
        visited.append(problem_id)
        return HttpResponse()

    urls.urlpatterns = [
        path("community/problems/", listing),
        path("community/problems/<uuid:problem_id>/", detail),
    ]
    rows = [SimpleNamespace(pk=UUID(int=1)), SimpleNamespace(pk=UUID(int=2))]
    loop = next(node for node in ast.walk(ast.parse(schema.smoke_command())) if isinstance(node, ast.For))
    compiled = compile(ast.Module(body=[loop], type_ignores=[]), "generated-compatibility-reader", "exec")
    with override_settings(ROOT_URLCONF=urls):
        exec(compiled, {"factory": RequestFactory(), "rows": rows, "user": user, "resolve": resolve})  # noqa: S102
    assert visited == ["/community/problems/", "/community/problems/", rows[0].pk, rows[1].pk]
