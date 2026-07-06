from __future__ import annotations

from collections import Counter
from collections import defaultdict
from decimal import Decimal
from statistics import mean

from inspinia.pages.technique_benchmarking.keys import build_benchmark_row_key
from inspinia.pages.technique_benchmarking.scoring import calculate_static_difficulty_score
from inspinia.pages.technique_benchmarking.scoring import calculate_static_importance_score
from inspinia.pages.technique_benchmarking.scoring import normalize_target_profile
from inspinia.pages.technique_benchmarking.scoring import target_weight_for_benchmark

HIGH_VALUE_THRESHOLD = Decimal("4.00")
QUICK_WIN_DIFFICULTY_MAX = Decimal("3.00")
DEEP_BLOCK_DIFFICULTY_MIN = Decimal("4.00")
CONFIDENCE_REVIEW_THRESHOLD = 80
CALIBRATION_QUEUE_THRESHOLD = 70
CONFIDENCE_HIGH_THRESHOLD = 90

TARGET_PROFILE_OPTIONS = [
    {"key": "jbmo", "label": "JBMO"},
    {"key": "national", "label": "National"},
    {"key": "imo_tst", "label": "IMO/TST"},
]
TARGET_PROFILE_LABELS = {option["key"]: option["label"] for option in TARGET_PROFILE_OPTIONS}

TECHNIQUE_BENCHMARK_TABLE_COLUMNS = [
    "Technique",
    "Area",
    "Family",
    "Training",
    "Target",
    "Value",
    "Difficulty",
    "MOHS",
    "Confidence",
    "Details",
]


def build_technique_benchmark_dashboard_context(
    benchmarks,
    *,
    raw_target_profile: str | None = None,
) -> dict[str, object]:
    target_profile = normalize_target_profile(raw_target_profile)
    rows = [_benchmark_dashboard_row(benchmark, target_profile=target_profile) for benchmark in benchmarks]
    matrix_payload = _matrix_payload(rows)
    heatmap_payload = _heatmap_payload(rows)
    return {
        "technique_benchmark_rows": rows,
        "technique_benchmark_total": len(rows),
        "technique_benchmark_target_profile": target_profile,
        "technique_benchmark_target_profile_label": TARGET_PROFILE_LABELS[target_profile],
        "technique_benchmark_target_profile_options": [
            {**option, "selected": option["key"] == target_profile}
            for option in TARGET_PROFILE_OPTIONS
        ],
        "technique_benchmark_summary_cards": _summary_cards(rows, target_profile=target_profile),
        "technique_benchmark_table_columns": TECHNIQUE_BENCHMARK_TABLE_COLUMNS,
        "technique_benchmark_matrix_payload": matrix_payload,
        "technique_benchmark_heatmap_payload": heatmap_payload,
    }


def _benchmark_dashboard_row(benchmark, *, target_profile: str) -> dict[str, object]:
    value_score = calculate_static_importance_score(benchmark, target_profile=target_profile)
    difficulty_score = calculate_static_difficulty_score(benchmark)
    target_weight = target_weight_for_benchmark(benchmark, target_profile)
    row_key = build_benchmark_row_key(benchmark.kind, benchmark.label_key)
    aliases = ", ".join(alias.alias_label for alias in benchmark.aliases.all())
    confidence = benchmark.benchmark_confidence
    missing_value_fields = _missing_fields(
        benchmark,
        (
            "syllabus_core",
            "contest_frequency",
            "transfer_value",
            "prerequisite_value",
        ),
    )
    missing_difficulty_fields = _missing_fields(
        benchmark,
        (
            "concept_load",
            "recognition_burden",
            "execution_load",
            "proof_fragility",
            "cross_topic_dependency",
        ),
    )
    primary_area = benchmark.primary_area or "Unclassified"
    parent_family = benchmark.parent_family or "Unassigned family"
    training_type = benchmark.training_type or "Unassigned"
    target_level = benchmark.target_level or "Unassigned"
    return {
        "row_key": row_key,
        "label": benchmark.normalized_label or benchmark.label,
        "kind": benchmark.kind,
        "kind_label": benchmark.get_kind_display(),
        "primary_area": primary_area,
        "parent_family": parent_family,
        "training_type": training_type,
        "target_level": target_level,
        "value_score": _decimal_display(value_score),
        "value_score_number": _decimal_number(value_score),
        "difficulty_score": _decimal_display(difficulty_score),
        "difficulty_score_number": _decimal_number(difficulty_score),
        "selected_target_weight": _decimal_display(target_weight),
        "selected_target_weight_number": _decimal_number(target_weight),
        "mohs_band_label": _mohs_band_label(benchmark),
        "mohs_start_percent": _mohs_start_percent(benchmark),
        "mohs_width_percent": _mohs_width_percent(benchmark),
        "typical_mohs_min": benchmark.typical_mohs_min,
        "typical_mohs_max": benchmark.typical_mohs_max,
        "benchmark_confidence": confidence,
        "confidence_label": f"{confidence}%" if confidence is not None else "",
        "confidence_bucket": _confidence_bucket(confidence),
        "confidence_variant": _confidence_variant(confidence),
        "chartable": value_score is not None and difficulty_score is not None,
        "alias_suggestions": aliases,
        "rationale": benchmark.rationale,
        "pitfalls": benchmark.pitfalls,
        "recommended_sequence": benchmark.recommended_sequence,
        "missing_value_fields": missing_value_fields,
        "missing_difficulty_fields": missing_difficulty_fields,
        "detail_groups": {
            "value_profile": [
                {"label": "Core", "value": benchmark.syllabus_core},
                {"label": "Frequency", "value": benchmark.contest_frequency},
                {"label": "Transfer", "value": benchmark.transfer_value},
                {"label": "Prereq", "value": benchmark.prerequisite_value},
            ],
            "difficulty_profile": [
                {"label": "Concept", "value": benchmark.concept_load},
                {"label": "Recognition", "value": benchmark.recognition_burden},
                {"label": "Execution", "value": benchmark.execution_load},
                {"label": "Fragility", "value": benchmark.proof_fragility},
                {"label": "Dependency", "value": benchmark.cross_topic_dependency},
            ],
            "target_weights": [
                {"label": "JBMO", "value": _decimal_display(benchmark.jbmo_weight)},
                {"label": "National", "value": _decimal_display(benchmark.national_weight)},
                {"label": "IMO/TST", "value": _decimal_display(benchmark.imo_tst_weight)},
            ],
        },
    }


def _summary_cards(rows: list[dict[str, object]], *, target_profile: str) -> list[dict[str, object]]:
    high_value_count = sum(1 for row in rows if _row_decimal(row, "value_score") >= HIGH_VALUE_THRESHOLD)
    quick_win_count = sum(
        1
        for row in rows
        if _row_decimal(row, "value_score") >= HIGH_VALUE_THRESHOLD
        and row["difficulty_score"]
        and Decimal(str(row["difficulty_score"])) <= QUICK_WIN_DIFFICULTY_MAX
    )
    deep_block_count = sum(1 for row in rows if _is_deep_block(row))
    confidence_review_count = sum(
        1
        for row in rows
        if row["benchmark_confidence"] is not None
        and row["benchmark_confidence"] < CONFIDENCE_REVIEW_THRESHOLD
    )
    calibration_queue_count = sum(
        1
        for row in rows
        if row["benchmark_confidence"] is not None
        and row["benchmark_confidence"] < CALIBRATION_QUEUE_THRESHOLD
    )
    target_weights = [
        Decimal(str(row["selected_target_weight"]))
        for row in rows
        if row["selected_target_weight"]
    ]
    target_average = _decimal_display(mean(target_weights)) if target_weights else ""
    return [
        {
            "key": "high_value",
            "label": "High-value topics",
            "value": high_value_count,
            "caption": f"Value score {HIGH_VALUE_THRESHOLD}+",
            "icon": "ti ti-diamond",
            "variant": "primary",
        },
        {
            "key": "deep_blocks",
            "label": "Deep blocks",
            "value": deep_block_count,
            "caption": "High value with heavier proof load",
            "icon": "ti ti-mountain",
            "variant": "warning",
        },
        {
            "key": "quick_wins",
            "label": "Quick wins",
            "value": quick_win_count,
            "caption": "High value, lower difficulty",
            "icon": "ti ti-bolt",
            "variant": "success",
        },
        {
            "key": "confidence_review",
            "label": "Confidence review",
            "value": confidence_review_count,
            "caption": f"{calibration_queue_count} below {CALIBRATION_QUEUE_THRESHOLD}%",
            "icon": "ti ti-alert-triangle",
            "variant": "danger" if calibration_queue_count else "info",
        },
        {
            "key": "target_focus",
            "label": "Target focus",
            "value": len(rows),
            "caption": f"{TARGET_PROFILE_LABELS[target_profile]} weights, avg {target_average or '-'}",
            "icon": "ti ti-target-arrow",
            "variant": "secondary",
        },
    ]


