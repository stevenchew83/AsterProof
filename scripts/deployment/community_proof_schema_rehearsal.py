# ruff: noqa: E402, EM101, S102, S603, TRY003
"""Pinned disposable PostgreSQL proof for the Community Proof Library migration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

from scripts.deployment import catalogue_schema
from scripts.deployment import community_proof_schema as schema
from scripts.deployment.newsletter_schema_rehearsal import migration_metadata
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.newsletter_schema_rehearsal import seed_fixture
from scripts.deployment.newsletter_schema_rehearsal import seed_subscribers
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_rehearsal import REHEARSAL_DATABASE
from scripts.deployment.schema_rehearsal import REHEARSAL_URL
from scripts.deployment.schema_rehearsal import _snapshot
from scripts.deployment.solution_pdf_schema_rehearsal import trigger_definitions
from scripts.deployment.statement_reports_schema_rehearsal import seed_shared_snapshots
from scripts.deployment.statement_reports_schema_rehearsal import seed_solution

OLD_PROBLEM_PROJECTION = (
    "to_jsonb(source) - ARRAY['embargo_until','legacy_member_visible',"
    "'public_hint','solution_known']::text[]"
)
LEGACY_FIXTURE_ROWS = 2


def migration_sources(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "inspinia").rglob("*")
        if path.parent.name == "migrations" and path.suffix in {".py", ".json"}
        and path.relative_to(root).as_posix() not in schema.INPUT_HASHES
    }


def existing_records(connection):
    """Hash every old row's original columns, excluding only four approved additions."""
    records = {}
    for table in sorted(connection.introspection.table_names()):
        if table == "django_migrations" or table in schema.TABLES:
            continue
        expression = OLD_PROBLEM_PROJECTION if table == schema.TABLE else "to_jsonb(source)"
        digest = hashlib.sha256()
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT ({expression})::text FROM {connection.ops.quote_name(table)} source "  # noqa: S608
                f'ORDER BY ({expression})::text COLLATE "C"',
            )
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    digest.update(row[0].encode())
                    digest.update(b"\0")
        records[table] = digest.hexdigest()
    return records


def existing_sequences(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT schemaname,sequencename,last_value FROM pg_catalog.pg_sequences "
            "WHERE schemaname='public' AND sequencename::text <> ALL(%s) ORDER BY 1,2",
            [["django_migrations_id_seq", "pages_problempublication_id_seq"]],
        )
        return cursor.fetchall()


def privilege_snapshot(connection):
    """Capture ACL/role metadata only in the empty, isolated CI database."""
    queries = {
        "roles": "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,"
                 "rolreplication,rolbypassrls "
                 "FROM pg_roles ORDER BY rolname",
        "memberships": "SELECT pg_get_userbyid(roleid),pg_get_userbyid(member),pg_get_userbyid(grantor),"
                       "admin_option,inherit_option,set_option "
                       "FROM pg_auth_members ORDER BY 1,2,3",
        "schemas": "SELECT nspname,nspacl::text FROM pg_namespace ORDER BY nspname",
        "defaults": "SELECT pg_get_userbyid(defaclrole),defaclnamespace,defaclobjtype,defaclacl::text "
                    "FROM pg_default_acl ORDER BY 1,2,3",
        "relations": "SELECT n.nspname,c.relname,c.relkind,c.relacl::text "
                     "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                     "WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m','f') "
                     "AND c.relname::text <> ALL(%s) ORDER BY 1,2",
        "columns": "SELECT n.nspname,c.relname,a.attname,a.attacl::text "
                   "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
                   "JOIN pg_namespace n ON n.oid=c.relnamespace "
                   "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f') "
                   "AND a.attnum>0 AND NOT a.attisdropped "
                   "AND c.relname::text <> ALL(%s) AND NOT (c.relname=%s AND a.attname::text=ANY(%s)) "
                   "ORDER BY 1,2,3",
        "functions": "SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),p.proacl::text "
                     "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                     "WHERE n.nspname='public' ORDER BY 1,2,3",
    }
    result = {}
    excluded = [*schema.TABLES, "pages_problempublication_id_seq"]
    with connection.cursor() as cursor:
        for name, sql in queries.items():
            parameters = [excluded] if name == "relations" else (
                [excluded, schema.TABLE, list(schema.NEW_COLUMNS)] if name == "columns" else None
            )
            cursor.execute(sql, parameters)
            result[name] = cursor.fetchall()
    return result


