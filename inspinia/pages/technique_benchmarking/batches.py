from __future__ import annotations

import json
import re
from typing import Any

from django.utils import timezone

from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import TechniqueBenchmarkExportBatch
from inspinia.pages.technique_benchmarking.coverage import BENCHMARK_GAP_KIND_LABELS
from inspinia.pages.technique_benchmarking.coverage import build_actionable_benchmark_rows
from inspinia.pages.technique_benchmarking.coverage import normalize_kind_filters
from inspinia.pages.technique_benchmarking.export import build_benchmark_export_payload
from inspinia.pages.technique_benchmarking.export import build_benchmark_prompt
from inspinia.pages.technique_benchmarking.importing import SCHEMA_VERSION
from inspinia.pages.technique_benchmarking.keys import parse_benchmark_row_key
from inspinia.pages.technique_benchmarking.scoring import REVIEW_CONFIDENCE_THRESHOLD
from inspinia.pages.technique_benchmarking.scoring import REVIEW_MOHS_BAND_WIDTH
from inspinia.pages.technique_benchmarking.scoring import normalize_target_profile

BATCH_SCOPE_CURRENT_VIEW = "current_view"
BATCH_SCOPE_ALL_MISSING = "all_missing"
BATCH_SCOPE_MISSING_BY_KIND = "missing_by_kind"
BATCH_SCOPE_HIGH_PRIORITY_MISSING = "high_priority_missing"
BATCH_SCOPE_NEEDS_REVIEW = "needs_review"
BATCH_SCOPE_LOW_CONFIDENCE_OR_WIDE_MOHS = "low_confidence_or_wide_mohs"
BATCH_SCOPE_CUSTOM_SELECTED = "custom_selected"

BATCH_SCOPE_MODES = {
    BATCH_SCOPE_CURRENT_VIEW,
    BATCH_SCOPE_ALL_MISSING,
    BATCH_SCOPE_MISSING_BY_KIND,
    BATCH_SCOPE_HIGH_PRIORITY_MISSING,
    BATCH_SCOPE_NEEDS_REVIEW,
    BATCH_SCOPE_LOW_CONFIDENCE_OR_WIDE_MOHS,
    BATCH_SCOPE_CUSTOM_SELECTED,
}
BATCH_SIZE_CHOICES = (25, 50, 100, 200)
BATCH_SORT_HIGH_REMAINING_LOW_COVERAGE = "high_remaining_low_coverage"
BATCH_SORT_PRIORITY_DESC = "priority_desc"
BATCH_SORT_REMAINING_DESC = "remaining_desc"
BATCH_SORT_LOWEST_COVERAGE = "lowest_coverage"
BATCH_SORT_LABEL = "label"
BATCH_SORT_MODES = {
    BATCH_SORT_HIGH_REMAINING_LOW_COVERAGE,
    BATCH_SORT_PRIORITY_DESC,
    BATCH_SORT_REMAINING_DESC,
    BATCH_SORT_LOWEST_COVERAGE,
    BATCH_SORT_LABEL,
}


