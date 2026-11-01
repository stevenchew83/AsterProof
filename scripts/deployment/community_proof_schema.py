# ruff: noqa: EM101, TRY003
"""Frozen data-class allowance for one Community Proof Library migration."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from scripts.deployment import catalogue_schema
from scripts.deployment import community_schema
from scripts.deployment.schema_fingerprint import canonical_json
from scripts.deployment.schema_fingerprint import migration_state
from scripts.deployment.schema_fingerprint import normalize_schema_snapshot
from scripts.deployment.schema_fingerprint import schema_state
from scripts.deployment.schema_rehearsal import REHEARSAL_DATABASE

KIND = "community-proof-library-maintenance-v1"
MIGRATIONS = ("0045_community_proof_library",)
MIGRATION_CLASSES = ("data-or-non-compatible",)
INPUT_HASHES = {
    "inspinia/pages/migrations/0045_community_proof_library.py":
        "63892e34819c93bbba63820cd7ba397afb8a1408d53b016d2063ad212c11be32",
}
PREREQUISITE_HASHES = {
    **community_schema.INPUT_HASHES,
    "inspinia/pages/migrations/0044_learning_page_activity.py":
        "a55e4fe4f34729e7db3f1c4bf67a1deaadeb39f799958b900e2c5d840e9559e2",
    "inspinia/solutions/migrations/0010_offline_evaluation_contract.py":
        "9fee1f590a8cdde9df9d30c201a49caea20a5c31efe2f4b0aa7c92171d4844a8",
}
PREREQUISITE_MIGRATIONS = (
    ("pages", "0044_learning_page_activity"),
    ("solutions", "0010_offline_evaluation_contract"),
)
TABLE = "pages_communityproblem"
NEW_COLUMNS = ("embargo_until", "legacy_member_visible", "public_hint", "solution_known")
TABLES = frozenset("pages_" + name for name in (
    "communityattempt", "communityprivateasset", "communityproblemrevision",
    "communitysolution", "communitycontentreport", "communitysolutionrevision",
    "communitysolutionasset", "moderationevent", "problempublication",
))
# Preparation is deliberately fail-closed until pinned PostgreSQL discovery is reviewed.
DELTA_SHA256 = "0" * 64
DELTA_PATH = Path("scripts/deployment/tests/fixtures/community-proof-schema-delta.json")
BEHAVIOUR_SHA256 = community_schema.BEHAVIOUR_SHA256
POSTGRES_VERSION = 170009
FINGERPRINT_FIELDS = catalogue_schema.FINGERPRINT_FIELDS
RECOVERY_POLICY = catalogue_schema.RECOVERY_POLICY
EVIDENCE_PATH = "deployment-schema-evidence.json"
MAX_DISCLOSURE_BYTES = 8192
FUNCTION_SQL = community_schema.FUNCTION_SQL
TRIGGERS_SQL = community_schema.TRIGGERS_SQL
OPERATION_SIGNATURES = (
    ("AddField", "communityproblem", "embargo_until", None),
    ("AddField", "communityproblem", "legacy_member_visible", None),
    ("AlterField", "communityproblem", "legacy_member_visible", None),
    ("AddField", "communityproblem", "public_hint", None),
    ("AddField", "communityproblem", "solution_known", None),
    ("AlterField", "communityproblem", "core_ideas", None),
    ("AlterField", "communityproblem", "mohs", None),
    ("AlterField", "communityproblem", "rationale", None),
    ("AlterField", "communityproblem", "topic_tags", None),
    ("CreateModel", None, "CommunityAttempt", None),
    ("CreateModel", None, "CommunityPrivateAsset", None),
    ("CreateModel", None, "CommunityProblemRevision", None),
    ("AddField", "communityattempt", "statement_revision", None),
    ("CreateModel", None, "CommunitySolution", None),
    ("CreateModel", None, "CommunityContentReport", None),
    ("CreateModel", None, "CommunitySolutionRevision", None),
    ("CreateModel", None, "CommunitySolutionAsset", None),
    ("AddField", "communitysolution", "current_revision", None),
    ("CreateModel", None, "ModerationEvent", None),
    ("CreateModel", None, "ProblemPublication", None),
    ("AddConstraint", "communityproblemrevision", None, "pages_cpr_problem_number_unique"),
    ("AddConstraint", "communityproblemrevision", None, "pages_cpr_number_positive"),
    ("AddConstraint", "communityattempt", None, "pages_ca_owner_problem_revision_unique"),
    ("AddConstraint", "communitysolutionrevision", None, "pages_csr_solution_number_unique"),
    ("AddConstraint", "communitysolutionrevision", None, "pages_csr_number_positive"),
    ("AddConstraint", "communitysolutionasset", None, "pages_csa_revision_name_unique"),
)
FLAGS = (
    "schema_delta_exact", "source_fixture_unchanged", "existing_records_unchanged",
    "existing_sequences_unchanged", "existing_trigger_definitions_unchanged",
    "existing_privileges_unchanged", "migration_record_exact", "legacy_audience_preserved",
    "new_posts_private", "no_public_content_backfill", "active_revision_smoke_passed",
    "authenticated_privacy_routes_passed", "ai_review_disabled", "ai_policy_unfunded",
)
AI_OFF_CHECK = """from django.conf import settings
from django.db.models import Q
from inspinia.pages.community_models import StatementReviewPolicy
from inspinia.solutions.review_models import SolutionReviewPolicy
if (getattr(settings,'PROBLEM_STATEMENT_AI_REVIEW_ENABLED',False) is not False
    or getattr(settings,'SOLUTION_AI_REVIEW_ENABLED',False) is not False):
    raise RuntimeError('Both AI review flags must remain disabled')
