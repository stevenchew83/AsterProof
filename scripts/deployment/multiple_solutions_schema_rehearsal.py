# ruff: noqa: E402, EM101, S102, S603, SLF001, TRY003
"""Rehearse the frozen multiple-solutions maintenance plan on disposable PostgreSQL 17.9."""

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts.deployment import catalogue_schema
from scripts.deployment import community_proof_schema
from scripts.deployment import database_recovery as recovery
from scripts.deployment import multiple_solutions_preservation as preservation
from scripts.deployment import multiple_solutions_schema as schema
from scripts.deployment.schema_rehearsal import REHEARSAL_DATABASE
from scripts.deployment.schema_rehearsal import _snapshot
from scripts.deployment.schema_rehearsal import configure_rehearsal_database
from scripts.deployment.solution_pdf_schema_rehearsal import trigger_definitions

LOCAL_DATABASE = "asterproof_0017_allowance_rehearsal"
LOCAL_PORT = 54897


def local_database(path):
    path = path.resolve()
    if (
        path.parent != Path("/private/tmp") or not path.name.startswith("asterproof-multi-pg17.")
        or not stat.S_ISSOCK((path / f".s.PGSQL.{LOCAL_PORT}").stat().st_mode)
    ):
        raise ValueError("Local rehearsal requires a dedicated temporary PostgreSQL Unix socket")
    return {
        "ENGINE": "django.db.backends.postgresql", "NAME": LOCAL_DATABASE,
        "HOST": str(path), "PORT": LOCAL_PORT, "USER": "stevenchew",
    }


def privileges(connection):
    queries = (
        "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls "
        "FROM pg_roles ORDER BY 1",
        "SELECT roleid,member,grantor,admin_option,inherit_option,set_option FROM pg_auth_members ORDER BY 1,2,3",
        "SELECT nspname,nspacl::text FROM pg_namespace ORDER BY 1",
        "SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY 1,2,3",
        "SELECT relname,relkind,relacl::text FROM pg_class WHERE relnamespace='public'::regnamespace "
        "AND relkind IN ('r','p','S','v','m','f') ORDER BY 1,2",
        "SELECT c.relname,a.attname,a.attacl::text FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
        "WHERE c.relnamespace='public'::regnamespace AND c.relkind IN ('r','p','v','m','f') AND a.attnum>0 "
        "AND NOT a.attisdropped AND NOT (c.relname='solutions_problemsolution' AND a.attname='additional_draft_key') "
        "ORDER BY 1,2",
        "SELECT proname,pg_get_function_identity_arguments(oid),proacl::text FROM pg_proc "
        "WHERE pronamespace='public'::regnamespace ORDER BY 1,2",
    )
    with connection.cursor() as cursor:
        result = []
        for query in queries:
            cursor.execute(query)
            result.append(cursor.fetchall())
    return result


def seed(executor, targets):
    from django.utils import timezone

    apps = executor.loader.project_state(targets).apps
    author = apps.get_model("users", "User").objects.create(email="multiple-solutions-rehearsal@example.invalid")
    problem = apps.get_model("pages", "ProblemSolveRecord").objects.create(
        contest="MULTIPLE SOLUTIONS REHEARSAL", year=2026, problem="P1",
    )
    completion = apps.get_model("pages", "UserProblemCompletion").objects.create(user=author, problem=problem)
    original = apps.get_model("solutions", "ProblemSolution").objects.create(
        author=author, problem=problem, title="Original preserved proof",
    )
    apps.get_model("solutions", "ProblemSolutionBlock").objects.create(
        solution=original, position=1, body_source="Original legacy block.",
    )
    source = "Original preserved document."
    revision = apps.get_model("solutions", "SolutionRevision").objects.create(
        solution=original, sequence=1, title=original.title, body_source=source,
        source_digest=hashlib.sha256(source.encode()).hexdigest(),
    )
    original.current_revision_id, original.edit_version = revision.pk, 1
    original.save(update_fields=["current_revision", "edit_version"])
    apps.get_model("solutions", "SolutionBodyImage").objects.create(
        solution=original, uploaded_by=author, file="solution_body_images/preserved.png",
    )
    share = apps.get_model("solutions", "SolutionPublicShare").objects.create(
        solution=original, is_active=True, snapshot={"title": original.title}, source_updated_at=timezone.now(),
    )
    return original.pk, str(revision.pk), str(share.token), completion.pk


def capture(connection, reader):
    connection.ensure_connection()
    raw = connection.connection
    with raw.transaction():
        with raw.cursor() as cursor:
            recovery._set_readonly(cursor)
        return reader(raw)


def active_reader(args, database, fixture):
    smoke = f"""from django.conf import settings
settings.DATABASES = {{'default': {database!r}}}
import django
django.setup()
from django.db import connection, transaction
from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions.models import ProblemSolution, SolutionPublicShare
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='30s'")
    original = ProblemSolution.objects.get(pk={fixture[0]!r})
    if (original.title, str(original.current_revision_id), original.current_revision.body_source) != (
        'Original preserved proof', {fixture[1]!r}, 'Original preserved document.',
    ):
        raise RuntimeError('Original solution differs in the active reader')
    if (str(SolutionPublicShare.objects.get(solution=original, is_active=True).token) != {fixture[2]!r}
        or original.body_images.get().file.name != 'solution_body_images/preserved.png'
        or UserProblemCompletion.objects.get(pk={fixture[3]!r}).problem_id != original.problem_id):
        raise RuntimeError('Original share, image or completion differs in the active reader')
"""
    subprocess.run(
        [sys.executable, "-c", smoke], cwd=args.active_source, check=True, timeout=60,
        env={**os.environ, "PYTHONPATH": str(args.active_source.resolve())},
    )


def probe_drafts(fixture):
    from django.db import IntegrityError
    from django.db import close_old_connections
    from django.db import transaction

    from inspinia.pages.models import UserProblemCompletion
    from inspinia.solutions.models import ProblemSolution

    original = ProblemSolution.objects.get(pk=fixture[0])
    identity = {"author_id": original.author_id, "problem_id": original.problem_id}
    key = uuid.uuid4()

    def create(_):
        close_old_connections()
        try:
            draft, created = ProblemSolution.objects.get_or_create(**identity, additional_draft_key=key)
            return draft.pk, created, draft.status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as workers:
        attempts = list(workers.map(create, range(2)))
    if (
        len({item[0] for item in attempts}) != 1 or sum(item[1] for item in attempts) != 1
        or any(item[2] != ProblemSolution.Status.DRAFT for item in attempts)
        or ProblemSolution.objects.filter(**identity).count() != len(attempts)
    ):
        raise ValueError("Concurrent creation did not reuse exactly one new private draft")
    try:
        with transaction.atomic():
            ProblemSolution.objects.create(**identity)
    except IntegrityError:
        pass
    else:
        raise ValueError("The original slot admitted a duplicate")
    if (
        str(original.public_share.token) != fixture[2]
        or UserProblemCompletion.objects.filter(
            problem_id=original.problem_id, user_id=original.author_id,
        ).count() != 1
    ):
        raise ValueError("A new draft affected the original public share or completion")


def rehearse(connection, args, database):  # noqa: C901 - Keep the ordered preservation gates together.
    from django.db.migrations.executor import MigrationExecutor

    if connection.vendor != "postgresql" or connection.pg_version != schema.POSTGRES_VERSION:
        raise ValueError("Expected PostgreSQL 17.9")
    if args.local_socket_dir:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_user, inet_server_addr(), current_setting('data_directory')",
            )
            name, role, address, directory = cursor.fetchone()
        if (name, role, address, Path(directory).resolve()) != (
            LOCAL_DATABASE, database["USER"], None, args.local_socket_dir.resolve() / "data",
        ):
            raise ValueError("Unexpected local rehearsal identity")
    if connection.introspection.table_names():
        raise ValueError("Rehearsal database must be empty")
    if args.active_sha != schema.ACTIVE_SHA or not schema.SHA.fullmatch(args.release_sha):
        raise ValueError("Rehearsal source identities differ from the frozen scope")
    if args.active_sha == args.release_sha:
        raise ValueError("Rehearsal requires a distinct candidate")
    if schema.migration_tree_sha256(args.active_source) != schema.PRIOR_TREE_SHA256:
        raise ValueError("Active migration tree differs from the frozen history")
    schema.validate_candidate(Path.cwd())
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    prior = [schema.PREVIOUS if node == schema.MIGRATION_NODE else node for node in targets]
    executor.migrate(prior)
    fixture = seed(executor, prior)
    before_catalog = _snapshot(connection)
    before = capture(connection, recovery.capture_manifest)
    behavior = community_proof_schema.behaviour_snapshot(connection)
    triggers, grants = trigger_definitions(connection), privileges(connection)
    if catalogue_schema.behaviour_fingerprint(behavior) != schema.BEHAVIOUR_SHA256:
        raise ValueError("Rehearsal baseline trigger behavior differs")
    exec(schema.MIGRATION_APPLY, {})
    after_catalog = _snapshot(connection)
    delta = community_proof_schema.catalog_delta(before_catalog, after_catalog)
    if delta != schema.frozen_delta(Path.cwd()):
        raise ValueError("Rehearsed delta differs from the frozen PostgreSQL catalog delta")
    active_reader(args, database, fixture)
    preservation.compare_preserved(before, capture(connection, preservation.capture_preservation))
    if (
        community_proof_schema.behaviour_snapshot(connection) != behavior
        or trigger_definitions(connection) != triggers or privileges(connection) != grants
    ):
        raise ValueError("Migration or compatibility probe changed database behavior or privileges")
    connection.check_constraints()
    probe_drafts(fixture)
    content = schema.evidence_bytes(release_sha=args.release_sha, active_sha=args.active_sha)
    if args.local_socket_dir:
        value = json.loads(content)
        value["purpose"] = "local-rehearsal"
        content = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    args.output.write_bytes(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--active-source", type=Path, required=True)
    parser.add_argument("--active-sha", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-socket-dir", type=Path)
    args = parser.parse_args()

    os.environ.update(DJANGO_SETTINGS_MODULE="config.settings.test", DJANGO_READ_DOT_ENV_FILE="false")
    from django.conf import settings

    if args.local_socket_dir:
        database = local_database(args.local_socket_dir)
        settings.DATABASES = {"default": database}
    else:
        configure_rehearsal_database(settings)
        database = REHEARSAL_DATABASE
    settings.SOLUTION_AI_REVIEW_ENABLED = False
    settings.SOLUTION_AI_EXECUTION_MODE = "offline"
    import django

    django.setup()
    from django.db import connection

    rehearse(connection, args, database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
