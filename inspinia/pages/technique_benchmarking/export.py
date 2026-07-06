from __future__ import annotations

import csv
import json
from decimal import Decimal
from typing import Any

from django.http import HttpResponse

from inspinia.pages.technique_benchmarking.importing import SCHEMA_VERSION
from inspinia.pages.technique_benchmarking.keys import benchmark_kind_for_gap_row
from inspinia.pages.technique_benchmarking.keys import benchmark_label_key_for_gap_row
from inspinia.pages.technique_benchmarking.keys import benchmark_row_key
from inspinia.pages.technique_benchmarking.scoring import benchmark_lookup_for_gap_rows

BENCHMARKABLE_CSV_CONTENT_TYPE = "text/csv; charset=utf-8"
BENCHMARKABLE_CSV_FIELDNAMES = [
    "row_key",
    "kind",
    "label",
    "label_key",
    "areas/0",
    "areas/1",
    "canonical_subtopic",
    "type",
    "completed",
    "total",
    "remaining",
    "coverage_percent",
    "avg_solved_mohs",
    "existing_benchmark",
    "areas/2",
    "areas/3",
]


def build_benchmark_export_payload(
    rows: list[dict[str, object]],
    *,
    target_profile: str = "national",
    include_existing_benchmark: bool = False,
    filters: dict[str, str] | None = None,
) -> dict[str, Any]:
    lookup = benchmark_lookup_for_gap_rows(rows) if include_existing_benchmark and rows else {}
    export_rows = []
    for row in rows:
        row_key = benchmark_row_key(row)
        lookup_entry = lookup.get(row_key, {})
        benchmark = lookup_entry.get("benchmark")
        export_rows.append(
            {
                "row_key": row_key,
                "kind": benchmark_kind_for_gap_row(row),
                "label": str(row.get("label") or ""),
                "label_key": benchmark_label_key_for_gap_row(row),
                "areas": list(row.get("main_topic_labels") or []),
                "canonical_subtopic": str(row.get("canonical_subtopic") or ""),
                "type": str(row.get("type") or ""),
                "completed": int(row.get("solved") or 0),
                "total": int(row.get("total") or 0),
                "remaining": int(row.get("remaining") or 0),
                "coverage_percent": int(row.get("completion_percent") or 0),
                "avg_solved_mohs": row.get("average_solved_mohs"),
                "existing_benchmark": _existing_benchmark_payload(benchmark) if benchmark is not None else None,
            },
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "target_profile": target_profile,
        "filters": filters or {},
        "row_count": len(export_rows),
        "scoring_summary": {
            "importance_score": (
                "0.30*syllabus_core + 0.25*contest_frequency + 0.20*transfer_value "
                "+ 0.15*prerequisite_value + 0.10*target_weight"
            ),
            "difficulty_score": (
                "0.25*concept_load + 0.25*recognition_burden + 0.20*execution_load "
                "+ 0.15*proof_fragility + 0.15*cross_topic_dependency"
            ),
        },
        "rows": export_rows,
    }


def build_benchmarkable_rows_csv_response(rows: list[dict[str, object]]) -> HttpResponse:
    response = HttpResponse(content_type=BENCHMARKABLE_CSV_CONTENT_TYPE)
    response["Content-Disposition"] = 'attachment; filename="technique-benchmarkable-rows.csv"'
    writer = csv.DictWriter(response, fieldnames=BENCHMARKABLE_CSV_FIELDNAMES)
    writer.writeheader()
    writer.writerows(_benchmarkable_csv_row(row) for row in rows)
    return response


def _benchmarkable_csv_row(row: dict[str, object]) -> dict[str, str]:
    benchmark = row.get("benchmark")
    existing_benchmark = _existing_benchmark_payload(benchmark) if benchmark is not None else None
    areas = list(row.get("main_topic_labels") or [])
    return {
        "row_key": str(row.get("benchmark_row_key") or benchmark_row_key(row)),
        "kind": benchmark_kind_for_gap_row(row),
        "label": str(row.get("label") or ""),
        "label_key": benchmark_label_key_for_gap_row(row),
        "areas/0": _list_cell(areas, 0),
        "areas/1": _list_cell(areas, 1),
        "canonical_subtopic": str(row.get("canonical_subtopic") or ""),
        "type": str(row.get("type") or ""),
        "completed": _csv_cell_value(row.get("solved")),
        "total": _csv_cell_value(row.get("total")),
        "remaining": _csv_cell_value(row.get("remaining")),
        "coverage_percent": _csv_cell_value(row.get("completion_percent")),
        "avg_solved_mohs": _csv_cell_value(row.get("average_solved_mohs")),
        "existing_benchmark": _json_csv_cell(existing_benchmark),
        "areas/2": _list_cell(areas, 2),
        "areas/3": _list_cell(areas, 3),
    }


