# ruff: noqa: EM101, EM102, TRY003
"""Frozen statement-report schema allowance; no other migration is admitted."""

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

MIGRATION = "pages.0041_statement_issue_reports"
MIGRATION_NAME = MIGRATION.split(".", 1)[1]
MIGRATION_PATH = Path("inspinia/pages/migrations/0041_statement_issue_reports.py")
MIGRATION_SHA256 = "15367bc1f22fdfa273bdc35893a5b73433d1dbd404fda7edb1506fee319f80cb"
DELTA_SHA256 = "ae217ed52eaedc3c6159142e85e821737cce739e160db362c385dd4815e66055"
EVIDENCE_PATH = "deployment-schema-evidence.json"
POSTGRES_VERSION = 170009
TABLE = "pages_statementissuereport"
TABLES = {TABLE}
PRIOR_MIGRATIONS = {
    "0001_initial.py": "ba637f216a27255924b013781f378acf578a9e06471c561da914fc561f686658",
    "0002_problemsolverecord_imo_slot_guess_value.py": (
        "a2e23dfb3482a9a8fdad9d7d8c772c3cb5c960e966426179a404c5f22d699cc3"
    ),
    "0003_problemsolverecord_rationale_value.py": "9ac165ec21f65be4ffc0f75c40daa6f6900e1f1d3e6d182cb3e8ddab670382d2",
    "0004_problemsolverecord_pitfalls_value.py": "9e49bdfd4cd97088a0230dc3228f5b17d3e81d3fd9f5bf4a0fd7ce50d630a445",
    "0005_problem_topic_technique_and_unique_problem.py": (
        "32ea043a0413d150e65e481b515d6af3ab13961e2bbfcde4d5d7ee01ca60f7ec"
    ),
    "0006_remove_problemsolverecord_solve_date.py": "0fdb0b77a410dace852e2376ad746e3f0929f4852b2c41d42cd1559d9af6a8c5",
    "0007_uppercase_problem_topic_techniques.py": "e561b9725293413f0f9a4c2ed3ab0aa2c85e94c654e3a1cf5fd46fca8b24bb00",
    "0008_problem_uuid_and_user_problem_completion.py": (
        "10bdb2563cc58d02dd5de6432a3c3d8acd27831a969db61630281602f3a1fc3b"
    ),
    "0009_contestproblemstatement.py": "0755fb7b1b650f4c1fe1c41018051b8519b907a57dab1513f1852b3f5132358c",
    "0010_contestproblemstatement_problem_uuid.py": "9a88a74ae8c4418da45219b432ebd0493a6230c73ca8e50c29cbe13eab797ecb",
    "0011_userproblemcompletion_completion_date_nullable.py": (
        "a0b39dd035b2ce3c24adde633804320264661b62aaee8b15affcfe0148e6628e"
    ),
    "0012_fix_userproblemcompletion_completion_date_nullability_db.py": (
        "d7ac1803c1e97f6af2858e7b52025ff0294139f2a849be64331984b446744236"
    ),
    "0013_alter_contestproblemstatement_options_and_more.py": (
        "e038763449413061ffaadfe6b1082a403e5922e8700960a19cfd8ada5f83923d"
    ),
    "0014_remove_contestproblemstatement_pages_contestproblemstatement_unique_contest_problem_code_and_more.py": (
        "430aaa0d4e0bf775a0ba1e0d7bd4d7c21949eba842a28173e2de992de4d00915"
    ),
    "0015_alter_contestproblemstatement_day_label.py": (
        "335dc0f85d1e30300163dabca156530c9461ab1e00fd80170d8d138ee68a3e4e"
    ),
    "0016_contestmetadata.py": "2c9b8d7b90d7f2699195d156ea0ff7d6fa90e2b4f487771f95210085f5fe0ade",
    "0017_remove_problemsolverecord_pages_problemsolverecord_unique_year_contest_problem.py": (
        "7f58a53b227083f978284bf4ddf903c9e589896ec4176ffcb1e01fa5a0a0f4d4"
    ),
    "0018_problemsolverecord_is_active.py": "74e2aa81042b9b12e808a2c6105d416fb525818830040f20d9986f15066613cd",
    "0019_contestproblemstatement_is_active.py": "2547df08a3d91a73ecd9559473f64393cad6c01adf2bfe398e713be9e9764cc4",
    "0020_statement_uuid_and_statement_completions.py": (
        "ab015026a8bdbe70a7998cd99fe5e72d8eca4556678b7db42e4ec19862b5baf9"
    ),
    "0021_statement_analytics_fields.py": "a6579d0616fa430108ef9a0a692d875aa51b969eba62d22551f323076bd6f6a6",
    "0022_userproblemcompletion_updated_index.py": "48ecd93b0f7e532b70e3c08aceb7a3da1f4278effd85f9f15fbd48b6d880ad8c",
    "0023_user_problem_difficulty_rating.py": "782ccbbd49630673efbb1b5d049c8a16c4c3e7a5c9bf4fc510e764af939d21e3",
    "0024_page_view_event.py": "febac2f2b7b74f81fb71178a3ac71b92d83c4100996e342547a1be0890e05556",
    "0025_userproblemcompletion_confidence_and_more.py": (
        "f40a2008bb69dca9a9c087b2cadfd7d8135bb47e9dfb0bf429e776b3ea567b97"
    ),
    "0026_core_ideas_fields.py": "560a4d7dc8e5af60b0c6cf413660ef4863f7f4e0dc47c99face8a411e78b5064",
    "0027_topic_technique_taxonomy_fields.py": "d97b932d25f7f17594f3fb9cb94bf1c9b0adbb92605f64e3939ed20150a1a2cd",
    "0028_problemtopictechnique_normalization_confidence_and_more.py": (
        "0761a1355b06ecb3a27bf813bc6526cecf537cfa4f3ec41a616bab39e7ac4a72"
    ),
    "0029_problemtopictechnique_lemma_theorem_tags_and_more.py": (
        "6c22e9e33c35b69ff42fbd982082cf8142d2e510851f8e59be89ec7a41501dd4"
    ),
    "0030_techniqueprogresscatalogstate_techniqueprogressfact.py": (
        "f9efd475679928bb4242b01e0bb6b0a3cc665adbb738d182a733a9a4741a9f0a"
    ),
    "0031_techniqueprogressfact_gap_filter_indexes.py": (
        "29c58ba80186820a2dd370905aca6fa0b85b87c8e150c923cbb565fcf381080f"
    ),
    "0032_techniquebenchmarkimportbatch_techniquebenchmark_and_more.py": (
        "fa2cb6f96abeabb5db6bcb7f65b7f991dc9dcca096eed62114fc61b888fc133f"
    ),
    "0033_techniquebenchmark_quality_flags_and_more.py": (
        "d37138066f8fd0002508c18ff8db350987385cc369dbcd9aa501b68bf2fce09d"
    ),
    "0034_userproblemcompletion_user_updated_index.py": (
        "a5c86fb9f707f4891d1029b4f20a4e55c4ada4825d07dc60352d35125113bec7"
    ),
    "0035_techniquebenchmark_curriculum_class_and_more.py": (
        "9af7bddd76f2576e9770e676c7ff4c759bc88c1250ae3eb5dcd09f62eb4060a2"
    ),
    "0036_concept_assignment_reviews.py": "e69f6ed407bfbf0bbf5dad09a6ada8c3f7efdb101db4a3b60c484264b0fde87d",
    "0037_catalogue_tables.py": "5eccd458a588eab19bc3bbfd4d58a2b7a0ab40bcefabbd7b53fcf226acb2ca18",
    "0038_catalogue_seed.json": "e98f5329e697597ef4dcadeb77d912213237365b05d3207d76391581222386f6",
    "0038_seed_catalogue.py": "ea1fedfed7c0220a89dad21d5cb5bd1d7edc5ebe2a3e74746254429fa7577d16",
    "0039_catalogue_revision_triggers.py": "03c531d47c50320c3f99f557ffd94df15e869b9cfceb5efa5b30700766c0c5ed",
    "0040_statement_authoring_metadata.py": "38094d06e4f6f5bbd02ec68bce8d55600d11cb680b469ec86a4972e998322466",
}
DIGEST = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_FIELDS = ("state_fingerprint", "schema_fingerprint", "migration_fingerprint")
MAX_DISCLOSURE_BYTES = 8192


