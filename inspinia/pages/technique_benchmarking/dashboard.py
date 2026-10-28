from __future__ import annotations

from collections import Counter
from collections import defaultdict
from decimal import Decimal
from statistics import mean

from django.core.paginator import Paginator

from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.technique_benchmarking.keys import build_benchmark_row_key
from inspinia.pages.technique_benchmarking.scoring import calculate_static_difficulty_score
from inspinia.pages.technique_benchmarking.scoring import calculate_static_importance_score
from inspinia.pages.technique_benchmarking.scoring import normalize_target_profile
from inspinia.pages.technique_benchmarking.scoring import target_weight_for_benchmark
from inspinia.pages.technique_concepts import CONCEPT_MEMBER_KEYS
from inspinia.pages.technique_concepts import CONCEPTS
from inspinia.pages.technique_concepts import PROFILE_FIELDS
from inspinia.pages.technique_concepts import benchmark_member_filter
from inspinia.pages.technique_concepts import catalog_concept_ids
from inspinia.pages.technique_concepts import concept_for_benchmark

HIGH_VALUE_THRESHOLD = Decimal("4.00")
QUICK_WIN_DIFFICULTY_MAX = Decimal("3.00")
DEEP_BLOCK_DIFFICULTY_MIN = Decimal("4.00")
CONFIDENCE_REVIEW_THRESHOLD = 80
CALIBRATION_QUEUE_THRESHOLD = 70
CONFIDENCE_HIGH_THRESHOLD = 90
MATRIX_POINT_LIMIT = 200
HEATMAP_FAMILY_LIMIT = 40
HEATMAP_AREA_LIMIT = 12

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


def build_technique_benchmark_dashboard_context(  # noqa: PLR0913 -- preserve existing dashboard call contract
    benchmarks,
    *,
    raw_target_profile: str | None = None,
    paginate: bool = False,
    page_number=None,
    sort: str = "value",
    catalog_filters: dict | None = None,
    combine_concepts: bool = True,
) -> dict[str, object]:
    target_profile = normalize_target_profile(raw_target_profile)
    catalog_subject = catalog_filters.get("topic", "Algebra") if catalog_filters is not None else ""
    rows = [
        _benchmark_dashboard_row(benchmark, target_profile=target_profile, include_details=not paginate)
        for benchmark in benchmarks
    ]
    # A filter selects concepts through any member. Load all of their profiles
    # together so a filtered member cannot silently become the canonical rating.
    concept_ids = {
        concept_for_benchmark(row["kind"], row["row_key"].partition(":")[2], topic=catalog_subject) for row in rows
    } - {""} if combine_concepts else set()
    if concept_ids:
        query = benchmark_member_filter(
            member for concept_id in concept_ids for member in CONCEPT_MEMBER_KEYS[concept_id]
        )
        members = TechniqueBenchmark.objects.filter(query)
        if not paginate:
            members = members.prefetch_related("aliases")
        by_id = {row["benchmark_id"]: row for row in rows}
        by_id.update({
            benchmark.pk: _benchmark_dashboard_row(
                benchmark, target_profile=target_profile, include_details=not paginate,
            )
            for benchmark in members
        })
        rows = list(by_id.values())
    rows = _concept_dashboard_rows(rows, combine_concepts=combine_concepts, topic=catalog_subject)
    if catalog_filters is not None:
        rows = _catalog_rows(rows, catalog_filters)
    rows.sort(key=lambda row: (-(row["value_score_number"] or 0), row["row_key"]))
    chart_rows = [row for row in rows if row["chartable"]][:MATRIX_POINT_LIMIT]
    matrix_payload = _matrix_payload(chart_rows)
    heatmap_payload = _heatmap_payload(rows)
    sort_field = {
        "value": "value_score_number",
        "difficulty": "difficulty_score_number",
        "confidence": "benchmark_confidence",
        "name": "label",
    }.get(sort, "value_score_number")
    rows.sort(
        key=lambda row: (
            row[sort_field] is None,
            row[sort_field].casefold() if sort_field == "label" else -(row[sort_field] or 0),
            row["row_key"],
        ),
    )
    page = None
    display_rows = rows
    if paginate:
        page = Paginator(rows, 25).get_page(page_number)
        visible = {
            item.pk: item
            for item in TechniqueBenchmark.objects.filter(pk__in=[
                profile_id for row in page.object_list for profile_id in row["profile_ids"]
            ])
            .prefetch_related("aliases")
        }
        detailed = _concept_dashboard_rows(
            [_benchmark_dashboard_row(item, target_profile=target_profile) for item in visible.values()],
            combine_concepts=combine_concepts,
            topic=catalog_subject,
        )
        detailed_by_key = {row["row_key"]: row for row in detailed}
        display_rows = [{**row, **detailed_by_key.get(row["row_key"], {}),
                         "primary_area": row["primary_area"], "parent_family": row["parent_family"]}
                        for row in page.object_list]
    return {
        "page_obj": page,
        "benchmark_sort": sort,
        "technique_benchmark_rows": display_rows,
        "technique_benchmark_total": len(rows),
        "technique_benchmark_chart_is_capped": (
            len(rows) > MATRIX_POINT_LIMIT
            or len({row["parent_family"] for row in rows}) > HEATMAP_FAMILY_LIMIT
            or len({row["primary_area"] for row in rows}) > HEATMAP_AREA_LIMIT
        ),
        "technique_benchmark_target_profile": target_profile,
        "technique_benchmark_target_profile_label": TARGET_PROFILE_LABELS[target_profile],
        "technique_benchmark_target_profile_options": [
            {**option, "selected": option["key"] == target_profile} for option in TARGET_PROFILE_OPTIONS
        ],
        "technique_benchmark_summary_cards": _summary_cards(rows, target_profile=target_profile),
        "technique_benchmark_table_columns": TECHNIQUE_BENCHMARK_TABLE_COLUMNS,
        "technique_benchmark_matrix_payload": matrix_payload,
        "technique_benchmark_heatmap_payload": heatmap_payload,
    }