def build_benchmark_prompt(payload: dict[str, Any], *, export_batch=None) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    batch_context = ""
    if export_batch is not None:
        batch_context = (
            f"Export batch: #{export_batch.pk}\n"
            f"Scope: {export_batch.scope_mode}\n"
            f"Expected rows: {export_batch.row_count}\n"
            f"Target profile: {export_batch.target_profile}\n\n"
        )
    return (
        "You are a math olympiad curriculum analyst.\n\n"
        "Task:\n"
        "Benchmark the following AsterProof subtopic practice gaps. The project does not have an "
        "internal AI model, so your output will be imported back into a Django table. "
        "Return strict JSON only.\n\n"
        f"{batch_context}"
        "Important:\n"
        f'- Use schema_version "{SCHEMA_VERSION}".\n'
        "- Do not change row_key.\n"
        "- Do not invent completed, total, remaining, or coverage values.\n"
        "- Benchmark the stable topic, not the current student.\n"
        "- The app will compute live priority rank later from static benchmark scores plus current gap data.\n"
        "- Use 1 to 5 integer scores unless the schema says otherwise.\n"
        "- training_type must be one of: Drill, Deep block, Mixed mock, Review, Postpone.\n"
        "- target_level must be one of: Foundation, JBMO, National, IMO/TST, Specialist.\n\n"
        "Return this JSON object shape:\n"
        "{\n"
        f'  "schema_version": "{SCHEMA_VERSION}",\n'
        '  "rows": [\n'
        "    {\n"
        '      "row_key": "string",\n'
        '      "normalized_label": "string",\n'
        '      "parent_family": "string",\n'
        '      "primary_area": "Algebra|Number Theory|Geometry|Combinatorics|Mixed",\n'
        '      "curriculum_class": "Foundation|Core|Advanced|Specialist",\n'
        '      "syllabus_core": 1,\n'
        '      "contest_frequency": 1,\n'
        '      "transfer_value": 1,\n'
        '      "prerequisite_value": 1,\n'
        '      "mohs_scalability": 1,\n'
        '      "concept_load": 1,\n'
        '      "recognition_burden": 1,\n'
        '      "execution_load": 1,\n'
        '      "proof_fragility": 1,\n'
        '      "cross_topic_dependency": 1,\n'
        '      "typical_mohs_min": 0,\n'
        '      "typical_mohs_max": 50,\n'
        '      "jbmo_weight": 1.00,\n'
        '      "national_weight": 1.00,\n'
        '      "imo_tst_weight": 1.00,\n'
        '      "training_type": "Drill",\n'
        '      "target_level": "Foundation",\n'
        '      "benchmark_confidence": 80,\n'
        '      "key_insight_spoiler_free": "compact non-spoiler insight",\n'
        '      "rationale": "one or two concise sentences",\n'
        '      "pitfalls": "common training mistake",\n'
        '      "recommended_sequence": "what to learn before/after",\n'
        '      "alias_suggestions": "optional semicolon-separated aliases",\n'
        '      "merge_note": "optional note for duplicate/merge handling"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rows to benchmark:\n"
        f"{payload_json}\n"
    )


def _existing_benchmark_payload(benchmark) -> dict[str, Any]:
    return {
        "normalized_label": benchmark.normalized_label,
        "parent_family": benchmark.parent_family,
        "primary_area": benchmark.primary_area,
        "curriculum_class": benchmark.curriculum_class,
        "syllabus_core": benchmark.syllabus_core,
        "contest_frequency": benchmark.contest_frequency,
        "transfer_value": benchmark.transfer_value,
        "prerequisite_value": benchmark.prerequisite_value,
        "mohs_scalability": benchmark.mohs_scalability,
        "concept_load": benchmark.concept_load,
        "recognition_burden": benchmark.recognition_burden,
        "execution_load": benchmark.execution_load,
        "proof_fragility": benchmark.proof_fragility,
        "cross_topic_dependency": benchmark.cross_topic_dependency,
        "difficulty_score": _decimal_to_float(benchmark.difficulty_score),
        "importance_score": _decimal_to_float(benchmark.importance_score),
        "typical_mohs_min": benchmark.typical_mohs_min,
        "typical_mohs_max": benchmark.typical_mohs_max,
        "jbmo_weight": _decimal_to_float(benchmark.jbmo_weight),
        "national_weight": _decimal_to_float(benchmark.national_weight),
        "imo_tst_weight": _decimal_to_float(benchmark.imo_tst_weight),
        "training_type": benchmark.training_type,
        "target_level": benchmark.target_level,
        "benchmark_confidence": benchmark.benchmark_confidence,
        "key_insight_spoiler_free": benchmark.key_insight_spoiler_free,
        "rationale": benchmark.rationale,
        "pitfalls": benchmark.pitfalls,
        "recommended_sequence": benchmark.recommended_sequence,
        "merge_note": benchmark.merge_note,
    }


def _decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _csv_cell_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _list_cell(values: list[object], index: int) -> str:
    try:
        return str(values[index] or "")
    except IndexError:
        return ""


def _json_csv_cell(value: object) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError
