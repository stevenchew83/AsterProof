"""Runnable, isolated SQLite preservation rehearsal; never production evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment import learning_schema as schema
from scripts.deployment.learning_compat import FLOOR_TABLES


def _rows_digest(rows):
    def scalar(value):
        return bytes(value).hex() if isinstance(value, (bytes, bytearray, memoryview)) else str(value)

    encoded = sorted(json.dumps(row, default=scalar, sort_keys=True) for row in rows)
    return hashlib.sha256("\n".join(encoded).encode()).hexdigest()


def _records(connection, tables):
    result = {}
    with connection.cursor() as cursor:
        for table in sorted(tables):
            if table == "django_migrations":
                continue
            cursor.execute(f"SELECT * FROM {connection.ops.quote_name(table)}")  # noqa: S608
            rows = cursor.fetchall()
            result[table] = {"count": len(rows), "digest": _rows_digest(rows)}
    return result


def _schema(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY 1,2")
        return cursor.fetchall()


def _sequences(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT name,seq FROM sqlite_sequence WHERE name <> 'django_migrations' ORDER BY name")
        return dict(cursor.fetchall())


def _seed(apps):
    """Only synthetic records; historical models avoid current write-side hooks."""
    from django.utils import timezone

    user = apps.get_model("users", "User").objects.create(
        email="synthetic@example.invalid",
        password="!",  # noqa: S106 - Unusable password in an isolated synthetic fixture.
    )
    for label in ("algebra", "geometry", "number-theory", "combinatorics", "foundations"):
        topic, _ = apps.get_model("training", "Topic").objects.get_or_create(
            slug=label,
            defaults={"title": label},
        )
        subtopic = apps.get_model("training", "Subtopic").objects.create(
            topic=topic,
            title=f"Synthetic {label}",
            slug="learning-preservation",
        )
        material = apps.get_model("training", "Material").objects.create(
            subtopic=subtopic,
            title=f"Synthetic preserved {label}",
            slug=f"learning-preserved-{label}",
            content_markdown="Synthetic original lecture $a+b$.",
        )
        completion = apps.get_model("training", "MaterialCompletion").objects.create(
            user=user,
            material=material,
            points_awarded=10,
        )
        apps.get_model("training", "PointLedger").objects.create(
            user=user,
            source_type="material_completion",
            source_id=str(completion.pk),
            points=10,
            reason="Synthetic historical award",
        )
        problem = apps.get_model("training", "Problem").objects.create(
            subtopic=subtopic,
            title="Synthetic exercise",
            slug=f"learning-practice-{label}",
            statement_markdown="Synthetic original practice.",
        )
        submission = apps.get_model("training", "Submission").objects.create(
            user=user,
            problem=problem,
            solution_markdown="Synthetic private student response.",
        )
        apps.get_model("training", "SubmissionComment").objects.create(
            submission=submission,
            author=user,
            body_markdown="Synthetic private feedback.",
        )
        if label != "foundations":
            area = apps.get_model("website", "LibraryArea").objects.create(
                subject=label,
                title="Synthetic historical area",
                slug="learning-preserved",
                is_published=True,
            )
            concept = apps.get_model("website", "LibraryConcept").objects.create(
                area=area,
                title="Synthetic historical concept",
                slug="learning-preserved",
                is_published=True,
            )
            apps.get_model("website", "LibraryLecture").objects.create(
                concept=concept,
                title="Synthetic historical lecture",
                slug="learning-preserved",
                body_markdown="Synthetic public historical explanation.",
                is_published=True,
            )
    apps.get_model("website", "NewsletterSubscriber").objects.create(
        email="synthetic-subscriber@example.invalid",
        requested_at=timezone.now(),
        status="confirmed",
    )
    problem = apps.get_model("pages", "ProblemSolveRecord").objects.create(
        contest="LEARNING REHEARSAL",
        year=2026,
        problem="P1",
        topic="ALG",
    )
    solution = apps.get_model("solutions", "ProblemSolution").objects.create(
        author=user,
        problem=problem,
        title="Synthetic preserved solution",
    )
    apps.get_model("solutions", "ProblemSolutionBlock").objects.create(
        solution=solution,
        position=1,
        body_source="Synthetic private original proof.",
    )
    apps.get_model("solutions", "SolutionPublicShare").objects.create(
        solution=solution,
        is_active=True,
        source_updated_at=timezone.now(),
        snapshot={"title": "Synthetic preserved share", "body": "Synthetic fixed public copy."},
    )


def rehearse(connection):
    from django.db.migrations.executor import MigrationExecutor

    if connection.vendor != "sqlite" or connection.introspection.table_names():
        message = "The local learning rehearsal requires a new, empty SQLite database."
        raise ValueError(message)
    schema.validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    baseline = [
        node for node in executor.loader.graph.leaf_nodes() if node[0] not in {"learning", "pages", "training"}
    ]
    baseline += list(schema.BASE_TARGETS)
    executor.migrate(baseline)
    _seed(executor.loader.project_state(baseline).apps)
    tables = set(connection.introspection.table_names())
    before_schema = _schema(connection)
    before_records = _records(connection, tables)
    before_sequences = _sequences(connection)
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    actual = [(migration.app_label, migration.name, backwards) for migration, backwards in plan]
    if actual != [(app, name, False) for app, name in schema.MIGRATIONS]:
        message = "The pending learning migration bundle differs from the exact local plan."
        raise ValueError(message)
    executor.migrate(executor.loader.graph.leaf_nodes())
    after_schema = _schema(connection)
    if any(row not in after_schema for row in before_schema):
        message = "Learning migrations changed an existing SQLite schema object."
        raise ValueError(message)
    if before_records != _records(connection, tables):
        message = "Learning migrations changed historical source, progress, solution or subscriber rows."
        raise ValueError(message)
    after_sequences = _sequences(connection)
    if any(after_sequences.get(key) != value for key, value in before_sequences.items()):
        message = "Learning migrations changed a historical sequence."
        raise ValueError(message)
    new_tables = set(connection.introspection.table_names()) - tables
    if not set(FLOOR_TABLES).issubset(new_tables):
        message = "The complete empty learning schema must establish the durable reader floor."
        raise ValueError(message)
    if any(value["count"] for value in _records(connection, new_tables).values()):
        message = "The additive migration unexpectedly generated learning content."
        raise ValueError(message)
    return {
        "format_version": 1,
        "engine": "sqlite",
        "production_release_qualified": False,
        "migration_bundle_sha256": schema.MIGRATION_SHA256,
        "old_schema_objects_unchanged": True,
        "historical_records_unchanged": True,
        "historical_sequences_unchanged": True,
        "empty_schema_reader_floor": True,
        "historical_tables_checked": len(before_records),
        "new_tables": sorted(new_tables),
        "requires": ["pinned_postgresql_17_9", "previous_release_smoke", "trusted_allowance_installation"],
    }


def _postgres_floor(connection):
    from scripts.deployment.learning_compat import FLOOR_SQL

    with connection.cursor() as cursor:
        cursor.execute(FLOOR_SQL)
        return cursor.fetchone() == (True,)


def _public_routines(connection):
    """Preserve helper routines too, including functions not directly bound to triggers."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT n.nspname,p.oid::regprocedure::text,pg_get_functiondef(p.oid) "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.prokind IN ('f','p') ORDER BY 1,2",
        )
        return cursor.fetchall()


