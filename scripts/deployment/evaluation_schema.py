"""Exact local-only evaluation schema rehearsal; this grants no production migration authority."""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_NAME = "0010_offline_evaluation_contract"
MIGRATION_PATH = Path("inspinia/solutions/migrations") / f"{MIGRATION_NAME}.py"
MIGRATION_SHA256 = "9fee1f590a8cdde9df9d30c201a49caea20a5c31efe2f4b0aa7c92171d4844a8"
BASELINE_NAME = "0009_problemsolution_edit_version_solutionreviewpolicy_and_more"
BASELINE_SHA256 = "c942e9376aaf99417debf7d1ef2cf76719652b581e21087b674b06a8046d161c"
MODELS = (
    "EvaluationLifecycle", "ReviewerProfile", "ActivationAuthorization", "AssistancePolicy",
    "EvaluationAuditEvent", "EvaluationDatasetSnapshot", "EvaluationProblemFamily", "EvaluationRun",
    "ReadinessEvidence", "ReviewConsent", "ReviewInputBundle", "ReviewExecutionAttempt", "ReviewBundleAsset",
    "EvaluationCase", "EvaluationAssignment", "CoachJudgment", "EvaluationFindingJudgment", "HintRevealEvent",
    "ReviewSpendEvent",
)
TABLES = frozenset(f"solutions_{name.lower()}" for name in MODELS)
POSTGRES_VERSION = 170009
MAX_EVIDENCE_BYTES = 8192


class EvaluationSchemaError(ValueError):
    """The exact rehearsal contract or disposable-target boundary was violated."""


def fingerprint(value) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_candidate(root: Path = ROOT) -> None:
    migration = root / MIGRATION_PATH
    baseline = root / MIGRATION_PATH.parent / f"{BASELINE_NAME}.py"
    for path, expected in ((migration, MIGRATION_SHA256), (baseline, BASELINE_SHA256)):
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise EvaluationSchemaError("Migration bytes differ from the frozen local evaluation contract.")
    tree = ast.parse(migration.read_text())
    definition = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "Migration")
    operations = next(item.value for item in definition.body if isinstance(item, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "operations" for target in item.targets))
    shape = []
    for operation in operations.elts:
        if not isinstance(operation, ast.Call) or not isinstance(operation.func, ast.Attribute):
            raise EvaluationSchemaError("Only the frozen CreateModel operations are permitted.")
        name = next((ast.literal_eval(value.value) for value in operation.keywords if value.arg == "name"), None)
        shape.append((operation.func.attr, name))
    if shape != [("CreateModel", name) for name in MODELS]:
        raise EvaluationSchemaError("Only the frozen CreateModel operations are permitted.")


def validate_plan(plan) -> None:
    actual = [
        (migration.app_label, migration.name, backwards,
         [(type(operation).__name__, getattr(operation, "name", None)) for operation in migration.operations])
        for migration, backwards in plan
    ]
    expected = [("solutions", MIGRATION_NAME, False, [("CreateModel", name) for name in MODELS])]
    if actual != expected:
        raise EvaluationSchemaError("The pending migration plan differs from the single frozen evaluation migration.")


def validate_connection(connection) -> None:
    database = connection.settings_dict
    if connection.vendor == "sqlite":
        path = Path(database["NAME"])
        if (
            not path.is_absolute() or path.resolve() != path or path.name != "rehearsal.sqlite3"
            or not path.parent.name.startswith("asterproof-evaluation-schema-") or not path.parent.is_dir()
        ):
            raise EvaluationSchemaError("SQLite rehearsal requires its automatically-created scratch database.")
    elif connection.vendor == "postgresql":
        from scripts.deployment.schema_rehearsal import REHEARSAL_DATABASE
        from scripts.deployment.schema_rehearsal import REHEARSAL_URL

        if (
            os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("DATABASE_URL") != REHEARSAL_URL
            or any(database.get(key) != value for key, value in REHEARSAL_DATABASE.items())
        ):
            raise EvaluationSchemaError("PostgreSQL rehearsal requires the exact disposable Actions database.")
    else:
        raise EvaluationSchemaError("Only the disposable SQLite or pinned PostgreSQL rehearsal is supported.")


