"""Learning deployment uses its exact allowance and requires the reader before DDL."""

import subprocess
from pathlib import Path

import pytest

from scripts.deployment import learning_compat
from scripts.deployment import learning_schema
from scripts.deployment import operation_worker
from scripts.deployment.concept_schema import audit_matches
from scripts.deployment.operation_worker import OperationError
from scripts.deployment.operation_worker import WorkerBackend
from scripts.deployment.operation_worker import run_operation
from scripts.deployment.release_manifest import ReleaseManifest
from scripts.deployment.release_state import atomic_write_json
from scripts.deployment.release_state import read_json
from scripts.deployment.tests.test_concept_schema import END
from scripts.deployment.tests.test_concept_schema import SchemaBackend
from scripts.deployment.tests.test_concept_schema import disclosure as concept_disclosure
from scripts.deployment.tests.test_operation_worker import NEW_SHA
from scripts.deployment.tests.test_operation_worker import OLD_SHA
from scripts.deployment.tests.test_operation_worker import FakeBackend
from scripts.deployment.tests.test_operation_worker import _contract
from scripts.deployment.tests.test_operation_worker import _seed


def write_real_reader_fixture(release):
    """Synthetic local release identity with the real reviewed reader bytes."""
    root = Path(__file__).resolve().parents[3]
    files = []
    for relative, checksum in learning_compat.READER_SOURCES.items():
        body = (root / relative).read_bytes()
        target = release / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        files.append({"path": relative, "sha256": checksum, "size": len(body)})
    manifest = ReleaseManifest(
        repository="owner/AsterProof",
        repository_id="123",
        release_sha=release.name,
        run_id="42",
        built_at="2026-11-01T00:00:00Z",
        target_platform="manylinux2014_x86_64",
        python_abi="cp312",
        files=tuple(files),
        learning_reader=learning_compat.READER_VERSION,
    )
    (release / "release-metadata.json").write_bytes(manifest.to_json_bytes())


