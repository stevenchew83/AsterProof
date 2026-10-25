"""Database boundary for the reviewed algebra maintenance command."""

from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING

from django.db import connection
from django.db import transaction
from django.db.models import F
from django.db.models import Q
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.db.models.functions import NullIf
from django.db.models.functions import Trim
from django.db.models.functions import Upper
from django.utils import timezone

from inspinia.pages.algebra_tag_aliases import ALGEBRA_TOPICS
from inspinia.pages.algebra_tag_aliases import SUPPRESSED_STATUSES
from inspinia.pages.algebra_tag_aliases import TAG_FIELDS
from inspinia.pages.algebra_tag_aliases import AlgebraAliasError
from inspinia.pages.algebra_tag_cleanup import FIELD_KINDS
from inspinia.pages.algebra_tag_cleanup import build_cleanup_report
from inspinia.pages.algebra_tag_cleanup import digest
from inspinia.pages.algebra_tag_cleanup import label_key
from inspinia.pages.algebra_tag_cleanup import review_fingerprint
from inspinia.pages.algebra_tag_imports import IMPORT_LOCK_KEY
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import TechniqueBenchmarkAlias
from inspinia.pages.technique_progress_catalog import queue_technique_progress_catalog_refresh

if TYPE_CHECKING:
    from pathlib import Path

MAX_TAG_ROWS = 60000
MAX_BENCHMARK_ROWS = 20000

BENCHMARK_FIELDS = (
    "id",
    "kind",
    "label",
    "label_key",
    "normalized_label",
    "parent_family",
    "primary_area",
    "area_labels",
    "syllabus_core",
    "contest_frequency",
    "transfer_value",
    "prerequisite_value",
    "mohs_scalability",
    "concept_load",
    "recognition_burden",
    "execution_load",
    "proof_fragility",
    "cross_topic_dependency",
    "difficulty_score",
    "importance_score",
    "typical_mohs_min",
    "typical_mohs_max",
    "typical_mohs_center",
    "jbmo_weight",
    "national_weight",
    "imo_tst_weight",
    "training_type",
    "target_level",
    "benchmark_confidence",
    "quality_flags",
)
ALIAS_FIELDS = ("id", "kind", "alias_label", "alias_key", "benchmark_id", "reason")


def _database_target() -> dict:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port()")
            database, role, address, port = cursor.fetchone()
        return {"vendor": connection.vendor, "database": database, "role": role, "address": address, "port": port}
    return {"vendor": connection.vendor, "database": str(connection.settings_dict["NAME"])}


def _guard_fingerprints(data: dict) -> dict:
    excluded = []
    for source, parent_key in (("problem", "problems"), ("statement", "statements")):
        parents = {row["id"]: row for row in data[parent_key]}
        for row in data[f"{source}_tags"]:
            parent = parents[row["parent_id"]]
            if (
                not parent["in_scope"] or not parent["is_active"]
                or str(row["normalization_status"]).strip().casefold() in SUPPRESSED_STATUSES
            ):
                excluded.append({"source": source, **row})
    return {
        "benchmark_definitions": digest(data["benchmarks"]),
        "parent_identities": digest({key: data[key] for key in ("problems", "statements")}),
        "excluded_tag_rows": digest(excluded),
    }


def _outside_alias_usage(plan: dict) -> dict:
    keys = {(r["kind"], r["alias_key"]) for r in plan["benchmark_alias_actions"] if r["action"] == "insert"}
    parents = {
        "problem": {r["id"]: r for r in ProblemSolveRecord.objects.values("id", "topic", "is_active")},
        "statement": {
            r["id"]: r for r in ContestProblemStatement.objects.values("id", "topic", "is_active", "linked_problem_id")
        },
    }
    counts = defaultdict(lambda: {"tag_rows": 0, "parents": set()})
    for source, model, fk in (
        ("problem", ProblemTopicTechnique, "record_id"),
        ("statement", StatementTopicTechnique, "statement_id"),
    ):
        for row in model.objects.values(fk, *FIELD_KINDS).iterator(chunk_size=1000):
            parent = parents[source][row[fk]]
            topic = parent["topic"]
            if source == "statement" and not str(topic or "").strip():
                topic = parents["problem"].get(parent["linked_problem_id"], {}).get("topic", "")
            algebra = str(topic or "").strip().upper() in ALGEBRA_TOPICS
            for field, kind in FIELD_KINDS.items():
                values = row[field] if isinstance(row[field], list) else [row[field]]
                for value in set(values):
                    pair = kind, label_key(value)
                    if pair in keys:
                        group = source, field, value, pair[0], pair[1], algebra, parent["is_active"]
                        counts[group]["tag_rows"] += 1
                        counts[group]["parents"].add(row[fk])
    usage = [
        {
            "source": key[0],
            "field": key[1],
            "label": key[2],
            "kind": key[3],
            "alias_key": key[4],
            "algebra": key[5],
            "is_active": key[6],
            "tag_rows": value["tag_rows"],
            "parent_count": len(value["parents"]),
        }
        for key, value in counts.items()
    ]
    return {"identity": {"query_effects": "select_only"}, "current_usage": usage}


