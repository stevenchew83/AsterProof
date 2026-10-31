# ruff: noqa: EM101, EM102, TRY003
"""Frozen onboarding schema allowance; no other migration is admitted."""

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
from scripts.deployment.schema_rehearsal import smoke_command as base_smoke_command

MIGRATION = "users.0009_user_solution_guide_status"
MIGRATION_NAME = MIGRATION.split(".", 1)[1]
MIGRATION_PATH = Path("inspinia/users/migrations/0009_user_solution_guide_status.py")
MIGRATION_SHA256 = "3ac8c1d7eb150ce93ee8f97caee0833e62de681d756caf7867a87220168c6acd"
DELTA_SHA256 = "508a0db0daece5a5f61361bd3165072adb62d170b3c18f1f1d8cc2310086c2ca"
EVIDENCE_PATH = "deployment-schema-evidence.json"
POSTGRES_VERSION = 170009
TABLE = "users_user"
COLUMNS = {"solution_guide_status"}
PRIOR_MIGRATIONS = {
    "0001_initial.py": "18224109454cbbe616419a66d5ed95e71a9c5fbc8d18011fc61fc0b86f663f4a",
    "0002_admin_group.py": "f79373376edcb267bc548081284dfa8822069f53828222be3df653d3d9fe20df",
    "0003_user_role.py": "205cfb4540a35fc4322bb8bfe4bc9aea675320384ca2337f78f4c79f841367f7",
    "0004_user_address_user_birthdate_user_contact_number_and_more.py": (
        "35fa559a4ae84fac3f7d0e0edc8ae1610c7d642ad2de2a4b37063b29a2fa0ef6"
    ),
    "0005_auditevent_usersession.py": "7732b405a7e9e944f1dc865f1ea11c538a5a2a472f22e21d8ef203d405c614c3",
    "0006_user_country_user_postal_code.py": "d589fd8957decea97ea17dc57c7f3c8fdd109daf922a0514e06d124b09ce68a5",
    "0007_user_is_approved_and_approval_audit_event.py": (
        "8922315af86f1a08a04ed1ad25dc0ca179aeefebe6c0a2f731b34006237fe6e9"
    ),
    "0008_useraccesssettings.py": "4227b33c7626162e306e9b0b3f260edc2c953383d7e36ae1f919d70576d1d13c",
}

DIGEST = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_FIELDS = ("state_fingerprint", "schema_fingerprint", "migration_fingerprint")
MAX_DISCLOSURE_BYTES = 8192
BASE_COLUMNS = (
    "id",
    "password",
    "last_login",
    "is_superuser",
    "email",
    "is_staff",
    "is_active",
    "date_joined",
    "name",
    "role",
    "address",
    "birthdate",
    "contact_number",
    "discord_username",
    "gender",
    "school",
    "social_media_links",
    "country",
    "postal_code",
    "is_approved",
)


def smoke_command():
    return (
        base_smoke_command()  # noqa: S608 - fixed rehearsal SQL with bound parameters
        + """
from inspinia.solutions.models import ProblemSolution
solution=ProblemSolution.objects.get(title='Synthetic preserved solution')
if solution.blocks.get().body_source != 'Synthetic preserved proof.':
    raise RuntimeError('Active revision solution read failed')
from django.db import connection, transaction
from inspinia.users.models import User
with transaction.atomic():
    probe=User.objects.create(pk=2147483000,email='old-code-signup@schema-rehearsal.example.invalid')
    with connection.cursor() as cursor:
        cursor.execute('SELECT solution_guide_status FROM users_user WHERE id=%s',[probe.pk])
        if cursor.fetchone() != ('not_enrolled',):
            raise RuntimeError('Old code account creation default is not compatible')
    transaction.set_rollback(True)
"""
    )


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected=[('users','{MIGRATION_NAME}',False,['AddField','AlterField'])]
if actual != expected:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('users','{MIGRATION_NAME}')])\n"


class OnboardingSchemaError(ConceptSchemaError):
    pass


