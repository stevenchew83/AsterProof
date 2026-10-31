# ruff: noqa: E402, EM101, S102, S603, TRY003
"""Disposable release-build PostgreSQL proof; never a production migration command."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment.concept_schema import DELTA_SHA256
from scripts.deployment.concept_schema import MIGRATION_APPLY
from scripts.deployment.concept_schema import MIGRATION_SHA256
from scripts.deployment.concept_schema import TABLES
from scripts.deployment.concept_schema import validate_candidate
from scripts.deployment.migration_audit import SCHEMA_SQL
from scripts.deployment.schema_fingerprint import schema_state

FIELDS = {
    "tables": ("schema", "table", "kind"),
    "columns": ("schema", "table", "position", "column", "type", "nullable", "default", "collation"),
    "constraints": ("schema", "table", "name", "type", "definition"),
    "indexes": ("schema", "table", "name", "definition"),
    "extensions": ("name", "version"),
}
POSTGRES_VERSION = 170009
REHEARSAL_URL = "postgres://postgres@127.0.0.1:5432/asterproof_schema_rehearsal"
REHEARSAL_DATABASE = {
    "ENGINE": "django.db.backends.postgresql",
    "HOST": "127.0.0.1",
    "PORT": "5432",
    "NAME": "asterproof_schema_rehearsal",
    "USER": "postgres",
    "PASSWORD": "",
}
SMOKE = """
import django
django.setup()
from django.core.management import call_command
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.statement_concept_coverage import statement_coverage_payloads
from inspinia.pages.concept_analytics import library_coverage_rows
call_command('check')
call_command('migrate', check=True, verbosity=0)
statement = ContestProblemStatement.objects.get(contest_name='SCHEMA REHEARSAL')
if not statement_coverage_payloads([statement])[statement.pk]['concept_coverage']:
    raise RuntimeError('Active revision statement coverage failed')
rows, options = library_coverage_rows({'contest':'','year':''})
if len(rows)!=1 or not next(iter(rows.values()))['concept_coverage']:
    raise RuntimeError('Active revision library coverage failed')
"""


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-source", type=Path, required=True)
    parser.add_argument("--active-sha", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def configure_rehearsal_database(settings):
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("DATABASE_URL") != REHEARSAL_URL:
        raise ValueError("Rehearsal requires its exact isolated Actions database target")
    # Test settings intentionally force SQLite; DATABASE_URL alone does not select PostgreSQL.
    settings.DATABASES = {"default": REHEARSAL_DATABASE.copy()}
    settings.CONCEPT_ASSIGNMENTS_ENABLED = False


def smoke_command():
    # The active revision has the same SQLite test default; configure its fresh process explicitly.
    return (
        "from django.conf import settings\n"
        f"settings.DATABASES = {{'default': {REHEARSAL_DATABASE!r}}}\n"
        "settings.CONCEPT_ASSIGNMENTS_ENABLED = False\n" + SMOKE
    )



def _snapshot(connection):
    result = {}
    with connection.cursor() as cursor:
        for category, query in SCHEMA_SQL.items():
            cursor.execute(query)
            result[category] = [dict(zip(FIELDS[category], row, strict=True)) for row in cursor.fetchall()]
    return result


def _approved_rehearsal(disclosed_migration):  # noqa: PLR0911 - Only literal, reviewed rehearsal imports.
    if disclosed_migration == "solutions.0006_solution_share_daily_views":
        from scripts.deployment.solution_analytics_schema_rehearsal import run

        return run
    if disclosed_migration == "solutions.0005_solutionpublicshare":
        from scripts.deployment.solution_sharing_schema_rehearsal import run

        return run
    # Every dispatch target is a literal import from the approved source.
    if disclosed_migration == "website.0003_newsletter_automation":
        from scripts.deployment.newsletter_automation_rehearsal import run

        return run
    if disclosed_migration == "users.0009_user_solution_guide_status":
        from scripts.deployment.onboarding_schema_rehearsal import run

        return run
    if disclosed_migration == "solutions.0004_solution_pdf_display_options":
        from scripts.deployment.solution_pdf_schema_rehearsal import run

        return run
    if disclosed_migration == "website.0002_newsletter_campaigns":
        from scripts.deployment.newsletter_schema_rehearsal import run

        return run
    if disclosed_migration == "website.0001_initial":
        from scripts.deployment.website_schema_rehearsal import run

        return run
    return None


def main():
    args = _arguments()
    migration = json.loads(os.environ.get("SCHEMA_DISCLOSURE") or "{}").get("migration")
    rehearsal = _approved_rehearsal(migration)
    if rehearsal is not None:
        return rehearsal(args)
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    os.environ["DJANGO_READ_DOT_ENV_FILE"] = "false"
    from django.conf import settings

    configure_rehearsal_database(settings)
    import django

    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    from inspinia.pages.models import ContestProblemStatement
    from inspinia.pages.models import ProblemSolveRecord
    from inspinia.pages.models import StatementTopicTechnique

    if connection.pg_version != POSTGRES_VERSION:
        raise ValueError("Pinned rehearsal PostgreSQL version does not match production")
    if connection.introspection.table_names():
        raise ValueError("Rehearsal database must be empty")
    validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    targets = [n for n in executor.loader.graph.leaf_nodes() if n[0] != "pages"] + [
        ("pages", "0035_techniquebenchmark_curriculum_class_and_more"),
    ]
    executor.migrate(targets)
    problem = ProblemSolveRecord.objects.create(
        contest="SCHEMA REHEARSAL", year=2026, problem="P1", topic="ALG", mohs=20,
    )
    statement = ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_name="SCHEMA REHEARSAL",
        contest_year=2026,
        problem_number=1,
        problem_code="P1",
        topic="A",
        statement_latex="Synthetic AM-GM statement.",
    )
    StatementTopicTechnique.objects.create(statement=statement, technique="AM-GM", main_topic="ALG", domains=["ALG"])

    def source_content():
        return json.dumps(
            [
                list(m.objects.order_by("pk").values())
                for m in (
                    ProblemSolveRecord,
                    ContestProblemStatement,
                    StatementTopicTechnique,
                )
            ],
            sort_keys=True,
            default=str,
        )

    before, content = _snapshot(connection), source_content()
    exec(MIGRATION_APPLY, {})
    after = _snapshot(connection)
    delta = {category: [row for row in rows if row.get("table") in TABLES] for category, rows in after.items()}
    previous = {category: [row for row in rows if row.get("table") not in TABLES] for category, rows in after.items()}
    if previous != before or source_content() != content:
        raise ValueError("Rehearsal changed an existing schema object or source fixture")
    if schema_state(delta)["fingerprint"] != DELTA_SHA256:
        raise ValueError("PostgreSQL catalog delta differs from the reviewed additive schema")
    smoke_env = {**os.environ, "PYTHONPATH": str(args.active_source.resolve())}
    subprocess.run([sys.executable, "-c", smoke_command()], cwd=args.active_source, env=smoke_env, check=True)
    if _snapshot(connection) != after or source_content() != content:
        raise ValueError("Active revision smoke changed schema or the source fixture")
    args.output.write_text(
        json.dumps(
            {
                "format_version": 1,
                "source_sha": args.release_sha,
                "active_sha": args.active_sha,
                "postgres_version": connection.pg_version,
                "migration_file_sha256": MIGRATION_SHA256,
                "delta_sha256": DELTA_SHA256,
                "existing_schema_unchanged": True,
                "source_fixture_unchanged": True,
                "active_revision_smoke_passed": True,
            },
            indent=2,
        )
        + "\n",
    )
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
