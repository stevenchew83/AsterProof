# ruff: noqa: EM101, PLR2004, S603, S102, TRY003
"""Exact additive learning allowance: real delta, bounded evidence and reader floor."""

import copy
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment import additive_schema
from scripts.deployment import learning_schema as schema
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import schema_state

ROOT = Path(__file__).resolve().parents[3]
ACTIVE_SHA = "a" * 40
TARGET_SHA = "b" * 40


def evidence_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def build_evidence():
    return {
        "format_version": 1,
        "source_sha": TARGET_SHA,
        "active_sha": ACTIVE_SHA,
        "postgres_version": schema.POSTGRES_VERSION,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "delta_sha256": schema.DELTA_SHA256,
        "required_learning_reader": schema.REQUIRED_LEARNING_READER,
        "ordinary_previous_reader_compatible": False,
        **dict.fromkeys(schema.PRESERVATION_FIELDS, True),
    }


def disclosure():
    return {
        "format_version": 1,
        "active_sha": ACTIVE_SHA,
        "target_sha": TARGET_SHA,
        "migration": schema.MIGRATION,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "starting": dict.fromkeys(schema.FINGERPRINT_FIELDS, "1" * 64),
        "expected": dict.fromkeys(schema.FINGERPRINT_FIELDS, "2" * 64),
        "postgresql_rehearsal_sha256": hashlib.sha256(evidence_bytes(build_evidence())).hexdigest(),
        "compatibility_smoke_sha256": schema.COMPATIBILITY_SMOKE_SHA256,
    }


def frozen_delta():
    return json.loads((Path(__file__).parent / "fixtures/learning-schema-delta.json").read_text())


def starting_audit():
    snapshot = {key: [] for key in ("tables", "columns", "constraints", "indexes", "extensions")}
    snapshot["tables"] = [{"schema": "public", "table": name, "kind": "r"} for name in schema.REQUIRED_BASE_TABLES]
    migrations = [list(node) for node in schema.REQUIRED_BASE_MIGRATIONS]
    state = {"schema": schema_state(snapshot), "migration": migration_state(migrations)}
    return {
        "server_version_num": schema.POSTGRES_VERSION,
        "catalog_snapshot": snapshot,
        "migration_rows": migrations,
        "state": state,
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
    }


def copy_candidate(destination):
    for source in (ROOT / "inspinia").rglob("*"):
        # The exact Learning allowance predates these separately reviewed successors.
        if (
            source.parent.name == "migrations" and source.suffix in {".py", ".json"}
            and source not in {
                ROOT / "inspinia/solutions/migrations/0013_solution_forum.py",
                ROOT / "inspinia/solutions/migrations/0014_admin_solution_review.py",
                ROOT / "inspinia/pages/migrations/0047_study_help.py",
                ROOT / "inspinia/rankings/migrations/0005_ranking_analysis_review.py",
                ROOT / "inspinia/rankings/migrations/0006_student_achievement_profiles.py",
            }
        ):
            target = destination / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())


def test_real_postgresql_delta_is_frozen_and_adds_only_empty_learning_schema():
    delta = frozen_delta()
    assert schema_state(delta)["fingerprint"] == schema.DELTA_SHA256
    assert {row["table"] for row in delta["tables"]} == schema.TABLES
    assert schema_state(delta)["counts"] == {
        "tables": 20,
        "columns": 172,
        "constraints": 119,
        "indexes": 104,
        "extensions": 0,
    }
    assert schema.REQUIRED_LEARNING_READER == 1
    assert len(schema.MIGRATIONS) == 4


def test_actual_learning_migration_bundle_and_entire_history_are_hash_bound(tmp_path):
    copy_candidate(tmp_path)
    schema.validate_candidate(tmp_path)
    target = tmp_path / next(iter(schema.MIGRATION_FILES))
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(schema.LearningSchemaError, match="migration bytes"):
        schema.validate_candidate(tmp_path)


