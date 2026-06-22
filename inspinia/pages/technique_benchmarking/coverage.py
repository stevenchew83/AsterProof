from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from inspinia.pages.technique_benchmarking.keys import benchmark_row_key
from inspinia.pages.technique_benchmarking.scoring import benchmark_lookup_for_gap_rows
from inspinia.pages.technique_benchmarking.scoring import benchmark_quality_status
from inspinia.pages.technique_benchmarking.scoring import computed_scores_for_row
from inspinia.pages.technique_benchmarking.scoring import normalize_target_profile
from inspinia.pages.technique_progress import GAP_KIND_LEMMAS
from inspinia.pages.technique_progress import GAP_KIND_METHODS
from inspinia.pages.technique_progress import GAP_KIND_OBJECTS
from inspinia.pages.technique_progress import GAP_KIND_PROOF_ROLES
from inspinia.pages.technique_progress import GAP_KIND_SUBTOPICS
from inspinia.pages.technique_progress import GAP_KIND_TECHNIQUES
from inspinia.pages.technique_progress import technique_progress_gap_rows_for_benchmark_export

BENCHMARK_GAP_KINDS = (
    GAP_KIND_SUBTOPICS,
    GAP_KIND_TECHNIQUES,
    GAP_KIND_OBJECTS,
    GAP_KIND_METHODS,
    GAP_KIND_LEMMAS,
    GAP_KIND_PROOF_ROLES,
)

BENCHMARK_GAP_KIND_LABELS = {
    GAP_KIND_SUBTOPICS: "Subtopics",
    GAP_KIND_TECHNIQUES: "Technique gaps",
    GAP_KIND_OBJECTS: "Object tags",
    GAP_KIND_METHODS: "Technique tags / methods",
    GAP_KIND_LEMMAS: "Lemmas",
    GAP_KIND_PROOF_ROLES: "Proof roles",
}

BENCHMARK_STATUSES = ("missing", "partial", "complete", "needs_review")


def build_actionable_benchmark_rows(  # noqa: PLR0913
    *,
    request_user,
    raw_user_id: str = "",
    raw_topic: str = "",
    raw_min_total: str = "",
    raw_canonical_subtopic: str = "",
    kind_filters: list[str] | tuple[str, ...] | None = None,
    target_profile: str = "national",
) -> list[dict[str, Any]]:
    kinds = normalize_kind_filters(kind_filters)
    rows: list[dict[str, Any]] = []
    seen_row_keys: set[str] = set()
    for kind in kinds:
        kind_rows = technique_progress_gap_rows_for_benchmark_export(
            request_user=request_user,
            raw_user_id=raw_user_id,
            raw_kind=kind,
            raw_topic=raw_topic,
            raw_min_total=raw_min_total,
            raw_canonical_subtopic=raw_canonical_subtopic,
        )
        for row in kind_rows:
            row_key = benchmark_row_key(row)
            if not row_key or row_key in seen_row_keys:
                continue
            seen_row_keys.add(row_key)
            rows.append(dict(row, benchmark_row_key=row_key))
    return enrich_benchmark_coverage_rows(rows, target_profile=target_profile)