for policy_model in (StatementReviewPolicy,SolutionReviewPolicy):
    if policy_model.objects.filter(Q(enabled=True)|Q(request_budget_micros__gt=0)
        |Q(daily_budget_micros__gt=0)|Q(monthly_budget_micros__gt=0)).exists():
        raise RuntimeError('AI review policies must remain disabled and unfunded')
"""
PLAN_CHECK = AI_OFF_CHECK + f"""from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
if (getattr(settings,'PROBLEM_STATEMENT_AI_REVIEW_ENABLED',False) is not False
    or getattr(settings,'SOLUTION_AI_REVIEW_ENABLED',False) is not False):
    raise RuntimeError('Both AI review flags must remain disabled')
executor=MigrationExecutor(connection)
if not set({PREREQUISITE_MIGRATIONS!r}).issubset(executor.loader.applied_migrations):
    raise RuntimeError('Community proof prerequisites must already be applied')
plan=executor.migration_plan(executor.loader.graph.leaf_nodes())
actual=[(m.app_label,m.name,b,tuple((type(o).__name__,getattr(o,'model_name',None),
    getattr(o,'name',None),getattr(getattr(o,'constraint',None),'name',None))
    for o in m.operations)) for m,b in plan]
expected=[('pages','{MIGRATIONS[0]}',False,{OPERATION_SIGNATURES!r})]
if actual != expected:
    raise RuntimeError('Pending migrations differ from the frozen community proof plan')