def validate_migration_record(before, after):
    old, sequence = before
    new, ending = after
    if (
        new[:-1] != old or len(new) != len(old) + 1
        or new[-1][1:3] != ("pages", schema.MIGRATIONS[0])
        or new[-1][0] != sequence + 1 or ending != sequence + 1
    ):
        raise ValueError("Community proof migration metadata changed beyond its one approved record")


def seed_legacy(apps):
    user_model = apps.get_model("users", "User")
    owner = user_model.objects.get(email="schema-rehearsal@example.invalid")
    user_model.objects.filter(pk=owner.pk).update(is_approved=True, name="Synthetic preserved learner")
    peer = user_model.objects.create(email="schema-peer@example.invalid", name="Synthetic peer", is_approved=True)
    reviewer = user_model.objects.create(
        email="schema-reviewer@example.invalid", name="Synthetic reviewer", is_approved=True, role="admin",
    )
    problem_model = apps.get_model("pages", "CommunityProblem")
    for status in ("pending", "approved"):
        problem = problem_model.objects.create(
            author_id=owner.pk, title="Synthetic legacy " + status, statement_latex="Preserved community statement.",
            topic="ALG", mohs=12, topic_tags="AM-GM", core_ideas="Preserved private idea.",
            rationale="Preserved difficulty rationale.", source_kind="original",
            source_details="Synthetic contributor", solution_outline="PRIVATE-LEGACY-OUTLINE",
            review_notes="Preserved member-visible review note.", status=status,
        )
        apps.get_model("pages", "CommunityProblemReview").objects.create(
            problem_id=problem.pk, reviewer_id=reviewer.pk, version=1, decision=status,
            notes="Preserved review event.", content_snapshot={"title": problem.title},
        )
    apps.get_model("pages", "StatementReviewPolicy").objects.create(enabled=False)
    apps.get_model("solutions", "SolutionReviewPolicy").objects.create(enabled=False)
    visit = apps.get_model("pages", "LearningPageVisit").objects.create(
        user_id=peer.pk, page_name="concepts", path="/library/", visible_ms=1200,
    )
    apps.get_model("pages", "LearningPageAction").objects.create(visit_id=visit.pk, action="open", count=1)
    return owner.pk, peer.pk, reviewer.pk


def legacy_defaults(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*),bool_and(legacy_member_visible),"
            "bool_and(embargo_until IS NULL AND public_hint='' AND solution_known=false) "
            "FROM pages_communityproblem",
        )
        count, visible, defaults = cursor.fetchone()
    if count != LEGACY_FIXTURE_ROWS or visible is not True or defaults is not True:
        raise ValueError("Community proof migration did not preserve the legacy audience/defaults")


def no_content_backfill(connection):
    with connection.cursor() as cursor:
        for table in sorted(schema.TABLES):
            cursor.execute(f"SELECT count(*) FROM {connection.ops.quote_name(table)}")  # noqa: S608
            if cursor.fetchone()[0] != 0:
                raise ValueError("Community proof migration unexpectedly backfilled public/private content or consent")
        cursor.execute(
            "SELECT last_value FROM pg_catalog.pg_sequences WHERE schemaname='public' "
            "AND sequencename='pages_problempublication_id_seq'",
        )
        if cursor.fetchone() != (None,):
            raise ValueError("Community proof migration unexpectedly consumed its publication sequence")


