# ruff: noqa: E402, EM101, PLR0915, S102, S603, TRY003
"""Rehearse only the frozen catalogue upgrade on the isolated pinned Actions DB."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment.catalogue_schema import INPUT_HASHES
from scripts.deployment.catalogue_schema import MIGRATION_APPLY
from scripts.deployment.catalogue_schema import TABLES
from scripts.deployment.catalogue_schema import behaviour_fingerprint
from scripts.deployment.catalogue_schema import behaviour_snapshot
from scripts.deployment.catalogue_schema import validate_behaviour_shape
from scripts.deployment.catalogue_schema import validate_candidate
from scripts.deployment.catalogue_schema import validate_rehearsal_evidence
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import POSTGRES_VERSION
from scripts.deployment.schema_rehearsal import _snapshot
from scripts.deployment.schema_rehearsal import configure_rehearsal_database
from scripts.deployment.schema_rehearsal import smoke_command

CONCEPT_COUNT = 1163

PRESERVED = (
    ("users", "User"), ("pages", "ProblemSolveRecord"), ("pages", "ContestProblemStatement"),
    ("pages", "StatementTopicTechnique"), ("pages", "UserProblemCompletion"),
    ("pages", "ProblemConceptAssignment"), ("pages", "ConceptAssignmentState"),
)


def record_values(apps):
    return {name: list(apps.get_model(app, name).objects.order_by("pk").values()) for app, name in PRESERVED}


def seed_existing_records(apps):
    user = apps.get_model("users", "User").objects.create(
        email="preserve@example.test", name="Catalogue rehearsal learner",
    )
    problem = apps.get_model("pages", "ProblemSolveRecord").objects.create(
        contest="SCHEMA REHEARSAL", year=2026, problem="P1", topic="ALG", mohs=20,
    )
    statement = apps.get_model("pages", "ContestProblemStatement").objects.create(
        linked_problem_id=problem.pk, problem_uuid=problem.problem_uuid,
        contest_name="SCHEMA REHEARSAL", contest_year=2026, problem_number=1, problem_code="P1",
        topic="ALG", statement_latex="Synthetic AM-GM statement.",
    )
    apps.get_model("pages", "StatementTopicTechnique").objects.create(
        statement_id=statement.pk, technique="AM-GM", main_topic="ALG", domains=["ALG"],
    )
    completion = apps.get_model("pages", "UserProblemCompletion")
    completion.objects.create(user_id=user.pk, problem_id=problem.pk, status="written", post_mortem="Retain notes.")
    completion.objects.create(user_id=user.pk, statement_id=statement.pk, status="attempted", time_spent_minutes=37)
    apps.get_model("pages", "ProblemConceptAssignment").objects.create(
        problem_uuid=problem.problem_uuid, concept_id="am-gm", disposition="accepted",
        source_fingerprint="0" * 64, concept_signature="1" * 64,
    )
    apps.get_model("pages", "ConceptAssignmentState").objects.create(singleton_key=1, enabled=False)


def verify_publication_and_invalidation():
    """Execute runtime paths with PostgreSQL triggers, including bulk SQL writes."""
    from django.db import connection

    from inspinia.pages.catalogue_models import CatalogueConcept
    from inspinia.pages.catalogue_models import CatalogueState
    from inspinia.pages.catalogue_snapshots import current_snapshot
    from inspinia.pages.catalogue_snapshots import rebuild_library_snapshot
    from inspinia.pages.catalogue_snapshots import user_progress_summary
    from inspinia.pages.concept_progress import build_concept_progress_context
    from inspinia.pages.models import ContestProblemStatement
    from inspinia.pages.models import UserProblemCompletion
    from inspinia.solutions.models import ProblemSolution
    from inspinia.users.models import User

    concept = CatalogueConcept.objects.get(pk="nt-powers-of-three")
    if not concept.redirect_id or CatalogueConcept.objects.count() != CONCEPT_COUNT:
        raise ValueError("Catalogue seed lost an existing concept identity")
    snapshot = rebuild_library_snapshot()
    user = User.objects.get(email="preserve@example.test")
    if snapshot.totals["c:am-gm"]["total"] != 1:
        raise ValueError("Published memberships differ from existing source coverage")
    summary = user_progress_summary(user, snapshot)
    if summary["c:am-gm"]["solved"] != 0:
        raise ValueError("Statement completion precedence was not preserved")
    UserProblemCompletion.objects.filter(statement__isnull=False).update(status=" WRITTEN ")
    if user_progress_summary(user, snapshot)["c:am-gm"]["solved"] != 1:
        raise ValueError("Derived personal progress did not reflect a bulk completion update")
    statement = ContestProblemStatement.objects.get()
    with connection.cursor() as cursor:
        cursor.execute("UPDATE pages_contestproblemstatement SET mohs=21 WHERE id=%s", [statement.pk])
    if current_snapshot() is not None:
        raise ValueError("Raw source SQL failed to invalidate the published snapshot")
    if not build_concept_progress_context(request_user=user, params={}).get("progress_unavailable"):
        raise ValueError("Stale progress must display the updating state")
    snapshot = rebuild_library_snapshot()
    before = CatalogueState.objects.get(pk=1).source_revision
    solution = ProblemSolution.objects.create(author=user, problem_id=statement.linked_problem_id, status="draft")
    if current_snapshot().pk != snapshot.pk or CatalogueState.objects.get(pk=1).source_revision != before:
        raise ValueError("Private draft evidence must not invalidate catalogue memberships")
    ProblemSolution.objects.filter(pk=solution.pk).update(status="published")
    if current_snapshot() is not None:
        raise ValueError("Published evidence must invalidate catalogue memberships")
    solution.delete()
    rebuild_library_snapshot()
    CatalogueConcept.objects.filter(pk="am-gm").update(description="Synthetic catalogue change")
    if current_snapshot() is not None:
        raise ValueError("Catalogue bulk updates must invalidate the published snapshot")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-source", type=Path, required=True)
    parser.add_argument("--active-sha", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    os.environ["DJANGO_READ_DOT_ENV_FILE"] = "false"
    from django.conf import settings

    configure_rehearsal_database(settings)
    import django

    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    if connection.pg_version != POSTGRES_VERSION or connection.introspection.table_names():
        raise ValueError("Catalogue rehearsal requires an empty isolated PostgreSQL 17.9 database")
    validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    targets = [n for n in executor.loader.graph.leaf_nodes() if n[0] != "pages"] + [
        ("pages", "0036_concept_assignment_reviews"),
    ]
    executor.migrate(targets)
    old_apps = executor.loader.project_state(targets).apps
    seed_existing_records(old_apps)
    before, records = _snapshot(connection), record_values(old_apps)
    empty_behaviour = behaviour_snapshot(connection)
    if empty_behaviour != {"functions": [], "triggers": []}:
        raise ValueError("Catalogue function or triggers already exist before upgrade")
    exec(MIGRATION_APPLY, {})
    after = _snapshot(connection)
    new_apps = MigrationExecutor(connection).loader.project_state().apps
    if record_values(new_apps) != records:
        raise ValueError("Catalogue upgrade changed an existing user, source, assignment or completion record")
    delta = {k: [r for r in rows if r.get("table") in TABLES] for k, rows in after.items()}
    previous = {k: [r for r in rows if r.get("table") not in TABLES] for k, rows in after.items()}
    if previous != before or {r["table"] for r in delta["tables"]} != TABLES:
        raise ValueError("Catalogue upgrade changed the previous schema or unexpected tables")
    behaviour = behaviour_snapshot(connection)
    validate_behaviour_shape(behaviour)
    subprocess.run(
        [sys.executable, "-c", smoke_command()], cwd=args.active_source,
        env={**os.environ, "PYTHONPATH": str(args.active_source.resolve())}, check=True,
    )
    if _snapshot(connection) != after or record_values(new_apps) != records:
        raise ValueError("Active-revision compatibility smoke changed schema or existing records")
    verify_publication_and_invalidation()
    # Reversal is exercised only on this synthetic database, never suggested as recovery.
    executor = MigrationExecutor(connection)
    executor.migrate([("pages", "0038_seed_catalogue")])
    if behaviour_snapshot(connection) != empty_behaviour:
        raise ValueError("Trigger uninstall failed on the disposable rehearsal database")
    MigrationExecutor(connection).migrate([("pages", "0039_catalogue_revision_triggers")])
    if behaviour_snapshot(connection) != behaviour:
        raise ValueError("Trigger reinstall produced different definitions")
    result = {
        "format_version": 1, "source_sha": args.release_sha, "active_sha": args.active_sha,
        "postgres_version": connection.pg_version, "input_hashes": INPUT_HASHES,
        "delta_sha256": schema_state(delta)["fingerprint"], "behaviour_sha256": behaviour_fingerprint(behaviour),
        "existing_schema_unchanged": True, "existing_records_unchanged": True,
        "active_revision_smoke_passed": True, "runtime_invalidation_passed": True,
        "trigger_uninstall_reinstall_passed": True,
    }
    validate_rehearsal_evidence(result, release_sha=args.release_sha, active_sha=args.active_sha)
    args.output.mkdir()
    for name, data in (("evidence", result), ("schema-delta", delta), ("behaviour", behaviour)):
        (args.output / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