@pytest.mark.parametrize(("app", "migration"), [
    ("solutions", "0013_solution_forum"),
    ("solutions", "0014_admin_solution_review"),
    ("pages", "0047_study_help"),
])
def test_successors_are_not_part_of_the_historical_learning_allowance(tmp_path, app, migration):
    copy_candidate(tmp_path)
    relative = f"inspinia/{app}/migrations/{migration}.py"
    (tmp_path / relative).write_bytes((ROOT / relative).read_bytes())
    with pytest.raises(schema.LearningSchemaError, match="Historical migration sources"):
        schema.validate_candidate(tmp_path)


@pytest.mark.parametrize("change", ["altered", "missing", "extra", "symlink"])
def test_prior_migration_sources_cannot_be_changed_or_expanded(tmp_path, change):
    copy_candidate(tmp_path)
    path = tmp_path / "inspinia/pages/migrations/0038_seed_catalogue.py"
    if change == "altered":
        path.write_bytes(path.read_bytes() + b"\n")
    elif change == "missing":
        path.unlink()
    elif change == "extra":
        path.with_name("9999_unreviewed.py").write_text("# unreviewed migration\n")
    else:
        path.unlink()
        path.symlink_to(ROOT / path.relative_to(tmp_path))
    with pytest.raises(schema.LearningSchemaError):
        schema.validate_candidate(tmp_path)


def test_exact_disclosure_routes_through_common_allowance_selector():
    value = disclosure()
    assert additive_schema.schema_for_disclosure(value) is schema
    assert additive_schema.validate_disclosure(value, target_sha=TARGET_SHA) == value


@pytest.mark.parametrize(
    "change",
    [
        {"format_version": True},
        {"extra": "unreviewed"},
        {"active_sha": TARGET_SHA},
        {"target_sha": ACTIVE_SHA},
        {"migration_file_sha256": "0" * 64},
        {"compatibility_smoke_sha256": "0" * 64},
        {"postgresql_rehearsal_sha256": None},
        {"migration": "learning.9999_unapproved"},
    ],
)
def test_disclosure_rejects_changed_scope_identity_and_evidence(change):
    with pytest.raises(schema.LearningSchemaError):
        schema.validate_disclosure({**disclosure(), **change}, target_sha=TARGET_SHA)


def test_each_starting_and_expected_fingerprint_must_change():
    value = disclosure()
    for key in schema.FINGERPRINT_FIELDS:
        changed = copy.deepcopy(value)
        changed["expected"][key] = changed["starting"][key]
        with pytest.raises(schema.LearningSchemaError):
            schema.validate_disclosure(changed, target_sha=TARGET_SHA)


def test_without_real_delta_even_well_formed_disclosure_is_closed(monkeypatch):
    monkeypatch.setattr(schema, "DELTA_SHA256", None)
    with pytest.raises(schema.LearningSchemaError, match="production schema allowance is unavailable"):
        schema.validate_disclosure(disclosure(), target_sha=TARGET_SHA)


def test_audit_matching_requires_exact_runtime_and_each_bound_fingerprint():
    value = disclosure()
    audit = {"server_version_num": schema.POSTGRES_VERSION, **value["starting"]}
    assert schema.audit_matches(value, audit, stage="starting")
    assert not schema.audit_matches(value, audit, stage="expected")
    assert not schema.audit_matches(value, {**audit, "server_version_num": 170010}, stage="starting")
    assert not schema.audit_matches(value, audit, stage="unknown")
    assert not schema.audit_matches(value, {}, stage="starting")


def test_only_release_bound_postgresql_evidence_is_accepted(tmp_path):
    path = tmp_path / schema.EVIDENCE_PATH
    path.write_bytes(evidence_bytes(build_evidence()))
    schema.validate_build_evidence(tmp_path, disclosure())
    # This is the real precommit report's intentional limitation, not an immutable release identity.
    value = {**build_evidence(), "source_sha": None}
    content = evidence_bytes(value)
    path.write_bytes(content)
    bound = {**disclosure(), "postgresql_rehearsal_sha256": hashlib.sha256(content).hexdigest()}
    with pytest.raises(schema.LearningSchemaError):
        schema.validate_build_evidence(tmp_path, bound)