def privacy_routes(identities):  # noqa: C901 - Keep the fixed, readable owner/peer/reviewer/public access matrix together.
    """Exercise actual GET views in a transaction rolled back without login/session writes."""
    from django.contrib.auth.models import AnonymousUser
    from django.db import transaction
    from django.http import Http404
    from django.test import RequestFactory
    from django.test import override_settings
    from django.urls import resolve
    from django.urls import reverse
    from django.utils import timezone

    from inspinia.pages.community_models import CommunityProblem
    from inspinia.pages.proof_library import ensure_statement_revision
    from inspinia.pages.proof_models import ModerationEvent
    from inspinia.pages.proof_models import ProblemPublication
    from inspinia.users.models import User

    owner, peer, reviewer = [User.objects.get(pk=identifier) for identifier in identities]
    factory = RequestFactory()

    def get(url, user):
        request = factory.get(url)
        request.user = user
        try:
            return resolve(request.path).func(request, **resolve(request.path).kwargs)
        except Http404:
            return SimpleNamespace(status_code=HTTPStatus.NOT_FOUND, content=b"")

    with transaction.atomic(), override_settings(ALLOWED_HOSTS=["testserver"]):
        private = CommunityProblem.objects.create(
            author=owner, title="PRIVATE-CANDIDATE-ONLY", statement_latex="Find $x$.",
            topic="ALG", source_kind="original", source_details="Synthetic origin.",
            solution_outline="PRIVATE-CANDIDATE-OUTLINE",
        )
        if private.legacy_member_visible or private.mohs is not None or private.solution_known:
            raise ValueError("New community submissions are not private with unknown-answer defaults")
        revision = ensure_statement_revision(private)
        if "solution_outline" in revision.snapshot or "core_ideas" in revision.snapshot:
            raise ValueError("A private field entered a public statement snapshot")
        detail = reverse("pages:community_problem_detail", args=[private.pk])
        if get(detail, owner).status_code != HTTPStatus.OK or get(detail, reviewer).status_code != HTTPStatus.OK:
            raise ValueError("Authorized private-statement access failed")
        if get(detail, peer).status_code != HTTPStatus.NOT_FOUND:
            raise ValueError("Another member could read a private community submission")
        listing = get(reverse("pages:community_problem_list") + "?tab=all", peer)
        if listing.status_code != HTTPStatus.OK or private.title.encode() in listing.content:
            raise ValueError("Private community content leaked through the member listing")
        for legacy in CommunityProblem.objects.filter(title__startswith="Synthetic legacy "):
            if get(reverse("pages:community_problem_detail", args=[legacy.pk]), peer).status_code != HTTPStatus.OK:
                raise ValueError("Existing member-visible community content became inaccessible")
        # An explicit negative fixture identity avoids advancing the new BigAutoField sequence.
        publication = ProblemPublication.objects.create(
            pk=-1, problem=private, statement_revision=revision, visibility="unlisted",
            consented_at=timezone.now(), public_credit="Synthetic public credit",
        )
        url = reverse("pages:proof_public_problem", args=[publication.token])
        if get(url, AnonymousUser()).status_code != HTTPStatus.NOT_FOUND:
            raise ValueError("Unreviewed community content was externally accessible")
        ModerationEvent.objects.create(
            problem=private, actor=reviewer, statement_revision=revision, action="statement_approved",
        )
        response = get(url, AnonymousUser())
        if response.status_code != HTTPStatus.OK or b"PRIVATE-CANDIDATE-OUTLINE" in response.content:
            raise ValueError("Approved publication failed or exposed the private outline")
        listing = get(reverse("pages:proof_public_list"), AnonymousUser())
        if private.title.encode() in listing.content:
            raise ValueError("An unlisted community statement entered public discovery")
        transaction.set_rollback(True)


def discovery_report(*, args, delta):
    """Preparation-only output intentionally cannot satisfy validate_rehearsal_evidence."""
    return {
        "format_version": 1, "purpose": "preparation-only-discovery", "deployment_proof": False,
        "source_sha": args.release_sha, "active_sha": args.active_sha, "postgres_version": schema.POSTGRES_VERSION,
        "input_hashes": schema.INPUT_HASHES, "prerequisite_hashes": schema.PREREQUISITE_HASHES,
        "delta_sha256": schema.delta_digest(delta), "delta": delta,
        "behaviour_sha256": schema.BEHAVIOUR_SHA256,
        "next_step": "Review and freeze this actual PostgreSQL catalog delta, then rerun without --discover-delta.",
    }