def old_reader_smoke():
    """The previous release reads preserved material and its fixed public copy."""
    from scripts.deployment.schema_rehearsal import REHEARSAL_DATABASE

    return f"""from django.conf import settings
settings.DATABASES={{'default': {REHEARSAL_DATABASE!r}}}
settings.CONCEPT_ASSIGNMENTS_ENABLED=False
import django
django.setup()
from django.core.management import call_command
from inspinia.training.models import Material,MaterialCompletion,PointLedger,Submission
from inspinia.solutions.models import ProblemSolution,SolutionPublicShare
from inspinia.website.models import LibraryLecture,NewsletterSubscriber
call_command('check')
if Material.objects.filter(slug__startswith='learning-preserved-').count() != 5:
    raise RuntimeError('Previous Training reader lost a subject or Foundations')
if MaterialCompletion.objects.count() != 5 or PointLedger.objects.count() != 5 or Submission.objects.count() != 5:
    raise RuntimeError('Previous Training progress identity changed')
if LibraryLecture.objects.filter(slug='learning-preserved',is_published=True).count() != 4:
    raise RuntimeError('Previous public lecture reader changed')
solution=ProblemSolution.objects.get(title='Synthetic preserved solution')
if solution.blocks.get().body_source != 'Synthetic private original proof.':
    raise RuntimeError('Previous solution reader changed')
if SolutionPublicShare.objects.get(solution=solution).snapshot.get('body') != 'Synthetic fixed public copy.':
    raise RuntimeError('Previous public solution snapshot changed')
if NewsletterSubscriber.objects.get(email='synthetic-subscriber@example.invalid').status != 'confirmed':
    raise RuntimeError('Previous subscriber state changed')
"""