def test_learning_backend_checks_candidate_bytes_before_exact_plan(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(learning_schema, "validate_candidate", lambda root: seen.append(("bytes", root)))
    backend = WorkerBackend()
    monkeypatch.setattr(backend, "_run_candidate", lambda contract, root, args: seen.append(("plan", args)))
    candidate = tmp_path / "candidate"
    backend.check_learning_schema(_contract(tmp_path), candidate)
    assert seen == [("bytes", candidate), ("plan", ["shell", "--command", learning_schema.PLAN_CHECK])]


def test_learning_backend_rejects_changed_bundle_before_candidate_execution(tmp_path, monkeypatch):
    def reject(_root):
        message = "Changed reviewed learning bundle"
        raise learning_schema.LearningSchemaError(message)

    monkeypatch.setattr(learning_schema, "validate_candidate", reject)
    backend = WorkerBackend()
    monkeypatch.setattr(backend, "_run_candidate", lambda *args, **kwargs: pytest.fail("Invalid candidate executed"))
    with pytest.raises(learning_schema.LearningSchemaError, match="Changed reviewed"):
        backend.check_learning_schema(_contract(tmp_path), tmp_path / "candidate")


def test_learning_apply_keeps_exact_bundle_lock_and_statement_bounds(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(operation_worker.subprocess, "run", lambda args, **kwargs: seen.append(args))
    WorkerBackend().migrate_learning_schema(_contract(tmp_path), tmp_path / "candidate")
    assert seen[0][-3:] == ["shell", "--command", learning_schema.MIGRATION_APPLY]
    assert "--setenv=PGOPTIONS=-c lock_timeout=2s -c statement_timeout=30s" in seen[0]


class LearningBackend(SchemaBackend):
    def __init__(self, *, fail_at=""):
        super().__init__(fail_at=fail_at)
        self.trace = []

    def prepare(self, contract, request, destination):
        FakeBackend.prepare(self, contract, request, destination)

    def ensure_learning_reader(self, contract, release, *, required=False):
        self.trace.append(("reader", required, self.stage))
        if required and (self.fail_at == "reader" or (self.fail_at == "reader_after" and self.migrated)):
            message = "learning_reader_required"
            raise OperationError(message)

    def check_learning_schema(self, contract, release):
        self.trace.append(("check",))
        if self.fail_at == "candidate":
            message = "Unapproved learning candidate"
            raise learning_schema.LearningSchemaError(message)

    def migrate_learning_schema(self, contract, release):
        self.trace.append(("migrate",))
        self.migrated = True
        self.stage = "expected"
        if self.fail_at == "migration":
            raise subprocess.CalledProcessError(1, ["exact-learning-bundle"])

    def check_concept_schema(self, contract, release):
        pytest.fail("Learning allowance fell through to generic concept preflight")

    def migrate_concept_schema(self, contract, release):
        pytest.fail("Learning allowance fell through to generic concept migration")

    def activate(self, contract, release_sha):
        self.trace.append(("activate",))
        return super().activate(contract, release_sha)


@pytest.fixture
def learning_operation(tmp_path, monkeypatch):
    contract = _contract(tmp_path)
    _seed(contract, migration_class="backward-compatible-schema")
    path = contract.registry_dir / "requests/42.json"
    request = read_json(path)
    disclosure = {
        **concept_disclosure(),
        "migration": learning_schema.MIGRATION,
        "migration_file_sha256": learning_schema.MIGRATION_SHA256,
    }
    request["schema_disclosure"] = disclosure
    atomic_write_json(path, request)
    # Isolate worker sequencing from the allowance's independently tested evidence
    # parser; no trusted deployment helper or database is invoked by this fixture.
    monkeypatch.setattr(operation_worker, "validate_disclosure", lambda value, **kwargs: value)
    monkeypatch.setattr(learning_schema, "audit_matches", audit_matches, raising=False)
    return contract, disclosure


@pytest.mark.parametrize(
    ("failure", "state", "migrated", "code"),
    [
        ("", "active", True, None),
        ("start", "failed", False, "schema_starting_state_mismatch"),
        ("reader", "failed", False, "learning_reader_required"),
        ("candidate", "failed", False, "schema_candidate_invalid"),
        ("evidence", "failed", False, "schema_candidate_invalid"),
        ("migration", "recovery_required", True, "operation_failed"),
        ("end", "recovery_required", True, "schema_ending_state_mismatch"),
        ("reader_after", "recovery_required", True, "learning_reader_required"),
    ],
)
def test_learning_worker_fails_closed_without_generic_fallback_or_redispatch(  # noqa: PLR0913 - Failure-state matrix.
    learning_operation,
    monkeypatch,
    failure,
    state,
    migrated,
    code,
):
    contract, disclosure = learning_operation
    backend = LearningBackend(fail_at=failure)

    def evidence(release, value):
        assert value == disclosure
        backend.trace.append(("evidence",))
        if failure == "evidence":
            message = "Rehearsal evidence differs from the release"
            raise learning_schema.LearningSchemaError(message)

    monkeypatch.setattr(learning_schema, "validate_build_evidence", evidence, raising=False)
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == state
    assert result["error_code"] == code
    assert backend.migrated is migrated
    assert (contract.release_root / "current").resolve().name == (NEW_SHA if state == "active" else OLD_SHA)
    assert run_operation(contract, "42", backend=backend) == result
    if migrated:
        assert backend.trace.index(("reader", True, "starting")) < backend.trace.index(("migrate",))
    if state == "active":
        assert backend.trace.index(("evidence",)) < backend.trace.index(("check",))
        assert backend.trace.index(("reader", True, "expected")) < backend.trace.index(("activate",))
        assert (
            read_json(contract.registry_dir / f"releases/{NEW_SHA}.json")["state_fingerprint"]
            == END["state_fingerprint"]
        )


def test_learning_worker_uses_real_frozen_allowance_bytes_and_evidence(tmp_path):
    import hashlib
    import json

    root = Path(__file__).resolve().parents[3]
    evidence = {
        "format_version": 1,
        "source_sha": NEW_SHA,
        "active_sha": OLD_SHA,
        "postgres_version": learning_schema.POSTGRES_VERSION,
        "migration_file_sha256": learning_schema.MIGRATION_SHA256,
        "delta_sha256": learning_schema.DELTA_SHA256,
        "required_learning_reader": 1,
        "ordinary_previous_reader_compatible": False,
        **dict.fromkeys(learning_schema.PRESERVATION_FIELDS, True),
    }
    packaged = (json.dumps(evidence, sort_keys=True, indent=2) + "\n").encode()
    contract = _contract(tmp_path)
    _seed(contract, migration_class="backward-compatible-schema")
    write_real_reader_fixture(contract.releases_dir / OLD_SHA)
    path = contract.registry_dir / "requests/42.json"
    request = read_json(path)
    request["schema_disclosure"] = {
        **concept_disclosure(),
        "migration": learning_schema.MIGRATION,
        "migration_file_sha256": learning_schema.MIGRATION_SHA256,
        "compatibility_smoke_sha256": learning_schema.COMPATIBILITY_SMOKE_SHA256,
        "postgresql_rehearsal_sha256": hashlib.sha256(packaged).hexdigest(),
    }
    atomic_write_json(path, request)

    class FrozenAllowanceBackend(LearningBackend):
        def prepare(self, contract, request, destination):
            super().prepare(contract, request, destination)
            write_real_reader_fixture(destination)
            for source in (root / "inspinia").glob("**/migrations/*"):
                if source.is_file() and source.suffix in {".py", ".json"}:
                    target = destination / source.relative_to(root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
            (destination / learning_schema.EVIDENCE_PATH).write_bytes(packaged)

        def ensure_learning_reader(self, contract, release, *, required=False):
            self.trace.append(("reader", required, self.stage))
            WorkerBackend.ensure_learning_reader(self, contract, release, required=required)

        def _run_candidate(self, contract, release, arguments, **kwargs):
            if arguments == ["shell", "--command", learning_schema.PLAN_CHECK]:
                self.trace.append(("exact_plan",))
            elif arguments == ["shell", "--command", learning_schema.MIGRATION_APPLY]:
                assert kwargs == {"migration": True}
                self.trace.append(("exact_apply",))
                self.migrated = True
                self.stage = "expected"
            else:
                pytest.fail("Unapproved candidate command")

        def check_learning_schema(self, contract, release):
            WorkerBackend.check_learning_schema(self, contract, release)

        def migrate_learning_schema(self, contract, release):
            WorkerBackend.migrate_learning_schema(self, contract, release)

    backend = FrozenAllowanceBackend()
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "active"
    assert backend.trace.index(("reader", True, "starting")) < backend.trace.index(("exact_apply",))
    assert backend.trace.index(("exact_plan",)) < backend.trace.index(("exact_apply",))
    assert backend.trace.index(("reader", True, "expected")) < backend.trace.index(("activate",))


@pytest.mark.parametrize(
    "defect", ["old_reader", "ineligible", "missing_eligibility", "changed_bytes", "wrong_identity"],
)
def test_learning_schema_refuses_incompatible_actual_recovery_baseline_before_ddl(
    learning_operation,
    monkeypatch,
    defect,
):
    import json

    contract, _disclosure = learning_operation
    baseline = contract.releases_dir / OLD_SHA
    if defect != "old_reader":
        write_real_reader_fixture(baseline)
    record_path = contract.registry_dir / f"releases/{OLD_SHA}.json"
    if defect in {"ineligible", "missing_eligibility"}:
        record = read_json(record_path)
        if defect == "ineligible":
            record["rollback_eligible"] = False
        else:
            record.pop("rollback_eligible")
        atomic_write_json(record_path, record)
    elif defect == "changed_bytes":
        guarded = baseline / next(iter(learning_compat.READER_SOURCES))
        guarded.write_bytes(guarded.read_bytes() + b"\n# Unreviewed reader change\n")
    elif defect == "wrong_identity":
        metadata = baseline / "release-metadata.json"
        value = json.loads(metadata.read_bytes())
        value["release_sha"] = NEW_SHA
        metadata.write_text(json.dumps(value))

    class RecoveryCheckBackend(LearningBackend):
        def ensure_learning_reader(self, contract, release, *, required=False):
            if required and release.name == OLD_SHA:
                return WorkerBackend.ensure_learning_reader(self, contract, release, required=True)
            return super().ensure_learning_reader(contract, release, required=required)

    monkeypatch.setattr(
        learning_schema,
        "validate_build_evidence",
        lambda *args: pytest.fail("Recovery eligibility must stop the operation before candidate DDL preflight"),
    )
    backend = RecoveryCheckBackend()
    result = run_operation(contract, "42", backend=backend)
    assert result["state"] == "failed"
    assert result["error_code"] == "learning_recovery_reader_required"
    assert backend.migrated is False
    assert ("activate",) not in backend.trace
    assert (contract.release_root / "current").resolve() == baseline
    assert not (contract.releases_dir / NEW_SHA).exists()