def preserved_state(connection, tables):
    """Hash only synthetic rows; compare exact old column, constraint, trigger and sequence state."""
    rows, columns, constraints = {}, {}, {}
    with connection.cursor() as cursor:
        for table in sorted(tables - {"django_migrations"}):
            quoted = connection.ops.quote_name(table)
            cursor.execute(f"SELECT * FROM {quoted}")  # noqa: S608 - introspected and quoted local table
            rows[table] = fingerprint(sorted(fingerprint(row) for row in cursor.fetchall()))
            columns[table] = [tuple(item) for item in connection.introspection.get_table_description(cursor, table)]
            constraints[table] = connection.introspection.get_constraints(cursor, table)
        cursor.execute("SELECT id, app, name, applied FROM django_migrations ORDER BY id")
        migrations = cursor.fetchall()
        if connection.vendor == "sqlite":
            cursor.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name")
            triggers = cursor.fetchall()
            cursor.execute("SELECT name,seq FROM sqlite_sequence WHERE name <> 'django_migrations' ORDER BY name")
            sequences = cursor.fetchall()
        else:
            from scripts.deployment.newsletter_schema_rehearsal import existing_sequences
            from scripts.deployment.solution_collections_schema_rehearsal import trigger_definitions

            triggers, sequences = trigger_definitions(connection), existing_sequences(connection)
    return {
        "rows": rows, "columns": columns, "constraints": constraints,
        "triggers": triggers, "sequences": sequences, "migrations": migrations,
    }


def seed_legacy(executor, targets, connection) -> None:
    """Create genuine synthetic blocks, document revisions, public shares and a preserved trigger."""
    from scripts.deployment.newsletter_schema_rehearsal import seed_fixture
    from scripts.deployment.newsletter_schema_rehearsal import seed_subscribers
    from scripts.deployment.solution_collections_schema_rehearsal import seed_shared_snapshots
    from scripts.deployment.solution_collections_schema_rehearsal import seed_solution
    from scripts.deployment.solution_document_schema_rehearsal import seed_collections

    apps = executor.loader.project_state(targets).apps
    seed_fixture()
    seed_subscribers()
    seed_solution(apps)
    seed_shared_snapshots(apps)
    seed_collections(apps)
    solution = apps.get_model("solutions", "ProblemSolution").objects.get(title="Synthetic preserved solution")
    source = "Synthetic immutable document before the evaluation migration."
    revision = apps.get_model("solutions", "SolutionRevision").objects.create(
        solution_id=solution.pk, sequence=1, body_source=source,
        source_digest=hashlib.sha256(source.encode()).hexdigest(),
    )
    solution.current_revision_id, solution.edit_version = revision.pk, 7
    solution.save(update_fields=["current_revision_id", "edit_version"])
    apps.get_model("solutions", "SolutionReviewPolicy").objects.create()
    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            cursor.execute("CREATE TRIGGER evaluation_preserve_legacy AFTER UPDATE ON solutions_problemsolution "
                           "BEGIN SELECT 1; END")
        else:
            cursor.execute("CREATE FUNCTION evaluation_preserve_legacy_fn() RETURNS trigger LANGUAGE plpgsql "
                           "AS $$ BEGIN RETURN NEW; END $$")
            cursor.execute("CREATE TRIGGER evaluation_preserve_legacy BEFORE UPDATE ON solutions_problemsolution "
                           "FOR EACH ROW EXECUTE FUNCTION evaluation_preserve_legacy_fn()")


def verify_preservation(connection, old_tables, before) -> None:
    from django.db import transaction

    if set(connection.introspection.table_names()) - old_tables != TABLES:
        raise EvaluationSchemaError("The migration did not create exactly the frozen evaluation tables.")
    if not old_tables.issubset(connection.introspection.table_names()):
        raise EvaluationSchemaError("The migration removed an existing table.")
    after = preserved_state(connection, old_tables)
    for key in ("rows", "columns", "constraints", "triggers", "sequences"):
        if before[key] != after[key]:
            raise EvaluationSchemaError(f"The evaluation migration changed existing {key}.")
    if (
        after["migrations"][:-1] != before["migrations"]
        or len(after["migrations"]) != len(before["migrations"]) + 1
        or after["migrations"][-1][1:3] != ("solutions", MIGRATION_NAME)
        or after["migrations"][-1][0] != before["migrations"][-1][0] + 1
    ):
        raise EvaluationSchemaError("Only the single evaluation migration recorder row may be appended.")
    with transaction.atomic(using=connection.alias):
        connection.check_constraints()
    with connection.cursor() as cursor:
        for table in sorted(TABLES):
            cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table)}")  # noqa: S608
            if cursor.fetchone()[0]:
                raise EvaluationSchemaError("New evidence tables must remain empty after schema-only migration.")
        cursor.execute("SELECT enabled,daily_budget_micros,monthly_budget_micros FROM solutions_solutionreviewpolicy")
        if cursor.fetchall() != [(False, 0, 0)]:
            raise EvaluationSchemaError("The synthetic policy must remain disabled and unfunded.")