def benchmark_navigation_context(params, *, options: list[dict], target_profile: str) -> dict:
    """Keep the selected subject/profile scope through GET navigation."""
    params = params.copy()
    params.pop("page", None)
    for option in options:
        target_params = params.copy()
        target_params["target_profile"] = option["key"]
        option["query"] = target_params.urlencode()
    reset_params = params.copy()
    for key in ("q", "sort", "family", "row_key"):
        reset_params.pop(key, None)
    reset_params["target_profile"] = target_profile
    return {
        "pagination_query": params.urlencode(),
        "benchmark_scope_filters": {
            key: params[key] for key in ("area", "family", "row_key", "scope", "view") if params.get(key)
        },
        "benchmark_reset_query": reset_params.urlencode(),
        **_benchmark_catalog_navigation(params),
    }


def _benchmark_catalog_navigation(params) -> dict:
    """Build subject and view links without carrying a stale chart selection."""
    area_options = []
    for area in ("", "Algebra", "Number Theory", "Geometry", "Combinatorics"):
        area_params = params.copy()
        for key in ("area", "family", "row_key", "scope"):
            area_params.pop(key, None)
        if area:
            area_params["area"] = area
        area_options.append({
            "label": area or "All subjects",
            "selected": params.get("area", "").casefold() == area.casefold(),
            "query": area_params.urlencode(),
        })
    view_options = []
    for view, label in (("", "Concepts"), ("profiles", "Role profiles")):
        view_params = params.copy()
        for key in ("view", "family", "row_key"):
            view_params.pop(key, None)
        if view:
            view_params["view"] = view
        view_options.append({
            "label": label,
            "selected": (params.get("view") == "profiles") == bool(view),
            "query": view_params.urlencode(),
        })
    scope_options = []
    if params.get("area", "").casefold() == "number theory" and params.get("view") != "profiles":
        for scope, label in (("core", "Core concepts"), ("shared", "Shared tools")):
            scope_params = params.copy()
            for key in ("family", "row_key"):
                scope_params.pop(key, None)
            scope_params["scope"] = scope
            scope_options.append({
                "label": label,
                "selected": params.get("scope", "core") == scope,
                "query": scope_params.urlencode(),
            })
    return {
        "benchmark_area_options": area_options,
        "benchmark_view_options": view_options,
        "benchmark_scope_options": scope_options,
    }