def rehearse_postgresql(connection, args):  # noqa: C901, PLR0915 - Keep the preservation evidence in one ordered rehearsal.
    """Generate candidate CI evidence; a later review freezes its exact delta."""
    from django.db.migrations.executor import MigrationExecutor

    from scripts.deployment.newsletter_schema_rehearsal import existing_sequences
    from scripts.deployment.newsletter_schema_rehearsal import migration_metadata
    from scripts.deployment.schema_fingerprint import schema_state
    from scripts.deployment.schema_rehearsal import _snapshot
    from scripts.deployment.solution_collections_schema_rehearsal import trigger_definitions

    if connection.vendor != "postgresql" or connection.pg_version != schema.POSTGRES_VERSION:
        message = "Learning release rehearsal requires the pinned PostgreSQL 17.9 runtime."
        raise ValueError(message)
    if connection.introspection.table_names():
        message = "The isolated PostgreSQL learning rehearsal database must be empty."
        raise ValueError(message)
    schema.validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    baseline = [
        node for node in executor.loader.graph.leaf_nodes() if node[0] not in {"learning", "pages", "training"}
    ]
    baseline += list(schema.BASE_TARGETS)
    executor.migrate(baseline)
    _seed(executor.loader.project_state(baseline).apps)
    tables = set(connection.introspection.table_names())
    before_schema = _snapshot(connection)
    before_records = _records(connection, tables)
    before_sequences = existing_sequences(connection)
    before_triggers = trigger_definitions(connection)
    before_routines = _public_routines(connection)
    before_metadata, before_sequence = migration_metadata(connection)
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    actual = [(migration.app_label, migration.name, backwards) for migration, backwards in plan]
    if actual != [(app, name, False) for app, name in schema.MIGRATIONS]:
        message = "The PostgreSQL learning migration plan differs from the exact bundle."
        raise ValueError(message)
    executor.migrate(executor.loader.graph.leaf_nodes())
    after_schema = _snapshot(connection)
    if any(row not in after_schema[key] for key, rows in before_schema.items() for row in rows):
        message = "Learning migration changed an existing PostgreSQL schema object."
        raise ValueError(message)
    new_tables = set(connection.introspection.table_names()) - tables
    delta = {key: [row for row in rows if row not in before_schema[key]] for key, rows in after_schema.items()}
    if delta["extensions"] or any(
        row.get("table") not in new_tables for key, rows in delta.items() if key != "extensions" for row in rows
    ):
        message = "Learning migration altered an object outside the new tables."
        raise ValueError(message)
    after_metadata, after_sequence = migration_metadata(connection)
    if (
        after_metadata[: len(before_metadata)] != before_metadata
        or [(row[1], row[2]) for row in after_metadata[len(before_metadata) :]] != list(schema.MIGRATIONS)
        or after_sequence != before_sequence + len(schema.MIGRATIONS)
    ):
        message = "Learning migration changed historical migration metadata."
        raise ValueError(message)
    after_sequences = existing_sequences(connection)
    if any(row not in after_sequences for row in before_sequences):
        message = "Learning migration changed a historical PostgreSQL sequence."
        raise ValueError(message)
    if (
        before_records != _records(connection, tables)
        or before_triggers != trigger_definitions(connection)
        or before_routines != _public_routines(connection)
    ):
        message = "Learning migration changed historical records or trigger/function definitions."
        raise ValueError(message)
    if not _postgres_floor(connection) or any(value["count"] for value in _records(connection, new_tables).values()):
        message = "The empty installed learning schema did not establish its reader floor."
        raise ValueError(message)
    subprocess.run(  # noqa: S603 - Fixed read-only synthetic smoke in the selected previous checkout.
        [sys.executable, "-c", old_reader_smoke()],
        cwd=args.active_source,
        env={**os.environ, "PYTHONPATH": str(args.active_source.resolve())},
        check=True,
        timeout=90,
    )
    if (
        _snapshot(connection) != after_schema
        or _records(connection, tables) != before_records
        or before_triggers != trigger_definitions(connection)
        or before_routines != _public_routines(connection)
        or not _postgres_floor(connection)
    ):
        message = "The previous-release smoke changed preserved state."
        raise ValueError(message)
    args.delta_output.write_text(json.dumps(delta, sort_keys=True, indent=2) + "\n")
    return {
        "format_version": 1,
        "postgres_version": connection.pg_version,
        "source_sha": args.release_sha,
        "active_sha": args.active_sha,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "delta_sha256": schema_state(delta)["fingerprint"],
        "existing_schema_unchanged": True,
        "source_fixture_unchanged": True,
        "existing_records_unchanged": True,
        "existing_sequences_unchanged": True,
        "existing_trigger_definitions_unchanged": True,
        "active_revision_smoke_passed": True,
        "new_learning_tables_empty": True,
        "empty_schema_reader_floor": True,
        "ordinary_previous_reader_compatible": False,
        "required_learning_reader": 1,
    }