def create_benchmark_export_batch(  # noqa: PLR0913
    *,
    request_user,
    created_by,
    raw_user_id: str = "",
    raw_topic: str = "",
    raw_min_total: str = "",
    raw_canonical_subtopic: str = "",
    raw_kind: str = "",
    scope_mode: str = BATCH_SCOPE_ALL_MISSING,
    kind_filters: list[str] | tuple[str, ...] | None = None,
    target_profile: str = "national",
    batch_size: int = 50,
    sort_mode: str = BATCH_SORT_HIGH_REMAINING_LOW_COVERAGE,
    custom_row_keys: list[str] | tuple[str, ...] | str | None = None,
) -> TechniqueBenchmarkExportBatch:
    selected_rows = select_benchmark_batch_rows(
        request_user=request_user,
        raw_user_id=raw_user_id,
        raw_topic=raw_topic,
        raw_min_total=raw_min_total,
        raw_canonical_subtopic=raw_canonical_subtopic,
        raw_kind=raw_kind,
        scope_mode=scope_mode,
        kind_filters=kind_filters,
        target_profile=target_profile,
        batch_size=batch_size,
        sort_mode=sort_mode,
        custom_row_keys=custom_row_keys,
    )
    normalized_scope_mode = normalize_scope_mode(scope_mode)
    normalized_kind_filters = _kind_filters_for_scope(
        normalized_scope_mode,
        raw_kind=raw_kind,
        kind_filters=kind_filters,
    )
    normalized_batch_size = normalize_batch_size(batch_size)
    normalized_target_profile = normalize_target_profile(target_profile)
    normalized_sort_mode = normalize_sort_mode(sort_mode)
    filters = {
        "scope_mode": normalized_scope_mode,
        "kind_filters": normalized_kind_filters,
        "topic": raw_topic or "all",
        "min_total": raw_min_total or "",
        "canonical_subtopic": raw_canonical_subtopic or "",
        "sort_mode": normalized_sort_mode,
    }
    payload = build_benchmark_export_payload(
        selected_rows,
        target_profile=normalized_target_profile,
        include_existing_benchmark=True,
        filters=filters,
    )
    frozen_row_keys = [str(row["row_key"]) for row in payload["rows"]]
    export_batch = TechniqueBenchmarkExportBatch.objects.create(
        schema_version=SCHEMA_VERSION,
        target_profile=normalized_target_profile,
        scope_mode=normalized_scope_mode,
        kind_filters=normalized_kind_filters,
        topic_filters={
            "topic": raw_topic or "all",
            "canonical_subtopic": raw_canonical_subtopic or "",
        },
        min_total=_coerce_nonnegative_int(raw_min_total),
        batch_size=normalized_batch_size,
        sort_mode=normalized_sort_mode,
        frozen_row_keys=frozen_row_keys,
        source_payload=payload,
        row_count=len(frozen_row_keys),
        status=TechniqueBenchmarkExportBatch.Status.EXPORTED,
        created_by=created_by,
    )
    payload["export_batch"] = _export_batch_payload(export_batch)
    export_batch.source_payload = payload
    export_batch.prompt_text = build_benchmark_prompt(payload, export_batch=export_batch)
    export_batch.save(update_fields=["source_payload", "prompt_text", "updated_at"])
    return export_batch


def select_benchmark_batch_rows(  # noqa: PLR0913
    *,
    request_user,
    raw_user_id: str = "",
    raw_topic: str = "",
    raw_min_total: str = "",
    raw_canonical_subtopic: str = "",
    raw_kind: str = "",
    scope_mode: str = BATCH_SCOPE_ALL_MISSING,
    kind_filters: list[str] | tuple[str, ...] | None = None,
    target_profile: str = "national",
    batch_size: int = 50,
    sort_mode: str = BATCH_SORT_HIGH_REMAINING_LOW_COVERAGE,
    custom_row_keys: list[str] | tuple[str, ...] | str | None = None,
) -> list[dict[str, Any]]:
    normalized_scope_mode = normalize_scope_mode(scope_mode)
    normalized_kind_filters = _kind_filters_for_scope(
        normalized_scope_mode,
        raw_kind=raw_kind,
        kind_filters=kind_filters,
    )
    rows = build_actionable_benchmark_rows(
        request_user=request_user,
        raw_user_id=raw_user_id,
        raw_topic=raw_topic,
        raw_min_total=raw_min_total,
        raw_canonical_subtopic=raw_canonical_subtopic,
        kind_filters=normalized_kind_filters,
        target_profile=target_profile,
    )
    rows = _rows_for_scope(
        rows,
        scope_mode=normalized_scope_mode,
        custom_row_keys=custom_row_keys,
    )
    rows = sort_batch_rows(rows, sort_mode=sort_mode)
    return rows[:normalize_batch_size(batch_size)]