@pytest.mark.parametrize("field", schema.PRESERVATION_FIELDS)
@pytest.mark.parametrize("value", [False, 1, None])
def test_preservation_flags_require_literal_true(tmp_path, field, value):
    report = {**build_evidence(), field: value}
    content = evidence_bytes(report)
    (tmp_path / schema.EVIDENCE_PATH).write_bytes(content)
    bound = {**disclosure(), "postgresql_rehearsal_sha256": hashlib.sha256(content).hexdigest()}
    with pytest.raises(schema.LearningSchemaError):
        schema.validate_build_evidence(tmp_path, bound)


@pytest.mark.parametrize(
    "change",
    [
        {"ordinary_previous_reader_compatible": True},
        {"ordinary_previous_reader_compatible": 0},
        {"required_learning_reader": True},
        {"required_learning_reader": 0},
        {"postgres_version": 170010},
        {"active_sha": TARGET_SHA},
        {"delta_sha256": "0" * 64},
        {"engine": "sqlite"},
        {"candidate_evidence_requires_review": True},
    ],
)
def test_evidence_cannot_claim_old_reader_compatibility_or_different_release(tmp_path, change):
    content = evidence_bytes({**build_evidence(), **change})
    (tmp_path / schema.EVIDENCE_PATH).write_bytes(content)
    bound = {**disclosure(), "postgresql_rehearsal_sha256": hashlib.sha256(content).hexdigest()}
    with pytest.raises(schema.LearningSchemaError):
        schema.validate_build_evidence(tmp_path, bound)


def test_packaged_evidence_digest_and_no_symlink_are_enforced(tmp_path):
    path = tmp_path / schema.EVIDENCE_PATH
    path.write_bytes(evidence_bytes({**build_evidence(), "source_sha": "c" * 40}))
    with pytest.raises(schema.LearningSchemaError, match="digest"):
        schema.validate_build_evidence(tmp_path, disclosure())
    path.unlink()
    source = tmp_path / "outside.json"
    source.write_bytes(evidence_bytes(build_evidence()))
    path.symlink_to(source)
    with pytest.raises(schema.LearningSchemaError):
        schema.validate_build_evidence(tmp_path, disclosure())


def test_expected_audit_adds_exactly_four_migrations_and_preserves_starting_input():
    start = starting_audit()
    original = copy.deepcopy(start)
    result = schema.expected_catalog_audit(start, frozen_delta())
    assert (
        result["migration_fingerprint"]
        == migration_state(
            [
                *start["migration_rows"],
                *[list(node) for node in schema.MIGRATIONS],
            ],
        )["fingerprint"]
    )
    assert result["schema_fingerprint"] != start["state"]["schema"]["fingerprint"]
    assert start == original


@pytest.mark.parametrize("change", ["default", "nullable", "column", "table", "index", "extension"])
def test_any_changed_catalog_delta_is_rejected(change):
    delta = frozen_delta()
    if change == "index":
        delta["indexes"][0]["name"] = "unreviewed"
    elif change == "extension":
        delta["extensions"] = [{"name": "unapproved", "version": "1"}]
    else:
        delta["columns"][0][change] = {
            "default": "false",
            "nullable": not delta["columns"][0]["nullable"],
            "column": "unreviewed",
            "table": "users_user",
        }[change]
    with pytest.raises(schema.LearningSchemaError):
        schema.expected_catalog_audit(starting_audit(), delta)