"""
MIGRATION_APPLY = PLAN_CHECK + f"executor.migrate([('pages','{MIGRATIONS[0]}')])\n"


def smoke_command():
    """Old-code reads run inside a PostgreSQL read-only transaction, never old writes."""
    return (
        "from django.conf import settings\n"
        f"settings.DATABASES={{'default':{REHEARSAL_DATABASE!r}}}\n"
        "settings.CONCEPT_ASSIGNMENTS_ENABLED=False\n"
        "settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED=False\n"
        "settings.SOLUTION_AI_REVIEW_ENABLED=False\n"
        "import django\ndjango.setup()\n"
        "from django.db import connection,transaction\n"
        "from django.test import RequestFactory,override_settings\n"
        "from django.urls import resolve\n"
        "from inspinia.pages.community_models import CommunityProblem\n"
        "from inspinia.solutions.models import ProblemSolution\n"
        "from inspinia.users.models import User\n"
        "with transaction.atomic(),override_settings(ALLOWED_HOSTS=['testserver']):\n"
        "    with connection.cursor() as cursor:\n"
        "        cursor.execute('SET TRANSACTION READ ONLY')\n"
        "        cursor.execute(\"SET LOCAL statement_timeout='30s'\")\n"
        "        cursor.execute(\"SET LOCAL lock_timeout='1s'\")\n"
        "    user=User.objects.get(email='schema-rehearsal@example.invalid')\n"
        "    rows=list(CommunityProblem.objects.filter(title__startswith='Synthetic legacy '))\n"
        "    if len(rows)!=2 or any(row.mohs!=12 for row in rows):\n"
        "        raise RuntimeError('Active revision legacy statement reads failed')\n"
        "    if ProblemSolution.objects.get(title='Synthetic preserved solution').blocks.get().body_source"
        " != 'Synthetic preserved proof.':\n"
        "        raise RuntimeError('Active revision private archive proof read failed')\n"
        "    factory=RequestFactory()\n"
        "    for url in ['/community/problems/','/community/problems/?tab=all',"
        "*['/community/problems/'+str(row.pk)+'/' for row in rows]]:\n"
        "        request=factory.get(url)\n"
        "        request.user=user\n"
        "        if resolve(request.path).func(request).status_code!=200:\n"
        "            raise RuntimeError('Active revision community reader failed')\n"
    )


COMPATIBILITY_SMOKE_SHA256 = hashlib.sha256(smoke_command().encode()).hexdigest()


def _require_frozen_delta():
    if not re.fullmatch(r"[0-9a-f]{64}", DELTA_SHA256) or DELTA_SHA256 == "0" * 64:
        raise ValueError("Community proof PostgreSQL delta has not been frozen")


def normalize_delta(value):
    if not isinstance(value, dict) or set(value) != {"add", "remove"}:
        raise ValueError("Community proof delta permits only add/remove catalog records")
    return {name: normalize_schema_snapshot(value[name]) for name in ("add", "remove")}


def delta_digest(value):
    return hashlib.sha256(canonical_json(normalize_delta(value))).hexdigest()


def catalog_delta(before, after):
    before, after = normalize_schema_snapshot(before), normalize_schema_snapshot(after)
    return normalize_delta({
        "add": {field: [row for row in after[field] if row not in before[field]] for field in before},
        "remove": {field: [row for row in before[field] if row not in after[field]] for field in before},
    })


def validate_delta_shape(value):  # noqa: C901 - Explicit allowlist for each catalog category and nullable-only change.
    """Structural guard used before discovery is frozen and again before activation."""
    delta = normalize_delta(value)
    added, removed = delta["add"], delta["remove"]
    if {row["table"] for row in added["tables"]} != TABLES or any(
        row["schema"] != "public" or row["kind"] != "r" for row in added["tables"]
    ):
        raise ValueError("Community proof delta must add exactly the nine ordinary tables")
    if added["extensions"] or any(removed[name] for name in ("tables", "constraints", "indexes", "extensions")):
        raise ValueError("Community proof delta cannot remove objects or change extensions/privileges")
    if any(
        row["schema"] != "public" or row["table"] not in TABLES
        for name in ("constraints", "indexes") for row in added[name]
    ):
        raise ValueError("Community proof delta changes an existing constraint or index")
    if any(
        row["schema"] != "public" or row["table"] not in {*TABLES, TABLE}
        for row in added["columns"]
    ):
        raise ValueError("Community proof delta changes an unrelated column")
    prior_columns = [row for row in added["columns"] if row["table"] == TABLE]
    if (
        {row["column"] for row in prior_columns} != {*NEW_COLUMNS, "mohs"}
        or len(prior_columns) != len(NEW_COLUMNS) + 1
    ):
        raise ValueError("Community proof delta must add only its four columns and nullable MOHS")
    if {row["table"] for row in added["columns"] if row["table"] in TABLES} != TABLES:
        raise ValueError("Community proof delta is missing a new table's columns")
    if len(removed["columns"]) != 1:
        raise ValueError("Community proof delta must replace only the old MOHS nullability")
    old = removed["columns"][0]
    new = next(row for row in prior_columns if row["column"] == "mohs")
    if (
        old["schema"] != "public" or old["table"] != TABLE or old["column"] != "mohs"
        or old["nullable"] is not False or new != {**old, "nullable": True}
    ):
        raise ValueError("Community proof MOHS change exceeds nullable-only scope")
    types = {
        "embargo_until": ("timestamp with time zone", True), "legacy_member_visible": ("boolean", False),
        "public_hint": ("text", False), "solution_known": ("boolean", False),
    }
    for row in prior_columns:
        if row["column"] != "mohs":
            kind, nullable = types[row["column"]]
            if row["type"] != kind or row["nullable"] is not nullable or row["default"] is not None:
                raise ValueError("Community proof added column type/default/nullability differs")
    return delta


def validate_candidate(release: Path, *, require_delta=True):
    root = release.resolve()
    for name, expected in {**INPUT_HASHES, **PREREQUISITE_HASHES}.items():
        path = release / name
        if (
            path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root)
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("Community proof migration/prerequisite differs from its frozen hash")
    if require_delta:
        _require_frozen_delta()
        path = release / DELTA_PATH
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("Community proof frozen delta fixture is unavailable")
        delta = validate_delta_shape(json.loads(path.read_bytes()))
        if delta_digest(delta) != DELTA_SHA256:
            raise ValueError("Community proof delta differs from its frozen hash")


def behaviour_snapshot(connection):
    return community_schema.behaviour_snapshot(connection)


def rehearsal_evidence(*, release_sha, active_sha):
    _require_frozen_delta()
    return {
        "format_version": 1, "purpose": "deployment-proof", "source_sha": release_sha,
        "active_sha": active_sha, "postgres_version": POSTGRES_VERSION, "input_hashes": INPUT_HASHES,
        "prerequisite_hashes": PREREQUISITE_HASHES, "delta_sha256": DELTA_SHA256,
        "behaviour_sha256": BEHAVIOUR_SHA256, "compatibility_smoke_sha256": COMPATIBILITY_SMOKE_SHA256,
        **dict.fromkeys(FLAGS, True),
    }


def evidence_bytes(*, release_sha, active_sha):
    return (json.dumps(rehearsal_evidence(
        release_sha=release_sha, active_sha=active_sha,
    ), sort_keys=True, indent=2) + "\n").encode()


def validate_rehearsal_evidence(value, *, release_sha, active_sha):
    if (
        not isinstance(value, dict) or type(value.get("format_version")) is not int
        or type(value.get("postgres_version")) is not int
        or value != rehearsal_evidence(release_sha=release_sha, active_sha=active_sha)
        or any(value.get(field) is not True for field in FLAGS)
    ):
        raise ValueError("Community proof rehearsal evidence differs from the exact release")


def validate_disclosure(value, *, target_sha):
    _require_frozen_delta()
    fields = {
        "format_version", "kind", "active_sha", "target_sha", "input_hashes",
        "starting", "expected", "postgresql_rehearsal_sha256", "recovery_policy",
    }
    if not isinstance(value, dict) or set(value) != fields or type(value.get("format_version")) is not int:
        raise ValueError("Malformed community proof maintenance disclosure")
    if value["format_version"] != 1 or value["kind"] != KIND or value["input_hashes"] != INPUT_HASHES:
        raise ValueError("Community proof migration is outside its frozen scope")
    if (
        not isinstance(target_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", target_sha)
        or not isinstance(value["active_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", value["active_sha"])
        or value["target_sha"] != target_sha or value["active_sha"] == target_sha
    ):
        raise ValueError("Community proof release identity mismatch")
    for name in ("starting", "expected"):
        state = value[name]
        if (
            not isinstance(state, dict) or set(state) != set(FINGERPRINT_FIELDS)
            or any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item) for item in state.values())
        ):
            raise ValueError("Community proof fingerprints differ from the fixed shape")
    if (
        any(value[name]["behaviour_fingerprint"] != BEHAVIOUR_SHA256 for name in ("starting", "expected"))
        or any(value["starting"][name] == value["expected"][name] for name in FINGERPRINT_FIELDS
               if name != "behaviour_fingerprint")
    ):
        raise ValueError("Community proof requires changed schema/state/migrations and unchanged behavior")
    policy = value["recovery_policy"]
    if (
        not isinstance(policy, dict) or policy != RECOVERY_POLICY
        or any(type(policy[key]) is not type(expected) for key, expected in RECOVERY_POLICY.items())
    ):
        raise ValueError("Community proof requires the unchanged verified recovery policy")
    digest = hashlib.sha256(evidence_bytes(release_sha=target_sha, active_sha=value["active_sha"])).hexdigest()
    if value["postgresql_rehearsal_sha256"] != digest or len(canonical_json(value)) > MAX_DISCLOSURE_BYTES:
        raise ValueError("Community proof rehearsal digest differs from the exact release")
    return value


def validate_build_evidence(release, disclosure):
    _require_frozen_delta()
    path = release / EVIDENCE_PATH
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DISCLOSURE_BYTES:
        raise ValueError("Invalid packaged community proof rehearsal evidence")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != disclosure["postgresql_rehearsal_sha256"]:
        raise ValueError("Packaged community proof rehearsal digest differs")
    validate_rehearsal_evidence(
        json.loads(content), release_sha=disclosure["target_sha"], active_sha=disclosure["active_sha"],
    )


def expected_catalog_audit(start, value):
    _require_frozen_delta()
    if (
        start.get("server_version_num") != POSTGRES_VERSION
        or hashlib.sha256(canonical_json(start["state"])).hexdigest() != start["state_fingerprint"]
        or start.get("behaviour_fingerprint") != BEHAVIOUR_SHA256
    ):
        raise ValueError("Starting community proof audit identity/version/behavior mismatch")
    delta = validate_delta_shape(value)
    if delta_digest(delta) != DELTA_SHA256:
        raise ValueError("Community proof delta differs from the frozen PostgreSQL rehearsal")
    before = normalize_schema_snapshot(start["catalog_snapshot"])
    if any(row["table"] in TABLES for row in before["tables"]) or not any(
        row["schema"] == "public" and row["table"] == TABLE for row in before["tables"]
    ):
        raise ValueError("Community proof starting tables differ or are already installed")
    old_columns = [row for row in before["columns"] if row["table"] == TABLE]
    maximum = max(row["position"] for row in old_columns)
    added_columns = {row["column"]: row for row in delta["add"]["columns"] if row["table"] == TABLE}
    if any(added_columns[name]["position"] != maximum + position for position, name in enumerate(NEW_COLUMNS, 1)):
        raise ValueError("Community proof columns must append in the frozen order")
    combined = {}
    for field in before:
        if any(row not in before[field] for row in delta["remove"][field]):
            raise ValueError("Community proof removal does not match the starting catalog")
        if any(row in before[field] for row in delta["add"][field]):
            raise ValueError("Community proof addition already exists in the starting catalog")
        combined[field] = [
            *[row for row in before[field] if row not in delta["remove"][field]], *delta["add"][field],
        ]
    migrations = start["migration_rows"]
    if any(["pages", name] in migrations for name in MIGRATIONS) or not all(
        list(pair) in migrations for pair in PREREQUISITE_MIGRATIONS
    ):
        raise ValueError("Community proof prerequisites are missing or the migration is already installed")
    if schema_state(before) != start["state"]["schema"] or migration_state(migrations) != start["state"]["migration"]:
        raise ValueError("Starting community proof catalog differs from its fingerprints")
    state = {
        **start["state"], "schema": schema_state(combined),
        "migration": migration_state([*migrations, *[["pages", name] for name in MIGRATIONS]]),
    }
    return {
        "state_fingerprint": hashlib.sha256(canonical_json(state)).hexdigest(),
        "schema_fingerprint": state["schema"]["fingerprint"],
        "migration_fingerprint": state["migration"]["fingerprint"],
        "behaviour_fingerprint": BEHAVIOUR_SHA256,
    }