def smoke_command():
    return (
        base_smoke_command()
        + """
from inspinia.solutions.models import ProblemSolution
solution=ProblemSolution.objects.get(title='Synthetic preserved solution')
if solution.blocks.get().body_source != 'Synthetic preserved proof.':
    raise RuntimeError('Active revision solution read failed')
"""
    )


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()
PLAN_CHECK = f"""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor=MigrationExecutor(connection)
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,[type(o).__name__ for o in m.operations]) for m,b in plan]
expected=[('pages','{MIGRATION_NAME}',False,['CreateModel'])]
if actual != expected:
    raise RuntimeError('Unapproved pending migration plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('pages','{MIGRATION_NAME}')])\n"


class StatementReportsSchemaError(ConceptSchemaError):
    pass


def _validate_fingerprints(value: dict[str, Any]) -> None:
    for stage in ("starting", "expected"):
        state = value[stage]
        if not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS):
            raise StatementReportsSchemaError("Invalid schema fingerprint fields")
        if any(not isinstance(v, str) or not DIGEST.fullmatch(v) for v in state.values()):
            raise StatementReportsSchemaError("Invalid schema fingerprints")
    if any(value["starting"][field] == value["expected"][field] for field in FINGERPRINT_FIELDS):
        raise StatementReportsSchemaError("The approved additive migration must change each fingerprint")


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
        raise StatementReportsSchemaError("Invalid bounded schema disclosure")
    if value["migration"] != MIGRATION or value["migration_file_sha256"] != MIGRATION_SHA256:
        raise StatementReportsSchemaError("Migration is outside the approved scope")
    if (
        not isinstance(value["active_sha"], str)
        or not SHA.fullmatch(value["active_sha"])
        or not SHA.fullmatch(target_sha)
        or value["target_sha"] != target_sha
        or value["active_sha"] == target_sha
    ):
        raise StatementReportsSchemaError("Schema disclosure release identity mismatch")
    for field in ("postgresql_rehearsal_sha256", "compatibility_smoke_sha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise StatementReportsSchemaError("Schema rehearsal and compatibility evidence must be frozen")
    if value["compatibility_smoke_sha256"] != COMPATIBILITY_SMOKE_SHA256:
        raise StatementReportsSchemaError(
            "Statement-report compatibility smoke differs from the approved fixed command",
        )
    _validate_fingerprints(value)
    if len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise StatementReportsSchemaError("Schema disclosure exceeds its bound")
    return value


def validate_candidate(release: Path) -> None:
    paths = {MIGRATION_PATH: MIGRATION_SHA256}
    paths.update({MIGRATION_PATH.parent / name: digest for name, digest in PRIOR_MIGRATIONS.items()})
    for relative, digest in paths.items():
        path = release / relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise StatementReportsSchemaError("Candidate migration bytes differ from the frozen solution plan")


def audit_matches(disclosure: dict[str, Any], audit: dict[str, Any], *, stage: str) -> bool:
    return audit.get("server_version_num") == POSTGRES_VERSION and all(
        audit.get(field) == disclosure[stage][field] for field in FINGERPRINT_FIELDS
    )


def validate_build_evidence(release: Path, disclosure: dict[str, Any]) -> None:
    import json

    path = release / EVIDENCE_PATH
    if path.is_symlink() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise StatementReportsSchemaError("Invalid packaged schema evidence")
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise StatementReportsSchemaError("Invalid packaged schema evidence JSON") from exc
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise StatementReportsSchemaError(
            "Packaged statement-report rehearsal proof digest does not match its disclosure",
        )
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
        "new_report_table_empty": True,
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
            "new_report_table_empty",
            "existing_trigger_definitions_unchanged",
        )
    ):
        raise StatementReportsSchemaError("Packaged PostgreSQL schema evidence does not match this release")


def expected_catalog_audit(start: dict[str, Any], rehearsal: dict[str, Any]) -> dict[str, Any]:
    """Append the rehearsed one-table delta to catalog metadata, without production data."""
    if start.get("server_version_num") != POSTGRES_VERSION or (
        hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
    ):
        raise StatementReportsSchemaError("Starting audit identity/version does not match the approved target")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    delta = normalize_schema_snapshot(rehearsal)
    if schema_state(delta)["fingerprint"] != DELTA_SHA256:
        raise StatementReportsSchemaError("Schema delta differs from the approved rehearsal")
    if any(row["table"] in TABLES for row in before["tables"]):
        raise StatementReportsSchemaError("Statement-report table already exists")
    if {row["table"] for row in delta["tables"]} != TABLES or delta["extensions"]:
        raise StatementReportsSchemaError("Rehearsal delta is not exactly the one approved table")
    if any(row["table"] not in TABLES for field in ("columns", "constraints", "indexes") for row in delta[field]):
        raise StatementReportsSchemaError("Rehearsal delta changes an existing schema object")
    if not any(
        row["schema"] == "public" and row["table"] == "pages_contestproblemstatement" for row in before["tables"]
    ):
        raise StatementReportsSchemaError("Existing statement table is required")
    migrations = start["migration_rows"]
    if ["pages", "0040_statement_authoring_metadata"] not in migrations:
        raise StatementReportsSchemaError("The previous statement migration must already be recorded")
    if ["pages", MIGRATION_NAME] in migrations:
        raise StatementReportsSchemaError("The approved migration is already recorded")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise StatementReportsSchemaError("Starting catalog evidence does not match its fingerprints")
    combined = {field: [*before[field], *delta[field]] for field in before}
    state = {
        **start["state"],
        "schema": schema_state(combined),
        "migration": migration_state([*migrations, ["pages", MIGRATION_NAME]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
    }