def _catalog_rows(rows: list[dict], filters: dict) -> list[dict]:
    existing = {row["concept_id"]: row for row in rows if row.get("concept_id")}
    subject = filters.get("topic", "Algebra")
    rows = [existing.get(cid) or _unrated_concept_row(cid) for cid in catalog_concept_ids(
        subject, scope=filters.get("scope", "core"),
    )]
    for row in rows:
        definition = CONCEPTS[row["concept_id"]]
        row.update(primary_area=subject, parent_family=definition["area_label"])
    if filters.get("search"):
        rows = [row for row in rows if all(
            token.casefold() in (str(row) + str(CONCEPTS[row["concept_id"]]["aliases"])).casefold()
            for token in filters.get("search").split()
        )]
    if filters.get("family"):
        rows = [row for row in rows if row["parent_family"] == filters.get("family")]
    if filters.get("row_key"):
        rows = [row for row in rows if row["row_key"] == filters.get("row_key")]
    return rows


def _concept_dashboard_rows(rows: list[dict], *, combine_concepts: bool = True, topic: str = "") -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        concept_id = concept_for_benchmark(
            row["kind"], row["row_key"].partition(":")[2], topic=topic,
        ) if combine_concepts else ""
        groups[concept_id or row["row_key"]].append(row)
    result = []
    for key, profiles in groups.items():
        definition = CONCEPTS.get(key)
        profiles.sort(key=lambda row: row["row_key"])
        preferred = definition["preferred"] if definition else key
        row = dict(next((item for item in profiles if item["row_key"] == preferred), profiles[0]))
        row.update(
            concept_id=key if definition else "", profile_ids=[item["benchmark_id"] for item in profiles],
            roles=sorted({item["kind_label"] for item in profiles}),
            profiles=profiles if definition else [], profile_conflicts=[],
        )
        if definition:
            row["label"] = definition["label"]
            reference = next((item for item in profiles if item["row_key"] == preferred), None)
            if definition.get("reference_policy") == "identical_profiles_only" and (
                not preferred or len({profile["rating_signature"] for profile in profiles}) > 1
            ):
                reference = None
                row["profile_conflicts"] = ["retained_profiles_require_review"]
            row["reference_resolution"] = definition["benchmark_resolution"]
            for profile in profiles:
                contract = next(
                    p for p in definition["profiles"]
                    if f"{p['kind']}:{p['label_key']}" == profile["row_key"]
                )
                profile["profile_usage"] = contract["usage"]
                profile["profile_usage_reason"] = contract["usage_reason"]
            if reference is None:
                row.update(value_score="", difficulty_score="", value_score_number=None,
                           difficulty_score_number=None, chartable=False, training_type="Unrated",
                           target_level="", mohs_band_label="", benchmark_confidence=None,
                           confidence_label="", selected_target_weight="", selected_target_weight_number=None)
                if definition.get("reference_policy"):
                    row["benchmark_id"] = None
                if preferred and not row["profile_conflicts"]:
                    row["profile_conflicts"] = ["missing_reviewed_reference"]
            row["row_key"] = f"concept:{key}"
        result.append(row)
    return result