def rehearse(connection, args):  # noqa: C901, PLR0912, PLR0915 - One linear, fail-closed preservation protocol.
    from django.db.migrations.executor import MigrationExecutor

    if connection.vendor != "postgresql":
        raise ValueError("Community proof rehearsal requires the pinned PostgreSQL 17.9 runtime")
    if (
        os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("DATABASE_URL") != REHEARSAL_URL
        or any(connection.settings_dict.get(key) != value for key, value in REHEARSAL_DATABASE.items())
        or connection.settings_dict.get("OPTIONS")
    ):
        raise ValueError("Community proof rehearsal requires its exact isolated Actions database target")
    if connection.pg_version != schema.POSTGRES_VERSION:
        raise ValueError("Community proof rehearsal requires the pinned PostgreSQL 17.9 runtime")
    if connection.introspection.table_names():
        raise ValueError("Community proof rehearsal requires an empty isolated database")
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (args.active_sha, args.release_sha)):
        raise ValueError("Community proof rehearsal requires exact source identities")
    if args.active_sha == args.release_sha:
        raise ValueError("Community proof active and candidate source identities must differ")
    schema.validate_candidate(Path.cwd(), require_delta=not args.discover_delta)
    if migration_sources(Path.cwd()) != migration_sources(args.active_source.resolve()):
        raise ValueError("A prior migration source differs from the active release")
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "pages"] + [
        ("pages", "0044_learning_page_activity"),
    ]
    executor.migrate(targets)
    apps = executor.loader.project_state(targets).apps
    seed_fixture()
    seed_subscribers()
    seed_solution(apps)
    seed_shared_snapshots(apps)
    identities = seed_legacy(apps)
    before = normalize_schema_snapshot(_snapshot(connection))
    records, sequences = existing_records(connection), existing_sequences(connection)
    triggers, privileges = trigger_definitions(connection), privilege_snapshot(connection)
    metadata = migration_metadata(connection)
    behavior = schema.behaviour_snapshot(connection)
    if catalogue_schema.behaviour_fingerprint(behavior) != schema.BEHAVIOUR_SHA256:
        raise ValueError("Community proof starting trigger/function behavior is not the expected baseline")
    exec(schema.MIGRATION_APPLY, {})
    metadata_after = migration_metadata(connection)
    validate_migration_record(metadata, metadata_after)
    after = normalize_schema_snapshot(_snapshot(connection))
    delta = schema.validate_delta_shape(schema.catalog_delta(before, after))
    if (
        trigger_definitions(connection) != triggers or privilege_snapshot(connection) != privileges
        or schema.behaviour_snapshot(connection) != behavior
    ):
        raise ValueError("Community proof migration changed existing triggers/functions/privileges")
    legacy_defaults(connection)
    no_content_backfill(connection)
    exec(schema.AI_OFF_CHECK, {})
    from scripts.deployment.community_proof_preservation import capture_preservation

    preservation = capture_preservation(connection)
    if preservation["legacy_default_violations"]:
        raise ValueError("Trusted community proof preservation found invalid legacy defaults")
    subprocess.run(
        [sys.executable, "-c", schema.smoke_command()], cwd=args.active_source,
        env={**os.environ, "PYTHONPATH": str(args.active_source.resolve()), "DJANGO_READ_DOT_ENV_FILE": "false"},
        check=True, timeout=60,
    )
    privacy_routes(identities)
    if (
        existing_records(connection) != records or existing_sequences(connection) != sequences
        or migration_metadata(connection) != metadata_after
        or normalize_schema_snapshot(_snapshot(connection)) != after
        or trigger_definitions(connection) != triggers or privilege_snapshot(connection) != privileges
        or schema.behaviour_snapshot(connection) != behavior
        or capture_preservation(connection) != preservation
    ):
        raise ValueError("Community proof rehearsal or compatibility reader changed preserved data/schema")
    no_content_backfill(connection)
    exec(schema.AI_OFF_CHECK, {})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.discover_delta:
        args.output.write_text(json.dumps(discovery_report(args=args, delta=delta), sort_keys=True, indent=2) + "\n")
        delta_output = args.delta_output or args.output.with_suffix(".delta.json")
        delta_output.parent.mkdir(parents=True, exist_ok=True)
        delta_output.write_text(json.dumps(delta, sort_keys=True, indent=2) + "\n")
    else:
        if schema.delta_digest(delta) != schema.DELTA_SHA256:
            raise ValueError("Community proof schema differs from its frozen PostgreSQL catalog delta")
        fixture = schema.normalize_delta(json.loads((Path.cwd() / schema.DELTA_PATH).read_bytes()))
        if delta != fixture:
            raise ValueError("Community proof actual schema delta differs from its exact fixture")
        args.output.write_bytes(schema.evidence_bytes(release_sha=args.release_sha, active_sha=args.active_sha))
    connection.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-source", type=Path, required=True)
    parser.add_argument("--active-sha", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--discover-delta", action="store_true")
    parser.add_argument("--delta-output", type=Path)
    args = parser.parse_args()
    return rehearse(prepare_django(), args)


if __name__ == "__main__":
    raise SystemExit(main())