def rehearse(connection, *, root: Path = ROOT, source_sha: str = "local-worktree", active_sha: str = "local-baseline"):
    from django.db.migrations.executor import MigrationExecutor

    validate_candidate(root)
    validate_connection(connection)
    authoritative = connection.vendor == "postgresql"
    if authoritative and connection.pg_version != POSTGRES_VERSION:
        raise EvaluationSchemaError("Authoritative rehearsal requires PostgreSQL 17.9.")
    if connection.introspection.table_names():
        raise EvaluationSchemaError("Rehearsal refuses a nonempty database; it never reads existing application data.")
    executor = MigrationExecutor(connection)
    # Keep the historical pages baseline: Study Help's later pages leaf
    # depends on a newer solutions migration and would overshoot this fixture.
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] not in {"pages", "solutions"}]
    targets.extend([("pages", "0046_prerequisitegraphstate_catalogueprerequisite"), ("solutions", BASELINE_NAME)])
    executor.migrate(targets)
    seed_legacy(executor, targets, connection)
    old_tables = set(connection.introspection.table_names())
    before = preserved_state(connection, old_tables)
    executor = MigrationExecutor(connection)
    # This historical rehearsal exercises only its frozen migration, even after
    # newer solution migrations exist. Production PLAN_CHECK still rejects any
    # pending migration outside its exact release allowance.
    validate_plan(executor.migration_plan([("solutions", MIGRATION_NAME)]))
    executor.migrate([("solutions", MIGRATION_NAME)])
    verify_preservation(connection, old_tables, before)
    report = {
        "format_version": 1, "source_sha": source_sha, "active_sha": active_sha,
        "migration": f"solutions.{MIGRATION_NAME}", "migration_file_sha256": MIGRATION_SHA256,
        "baseline_migration_file_sha256": BASELINE_SHA256,
        "operation_count": len(MODELS), "new_tables": sorted(TABLES),
        "engine": connection.vendor, "postgres_version": connection.pg_version if authoritative else None,
        "verification_status": "postgresql_rehearsal_passed" if authoritative else "local_sqlite_smoke_passed",
        "authoritative_postgresql_rehearsal": authoritative,
        "existing_records_unchanged": True, "existing_columns_unchanged": True,
        "existing_constraints_and_foreign_keys_unchanged": True,
        "existing_triggers_unchanged": True, "existing_sequences_unchanged": True,
        "foreign_keys_valid": True, "new_tables_empty": True, "ai_disabled_and_unfunded": True,
        "exact_new_tables_created": True, "single_migration_record_appended": True,
        "preserved_fixture_digest": fingerprint({key: before[key] for key in before if key != "migrations"}),
        "production_migration_authorized": False, "engineering_readiness_established": False,
        "active_code_smoke": "not_run", "model_readiness": False,
    }
    if len(json.dumps(report).encode()) > MAX_EVIDENCE_BYTES:
        raise EvaluationSchemaError("Schema evidence exceeds its bounded contract.")
    return report


def run(args) -> int:
    # This process never inherits a deployment environment or provider activation.
    os.environ.update(DJANGO_SETTINGS_MODULE="config.settings.test", DJANGO_READ_DOT_ENV_FILE="false",
                      OPENAI_API_KEY="", SOLUTION_AI_REVIEW_ENABLED="false", SOLUTION_AI_EXECUTION_MODE="offline")
    from django.conf import settings

    with tempfile.TemporaryDirectory(prefix="asterproof-evaluation-schema-") as temporary:
        scratch = Path(temporary).resolve()
        settings.MEDIA_ROOT = str(scratch / "media")
        settings.SOLUTION_AI_REVIEW_ENABLED = False
        settings.SOLUTION_AI_EXECUTION_MODE = "offline"
        if args.sqlite:
            settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                                               "NAME": str(scratch / "rehearsal.sqlite3")}}
        else:
            from scripts.deployment.schema_rehearsal import configure_rehearsal_database

            configure_rehearsal_database(settings)
        import django

        django.setup()
        from django.db import connection

        report = rehearse(connection, source_sha=args.release_sha, active_sha=args.active_sha)
        if connection.vendor == "postgresql":
            from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
            from scripts.deployment.schema_rehearsal import _snapshot

            snapshot = normalize_schema_snapshot(_snapshot(connection))
            delta = {field: [row for row in rows if row.get("table") in TABLES]
                     for field, rows in snapshot.items()}
            args.output.with_name("evaluation-schema-delta.json").write_text(
                json.dumps(delta, sort_keys=True, indent=2) + "\n",
            )
        connection.close()
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", action="store_true", help="Run a smoke on an automatically-created scratch DB.")
    parser.add_argument("--active-source", type=Path, help="CI baseline checked for the frozen 0009 migration.")
    parser.add_argument("--active-sha", default="local-baseline")
    parser.add_argument("--release-sha", default="local-worktree")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.sqlite and any(not re.fullmatch(r"[0-9a-f]{40}", value)
                               for value in (args.active_sha, args.release_sha)):
        parser.error("Authoritative CI evidence requires exact active and release commit IDs.")
    if args.active_source:
        path = args.active_source / MIGRATION_PATH.parent / f"{BASELINE_NAME}.py"
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != BASELINE_SHA256:
            parser.error("The active baseline lacks the exact document-compatible migration.")
    try:
        return run(args)
    except (EvaluationSchemaError, ValueError) as error:
        parser.exit(2, f"Evaluation schema rehearsal not verified: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