def sort_batch_rows(rows: list[dict[str, Any]], *, sort_mode: str) -> list[dict[str, Any]]:
    normalized_sort_mode = normalize_sort_mode(sort_mode)
    if normalized_sort_mode == BATCH_SORT_PRIORITY_DESC:
        return sorted(
            rows,
            key=lambda row: (
                _none_last_negative(row.get("priority_score")),
                -int(row.get("remaining") or 0),
                str(row.get("label") or "").casefold(),
            ),
        )
    if normalized_sort_mode == BATCH_SORT_REMAINING_DESC:
        return sorted(rows, key=lambda row: (-int(row.get("remaining") or 0), str(row.get("label") or "").casefold()))
    if normalized_sort_mode == BATCH_SORT_LOWEST_COVERAGE:
        return sorted(
            rows,
            key=lambda row: (
                int(row.get("completion_percent") or 0),
                -int(row.get("remaining") or 0),
                str(row.get("label") or "").casefold(),
            ),
        )
    if normalized_sort_mode == BATCH_SORT_LABEL:
        return sorted(rows, key=lambda row: (str(row.get("label") or "").casefold(), str(row.get("type") or "")))
    return sorted(
        rows,
        key=lambda row: (
            -int(row.get("remaining") or 0),
            int(row.get("completion_percent") or 0),
            -int(row.get("total") or 0),
            str(row.get("label") or "").casefold(),
            str(row.get("type") or "").casefold(),
        ),
    )


def mark_benchmark_rows_reviewed(row_keys: list[str] | tuple[str, ...] | str) -> int:
    reviewed = 0
    for row_key in parse_row_keys(row_keys):
        kind, label_key = parse_benchmark_row_key(row_key)
        if not kind or not label_key:
            continue
        benchmark = TechniqueBenchmark.objects.filter(kind=kind, label_key=label_key).first()
        if benchmark is None or not benchmark.quality_flags:
            continue
        benchmark.quality_flags = []
        benchmark.save(update_fields=["quality_flags", "updated_at"])
        reviewed += 1
    return reviewed


def mark_export_batch_previewed(export_batch: TechniqueBenchmarkExportBatch) -> None:
    if export_batch.status == TechniqueBenchmarkExportBatch.Status.EXPORTED:
        export_batch.status = TechniqueBenchmarkExportBatch.Status.PREVIEWED
        export_batch.save(update_fields=["status", "updated_at"])


def mark_export_batch_applied(export_batch: TechniqueBenchmarkExportBatch) -> None:
    export_batch.status = TechniqueBenchmarkExportBatch.Status.APPLIED
    export_batch.updated_at = timezone.now()
    export_batch.save(update_fields=["status", "updated_at"])


def normalize_scope_mode(scope_mode: str) -> str:
    value = str(scope_mode or "").strip()
    return value if value in BATCH_SCOPE_MODES else BATCH_SCOPE_ALL_MISSING


def normalize_batch_size(batch_size: int | str) -> int:
    value = _coerce_nonnegative_int(batch_size)
    if not value:
        return 50
    return min(value, 250)


def normalize_sort_mode(sort_mode: str) -> str:
    value = str(sort_mode or "").strip()
    return value if value in BATCH_SORT_MODES else BATCH_SORT_HIGH_REMAINING_LOW_COVERAGE


def parse_row_keys(row_keys: list[str] | tuple[str, ...] | str | None) -> list[str]:
    raw_values = re.split(r"[\s,]+", row_keys) if isinstance(row_keys, str) else list(row_keys or [])
    normalized = []
    for row_key in raw_values:
        kind, label_key = parse_benchmark_row_key(row_key)
        if kind and label_key:
            normalized.append(f"{kind}:{label_key}")
    return list(dict.fromkeys(normalized))


def batch_scope_options() -> list[dict[str, str]]:
    return [
        {"value": BATCH_SCOPE_CURRENT_VIEW, "label": "Current view"},
        {"value": BATCH_SCOPE_ALL_MISSING, "label": "All missing benchmarks"},
        {"value": BATCH_SCOPE_MISSING_BY_KIND, "label": "Missing by kind"},
        {"value": BATCH_SCOPE_HIGH_PRIORITY_MISSING, "label": "High-priority missing"},
        {"value": BATCH_SCOPE_NEEDS_REVIEW, "label": "Needs review only"},
        {"value": BATCH_SCOPE_LOW_CONFIDENCE_OR_WIDE_MOHS, "label": "Low confidence / wide MOHS band"},
        {"value": BATCH_SCOPE_CUSTOM_SELECTED, "label": "Custom selected rows"},
    ]