def _validate_fingerprints(value: dict[str, Any]) -> None:
    for stage in ("starting", "expected"):
        state = value[stage]
        if not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS):
            raise OnboardingSchemaError("Invalid schema fingerprint fields")
        if any(not isinstance(v, str) or not DIGEST.fullmatch(v) for v in state.values()):
            raise OnboardingSchemaError("Invalid schema fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise OnboardingSchemaError("The approved additive migration must change each fingerprint")


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
        raise OnboardingSchemaError("Invalid bounded schema disclosure")
    if value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256:
        raise OnboardingSchemaError("Migration is outside the approved scope")
    if (
        not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise OnboardingSchemaError("Schema disclosure release identity mismatch")
    for field in ("postgresql_rehearsal_sha256", "compatibility_smoke_sha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise OnboardingSchemaError("Schema rehearsal and compatibility evidence must be frozen")
    if value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256:
        raise OnboardingSchemaError("Onboarding compatibility smoke differs from the approved fixed command")
    _validate_fingerprints(value)
    if len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise OnboardingSchemaError("Schema disclosure exceeds its bound")
    return value


def validate_candidate(release: Path) -> None:
    paths = {MIGRATION_PATH: MIGRATION_SHA256}
    paths.update({MIGRATION_PATH.parent / name: digest for name, digest in PRIOR_MIGRATIONS.items()})
    for relative, digest in paths.items():
        path = release / relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise OnboardingSchemaError("Candidate migration bytes differ from the frozen solution plan")


def audit_matches(disclosure: dict[str, Any], audit: dict[str, Any], *, stage: str) -> bool:
    return audit.get("server_version_num") == POSTGRES_VERSION and all(
        audit.get(field) == disclosure[stage][field] for field in FINGERPRINT_FIELDS
    )


def validate_build_evidence(release: Path, disclosure: dict[str, Any]) -> None:
    import json

    path = release / EVIDENCE_PATH
    if path.is_symlink() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise OnboardingSchemaError("Invalid packaged schema evidence")
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise OnboardingSchemaError("Invalid packaged schema evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise OnboardingSchemaError("Packaged onboarding rehearsal proof digest does not match its disclosure")
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
        "existing_users_not_enrolled": True,
        "new_accounts_enrolled": True,
        "existing_trigger_definitions_unchanged": True,
    }
    if value != expected or any(
        value[field] is not True
        for field in (
            "existing_schema_unchanged",
            "source_fixture_unchanged",
            "active_revision_smoke_passed",
            "existing_records_unchanged",
            "existing_sequences_unchanged",
            "existing_users_not_enrolled",
            "new_accounts_enrolled",
            "existing_trigger_definitions_unchanged",
        )
    ):
        raise OnboardingSchemaError("Packaged PostgreSQL schema evidence does not match this release")


def expected_catalog_audit(start: dict[str, Any], rehearsal: dict[str, Any]) -> dict[str, Any]:
    """Append only the one frozen column record to verified catalog metadata."""
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise OnboardingSchemaError("Starting audit identity/version does not match the approved target")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    delta = normalize_schema_snapshot(rehearsal)
    if schema_state(delta)["fingerprint"] != DELTA_SHA256:
        raise OnboardingSchemaError("Schema delta differs from the frozen one-column fixture")
    if not any(row["schema"] == "public" and row["table"] == TABLE for row in before["tables"]):
        raise OnboardingSchemaError("Existing user table is required")
    existing_columns = sorted(
        (row for row in before["columns"] if row["schema"] == "public" and row["table"] == TABLE),
        key=lambda row: row["position"],
    )
    if [(row["position"], row["column"]) for row in existing_columns] != list(enumerate(BASE_COLUMNS, 1)):
        raise OnboardingSchemaError("Existing user columns differ from the frozen starting shape")
    if any(row["table"] == TABLE and row["column"] in COLUMNS for row in before["columns"]):
        raise OnboardingSchemaError("Solution guide column already exist")
    if any(delta[field] for field in ("tables", "constraints", "indexes", "extensions")) or (
        {row["column"] for row in delta["columns"]} != COLUMNS
        or any(row["schema"] != "public" or row["table"] != TABLE for row in delta["columns"])
    ):
        raise OnboardingSchemaError("Schema delta is not exactly the one approved column")
    migrations = start["migration_rows"]
    if ["users", MIGRATION_NAME] in migrations:
        raise OnboardingSchemaError("The frozen migration is already recorded")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise OnboardingSchemaError("Starting catalog evidence does not match its fingerprints")
    combined = {field: [*before[field], *delta[field]] for field in before}
    state = {
        **start["state"],
        "schema": schema_state(combined),
        "migration": migration_state([*migrations, ["users", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