@pytest.mark.parametrize("change", ["version", "state", "prior", "already_applied", "existing_table", "missing_table"])
def test_unknown_starting_catalog_baseline_fails_closed(change):
    start = starting_audit()
    if change == "version":
        start["server_version_num"] = 170010
    elif change == "state":
        start["state_fingerprint"] = "0" * 64
    elif change == "prior":
        start["migration_rows"].pop()
    elif change == "already_applied":
        start["migration_rows"].append(list(schema.MIGRATIONS[0]))
    elif change == "existing_table":
        start["catalog_snapshot"]["tables"].append(
            {"schema": "public", "table": next(iter(schema.TABLES)), "kind": "r"},
        )
    else:
        start["catalog_snapshot"]["tables"].pop()
    with pytest.raises(schema.LearningSchemaError):
        schema.expected_catalog_audit(start, frozen_delta())


def plan_executor(monkeypatch, *, changed=False, content=False, floor=True):
    operations = [
        (
            SimpleNamespace(
                app_label=app,
                name=name,
                operations=[type(operation, (), {})() for operation in sequence],
            ),
            False,
        )
        for (app, name), sequence in zip(schema.MIGRATIONS, schema.OPERATION_SEQUENCES, strict=True)
    ]
    if changed:
        operations[0][0].operations.reverse()
        operations.append((SimpleNamespace(app_label="users", name="unapproved", operations=[]), False))
    migrated = []
    executor = SimpleNamespace(
        loader=SimpleNamespace(graph=SimpleNamespace(leaf_nodes=lambda: list(schema.MIGRATIONS))),
        migration_plan=lambda targets: operations,
        migrate=lambda targets: migrated.append(targets),
    )

    class Cursor:
        last = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, sql):
            self.last = sql

        def fetchone(self):
            return ((1 if content else 0),) if "count(*)" in self.last else (floor,)

    connection = SimpleNamespace(
        vendor="postgresql",
        pg_version=schema.POSTGRES_VERSION,
        cursor=Cursor,
        ops=SimpleNamespace(quote_name=lambda table: '"' + table + '"'),
    )
    monkeypatch.setattr("django.db.connection", connection)
    monkeypatch.setattr("django.db.migrations.executor.MigrationExecutor", lambda connection: executor)
    return migrated


def test_frozen_plan_remains_fail_closed_under_optimized_python(monkeypatch):
    migrated = plan_executor(monkeypatch)
    exec(compile(schema.MIGRATION_APPLY, "<learning-apply>", "exec", optimize=2), {})
    assert migrated == [list(schema.MIGRATIONS)]
    plan_executor(monkeypatch, changed=True)
    with pytest.raises(RuntimeError, match="Unapproved"):
        exec(compile(schema.PLAN_CHECK, "<learning-plan>", "exec", optimize=2), {})


@pytest.mark.parametrize(("content", "floor"), [(True, True), (False, False)])
def test_runtime_apply_requires_empty_new_tables_and_durable_reader_floor(monkeypatch, content, floor):
    plan_executor(monkeypatch, content=content, floor=floor)
    with pytest.raises(RuntimeError):
        exec(compile(schema.MIGRATION_APPLY, "<learning-apply>", "exec", optimize=2), {})


def test_classification_explicitly_limits_recovery_to_verified_learning_readers():
    from scripts.deployment.migration_plan import load_registry

    registry = load_registry(ROOT / "deployment/migration-classifications.yml")
    for app, name in schema.MIGRATIONS:
        entry = registry[f"{app}.{name}"]
        assert entry["classification"] == "backward-compatible-schema"
        assert entry["code_rollback_permitted"] is True
        assert "verified_learning_reader_for_activation_and_recovery" in entry["data_preconditions"]
        assert "ordinary previous reader is incompatible" in entry["rationale"]


