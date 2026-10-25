"""Second-batch vocabulary policy and pure, benchmark-aware consolidation report."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from inspinia.pages.algebra_tag_aliases import ARRAY_FIELDS
from inspinia.pages.algebra_tag_aliases import SUPPRESSED_STATUSES
from inspinia.pages.algebra_tag_aliases import AlgebraAliasError
from inspinia.pages.algebra_tag_aliases import load_policy
from inspinia.pages.algebra_tag_cleanup import FIELD_KINDS
from inspinia.pages.algebra_tag_cleanup import build_cleanup_report
from inspinia.pages.algebra_tag_cleanup import digest
from inspinia.pages.algebra_tag_cleanup import projected_snapshot
from inspinia.pages.algebra_tag_cleanup import resolve_benchmark

VOCABULARY_PATH = Path(__file__).parent / "data" / "algebra_vocabulary_v2.json"
RATING_FIELDS = (
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
)


@lru_cache(maxsize=1)
def load_vocabulary_plan() -> dict:
    return json.loads(VOCABULARY_PATH.read_bytes())


def vocabulary_sha256() -> str:
    return hashlib.sha256(VOCABULARY_PATH.read_bytes()).hexdigest()


def vocabulary_operation_plan(policy: dict) -> dict:
    return {
        "mappings": [
            {
                "mapping_id": r["id"],
                "source_field": r["field"],
                "source_label": r["source"],
                "target_layer": r["field"],
                "target_labels": [r["target"]],
            }
            for r in policy["mappings"]
        ],
        "benchmark_alias_actions": [
            {
                "action": "insert",
                "kind": r["kind"],
                "alias_key": r["alias_key"],
                "before": None,
                "candidate_after": {k: r[k] for k in ("kind", "alias_label", "alias_key", "benchmark_id", "reason")},
            }
            for r in policy["activation_aliases"]
        ],
    }


def vocabulary_normalization_policy(policy: dict, policy_sha: str) -> dict:
    return {
        **policy,
        "reviewed_plan_sha256": policy_sha,
        "specificity": {"problem_uuid": "", "sources": [], "target": ""},
    }


@lru_cache(maxsize=1)
def _concept_normalization_rules() -> list:
    return json.loads(
        (Path(__file__).parent / "data" / "algebra_concept_normalization_policy_v1.json").read_bytes(),
    )["mappings"]


def combined_import_policy() -> dict:
    base = load_policy()
    rules = _concept_normalization_rules()
    methods = {r["source"]: r["target"] for r in rules if r["field"] == "technique_tags"}
    subtopics = {r["source"].upper(): r["target"] for r in rules if r["field"] == "canonical_subtopic"}
    return {
        **base,
        "mappings": [*base["mappings"], *rules],
        "method_imports": {**methods, **{v: v for v in methods.values()}},
        "subtopic_imports": {**subtopics, **{v.upper(): v for v in subtopics.values()}},
    }


def _benchmark_equivalences(snapshot: dict, policy: dict, conflicts: list) -> tuple[dict, list]:
    benchmarks = {r["id"]: r for r in snapshot["benchmarks"]}
    equivalents = {}
    details = []
    for rule in policy["benchmark_equivalences"]:
        source, target = benchmarks.get(rule["source_id"]), benchmarks.get(rule["target_id"])
        if not source or not target:
            conflicts.append({"type": "MISSING_EQUIVALENT_BENCHMARK", "source_id": rule["source_id"]})
            continue
        unchanged = digest(source) == rule["source_sha256"] and digest(target) == rule["target_sha256"]
        valid_keys = (source["kind"], target["kind"], source["label_key"], target["label_key"]) == (
            rule["kind"],
            rule["kind"],
            rule["source_key"],
            rule["target_key"],
        )
        same_ratings = all(source[f] == target[f] for f in RATING_FIELDS)
        if not (unchanged and valid_keys and same_ratings):
            conflicts.append(
                {"type": "EQUIVALENT_BENCHMARK_CHANGED", "source_id": source["id"], "target_id": target["id"]},
            )
            continue
        equivalents[source["id"]] = target["id"]
        details.append(
            {
                "source_id": source["id"],
                "target_id": target["id"],
                "rating_values_equal": True,
                "metadata_differences": {
                    k: {"before": source[k], "canonical": target[k]} for k in source if source[k] != target[k]
                },
                "definition_writes": 0,
            },
        )
    return equivalents, details


def _eligible_rows(snapshot: dict, source: str):
    parents = {r["id"]: r for r in snapshot["problems" if source == "problem" else "statements"]}
    for row in snapshot[source + "_tags"]:
        parent = parents[row["parent_id"]]
        if (
            parent["in_scope"]
            and parent["is_active"]
            and str(row["normalization_status"]).strip().casefold() not in SUPPRESSED_STATUSES
        ):
            yield row, parent


def vocabulary_counts(snapshot: dict) -> dict:
    labels = defaultdict(set)
    for source in ("problem", "statement"):
        for row, _parent in _eligible_rows(snapshot, source):
            labels["canonical_subtopic"].update([row["canonical_subtopic"]] if row["canonical_subtopic"] else [])
            labels["technique_tags"].update(row["technique_tags"])
    return {field: len(labels[field]) for field in ("canonical_subtopic", "technique_tags")}


def _lookup_changes(snapshot: dict, after: dict, actions: list, policy: dict) -> list:
    effects = Counter()
    targets = {(r["field"], r["source"]): r["target"] for r in policy["mappings"]}
    rows = {(source, r["id"]): r for source in ("problem", "statement") for r in after[source + "_tags"]}
    for action in actions:
        survivor = action["after"] or rows[(action["source"], action["merge_into_id"])]
        for field in ("canonical_subtopic", "technique_tags", "technique"):
            kind = FIELD_KINDS[field]
            old = action["before"][field] if field in ARRAY_FIELDS else [action["before"][field]]
            new = survivor[field] if field in ARRAY_FIELDS else [survivor[field]]
            for value in set(old) - set(new):
                old_id = resolve_benchmark(snapshot, kind, value)
                target = targets.get((field, value))
                if target in new:
                    new_id = resolve_benchmark(after, kind, target)
                    effects[(field, value, target, old_id, new_id)] += 1
    return [
        {
            "field": f,
            "source_label": s,
            "canonical_label": t,
            "before_benchmark_id": old,
            "after_benchmark_id": new,
            "tag_rows": n,
        }
        for (f, s, t, old, new), n in sorted(effects.items(), key=lambda item: str(item[0]))
    ]


def _groups(snapshot: dict, policy: dict) -> list:
    result = []
    for rule in policy["mappings"]:
        if rule["field"] == "technique":
            continue
        members = {"source": set(), "target": set()}
        for source in ("problem", "statement"):
            for row, parent in _eligible_rows(snapshot, source):
                values = row[rule["field"]] if rule["field"] in ARRAY_FIELDS else [row[rule["field"]]]
                for label, key in ((rule["source"], "source"), (rule["target"], "target")):
                    if label in values:
                        members[key].add(parent["problem_uuid"])
        result.append(
            {
                "group": rule["group"],
                "field": rule["field"],
                "source": rule["source"],
                "canonical": rule["target"],
                "source_problem_identities": len(members["source"]),
                "canonical_problem_identities": len(members["target"]),
                "overlap_problem_identities": len(members["source"] & members["target"]),
                "union_problem_identities": len(members["source"] | members["target"]),
            },
        )
    return result


def build_vocabulary_report(snapshot: dict, reviewed_plan: dict, *, policy: dict, plan_sha256: str) -> dict:
    if reviewed_plan != vocabulary_operation_plan(policy):
        message = "The vocabulary operation differs from its packaged policy."
        raise AlgebraAliasError(message)
    conflicts = []
    requested = {tuple(key) for key in snapshot.get("alias_impact", {}).get("requested_keys", [])}
    required = {(r["kind"], r["alias_key"]) for r in policy["activation_aliases"]}
    if not required.issubset(requested):
        conflicts.append({"type": "MISSING_VOCABULARY_ALIAS_SCOPE_EVIDENCE"})
    equivalents, details = _benchmark_equivalences(snapshot, policy, conflicts)
    report = build_cleanup_report(
        snapshot,
        reviewed_plan,
        policy=vocabulary_normalization_policy(policy, plan_sha256),
        plan_sha256=plan_sha256,
        benchmark_equivalences=equivalents,
    )
    report["conflicts"].extend(conflicts)
    after = projected_snapshot(snapshot, report["tag_actions"], report["alias_actions"])
    report.update(
        schema="algebra-vocabulary-consolidation-v2",
        vocabulary_before=vocabulary_counts(snapshot),
        vocabulary_after=vocabulary_counts(after),
        groups=_groups(snapshot, policy),
        benchmark_equivalences=details,
        benchmark_lookup_changes=_lookup_changes(snapshot, after, report["tag_actions"], policy),
        benchmark_definition_writes=0,
        primary_topics_unchanged=True,
        held_distinctions=policy["held_distinctions"],
    )
    return report