def enrich_benchmark_coverage_rows(
    rows: list[dict[str, Any]],
    *,
    target_profile: str = "national",
) -> list[dict[str, Any]]:
    if not rows:
        return []
    lookup = benchmark_lookup_for_gap_rows(rows)
    max_remaining = max(int(row.get("remaining") or 0) for row in rows)
    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        row_key = str(row.get("benchmark_row_key") or benchmark_row_key(row))
        lookup_entry = lookup.get(row_key, {})
        benchmark = lookup_entry.get("benchmark")
        matched_by_alias = bool(lookup_entry.get("matched_by_alias"))
        alias_reason = str(lookup_entry.get("alias_reason") or "")
        status = benchmark_quality_status(
            benchmark=benchmark,
            matched_by_alias=matched_by_alias,
            alias_reason=alias_reason,
        )
        scores = computed_scores_for_row(
            row,
            benchmark=benchmark,
            max_remaining=max_remaining,
            target_profile=normalize_target_profile(target_profile),
        )
        enriched_rows.append(
            {
                **row,
                "benchmark_row_key": row_key,
                "benchmark_status": status,
                "benchmark": benchmark,
                "benchmark_matched_by_alias": matched_by_alias,
                "benchmark_alias_reason": alias_reason,
                "parent_family": getattr(benchmark, "parent_family", "") if benchmark is not None else "",
                "benchmark_confidence": getattr(benchmark, "benchmark_confidence", None)
                if benchmark is not None
                else None,
                "typical_mohs_min": getattr(benchmark, "typical_mohs_min", None)
                if benchmark is not None
                else None,
                "typical_mohs_max": getattr(benchmark, "typical_mohs_max", None)
                if benchmark is not None
                else None,
                **scores,
            },
        )
    return enriched_rows


def build_benchmark_coverage_summary(  # noqa: PLR0913
    *,
    request_user,
    raw_user_id: str = "",
    raw_topic: str = "",
    raw_min_total: str = "",
    raw_canonical_subtopic: str = "",
    kind_filters: list[str] | tuple[str, ...] | None = None,
    target_profile: str = "national",
) -> dict[str, Any]:
    rows = build_actionable_benchmark_rows(
        request_user=request_user,
        raw_user_id=raw_user_id,
        raw_topic=raw_topic,
        raw_min_total=raw_min_total,
        raw_canonical_subtopic=raw_canonical_subtopic,
        kind_filters=kind_filters,
        target_profile=target_profile,
    )
    return coverage_summary_from_rows(rows)


def coverage_summary_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = _empty_status_counts()
    by_kind = {
        kind: {"label": label, **_empty_status_counts()}
        for kind, label in BENCHMARK_GAP_KIND_LABELS.items()
    }
    by_area_counter: dict[str, Counter[str]] = {}
    for row in rows:
        status = str(row.get("benchmark_status") or "missing")
        if status not in BENCHMARK_STATUSES:
            status = "missing"
        counts["total"] += 1
        counts[status] += 1

        kind = str(row.get("layer_kind") or "")
        if kind not in by_kind:
            by_kind[kind] = {"label": kind or "Other", **_empty_status_counts()}
        by_kind[kind]["total"] += 1
        by_kind[kind][status] += 1

        area_labels = list(row.get("main_topic_labels") or [])
        if not area_labels:
            area_labels = [str(row.get("main_topic") or "Other")]
        for area_label in area_labels:
            area = str(area_label or "Other").strip() or "Other"
            if area not in by_area_counter:
                by_area_counter[area] = Counter(dict.fromkeys(("total", *BENCHMARK_STATUSES), 0))
            by_area_counter[area]["total"] += 1
            by_area_counter[area][status] += 1

    by_area = {
        area: dict(counter)
        for area, counter in sorted(by_area_counter.items(), key=lambda item: item[0].casefold())
    }
    return {
        "counts": counts,
        "by_kind": by_kind,
        "by_area": by_area,
        "rows": rows,
    }


def normalize_kind_filters(kind_filters: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized = []
    for raw_kind in kind_filters or BENCHMARK_GAP_KINDS:
        kind = str(raw_kind or "").strip()
        if kind == "all":
            return list(BENCHMARK_GAP_KINDS)
        if kind in BENCHMARK_GAP_KINDS and kind not in normalized:
            normalized.append(kind)
    return normalized or list(BENCHMARK_GAP_KINDS)


def decimal_to_float(value: object) -> float | None:
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return None
    return float(value)


def _empty_status_counts() -> dict[str, int]:
    return {
        "total": 0,
        "missing": 0,
        "partial": 0,
        "complete": 0,
        "needs_review": 0,
    }