def batch_sort_options() -> list[dict[str, str]]:
    return [
        {"value": BATCH_SORT_HIGH_REMAINING_LOW_COVERAGE, "label": "High remaining + low coverage"},
        {"value": BATCH_SORT_PRIORITY_DESC, "label": "Priority score"},
        {"value": BATCH_SORT_REMAINING_DESC, "label": "Remaining count"},
        {"value": BATCH_SORT_LOWEST_COVERAGE, "label": "Lowest coverage"},
        {"value": BATCH_SORT_LABEL, "label": "Label"},
    ]


def kind_filter_options() -> list[dict[str, str]]:
    return [
        {"value": kind, "label": label}
        for kind, label in BENCHMARK_GAP_KIND_LABELS.items()
    ]


def _rows_for_scope(
    rows: list[dict[str, Any]],
    *,
    scope_mode: str,
    custom_row_keys: list[str] | tuple[str, ...] | str | None,
) -> list[dict[str, Any]]:
    if scope_mode == BATCH_SCOPE_CURRENT_VIEW:
        return rows
    if scope_mode in {BATCH_SCOPE_ALL_MISSING, BATCH_SCOPE_MISSING_BY_KIND, BATCH_SCOPE_HIGH_PRIORITY_MISSING}:
        return [row for row in rows if row.get("benchmark_status") == "missing"]
    if scope_mode == BATCH_SCOPE_NEEDS_REVIEW:
        return [row for row in rows if row.get("benchmark_status") == "needs_review"]
    if scope_mode == BATCH_SCOPE_LOW_CONFIDENCE_OR_WIDE_MOHS:
        return [
            row
            for row in rows
            if row.get("benchmark_status") == "needs_review"
            and (
                _is_low_confidence(row)
                or _has_wide_mohs_band(row)
                or bool(getattr(row.get("benchmark"), "quality_flags", []))
            )
        ]
    if scope_mode == BATCH_SCOPE_CUSTOM_SELECTED:
        wanted = set(parse_row_keys(custom_row_keys))
        return [row for row in rows if row.get("benchmark_row_key") in wanted]
    return rows


def _kind_filters_for_scope(
    scope_mode: str,
    *,
    raw_kind: str,
    kind_filters: list[str] | tuple[str, ...] | None,
) -> list[str]:
    if scope_mode == BATCH_SCOPE_CURRENT_VIEW and raw_kind:
        return normalize_kind_filters([raw_kind])
    return normalize_kind_filters(kind_filters)


def _is_low_confidence(row: dict[str, Any]) -> bool:
    confidence = row.get("benchmark_confidence")
    return confidence is not None and int(confidence) < REVIEW_CONFIDENCE_THRESHOLD


def _has_wide_mohs_band(row: dict[str, Any]) -> bool:
    mohs_min = row.get("typical_mohs_min")
    mohs_max = row.get("typical_mohs_max")
    return (
        mohs_min is not None
        and mohs_max is not None
        and int(mohs_max) - int(mohs_min) >= REVIEW_MOHS_BAND_WIDTH
    )


def _none_last_negative(value: object) -> tuple[int, float]:
    if value is None:
        return (1, 0)
    return (0, -float(value))


def _coerce_nonnegative_int(value: object) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _export_batch_payload(export_batch: TechniqueBenchmarkExportBatch) -> dict[str, Any]:
    return {
        "id": export_batch.pk,
        "schema_version": export_batch.schema_version,
        "target_profile": export_batch.target_profile,
        "scope_mode": export_batch.scope_mode,
        "kind_filters": export_batch.kind_filters,
        "row_count": export_batch.row_count,
        "status": export_batch.status,
    }


def export_batch_source_json(export_batch: TechniqueBenchmarkExportBatch) -> str:
    return json.dumps(export_batch.source_payload, ensure_ascii=False, indent=2, default=str)