def _unrated_concept_row(concept_id: str) -> dict:
    definition = CONCEPTS[concept_id]
    # An unsaved model supplies only display defaults; no benchmark is created.
    placeholder = TechniqueBenchmark(kind="method", label=definition["label"])
    row = _benchmark_dashboard_row(placeholder, target_profile="national", include_details=False)
    row.update(
        concept_id=concept_id, row_key=f"concept:{concept_id}", profile_ids=[], profiles=[],
        roles=sorted({kind for kind, _label in definition["aliases"]}), profile_conflicts=[],
        reference_resolution=definition["benchmark_resolution"], chartable=False,
        value_score="", value_score_number=None, difficulty_score="", difficulty_score_number=None,
        selected_target_weight="", selected_target_weight_number=None, training_type="Unrated",
        confidence_label="", benchmark_confidence=None, mohs_band_label="",
    )
    return row


def _benchmark_dashboard_row(benchmark, *, target_profile: str, include_details: bool = True) -> dict[str, object]:
    value_score = calculate_static_importance_score(benchmark, target_profile=target_profile)
    difficulty_score = calculate_static_difficulty_score(benchmark)
    target_weight = target_weight_for_benchmark(benchmark, target_profile)
    row_key = build_benchmark_row_key(benchmark.kind, benchmark.label_key)
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
    row = {
        "benchmark_id": benchmark.pk,
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
        "rating_signature": tuple(str(getattr(benchmark, field)) for field in PROFILE_FIELDS),
    }
    if not include_details:
        return row
    row.update(
        {
            "alias_suggestions": ", ".join(alias.alias_label for alias in benchmark.aliases.all()),
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
        },
    )
    return row


def _summary_cards(rows: list[dict[str, object]], *, target_profile: str) -> list[dict[str, object]]:
    high_value_count = sum(1 for row in rows if _row_decimal(row, "value_score") >= HIGH_VALUE_THRESHOLD)
    quick_win_count = sum(
        1
        for row in rows
        if not row.get("profile_conflicts")
        and _row_decimal(row, "value_score") >= HIGH_VALUE_THRESHOLD
        and row["difficulty_score"]
        and Decimal(str(row["difficulty_score"])) <= QUICK_WIN_DIFFICULTY_MAX
    )
    deep_block_count = sum(1 for row in rows if _is_deep_block(row))
    confidence_review_count = sum(
        1
        for row in rows
        if row["benchmark_confidence"] is not None and row["benchmark_confidence"] < CONFIDENCE_REVIEW_THRESHOLD
    )
    calibration_queue_count = sum(
        1
        for row in rows
        if row["benchmark_confidence"] is not None and row["benchmark_confidence"] < CALIBRATION_QUEUE_THRESHOLD
    )
    target_weights = [
        Decimal(str(row["selected_target_weight"])) for row in rows
        if row["selected_target_weight"] and "selected_target_weight" not in row.get("profile_conflicts", [])
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
            {"name": training_type, "data": points} for training_type, points in sorted(series_by_training.items())
        ],
    }


def _heatmap_payload(rows: list[dict[str, object]]) -> dict[str, object]:
    families = [
        family for family, _count in Counter(row["parent_family"] for row in rows).most_common(HEATMAP_FAMILY_LIMIT)
    ]
    areas = sorted({row["primary_area"] for row in rows})[:HEATMAP_AREA_LIMIT]
    values_by_cell = defaultdict(list)
    count_by_cell = Counter()
    for row in rows:
        key = (row["primary_area"], row["parent_family"])
        count_by_cell[key] += 1
        if row["value_score_number"] is not None:
            values_by_cell[key].append(float(row["value_score_number"]))

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
    if row.get("profile_conflicts"):
        return False
    if row["training_type"] == "Deep block":
        return True
    if not row["value_score"] or not row["difficulty_score"]:
        return False
    return (
        Decimal(str(row["value_score"])) >= HIGH_VALUE_THRESHOLD
        and Decimal(str(row["difficulty_score"])) >= DEEP_BLOCK_DIFFICULTY_MIN
    )


def _row_decimal(row: dict[str, object], key: str) -> Decimal:
    if key in row.get("profile_conflicts", []):
        return Decimal("0")
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
