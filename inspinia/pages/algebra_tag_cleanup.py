"""Pure, reviewable planner used by both dry-run and transactional application."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections import defaultdict
from copy import deepcopy

from inspinia.pages.algebra_tag_aliases import ARRAY_FIELDS
from inspinia.pages.algebra_tag_aliases import SUPPRESSED_STATUSES
from inspinia.pages.algebra_tag_aliases import TAG_FIELDS
from inspinia.pages.algebra_tag_aliases import AlgebraAliasError
from inspinia.pages.algebra_tag_aliases import merge_raw_sources
from inspinia.pages.algebra_tag_aliases import normalize_tag_fields
from inspinia.pages.algebra_tag_aliases import unique

FIELD_KINDS = {
    "canonical_subtopic": "canonical_subtopic",
    "technique": "technique",
    "technique_tags": "method",
    "object_tags": "object",
    "lemma_theorem_tags": "lemma",
    "proof_roles": "proof_role",
}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def label_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "").strip().lower()).replace("&", " and ")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value)).strip("-")


def tag_values(row: dict) -> dict:
    return {field: deepcopy(row[field]) for field in TAG_FIELDS}


def resolve_benchmark(snapshot: dict, kind: str, label: str) -> int | None:
    key = label_key(label)
    direct = next((r for r in snapshot["benchmarks"] if r["kind"] == kind and r["label_key"] == key), None)
    if direct:
        return direct["id"]
    alias = next((r for r in snapshot["benchmark_aliases"] if r["kind"] == kind and r["alias_key"] == key), None)
    return alias["benchmark_id"] if alias else None


def _alias_actions(snapshot: dict, plan: dict, conflicts: list) -> tuple[list, dict]:
    projected = deepcopy(snapshot)
    actions = []
    for intended in plan["benchmark_alias_actions"]:
        target = intended["candidate_after"]
        existing = next(
            (
                r
                for r in projected["benchmark_aliases"]
                if r["kind"] == target["kind"] and r["alias_key"] == target["alias_key"]
            ),
            None,
        )
        if existing and all(existing.get(k) == v for k, v in target.items() if k != "id"):
            continue
        if intended["action"] == "insert":
            if existing or resolve_benchmark(projected, target["kind"], target["alias_key"]) is not None:
                conflicts.append({"type": "ALIAS_KEY_CHANGED", "key": target["alias_key"]})
                continue
            action = {"action": "insert", "alias_id": None, "before": None, "after": deepcopy(target)}
            projected["benchmark_aliases"].append({"id": -(len(actions) + 1), **target})
        else:
            if existing != intended["before"]:
                conflicts.append({"type": "ALIAS_BEFORE_CHANGED", "alias_id": intended["alias_id"]})
                continue
            winner = resolve_benchmark(projected, target["kind"], target["alias_key"])
            if winner != target["benchmark_id"]:
                conflicts.append({"type": "DIRECT_BENCHMARK_CHANGED", "key": target["alias_key"]})
                continue
            action = {
                "action": "update",
                "alias_id": existing["id"],
                "before": deepcopy(existing),
                "after": deepcopy(target),
            }
            existing.update(target)
        benchmark = next((r for r in projected["benchmarks"] if r["id"] == target["benchmark_id"]), None)
        if not benchmark or benchmark["kind"] != target["kind"]:
            conflicts.append({"type": "BENCHMARK_KIND_CHANGED", "key": target["alias_key"]})
        actions.append(action)
    return actions, projected


def _combine_keeper_fields(keeper: dict, rows: list, metadata: tuple) -> None:
    for field in ARRAY_FIELDS:
        keeper[field] = unique(
            [
                *keeper[field],
                *(
                    item
                    for row in sorted(rows, key=lambda r: r["id"])
                    if row["id"] != keeper["id"]
                    for item in row[field]
                ),
            ],
        )
    for field in metadata:
        if not keeper[field]:
            keeper[field] = next((row[field] for row in rows if row[field]), "")


def _merge_rows(before: dict, after: dict, eligible: dict, *, source: str, conflicts: list) -> dict:
    groups = defaultdict(list)
    for row in after.values():
        groups[(row["parent_id"], row["technique"])].append(row)
    removed = {}
    for (_parent_id, technique), rows in groups.items():
        if len(rows) <= 1:
            continue
        ids = sorted(r["id"] for r in rows)
        if not all(eligible[rid] for rid in ids):
            conflicts.append({"type": "MERGE_TOUCHES_EXCLUDED_ROW", "source": source, "row_ids": ids})
            continue
        metadata = ("main_topic", "canonical_subtopic", "normalization_status", "normalization_confidence")
        disagreements = [field for field in metadata if len({r[field] for r in rows if r[field]}) > 1]
        if disagreements:
            conflicts.append(
                {"type": "MERGE_METADATA_CONFLICT", "source": source, "row_ids": ids, "fields": disagreements},
            )
            continue
        keeper = min(rows, key=lambda r: (before[r["id"]]["technique"] != technique, r["id"]))
        try:
            raw_tag = merge_raw_sources([before[rid]["raw_tag"] or before[rid]["technique"] for rid in ids])
        except AlgebraAliasError as exc:
            conflicts.append({"type": "PROVENANCE_OVERFLOW", "source": source, "row_ids": ids, "detail": str(exc)})
            continue
        _combine_keeper_fields(keeper, rows, metadata)
        keeper["raw_tag"] = raw_tag
        for rid in ids:
            if rid != keeper["id"]:
                removed[rid] = keeper["id"]
                del after[rid]
    return removed


def _validate_changed_row(new: dict | None, *, source: str, rid: int, eligible: bool) -> list:
    conflicts = []
    if not eligible:
        conflicts.append({"type": "EXCLUDED_ROW_CHANGED", "source": source, "row_id": rid})
    if new is None:
        return conflicts
    for field, maximum in (("technique", 512), ("main_topic", 16), ("canonical_subtopic", 160), ("raw_tag", 512)):
        if len(new[field]) > maximum or (field == "technique" and not new[field]):
            conflicts.append({"type": "INVALID_FIELD_LENGTH", "source": source, "row_id": rid, "field": field})

    return conflicts


def _tag_actions(snapshot: dict, policy: dict, conflicts: list) -> list[dict]:
    actions = []
    for source, parent_key in (("problem", "problems"), ("statement", "statements")):
        parents = {r["id"]: r for r in snapshot[parent_key]}
        before = {r["id"]: r for r in snapshot[f"{source}_tags"]}
        after = {}
        eligible = {}
        for rid, row in before.items():
            parent = parents[row["parent_id"]]
            eligible[rid] = bool(
                parent["in_scope"]
                and parent["is_active"]
                and str(row["normalization_status"]).strip().casefold() not in SUPPRESSED_STATUSES,
            )
            fields = normalize_tag_fields(
                tag_values(row),
                topic=parent.get("effective_topic", parent["topic"]),
                active=parent["is_active"] and parent["in_scope"],
                problem_uuid=parent["problem_uuid"],
                policy=policy,
            )
            after[rid] = {**row, **fields}
        removed = _merge_rows(before, after, eligible, source=source, conflicts=conflicts)
        for rid, old in before.items():
            new = after.get(rid)
            if new is not None and tag_values(old) == tag_values(new):
                continue
            parent = parents[old["parent_id"]]
            conflicts.extend(_validate_changed_row(new, source=source, rid=rid, eligible=eligible[rid]))
            actions.append(
                {
                    "source": source,
                    "row_id": rid,
                    "parent_id": old["parent_id"],
                    "problem_uuid": parent["problem_uuid"],
                    "reference": parent["reference"],
                    "action": "merge_remove" if rid in removed else "update",
                    "merge_into_id": removed.get(rid),
                    "before": tag_values(old),
                    "after": tag_values(new) if new else None,
                },
            )
    return actions


def projected_snapshot(snapshot: dict, tag_actions: list, alias_actions: list) -> dict:
    projected = deepcopy(snapshot)
    for source in ("problem", "statement"):
        rows = {r["id"]: r for r in projected[f"{source}_tags"]}
        for action in tag_actions:
            if action["source"] != source:
                continue
            if action["action"] == "merge_remove":
                del rows[action["row_id"]]
            else:
                rows[action["row_id"]].update(action["after"])
        projected[f"{source}_tags"] = list(rows.values())
    aliases = {r["id"]: r for r in projected["benchmark_aliases"]}
    for action in alias_actions:
        if action["action"] == "insert":
            rid = -(len(aliases) + 1)
            aliases[rid] = {"id": rid, **action["after"]}
        else:
            aliases[action["alias_id"]].update(action["after"])
    projected["benchmark_aliases"] = list(aliases.values())
    return projected


def _concepts(rows: list) -> set:
    return {
        (field, value)
        for row in rows
        for field in TAG_FIELDS
        if field not in {"raw_tag", "normalization_status", "normalization_confidence"}
        for value in (row[field] if field in ARRAY_FIELDS else [row[field]])
        if value
    }


def _check_alias_scope(snapshot: dict, alias_actions: list, conflicts: list) -> None:
    impact = snapshot.get("alias_impact")
    if not impact or not (
        impact["identity"].get("read_only") == "on" or impact["identity"].get("query_effects") == "select_only"
    ):
        conflicts.append({"type": "MISSING_ALIAS_SCOPE_EVIDENCE"})
        return
    inserted = {(a["after"]["kind"], a["after"]["alias_key"]) for a in alias_actions if a["action"] == "insert"}
    conflicts.extend(
        {"type": "OUTSIDE_TOPIC_BENCHMARK_COVERAGE", "usage": usage}
        for usage in impact["current_usage"]
        if not usage["algebra"] and usage["tag_rows"] and (usage["kind"], usage["alias_key"]) in inserted
    )


def _check_benchmark_bindings(
    snapshot: dict, aliases_projected: dict, tag_actions: list, conflicts: list,
    equivalences: dict | None = None,
) -> None:
    # Check actual names being removed, rather than treating an added facet as a rebinding.
    survivors = {
        (source, row["id"]): row
        for source in ("problem", "statement") for row in aliases_projected[f"{source}_tags"]
    }
    for action in tag_actions:
        after = action["after"] or survivors[(action["source"], action["merge_into_id"])]
        for field, kind in FIELD_KINDS.items():
            old_values = action["before"][field] if field in ARRAY_FIELDS else [action["before"][field]]
            new_values = after[field] if field in ARRAY_FIELDS else [after[field]]
            for value in set(old_values) - set(new_values):
                old_id = resolve_benchmark(snapshot, kind, value)
                canonical_id = (equivalences or {}).get(old_id, old_id)
                if old_id is not None and canonical_id not in {
                    resolve_benchmark(aliases_projected, kind, target) for target in new_values
                }:
                    conflicts.append(
                        {
                            "type": "BENCHMARK_BINDING_CHANGED",
                            "source": action["source"],
                            "row_id": action["row_id"],
                            "field": field,
                            "benchmark_id": old_id,
                        },
                    )


def _check_activation_targets(projected: dict, policy: dict, conflicts: list) -> None:
    for rule in policy["activation_aliases"]:
        rid = resolve_benchmark(projected, rule["kind"], rule["alias_key"])
        benchmark = next((r for r in projected["benchmarks"] if r["id"] == rid), None)
        if not benchmark or (benchmark["kind"], benchmark["label_key"]) != (
            rule["target_kind"], rule["target_label_key"],
        ):
            conflicts.append({"type": "ACTIVATION_BENCHMARK_CHANGED", "key": rule["alias_key"]})


def _check_mirrors(snapshot: dict, projected: dict, tag_actions: list, conflicts: list) -> list:
    maps = {}
    for phase, data in (("before", snapshot), ("after", projected)):
        maps[phase] = {}
        for source in ("problem", "statement"):
            groups = defaultdict(list)
            for row in data[f"{source}_tags"]:
                groups[row["parent_id"]].append(row)
            maps[phase][source] = groups
    touched_problem = {a["parent_id"] for a in tag_actions if a["source"] == "problem"}
    touched_statement = {a["parent_id"] for a in tag_actions if a["source"] == "statement"}
    catalog_ids = []
    for statement in snapshot["statements"]:
        sid, pid = statement["id"], statement["linked_problem_id"]
        if sid not in touched_statement and pid not in touched_problem:
            continue
        catalog_ids.append(sid)
        if pid is None or not maps["before"]["statement"][sid]:
            continue
        differences = {}
        for phase in maps:
            differences[phase] = _concepts(maps[phase]["problem"][pid]) ^ _concepts(maps[phase]["statement"][sid])
        if len(differences["after"]) > len(differences["before"]):
            conflicts.append({"type": "WIDENED_MIRROR_DIFFERENCE", "statement_id": sid})
        if statement["problem_uuid"] != statement["linked_problem_uuid"]:
            conflicts.append({"type": "UUID_MISMATCH", "statement_id": sid})
    return catalog_ids


def build_cleanup_report(
    snapshot: dict, reviewed_plan: dict, *, policy: dict, plan_sha256: str,
    benchmark_equivalences: dict | None = None,
) -> dict:
    """No database, filesystem, cache, signal, or model-save side effects."""
    conflicts = []
    expected = {(r["id"], r["field"], r["source"], r["target"]) for r in policy["mappings"]}
    actual = {
        (r["mapping_id"], r["source_field"], r["source_label"], r["target_labels"][0])
        for r in reviewed_plan["mappings"]
        if r["source_field"] == r["target_layer"]
    }
    if plan_sha256 != policy["reviewed_plan_sha256"] or expected != actual:
        message = "The cleanup plan does not match the reviewed algebra policy."
        raise AlgebraAliasError(message)
    alias_actions, _ = _alias_actions(snapshot, reviewed_plan, conflicts)
    impact = snapshot.get("alias_impact")
    _check_alias_scope(snapshot, alias_actions, conflicts)
    tag_actions = _tag_actions(snapshot, policy, conflicts)
    projected = projected_snapshot(snapshot, tag_actions, alias_actions)
    _check_activation_targets(projected, policy, conflicts)
    _check_benchmark_bindings(snapshot, projected, tag_actions, conflicts, benchmark_equivalences)
    catalog_ids = _check_mirrors(snapshot, projected, tag_actions, conflicts)
    source = {
        key: snapshot[key]
        for key in ("problems", "statements", "problem_tags", "statement_tags", "benchmarks", "benchmark_aliases")
    }
    source["alias_usage"] = sorted(
        (impact or {}).get("current_usage", []),
        key=lambda r: json.dumps(r, sort_keys=True),
    )
    return {
        "schema": "algebra-tag-cleanup-v1",
        "policy_version": policy["version"],
        "plan_sha256": plan_sha256,
        "source_fingerprint": digest(source),
        "identity": snapshot.get("identity", {}),
        "conflicts": conflicts,
        "tag_actions": tag_actions,
        "alias_actions": alias_actions,
        "counts": dict(Counter(f"{a['source']}_{a['action']}" for a in tag_actions)),
        "affected_problem_uuids": len({a["problem_uuid"] for a in tag_actions}),
        "catalog_statement_ids": sorted(set(catalog_ids)),
        "catalog_effect": "Mark stale atomically on apply; rebuild after verification.",
    }


def review_fingerprint(report: dict) -> str:
    return digest({key: value for key, value in report.items() if key != "identity"})