def capture_snapshot(plan: dict) -> dict:
    """Read ORM projections only; do not call catalog helpers that create state."""
    problem_scope = ProblemSolveRecord.objects.annotate(scope_topic=Upper(Trim("topic"))).filter(
        scope_topic__in=ALGEBRA_TOPICS,
    )
    statement_scope = ContestProblemStatement.objects.annotate(
        effective_topic=Coalesce(NullIf(Trim("topic"), Value("")), F("linked_problem__topic"), Value("")),
    ).annotate(scope_topic=Upper(Trim("effective_topic")))
    statements = list(
        statement_scope.filter(Q(scope_topic__in=ALGEBRA_TOPICS) | Q(linked_problem_id__in=problem_scope.values("id")))
        .values(
            "id",
            "problem_uuid",
            "topic",
            "effective_topic",
            "is_active",
            "linked_problem_id",
            "linked_problem__problem_uuid",
            "contest_year_problem",
        )
        .order_by("id"),
    )
    problems = list(
        ProblemSolveRecord.objects.filter(
            Q(id__in=problem_scope.values("id")) | Q(id__in=[r["linked_problem_id"] for r in statements]),
        )
        .values("id", "problem_uuid", "topic", "is_active", "contest", "year", "problem")
        .order_by("id"),
    )
    for row in problems:
        row["reference"] = f"{row.pop('contest')} {row.pop('year')} {row.pop('problem')}"
        row["in_scope"] = str(row["topic"] or "").strip().upper() in ALGEBRA_TOPICS
        row["problem_uuid"] = str(row["problem_uuid"])
    for row in statements:
        row["reference"] = row.pop("contest_year_problem")
        linked_uuid = row.pop("linked_problem__problem_uuid")
        row["linked_problem_uuid"] = str(linked_uuid) if linked_uuid else None
        row["problem_uuid"] = str(row["problem_uuid"])
        row["in_scope"] = str(row["effective_topic"] or "").strip().upper() in ALGEBRA_TOPICS
    data = {
        "identity": {
            "captured_at_utc": timezone.now().isoformat(), "source": "Django ORM", "target": _database_target(),
        },
        "problems": problems,
        "statements": statements,
    }
    for source, model, fk, parents in (
        ("problem", ProblemTopicTechnique, "record_id", problems),
        ("statement", StatementTopicTechnique, "statement_id", statements),
    ):
        rows = list(
            model.objects.filter(**{f"{fk}__in": [r["id"] for r in parents]})
            .values("id", fk, *TAG_FIELDS)
            .order_by(fk, "id"),
        )
        for row in rows:
            row["parent_id"] = row.pop(fk)
        data[f"{source}_tags"] = rows
    data["benchmarks"] = list(TechniqueBenchmark.objects.values(*BENCHMARK_FIELDS).order_by("id"))
    data["benchmark_aliases"] = list(TechniqueBenchmarkAlias.objects.values(*ALIAS_FIELDS).order_by("id"))
    if (
        max(len(data["problem_tags"]), len(data["statement_tags"])) > MAX_TAG_ROWS
        or len(data["benchmarks"]) > MAX_BENCHMARK_ROWS
    ):
        message = "Algebra cleanup snapshot exceeds its reviewed bounds."
        raise AlgebraAliasError(message)
    data["alias_impact"] = _outside_alias_usage(plan)
    # JSON roundtrip gives the same UUID/Decimal representation as the production reader.
    data = json.loads(json.dumps(data, default=str))
    data["identity"]["guard_fingerprints"] = _guard_fingerprints(data)
    return data


def _write_audit(path: Path, value: dict, *, exclusive: bool = False) -> None:
    target = path if exclusive else path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target, flags, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    if not exclusive:
        target.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _require_import_lock(*, acquired: bool) -> None:
    if not acquired:
        message = "An import is in progress; cleanup application is refused."
        raise AlgebraAliasError(message)