def test_sqlite_upgrade_preserves_sources_progress_solutions_and_subscribers(tmp_path):
    database, report = tmp_path / "learning.sqlite3", tmp_path / "report.json"
    # Exercise the current rehearsal against its historical source boundary.
    # Keep the trusted validator exact; later migrations are out of scope.
    source = tmp_path / "historical-source"
    for package in ("config", "inspinia", "scripts"):
        shutil.copytree(
            ROOT / package, source / package,
            ignore=shutil.ignore_patterns(
                "__pycache__", "static", "0013_solution_forum.py", "0005_ranking_analysis_review.py",
                "0006_student_achievement_profiles.py", "0014_admin_solution_review.py", "0047_study_help.py",
            ),
        )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.deployment.learning_schema_rehearsal",
            "--sqlite",
            str(database),
            "--output",
            str(report),
        ],
        cwd=source,
        env={**os.environ, "DJANGO_READ_DOT_ENV_FILE": "false", "PYTHONPATH": str(source)},
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr[-6000:]
    evidence = json.loads(report.read_text())
    assert evidence["production_release_qualified"] is False
    assert evidence["historical_records_unchanged"] is True
    assert evidence["old_schema_objects_unchanged"] is True
    assert evidence["historical_sequences_unchanged"] is True
    assert evidence["empty_schema_reader_floor"] is True
    assert evidence["historical_tables_checked"] > len(evidence["new_tables"])
    assert "learning_contentdocument" in evidence["new_tables"]
    with sqlite3.connect(database) as connection:
        counts = {
            table: connection.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0]  # noqa: S608
            for table in COMMUNITY_TABLES
        }
        assert counts == {
            "pages_communityproblem": 5,
            "pages_communityattempt": 5,
            "pages_communitycontentreport": 5,
            "pages_communityprivateasset": 5,
            "pages_communityproblemrevision": 10,
            "pages_communitysolution": 5,
            "pages_communitysolutionasset": 10,
            "pages_communitysolutionrevision": 10,
            "pages_moderationevent": 21,
            "pages_problempublication": 5,
        }
        assert {
            table: connection.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0]  # noqa: S608
            for table in ASSESSMENT_TABLES
        } == {
            "solutions_problemevaluationpackage": 1,
            "solutions_evaluationpackageapproval": 2,
            "solutions_syntheticreview": 1,
            "solutions_synthetichintreveal": 1,
        }
    # Run the exact source-smoke checks too; SQLite remains explicitly non-release evidence.
    smoke = subprocess.run(
        [sys.executable, "-c", schema.smoke_command({"ENGINE": "django.db.backends.sqlite3", "NAME": str(database)})],
        cwd=source,
        env={
            **os.environ, "DJANGO_READ_DOT_ENV_FILE": "false", "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "PYTHONPATH": str(source),
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert smoke.returncode == 0, smoke.stderr[-6000:]


COMMUNITY_TABLES = {
    "pages_communityproblem",
    "pages_communityattempt",
    "pages_communitycontentreport",
    "pages_communityprivateasset",
    "pages_communityproblemrevision",
    "pages_communitysolution",
    "pages_communitysolutionasset",
    "pages_communitysolutionrevision",
    "pages_moderationevent",
    "pages_problempublication",
}


def refresh_starting_fingerprints(start):
    start["state"] = {
        "schema": schema_state(start["catalog_snapshot"]),
        "migration": migration_state(start["migration_rows"]),
    }
    start["state_fingerprint"] = hashlib.sha256(canonical_json(start["state"])).hexdigest()


def test_learning_baseline_requires_community_before_its_four_migrations():
    assert schema.BASE_TARGETS[0] == ("pages", "0045_community_proof_library")
    assert schema.MIGRATIONS[0] == ("pages", "0046_prerequisitegraphstate_catalogueprerequisite")
    assert schema.PRIOR_MIGRATION_SOURCE_COUNT == 95
    assert COMMUNITY_TABLES <= schema.REQUIRED_BASE_TABLES
    assert not COMMUNITY_TABLES & schema.TABLES


@pytest.mark.parametrize("table", sorted(COMMUNITY_TABLES))
def test_learning_start_rejects_each_missing_community_table_even_with_valid_fingerprints(table):
    start = starting_audit()
    start["catalog_snapshot"]["tables"] = [row for row in start["catalog_snapshot"]["tables"] if row["table"] != table]
    refresh_starting_fingerprints(start)
    with pytest.raises(schema.LearningSchemaError, match="required preserved tables"):
        schema.expected_catalog_audit(start, frozen_delta())


def test_learning_start_rejects_missing_community_migration_even_with_community_tables():
    start = starting_audit()
    start["migration_rows"].remove(["pages", "0045_community_proof_library"])
    refresh_starting_fingerprints(start)
    with pytest.raises(schema.LearningSchemaError, match="previous migration baseline"):
        schema.expected_catalog_audit(start, frozen_delta())


def test_community_migration_is_an_immutable_historical_learning_input(tmp_path):
    copy_candidate(tmp_path)
    path = tmp_path / "inspinia/pages/migrations/0045_community_proof_library.py"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(schema.LearningSchemaError, match="Historical migration sources"):
        schema.validate_candidate(tmp_path)


def test_binary_preservation_digest_accounts_for_blob_bytes():
    from scripts.deployment.learning_schema_rehearsal import _rows_digest

    assert _rows_digest([(b"private original",)]) == _rows_digest([(memoryview(b"private original"),)])
    assert _rows_digest([(b"private original",)]) != _rows_digest([(b"public replacement",)])


def test_reviewed_smoke_and_actual_rehearsal_share_exact_read_only_checks():
    from scripts.deployment.learning_schema_rehearsal import old_reader_smoke

    assert old_reader_smoke() == schema.smoke_command()
    assert "CommunityPrivateAsset" in schema.smoke_command()
    assert "Previous Community held/withdrawn proof visibility changed" in schema.smoke_command()


ASSESSMENT_TABLES = {
    "solutions_problemevaluationpackage",
    "solutions_evaluationpackageapproval",
    "solutions_syntheticreview",
    "solutions_synthetichintreveal",
}


def test_learning_requires_both_assessment_migrations_as_preserved_history():
    assert ("solutions", "0011_problem_evaluation_packages") in schema.REQUIRED_BASE_MIGRATIONS
    assert ("solutions", "0012_synthetic_review_prototype") in schema.REQUIRED_BASE_MIGRATIONS
    assert ASSESSMENT_TABLES <= schema.REQUIRED_BASE_TABLES
    assert not ASSESSMENT_TABLES & schema.TABLES


@pytest.mark.parametrize("table", sorted(ASSESSMENT_TABLES))
def test_learning_rejects_each_missing_assessment_table_even_with_valid_fingerprints(table):
    start = starting_audit()
    start["catalog_snapshot"]["tables"] = [row for row in start["catalog_snapshot"]["tables"] if row["table"] != table]
    refresh_starting_fingerprints(start)
    with pytest.raises(schema.LearningSchemaError, match="required preserved tables"):
        schema.expected_catalog_audit(start, frozen_delta())


@pytest.mark.parametrize("migration", ["0011_problem_evaluation_packages", "0012_synthetic_review_prototype"])
def test_learning_rejects_missing_assessment_migrations_even_with_all_tables(migration):
    start = starting_audit()
    start["migration_rows"].remove(["solutions", migration])
    refresh_starting_fingerprints(start)
    with pytest.raises(schema.LearningSchemaError, match="previous migration baseline"):
        schema.expected_catalog_audit(start, frozen_delta())


@pytest.mark.parametrize("migration", ["0011_problem_evaluation_packages", "0012_synthetic_review_prototype"])
def test_assessment_migrations_are_immutable_historical_learning_inputs(tmp_path, migration):
    copy_candidate(tmp_path)
    path = tmp_path / "inspinia/solutions/migrations" / (migration + ".py")
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(schema.LearningSchemaError, match="Historical migration sources"):
        schema.validate_candidate(tmp_path)