def run(args):
    """Entry point for the existing fixed-schema CI dispatcher."""
    database = args.sqlite.absolute() if getattr(args, "sqlite", None) else None
    if (database and (database.exists() or database.is_symlink())) or args.output.exists() or args.output.is_symlink():
        message = "Use new database and output paths; the rehearsal never replaces existing files."
        raise ValueError(message)
    os.environ["DJANGO_READ_DOT_ENV_FILE"] = "false"
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    from django.conf import settings

    if database:
        settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(database)}}
    else:
        from scripts.deployment.schema_rehearsal import configure_rehearsal_database

        if not args.active_source or not args.active_sha or not args.release_sha:
            message = "PostgreSQL mode requires the exact previous source and both release SHAs."
            raise ValueError(message)
        args.delta_output = getattr(args, "delta_output", None) or args.output.with_name("learning-schema-delta.json")
        if args.delta_output.exists() or args.delta_output.is_symlink():
            message = "Use a new PostgreSQL candidate-delta output path."
            raise ValueError(message)
        configure_rehearsal_database(settings)
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.LEARNING_MODULE_ENABLED = False
    settings.LEARNING_CONTRIBUTIONS_ENABLED = False
    settings.LEARNING_PUBLICATION_ENABLED = False
    import django

    django.setup()
    from django.db import connection

    try:
        report = rehearse(connection) if database else rehearse_postgresql(connection, args)
        args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    finally:
        connection.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--delta-output", type=Path)
    parser.add_argument("--active-source", type=Path)
    parser.add_argument("--active-sha")
    parser.add_argument("--release-sha")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
