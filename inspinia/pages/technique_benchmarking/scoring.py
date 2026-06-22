from __future__ import annotations

import math
from decimal import ROUND_HALF_UP
from decimal import Decimal
from typing import TYPE_CHECKING

from inspinia.pages.technique_benchmarking.keys import benchmark_kind_for_gap_row
from inspinia.pages.technique_benchmarking.keys import benchmark_label_key_for_gap_row
from inspinia.pages.technique_benchmarking.keys import benchmark_row_key

if TYPE_CHECKING:
    from inspinia.pages.models import TechniqueBenchmark

TARGET_PROFILE_JBMO = "jbmo"
TARGET_PROFILE_NATIONAL = "national"
TARGET_PROFILE_IMO_TST = "imo_tst"
DEFAULT_TARGET_PROFILE = TARGET_PROFILE_NATIONAL
TARGET_PROFILES = {
    TARGET_PROFILE_JBMO,
    TARGET_PROFILE_NATIONAL,
    TARGET_PROFILE_IMO_TST,
}

BENCHMARK_STATUS_MISSING = "missing"
BENCHMARK_STATUS_PARTIAL = "partial"
BENCHMARK_STATUS_COMPLETE = "complete"
BENCHMARK_STATUS_NEEDS_REVIEW = "needs_review"
REVIEW_CONFIDENCE_THRESHOLD = 70
REVIEW_MOHS_BAND_WIDTH = 25
PRIORITY_HIGH_THRESHOLD = Decimal("80")
PRIORITY_MEDIUM_THRESHOLD = Decimal("60")
PRIORITY_REVIEW_THRESHOLD = Decimal("40")
DIFFICULTY_DRILL_MAX = Decimal("3")
EFFICIENCY_DRILL_THRESHOLD = Decimal("20")

REQUIRED_IMPORTANCE_FIELDS = (
    "syllabus_core",
    "contest_frequency",
    "transfer_value",
    "prerequisite_value",
)
REQUIRED_DIFFICULTY_FIELDS = (
    "concept_load",
    "recognition_burden",
    "execution_load",
    "proof_fragility",
    "cross_topic_dependency",
)


def normalize_target_profile(raw_value: str | None) -> str:
    value = str(raw_value or "").strip().casefold().replace("-", "_")
    return value if value in TARGET_PROFILES else DEFAULT_TARGET_PROFILE


def target_weight_for_benchmark(benchmark: TechniqueBenchmark | None, target_profile: str | None = None) -> Decimal:
    if benchmark is None:
        return Decimal("1.00")
    profile = normalize_target_profile(target_profile)
    field_name = {
        TARGET_PROFILE_JBMO: "jbmo_weight",
        TARGET_PROFILE_NATIONAL: "national_weight",
        TARGET_PROFILE_IMO_TST: "imo_tst_weight",
    }[profile]
    return _decimal(getattr(benchmark, field_name, Decimal("1.00")), default=Decimal("1.00"))


def calculate_static_importance_score(
    benchmark: TechniqueBenchmark,
    *,
    target_profile: str | None = None,
) -> Decimal | None:
    values = [getattr(benchmark, field_name, None) for field_name in REQUIRED_IMPORTANCE_FIELDS]
    if any(value is None for value in values):
        return None
    target_weight = target_weight_for_benchmark(benchmark, target_profile)
    score = (
        Decimal("0.30") * Decimal(values[0])
        + Decimal("0.25") * Decimal(values[1])
        + Decimal("0.20") * Decimal(values[2])
        + Decimal("0.15") * Decimal(values[3])
        + Decimal("0.10") * target_weight
    )
    return _quantize(score, places="0.01")


def calculate_static_difficulty_score(benchmark: TechniqueBenchmark) -> Decimal | None:
    values = [getattr(benchmark, field_name, None) for field_name in REQUIRED_DIFFICULTY_FIELDS]
    if any(value is None for value in values):
        return None
    score = (
        Decimal("0.25") * Decimal(values[0])
        + Decimal("0.25") * Decimal(values[1])
        + Decimal("0.20") * Decimal(values[2])
        + Decimal("0.15") * Decimal(values[3])
        + Decimal("0.15") * Decimal(values[4])
    )
    return _quantize(score, places="0.01")


def gap_pressure_for_row(row: dict[str, object], *, max_remaining: int) -> Decimal:
    total = max(int(row.get("total") or 0), 0)
    solved = max(int(row.get("solved") or 0), 0)
    remaining = max(int(row.get("remaining") or 0), 0)
    coverage_gap = Decimal("0")
    if total:
        coverage_gap = Decimal("1") - (Decimal(min(solved, total)) / Decimal(total))
    volume_gap = Decimal("0")
    if max_remaining > 0:
        volume_gap = Decimal(str(math.log(remaining + 1) / math.log(max_remaining + 1)))
    score = Decimal("100") * (Decimal("0.65") * coverage_gap + Decimal("0.35") * volume_gap)
    return _quantize(score, places="0.01")


