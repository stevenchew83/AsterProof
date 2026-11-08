# ruff: noqa: EM101, S102, S603, TRY003
"""Rehearse the exact public-registration allowance on disposable PostgreSQL 17.9."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment import evaluation_schema as preservation
from scripts.deployment import registration_compat
from scripts.deployment import registration_schema as schema
from scripts.deployment.newsletter_schema_rehearsal import migration_metadata
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.onboarding_schema_rehearsal import seed_fixture
from scripts.deployment.onboarding_schema_rehearsal import seed_solution
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import _snapshot


def catalog_delta(connection, before):
    after = normalize_schema_snapshot(_snapshot(connection))
    delta = {field: [row for row in rows if row not in before[field]] for field, rows in after.items()}
    if any(row not in after[field] for field, rows in before.items() for row in rows):
        raise ValueError("Public registration rehearsal removed an existing schema object")
    if schema_state(delta)["fingerprint"] != schema.DELTA_SHA256:
        raise ValueError(f"Public registration catalog differs from the frozen delta: {delta!r}")  # noqa: EM102
    return after


def verify_reader_floor(connection, *, required):
    with connection.cursor() as cursor:
        cursor.execute(registration_compat.FLOOR_SQL)
        if cursor.fetchone() != (required,):
            raise ValueError("Registration reader floor differs from the installed schema")


def verify_registration_gate(settings_row):
    from django.db import transaction
    from django.test import override_settings

    from inspinia.users.models import UserAccessSettings

    with transaction.atomic(), override_settings(ACCOUNT_ALLOW_REGISTRATION=True):
        if not settings_row.allow_public_registration or not UserAccessSettings.public_registration_is_open():
            raise ValueError("Existing settings must default to open registration")
        UserAccessSettings.objects.filter(pk=settings_row.pk).update(allow_public_registration=False)
        if UserAccessSettings.public_registration_is_open():
            raise ValueError("The registration gate ignored the saved closure")
        UserAccessSettings.objects.filter(pk=settings_row.pk).update(allow_public_registration=True)
        with override_settings(ACCOUNT_ALLOW_REGISTRATION=False):
            if UserAccessSettings.public_registration_is_open():
                raise ValueError("The registration gate ignored the server override")
        transaction.set_rollback(True)


def run(args):
    connection = prepare_django()
    from django.db.migrations.executor import MigrationExecutor

    preservation.validate_connection(connection)
    if connection.pg_version != schema.POSTGRES_VERSION or connection.introspection.table_names():
        raise ValueError("Public registration rehearsal requires an empty PostgreSQL 17.9 database")
    schema.validate_candidate(Path.cwd())
    if (args.active_source / schema.MIGRATION_PATH).exists() or (
        schema.migration_tree_sha256(args.active_source) != schema.PRIOR_MIGRATION_TREE_SHA256
    ):
        raise ValueError("Active source differs from the required migration baseline")

    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "users"] + [schema.PREVIOUS]
    executor.migrate(targets)
    apps = executor.loader.project_state(targets).apps
    seed_fixture(apps)
    seed_solution(apps)
    legacy_settings = apps.get_model("users", "UserAccessSettings").objects
    legacy_settings.create(pk=1, auto_approve_new_users=True)
    legacy_audit = apps.get_model("users", "AuditEvent").objects
    legacy_audit.create(event_type="users.approval_changed", message="Synthetic existing approval")

    tables = set(connection.introspection.table_names())
    prior_tables = tables - {schema.TABLE}
    before = preservation.preserved_state(connection, prior_tables)
    settings_before = legacy_settings.values().get()
    catalog_before = normalize_schema_snapshot(_snapshot(connection))
    old_rows, old_sequence = migration_metadata(connection)
    verify_reader_floor(connection, required=False)
    exec(schema.MIGRATION_APPLY, {})
    verify_reader_floor(connection, required=True)
    catalog_after = catalog_delta(connection, catalog_before)

    from inspinia.users.models import UserAccessSettings

    verify_registration_gate(UserAccessSettings.objects.get(pk=1))
    subprocess.run(
        [sys.executable, "-c", schema.SMOKE_COMMAND],
        cwd=args.active_source,
        env={**os.environ, "PYTHONPATH": str(args.active_source.resolve())},
        check=True,
    )
    after = preservation.preserved_state(connection, prior_tables)
    if (
        set(connection.introspection.table_names()) != tables
        or normalize_schema_snapshot(_snapshot(connection)) != catalog_after
        or any(after[key] != before[key] for key in ("rows", "columns", "constraints", "triggers", "sequences"))
        or legacy_settings.values().get() != settings_before
        or not UserAccessSettings.objects.get(pk=1).allow_public_registration
    ):
        raise ValueError("Public registration rehearsal changed existing data or database objects")
    new_rows, new_sequence = migration_metadata(connection)
    if (
        new_rows[:-1] != old_rows or len(new_rows) != len(old_rows) + 1
        or new_rows[-1][:3] != (old_sequence + 1, "users", schema.MIGRATION_NAME)
        or new_sequence != old_sequence + 1
    ):
        raise ValueError("Only the public registration migration recorder row may be appended")
    connection.check_constraints()
    args.output.write_bytes(schema.evidence_bytes(args.release_sha, args.active_sha))
    connection.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-source", type=Path, required=True)
    parser.add_argument("--active-sha", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
