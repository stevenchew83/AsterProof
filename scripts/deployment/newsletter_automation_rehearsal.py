# ruff: noqa: E402, EM101, S102, S603, TRY003
"""Exact automation migration proof on the isolated, pinned Actions database."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.deployment import newsletter_automation_schema as schema
from scripts.deployment.newsletter_schema_rehearsal import existing_sequences
from scripts.deployment.newsletter_schema_rehearsal import migration_metadata
from scripts.deployment.newsletter_schema_rehearsal import prepare_django
from scripts.deployment.newsletter_schema_rehearsal import seed_fixture
from scripts.deployment.newsletter_schema_rehearsal import seed_subscribers
from scripts.deployment.newsletter_schema_rehearsal import subscriber_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import _snapshot


def existing_records(connection, before):
    """Hash only pre-existing columns; no production records are read or exported."""
    records = {}
    for table in sorted(row["table"] for row in before["tables"] if row["table"] != "django_migrations"):
        columns = [row["column"] for row in before["columns"] if row["table"] == table]
        names = ",".join(connection.ops.quote_name(name) for name in columns)
        quoted = connection.ops.quote_name(table)
        digest = hashlib.sha256()
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT to_jsonb(source)::text FROM (SELECT {names} FROM {quoted}) source "  # noqa: S608
                'ORDER BY to_jsonb(source)::text COLLATE "C"',
            )
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    digest.update(row[0].encode())
                    digest.update(b"\0")
        records[table] = digest.hexdigest()
    return records


def validate_migration_record(before, after):
    old, counter = before
    new, new_counter = after
    if (
        len(new) != len(old) + 1
        or new[:-1] != old
        or new[-1][0] != counter + 1
        or new_counter != counter + 1
        or new[-1][1:3] != ("website", "0003_newsletter_automation")
    ):
        raise ValueError("Automation changed migration metadata beyond its one approved record")


def seed_campaigns(executor):
    from django.utils import timezone

    apps = executor.loader.project_state([("website", "0002_newsletter_campaigns")]).apps
    campaign_model = apps.get_model("website", "NewsletterCampaign")
    delivery_model = apps.get_model("website", "NewsletterDelivery")
    subscriber = apps.get_model("website", "NewsletterSubscriber").objects.get(status="confirmed")
    draft = campaign_model.objects.create(subject="Historical draft", body_markdown="Preserve this branded draft.")
    history = campaign_model.objects.create(
        subject="Historical campaign",
        body_markdown="Preserve this content.",
        status="completed",
        started_at=timezone.now(),
        completed_at=timezone.now(),
    )
    for campaign, kind, status in (
        (draft, "test", "accepted"),
        (history, "campaign", "accepted"),
        (history, "test", "unknown"),
    ):
        delivery_model.objects.create(
            campaign=campaign,
            subscriber=subscriber,
            recipient_email=subscriber.email,
            subject=campaign.subject,
            consent_confirmed_at=subscriber.confirmed_at,
            campaign_version=1,
            kind=kind,
            status=status,
            attempted_at=timezone.now(),
            finished_at=timezone.now(),
        )


def _migrate_fixture(connection):
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    executor.migrate(
        [node for node in executor.loader.graph.leaf_nodes() if node[0] != "website"]
        + [("website", "0002_newsletter_campaigns")],
    )
    seed_fixture()
    seed_subscribers()
    seed_campaigns(executor)


def _preservation_snapshot(connection, before):
    return existing_records(connection, before), existing_sequences(connection), subscriber_snapshot(connection)


def run(args):
    connection = prepare_django()
    if connection.pg_version != schema.POSTGRES_VERSION or connection.introspection.table_names():
        raise ValueError("Automation rehearsal requires an empty, pinned PostgreSQL 17.9 Actions database")
    schema.validate_candidate(Path.cwd())
    _migrate_fixture(connection)
    before = _snapshot(connection)
    preserved = _preservation_snapshot(connection, before)
    metadata = migration_metadata(connection)
    exec(schema.MIGRATION_APPLY, {})
    after = _snapshot(connection)
    metadata_after = migration_metadata(connection)
    validate_migration_record(metadata, metadata_after)
    if any(row not in after[field] for field in before for row in before[field]):
        raise ValueError("Automation removed or changed a pre-existing schema object")
    delta = {field: [row for row in after[field] if row not in before[field]] for field in after}
    if {row["table"] for row in delta["tables"]} != schema.TABLES or delta["extensions"]:
        raise ValueError("Automation did not add exactly its four approved tables")
    if _preservation_snapshot(connection, before) != preserved:
        raise ValueError("Automation changed pre-existing records, consent or sequences")
    from inspinia.website.models import NewsletterAutomation
    from inspinia.website.models import NewsletterDelivery

    if (
        NewsletterAutomation.objects.exists()
        or NewsletterDelivery.objects.exclude(delivery_result="unconfirmed").exists()
    ):
        raise ValueError("Automation enabled itself or inferred historical delivery success")
    fingerprint = schema_state(delta)["fingerprint"]
    if not getattr(args, "record_delta", False) and fingerprint != schema.DELTA_SHA256:
        raise ValueError("Automation schema delta differs from the frozen rehearsal")
    env = {**os.environ, "PYTHONPATH": str(args.active_source.resolve())}
    subprocess.run([sys.executable, "-c", schema.COMPATIBILITY_SMOKE], cwd=args.active_source, env=env, check=True)
    if (
        _snapshot(connection) != after
        or _preservation_snapshot(connection, before) != preserved
        or migration_metadata(connection) != metadata_after
    ):
        raise ValueError("Active application smoke changed schema or pre-existing records")
    evidence = {
        "format_version": 1,
        "source_sha": args.release_sha,
        "active_sha": args.active_sha,
        "postgres_version": connection.pg_version,
        "migration_file_sha256": schema.MIGRATION_SHA256,
        "delta_sha256": schema.DELTA_SHA256,
        "existing_schema_unchanged": True,
        "source_fixture_unchanged": True,
        "active_revision_smoke_passed": True,
        "existing_records_unchanged": True,
        "existing_sequences_unchanged": True,
        "existing_subscribers_unchanged": True,
        "existing_campaigns_unchanged": True,
    }
    args.output.write_text(
        json.dumps(delta if getattr(args, "record_delta", False) else evidence, sort_keys=True, indent=2) + "\n",
    )
    print("Automation PostgreSQL delta:", fingerprint)  # noqa: T201
    connection.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-source", type=Path, required=True)
    parser.add_argument("--active-sha", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record-delta", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