def _matrix_payload(rows: list[dict[str, object]]) -> dict[str, object]:
    series_by_training = defaultdict(list)
    for row in rows:
        if not row["chartable"]:
            continue
        series_by_training[row["training_type"]].append(
            {
                "x": row["difficulty_score_number"],
                "y": row["value_score_number"],
                "z": max(6, round(float(row["selected_target_weight_number"] or 1) * 10, 2)),
                "row_key": row["row_key"],
                "label": row["label"],
                "primary_area": row["primary_area"],
                "parent_family": row["parent_family"],
                "training_type": row["training_type"],
                "target_level": row["target_level"],
                "mohs_band_label": row["mohs_band_label"],
                "confidence_label": row["confidence_label"],
                "confidence_bucket": row["confidence_bucket"],
            },
        )
    return {
        "series": [
            {"name": training_type, "data": points}
            for training_type, points in sorted(series_by_training.items())
        ],
    }


def _heatmap_payload(rows: list[dict[str, object]]) -> dict[str, object]:
    families = [
        family
        for family, _count in Counter(row["parent_family"] for row in rows).most_common()
    ]
    areas = sorted({row["primary_area"] for row in rows})
    values_by_cell = defaultdict(list)
    count_by_cell = Counter()
    for row in rows:
        key = (row["primary_area"], row["parent_family"])
        count_by_cell[key] += 1
        if row["value_score"]:
            values_by_cell[key].append(float(row["value_score"]))

    series = []
    for area in areas:
        data = []
        for family in families:
            key = (area, family)
            values = values_by_cell[key]
            average_value = round(sum(values) / len(values), 2) if values else 0
            data.append(
                {
                    "x": family,
                    "y": average_value,
                    "row_count": count_by_cell[key],
                    "primary_area": area,
                    "parent_family": family,
                    "display": f"{average_value:.2f}" if values else "",
                },
            )
        series.append({"name": area, "data": data})
    return {"series": series}


def _is_deep_block(row: dict[str, object]) -> bool:
    if row["training_type"] == "Deep block":
        return True
    if not row["value_score"] or not row["difficulty_score"]:
        return False
    return (
        Decimal(str(row["value_score"])) >= HIGH_VALUE_THRESHOLD
        and Decimal(str(row["difficulty_score"])) >= DEEP_BLOCK_DIFFICULTY_MIN
    )


def _row_decimal(row: dict[str, object], key: str) -> Decimal:
    value = row.get(key)
    if not value:
        return Decimal("0")
    return Decimal(str(value))


def _mohs_band_label(benchmark) -> str:
    if benchmark.typical_mohs_min is None or benchmark.typical_mohs_max is None:
        return ""
    return f"{benchmark.typical_mohs_min}M-{benchmark.typical_mohs_max}M"


def _mohs_start_percent(benchmark) -> str:
    if benchmark.typical_mohs_min is None:
        return "0"
    return _percent_display(min(max(benchmark.typical_mohs_min, 0), 60) / 60 * 100)


def _mohs_width_percent(benchmark) -> str:
    if benchmark.typical_mohs_min is None or benchmark.typical_mohs_max is None:
        return "0"
    width = min(max(benchmark.typical_mohs_max - benchmark.typical_mohs_min, 0), 60)
    return _percent_display(width / 60 * 100)


def _percent_display(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _confidence_bucket(confidence: int | None) -> str:
    if confidence is None:
        return "Unrated"
    if confidence >= CONFIDENCE_HIGH_THRESHOLD:
        return "90+"
    if confidence >= CONFIDENCE_REVIEW_THRESHOLD:
        return "80-89"
    if confidence >= CALIBRATION_QUEUE_THRESHOLD:
        return "70-79"
    return "<70"


def _confidence_variant(confidence: int | None) -> str:
    if confidence is None:
        return "secondary"
    if confidence >= CONFIDENCE_HIGH_THRESHOLD:
        return "success"
    if confidence >= CONFIDENCE_REVIEW_THRESHOLD:
        return "info"
    if confidence >= CALIBRATION_QUEUE_THRESHOLD:
        return "warning"
    return "danger"


def _missing_fields(benchmark, field_names: tuple[str, ...]) -> list[str]:
    return [field_name for field_name in field_names if getattr(benchmark, field_name, None) is None]


def _decimal_display(value) -> str:
    if value is None:
        return ""
    return f"{Decimal(str(value)):.2f}"


def _decimal_number(value) -> float | None:
    if value is None:
        return None
    return float(value)
