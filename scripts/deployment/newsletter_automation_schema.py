# ruff: noqa: EM101, EM102, TRY003
"""Frozen newsletter automation schema allowance; no other migration is admitted."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from scripts.deployment.concept_schema import ConceptSchemaError
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import smoke_command

MIGRATION = "website.0003_newsletter_automation"
MIGRATION_NAME = MIGRATION.split(".", 1)[1]
MIGRATION_PATH = Path("inspinia/website/migrations/0003_newsletter_automation.py")
MIGRATION_SHA256 = "a622ada6781d9231f203c3adf1ee1c0649fb24b264f6d802f4c80e07d4a7a885"
DELTA_SHA256 = "0000000000000000000000000000000000000000000000000000000000000000"
EVIDENCE_PATH = "deployment-schema-evidence.json"
POSTGRES_VERSION = 170009
TABLES = {
    "website_newsletterautomation",
    "website_newsletterlecturenotice",
    "website_newsletterbouncereport",
    "website_newslettersendinghold",
}
EXTENDED_TABLES = {"website_newslettercampaign", "website_newsletterdelivery"}
DIGEST = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_FIELDS = ("state_fingerprint", "schema_fingerprint", "migration_fingerprint")
MAX_DISCLOSURE_BYTES = 8192
COMPATIBILITY_SMOKE = (
    smoke_command()
    + """
from inspinia.website.models import NewsletterSubscriber, NewsletterCampaign, NewsletterDelivery
from inspinia.website.campaigns import preview_html
counts = (NewsletterSubscriber.objects.count(), NewsletterCampaign.objects.count(), NewsletterDelivery.objects.count())
if counts != (3, 2, 3):
    raise RuntimeError('Active newsletter record read failed')
if 'asterproof' not in preview_html(NewsletterCampaign.objects.get(subject='Historical draft')).lower():
    raise RuntimeError('Active newsletter preview failed')
"""
)
COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(COMPATIBILITY_SMOKE.encode()).hexdigest()
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected=[('website','{MIGRATION_NAME}',False,['AddField']*6+['AlterField']+['CreateModel']*4)]
if actual != expected:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('website','{MIGRATION_NAME}')])\n"


class NewsletterAutomationSchemaError(ConceptSchemaError):
    pass


def _validate_fingerprints(value: dict[str, Any]) -> None:
    for stage in ("starting", "expected"):
        state = value[stage]
        if not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS):
            raise NewsletterAutomationSchemaError("Invalid schema fingerprint fields")
        if any(not isinstance(v, str) or not DIGEST.fullmatch(v) for v in state.values()):
            raise NewsletterAutomationSchemaError("Invalid schema fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise NewsletterAutomationSchemaError("The approved additive migration must change each fingerprint")


def validate_disclosure(value: Any, *, target_sha: str) -> dict[str, Any]:
    fields = {
        "format_version",
        "active_sha",
        "target_sha",
        "migration",
        "migration_file_sha256",
        "starting",
        "expected",
        "postgresql_rehearsal_sha256",
        "compatibility_smoke_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields or value["format_version"] != 1:
        raise NewsletterAutomationSchemaError("Invalid bounded schema disclosure")
    if value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256:
        raise NewsletterAutomationSchemaError("Migration is outside the approved scope")
    if (
        not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise NewsletterAutomationSchemaError("Schema disclosure release identity mismatch")
    for field in ("postgresql_rehearsal_sha256", "compatibility_smoke_sha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise NewsletterAutomationSchemaError("Schema rehearsal and compatibility evidence must be frozen")
    if value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256:
        raise NewsletterAutomationSchemaError("Newsletter compatibility smoke differs from the approved fixed command")
    _validate_fingerprints(value)
    if len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise NewsletterAutomationSchemaError("Schema disclosure exceeds its bound")
    return value


def validate_candidate(release: Path) -> None:
    from scripts.deployment.newsletter_schema import validate_candidate as validate_initial

    validate_initial(release)
    path = release / MIGRATION_PATH
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != MIGRATION_SHA256:
        raise NewsletterAutomationSchemaError("Candidate migration bytes differ from the approved migration")


def audit_matches(disclosure: dict[str, Any], audit: dict[str, Any], *, stage: str) -> bool:
    return audit.get("server_version_num") == POSTGRES_VERSION and all(
        audit.get(field) == disclosure[stage][field] for field in FINGERPRINT_FIELDS
    )


def validate_build_evidence(release: Path, disclosure: dict[str, Any]) -> None:
    import json

    path = release / EVIDENCE_PATH
    if path.is_symlink() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise NewsletterAutomationSchemaError("Invalid packaged schema evidence")
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise NewsletterAutomationSchemaError("Invalid packaged schema evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise NewsletterAutomationSchemaError("Packaged website rehearsal proof digest does not match its disclosure")
    expected = {
        "format_version": 1,
        "source_sha": disclosure["target_sha"],
        "active_sha": disclosure["active_sha"],
        "postgres_version": POSTGRES_VERSION,
        "migration_file_sha256": MIGRATION_SHA256,
        "delta_sha256": DELTA_SHA256,
        "existing_schema_unchanged": True,
        "source_fixture_unchanged": True,
        "active_revision_smoke_passed": True,
        "existing_records_unchanged": True,
        "existing_sequences_unchanged": True,
        "existing_subscribers_unchanged": True,
        "existing_campaigns_unchanged": True,
    }
    if value != expected or any(
        value[field] is not True
        for field in (
            "existing_schema_unchanged",
            "source_fixture_unchanged",
            "active_revision_smoke_passed",
            "existing_records_unchanged",
            "existing_sequences_unchanged",
            "existing_subscribers_unchanged",
            "existing_campaigns_unchanged",
        )
    ):
        raise NewsletterAutomationSchemaError("Packaged PostgreSQL schema evidence does not match this release")


def expected_catalog_audit(start: dict[str, Any], rehearsal: dict[str, Any]) -> dict[str, Any]:
    """Append the rehearsed four-table and appended-column delta to catalog metadata, without production data."""
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise NewsletterAutomationSchemaError("Starting audit identity/version does not match the approved target")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    delta = normalize_schema_snapshot(rehearsal)
    if schema_state(delta)["fingerprint"] != DELTA_SHA256:
        raise NewsletterAutomationSchemaError("Schema delta differs from the approved rehearsal")
    if any(row["table"] in TABLES for row in before["tables"]):
        raise NewsletterAutomationSchemaError("Newsletter tables already exist")
    if {row["table"] for row in delta["tables"]} != TABLES or delta["extensions"]:
        raise NewsletterAutomationSchemaError("Rehearsal delta is not exactly the four approved tables")
    if any(
        row["table"] not in TABLES | EXTENDED_TABLES
        for field in ("columns", "constraints", "indexes")
        for row in delta[field]
    ):
        raise NewsletterAutomationSchemaError("Rehearsal delta changes an existing schema object")
    if any(row in before[field] for field in delta for row in delta[field]):
        raise NewsletterAutomationSchemaError("An approved new schema object already exists")
    migrations = start["migration_rows"]
    if ["website", MIGRATION_NAME] in migrations:
        raise NewsletterAutomationSchemaError("The approved migration is already recorded")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise NewsletterAutomationSchemaError("Starting catalog evidence does not match its fingerprints")
    combined = {field: [*before[field], *delta[field]] for field in before}
    state = {
        **start["state"],
        "schema": schema_state(combined),
        "migration": migration_state([*migrations, ["website", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