def computed_scores_for_row(
    row: dict[str, object],
    *,
    benchmark: TechniqueBenchmark | None,
    max_remaining: int,
    target_profile: str | None = None,
) -> dict[str, Decimal | None]:
    gap_pressure = gap_pressure_for_row(row, max_remaining=max_remaining)
    importance_score = (
        calculate_static_importance_score(benchmark, target_profile=target_profile)
        if benchmark
        else None
    )
    difficulty_score = calculate_static_difficulty_score(benchmark) if benchmark else None
    if importance_score is None:
        return {
            "gap_pressure": gap_pressure,
            "importance_score": None,
            "difficulty_score": difficulty_score,
            "priority_score": None,
            "efficiency_score": None,
            "deep_work_score": None,
        }
    priority_score = _quantize(gap_pressure * importance_score / Decimal("5"), places="0.01")
    efficiency_score = None
    deep_work_score = None
    if difficulty_score is not None and difficulty_score > 0:
        efficiency_score = _quantize(priority_score / difficulty_score, places="0.01")
        deep_work_score = _quantize(priority_score * difficulty_score / Decimal("5"), places="0.01")
    return {
        "gap_pressure": gap_pressure,
        "importance_score": importance_score,
        "difficulty_score": difficulty_score,
        "priority_score": priority_score,
        "efficiency_score": efficiency_score,
        "deep_work_score": deep_work_score,
    }


def benchmark_quality_status(
    *,
    benchmark: TechniqueBenchmark | None,
    matched_by_alias: bool = False,
    alias_reason: str = "",
) -> str:
    if benchmark is None:
        return BENCHMARK_STATUS_MISSING
    required_fields = (*REQUIRED_IMPORTANCE_FIELDS, *REQUIRED_DIFFICULTY_FIELDS)
    if any(getattr(benchmark, field_name, None) is None for field_name in required_fields):
        return BENCHMARK_STATUS_PARTIAL
    if _needs_review(benchmark, matched_by_alias=matched_by_alias, alias_reason=alias_reason):
        return BENCHMARK_STATUS_NEEDS_REVIEW
    return BENCHMARK_STATUS_COMPLETE


def final_training_type(
    *,
    benchmark: TechniqueBenchmark | None,
    priority_score: Decimal | None,
    difficulty_score: Decimal | None,
    efficiency_score: Decimal | None,
) -> str:
    if priority_score is None or difficulty_score is None:
        return getattr(benchmark, "training_type", "") if benchmark is not None else ""
    action = "Postpone"
    if priority_score >= PRIORITY_HIGH_THRESHOLD and difficulty_score <= DIFFICULTY_DRILL_MAX:
        action = "Drill"
    elif priority_score >= PRIORITY_HIGH_THRESHOLD:
        action = "Deep block"
    elif (
        priority_score >= PRIORITY_MEDIUM_THRESHOLD
        and efficiency_score is not None
        and efficiency_score >= EFFICIENCY_DRILL_THRESHOLD
    ):
        action = "Drill"
    elif priority_score >= PRIORITY_MEDIUM_THRESHOLD:
        action = "Mixed mock"
    elif priority_score >= PRIORITY_REVIEW_THRESHOLD:
        action = "Review"
    return action


def benchmark_lookup_for_gap_rows(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    from inspinia.pages.models import TechniqueBenchmark
    from inspinia.pages.models import TechniqueBenchmarkAlias

    row_keys = [benchmark_row_key(row) for row in rows]
    kind_key_pairs = {
        (benchmark_kind_for_gap_row(row), benchmark_label_key_for_gap_row(row))
        for row in rows
    }
    direct_benchmarks = {
        (benchmark.kind, benchmark.label_key): benchmark
        for benchmark in TechniqueBenchmark.objects.filter(
            kind__in={kind for kind, _label_key in kind_key_pairs},
            label_key__in={label_key for _kind, label_key in kind_key_pairs},
        )
    }
    aliases = {
        (alias.kind, alias.alias_key): alias
        for alias in TechniqueBenchmarkAlias.objects.filter(
            kind__in={kind for kind, _label_key in kind_key_pairs},
            alias_key__in={label_key for _kind, label_key in kind_key_pairs},
        ).select_related("benchmark")
    }

    lookup = {}
    for row, row_key in zip(rows, row_keys, strict=True):
        key_pair = (benchmark_kind_for_gap_row(row), benchmark_label_key_for_gap_row(row))
        benchmark = direct_benchmarks.get(key_pair)
        alias = None
        matched_by_alias = False
        if benchmark is None:
            alias = aliases.get(key_pair)
            if alias is not None:
                benchmark = alias.benchmark
                matched_by_alias = True
        lookup[row_key] = {
            "benchmark": benchmark,
            "alias": alias,
            "matched_by_alias": matched_by_alias,
            "alias_reason": alias.reason if alias is not None else "",
        }
    return lookup


def _needs_review(
    benchmark: TechniqueBenchmark,
    *,
    matched_by_alias: bool,
    alias_reason: str,
) -> bool:
    if benchmark.benchmark_confidence is not None and benchmark.benchmark_confidence < REVIEW_CONFIDENCE_THRESHOLD:
        return True
    if benchmark.typical_mohs_min is not None and benchmark.typical_mohs_max is not None:
        if benchmark.typical_mohs_max - benchmark.typical_mohs_min >= REVIEW_MOHS_BAND_WIDTH:
            return True
    if matched_by_alias and "ambiguous" in alias_reason.casefold():
        return True
    latest_batch = benchmark.imported_from_batch
    if latest_batch is not None:
        preview_payload = latest_batch.preview_payload or {}
        changed_parent_families = preview_payload.get("changed_parent_family_row_keys") or []
        row_key = f"{benchmark.kind}:{benchmark.label_key}"
        if row_key in changed_parent_families:
            return True
    return False


def _decimal(value: object, *, default: Decimal) -> Decimal:
    if value is None:
        return default
    return Decimal(str(value))


def _quantize(value: Decimal, *, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