def _lock_dependencies(reviewed: dict) -> None:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '1s'")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [IMPORT_LOCK_KEY])
            _require_import_lock(acquired=cursor.fetchone()[0])
    # Parent locks also prevent child insertions from racing a reviewed merge.
    for source, model, tag_model, fk in (
        ("problem", ProblemSolveRecord, ProblemTopicTechnique, "record_id"),
        ("statement", ContestProblemStatement, StatementTopicTechnique, "statement_id"),
    ):
        ids = {a["parent_id"] for a in reviewed["tag_actions"] if a["source"] == source}
        list(model.objects.filter(id__in=ids).select_for_update(nowait=True).values_list("id", flat=True))
        list(
            tag_model.objects.filter(**{f"{fk}__in": ids}).select_for_update(nowait=True).values_list("id", flat=True),
        )
    # Benchmark definitions are small maintenance metadata. Lock the resolver
    # dependencies so no existing score or alias can change during application.
    list(TechniqueBenchmark.objects.select_for_update(nowait=True).values_list("id", flat=True))
    list(TechniqueBenchmarkAlias.objects.select_for_update(nowait=True).values_list("id", flat=True))


def _require_matching_review(fresh: dict, reviewed: dict) -> None:
    if fresh["identity"].get("target") != reviewed.get("identity", {}).get("target"):
        message = "The database target differs from the reviewed dry run; application is refused."
        raise AlgebraAliasError(message)
    if fresh["conflicts"] or review_fingerprint(fresh) != review_fingerprint(reviewed):
        message = "Production before-values changed; generate and review a new dry run."
        raise AlgebraAliasError(message)


def _apply_changes(fresh: dict) -> None:
    for action in fresh["alias_actions"]:
        values = {k: v for k, v in action["after"].items() if k != "id"}
        if action["action"] == "insert":
            TechniqueBenchmarkAlias.objects.create(**values)
        else:
            TechniqueBenchmarkAlias.objects.filter(id=action["alias_id"]).update(**values)
    for source, model in (("problem", ProblemTopicTechnique), ("statement", StatementTopicTechnique)):
        actions = [a for a in fresh["tag_actions"] if a["source"] == source]
        model.objects.filter(id__in=[a["row_id"] for a in actions if a["action"] == "merge_remove"]).delete()
        updates = [model(id=a["row_id"], **a["after"]) for a in actions if a["action"] == "update"]
        if updates:
            model.objects.bulk_update(updates, TAG_FIELDS, batch_size=200)
    if fresh["tag_actions"]:
        queue_technique_progress_catalog_refresh(statement_ids=fresh["catalog_statement_ids"])


def apply_reviewed_report(
    reviewed: dict,
    plan: dict,
    *,
    policy: dict,
    plan_sha256: str,
    audit_directory: Path,
) -> dict:
    """Explicit apply only: lock, replan, audit before DML, then commit atomically."""
    if reviewed["conflicts"]:
        message = "The reviewed dry run has conflicts; application is refused."
        raise AlgebraAliasError(message)
    if connection.in_atomic_block:
        message = "Cleanup application requires a standalone transaction."
        raise AlgebraAliasError(message)
    audit_directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    operation_id = str(uuid.uuid4())
    receipt = {"operation_id": operation_id, "status": "preparing", "review_fingerprint": review_fingerprint(reviewed)}
    receipt_path = audit_directory / "receipt.json"
    _write_audit(receipt_path, receipt, exclusive=True)
    committed = False
    commit_started = False
    try:
        with transaction.atomic():
            _lock_dependencies(reviewed)
            fresh = build_cleanup_report(capture_snapshot(plan), plan, policy=policy, plan_sha256=plan_sha256)
            _require_matching_review(fresh, reviewed)
            _write_audit(audit_directory / "before-and-after.json", fresh, exclusive=True)
            receipt["status"] = "prepared"
            _write_audit(receipt_path, receipt)
            _apply_changes(fresh)
            commit_started = True
        committed = True
        receipt["status"] = "committed"
        _write_audit(receipt_path, receipt)
    except Exception:
        if committed or commit_started:
            message = (
                f"Commit was attempted; reconcile the database and audit before retrying operation {operation_id}."
            )
            raise AlgebraAliasError(message) from None
        receipt["status"] = "failed_before_commit"
        _write_audit(receipt_path, receipt)
        raise
    return receipt
