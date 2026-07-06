from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse

from django.db import transaction
from django.utils import timezone

from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import TechniqueBenchmarkAlias
from inspinia.pages.models import TechniqueBenchmarkExportBatch
from inspinia.pages.models import TechniqueBenchmarkImportBatch
from inspinia.pages.technique_benchmarking.keys import build_benchmark_row_key
from inspinia.pages.technique_benchmarking.keys import normalize_benchmark_key
from inspinia.pages.technique_benchmarking.keys import parse_benchmark_row_key
from inspinia.pages.technique_benchmarking.scoring import calculate_static_difficulty_score
from inspinia.pages.technique_benchmarking.scoring import calculate_static_importance_score

SCHEMA_VERSION = "technique-gap-benchmark-v1"
MAX_PASTED_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 250
MAX_LONG_TEXT_CHARS = 500
MAX_BENCHMARK_TEXT_CHARS = 255
MAX_PRIMARY_AREA_CHARS = 64
MIN_MARKDOWN_TABLE_LINES = 3
SCORE_MIN = 1
SCORE_MAX = 5
MOHS_MIN = 0
MOHS_MAX = 60
CONFIDENCE_MIN = 0
CONFIDENCE_MAX = 100
MAX_PROFILE_WEIGHT = Decimal("3.00")
SCORE_FIELDS = (
    "syllabus_core",
    "contest_frequency",
    "transfer_value",
    "prerequisite_value",
    "concept_load",
    "recognition_burden",
    "execution_load",
    "proof_fragility",
    "cross_topic_dependency",
)
WEIGHT_FIELDS = ("jbmo_weight", "national_weight", "imo_tst_weight")
TEXT_LIMIT_FIELDS = ("rationale", "pitfalls", "recommended_sequence")
MODEL_TEXT_LIMIT_FIELDS = {
    "label_key": MAX_BENCHMARK_TEXT_CHARS,
    "normalized_label": MAX_BENCHMARK_TEXT_CHARS,
    "parent_family": MAX_BENCHMARK_TEXT_CHARS,
    "primary_area": MAX_PRIMARY_AREA_CHARS,
}
TRAINING_TYPES = TechniqueBenchmark.TRAINING_TYPES
TARGET_LEVELS = TechniqueBenchmark.TARGET_LEVELS
LAYER_KIND_TO_BENCHMARK_KIND = {
    "subtopics": TechniqueBenchmark.Kind.CANONICAL_SUBTOPIC,
    "techniques": TechniqueBenchmark.Kind.TECHNIQUE,
    "objects": TechniqueBenchmark.Kind.OBJECT,
    "methods": TechniqueBenchmark.Kind.METHOD,
    "lemmas": TechniqueBenchmark.Kind.LEMMA,
    "proof_roles": TechniqueBenchmark.Kind.PROOF_ROLE,
}
TYPE_TO_BENCHMARK_KIND = {
    "canonical subtopic": TechniqueBenchmark.Kind.CANONICAL_SUBTOPIC,
    "subtopic": TechniqueBenchmark.Kind.CANONICAL_SUBTOPIC,
    "technique": TechniqueBenchmark.Kind.TECHNIQUE,
    "object": TechniqueBenchmark.Kind.OBJECT,
    "method": TechniqueBenchmark.Kind.METHOD,
    "lemma": TechniqueBenchmark.Kind.LEMMA,
    "lemma theorem": TechniqueBenchmark.Kind.LEMMA,
    "lemma/theorem": TechniqueBenchmark.Kind.LEMMA,
    "proof role": TechniqueBenchmark.Kind.PROOF_ROLE,
    "parent family": TechniqueBenchmark.Kind.PARENT_FAMILY,
}
MODEL_UPDATE_FIELDS = (
    "label",
    "normalized_label",
    "parent_family",
    "primary_area",
    "area_labels",
    "syllabus_core",
    "contest_frequency",
    "transfer_value",
    "prerequisite_value",
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
    "rationale",
    "pitfalls",
    "recommended_sequence",
    "source_version",
)
PREVIEW_CHANGED_FIELD_LABELS = {
    "normalized_label": "Normalized label",
    "parent_family": "Parent family",
    "primary_area": "Primary area",
    "syllabus_core": "Syllabus",
    "contest_frequency": "Frequency",
    "transfer_value": "Transfer",
    "prerequisite_value": "Prerequisite",
    "concept_load": "Concept",
    "recognition_burden": "Recognition",
    "execution_load": "Execution",
    "proof_fragility": "Fragility",
    "cross_topic_dependency": "Dependency",
    "typical_mohs_min": "MOHS min",
    "typical_mohs_max": "MOHS max",
    "jbmo_weight": "JBMO weight",
    "national_weight": "National weight",
    "imo_tst_weight": "IMO/TST weight",
    "training_type": "Training type",
    "target_level": "Target level",
    "benchmark_confidence": "Confidence",
    "rationale": "Rationale",
    "pitfalls": "Pitfalls",
    "recommended_sequence": "Recommended sequence",
}


class BenchmarkImportValidationError(ValueError):
    """Raised when a pasted benchmark import cannot be safely previewed."""


@dataclass(frozen=True)
class BenchmarkImportPreview:
    schema_version: str
    rows_total: int
    rows_valid: int
    rows_invalid: int
    valid_rows: list[dict[str, Any]]
    invalid_rows: list[dict[str, Any]]
    preview_rows: list[dict[str, Any]]
    preview_payload: dict[str, Any]


def preview_benchmark_import(
    pasted_response: str,
    *,
    known_row_keys: set[str] | None = None,
    export_batch: TechniqueBenchmarkExportBatch | None = None,
) -> BenchmarkImportPreview:
    schema_version, raw_rows = parse_benchmark_import_response(pasted_response)
    inference_row_keys = _inference_row_keys(known_row_keys=known_row_keys, export_batch=export_batch)
    expected_row_keys = _expected_row_keys(export_batch=export_batch)

    seen_row_keys: set[str] = set()
    received_row_keys: set[str] = set()
    valid_rows: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []
    preview_rows: list[dict[str, Any]] = []
    old_rows: dict[str, dict[str, Any] | None] = {}
    new_rows: dict[str, dict[str, Any]] = {}
    old_aliases: dict[str, dict[str, Any] | None] = {}
    new_aliases: dict[str, dict[str, Any]] = {}
    changed_parent_family_row_keys: list[str] = []

    for index, raw_row in enumerate(raw_rows, start=1):
        normalized_row, errors = _validate_raw_row(
            raw_row,
            index=index,
            inference_row_keys=inference_row_keys,
            expected_row_keys=expected_row_keys,
            seen_row_keys=seen_row_keys,
        )
        row_key = str(normalized_row.get("row_key") or raw_row.get("row_key") or f"row-{index}")
        if normalized_row.get("row_key"):
            received_row_keys.add(str(normalized_row["row_key"]))
        if errors:
            invalid_row = {
                "index": index,
                "row_key": row_key,
                "errors": errors,
            }
            invalid_rows.append(invalid_row)
            preview_rows.append({"status": "error", **invalid_row})
            continue

        valid_rows.append(normalized_row)
        benchmark = TechniqueBenchmark.objects.filter(
            kind=normalized_row["kind"],
            label_key=normalized_row["label_key"],
        ).first()
        old_snapshot = snapshot_benchmark(benchmark)
        new_snapshot = _snapshot_from_import_row(normalized_row, existing_benchmark=benchmark)
        old_rows[row_key] = old_snapshot
        new_rows[row_key] = new_snapshot
        row_old_aliases, row_new_aliases = _alias_snapshots_from_import_row(normalized_row)
        old_aliases.update(row_old_aliases)
        new_aliases.update(row_new_aliases)
        if (
            old_snapshot is not None
            and old_snapshot.get("parent_family")
            and old_snapshot.get("parent_family") != new_snapshot.get("parent_family")
        ):
            changed_parent_family_row_keys.append(row_key)
            new_snapshot["quality_flags"] = _quality_flags_with(
                new_snapshot.get("quality_flags"),
                "parent_family_changed",
            )
        preview_rows.append(
            {
                "index": index,
                "row_key": row_key,
                "status": _preview_status(old_snapshot, new_snapshot),
                "label": new_snapshot["label"],
                "old": old_snapshot,
                "new": new_snapshot,
                "details": _preview_details(old_snapshot, new_snapshot),
            },
        )

    preview_payload = {
        "schema_version": schema_version,
        "old_rows": old_rows,
        "new_rows": new_rows,
        "old_aliases": old_aliases,
        "new_aliases": new_aliases,
        "invalid_rows": invalid_rows,
        "changed_parent_family_row_keys": changed_parent_family_row_keys,
        "export_batch_id": export_batch.pk if export_batch is not None else None,
        "expected_row_count": len(expected_row_keys),
        "received_row_count": len(received_row_keys),
        "missing_row_keys": sorted(expected_row_keys - received_row_keys),
    }
    return BenchmarkImportPreview(
        schema_version=schema_version,
        rows_total=len(raw_rows),
        rows_valid=len(valid_rows),
        rows_invalid=len(invalid_rows),
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        preview_rows=preview_rows,
        preview_payload=preview_payload,
    )


def parse_benchmark_import_response(pasted_response: str) -> tuple[str, list[dict[str, Any]]]:
    raw_text = str(pasted_response or "")
    if not raw_text.strip():
        msg = "Paste a ChatGPT benchmark response before previewing."
        raise BenchmarkImportValidationError(msg)
    if len(raw_text.encode("utf-8")) > MAX_PASTED_RESPONSE_BYTES:
        msg = "Pasted benchmark response is too large."
        raise BenchmarkImportValidationError(msg)

    parsed_payload = _parse_supported_payload(raw_text)
    if parsed_payload is None:
        msg = "Benchmark response must be valid JSON, fenced JSON, JSONL, markdown table, CSV, or TSV."
        raise BenchmarkImportValidationError(msg)

    schema_version, rows = _rows_from_payload(parsed_payload)
    if _looks_like_source_export_rows(rows):
        msg = (
            "This looks like the source export payload, not ChatGPT's benchmark response. "
            "It contains completed/total/remaining fields but no syllabus_core or difficulty fields. "
            "Paste the JSON object returned by ChatGPT."
        )
        raise BenchmarkImportValidationError(msg)
    if schema_version != SCHEMA_VERSION:
        msg = f"Unsupported benchmark schema version: {schema_version or 'missing'}."
        raise BenchmarkImportValidationError(msg)
    if len(rows) > MAX_IMPORT_ROWS:
        msg = f"Benchmark import has {len(rows)} rows; maximum is {MAX_IMPORT_ROWS}."
        raise BenchmarkImportValidationError(msg)
    return schema_version, rows


@transaction.atomic
def apply_benchmark_import(
    preview: BenchmarkImportPreview,
    *,
    user,
    prompt_text: str = "",
    pasted_response: str = "",
    export_batch: TechniqueBenchmarkExportBatch | None = None,
) -> TechniqueBenchmarkImportBatch:
    batch = TechniqueBenchmarkImportBatch.objects.create(
        created_by=user,
        export_batch=export_batch,
        status=TechniqueBenchmarkImportBatch.Status.APPLIED,
        prompt_text=prompt_text,
        pasted_response=pasted_response,
        rows_total=preview.rows_total,
        rows_valid=preview.rows_valid,
        rows_invalid=preview.rows_invalid,
        preview_payload=preview.preview_payload,
        applied_at=timezone.now(),
    )
    created_count = 0
    updated_count = 0
    unchanged_count = 0
    for row in preview.valid_rows:
        row_key = row["row_key"]
        old_snapshot = preview.preview_payload["old_rows"].get(row_key)
        new_snapshot = preview.preview_payload["new_rows"][row_key]

        benchmark = TechniqueBenchmark.objects.filter(kind=row["kind"], label_key=row["label_key"]).first()
        if benchmark is None:
            benchmark = TechniqueBenchmark(kind=row["kind"], label_key=row["label_key"])
            created_count += 1
        elif old_snapshot != new_snapshot:
            updated_count += 1
        else:
            unchanged_count += 1

        if old_snapshot != new_snapshot:
            _apply_snapshot_to_benchmark(benchmark, new_snapshot)
            benchmark.imported_from_batch = batch
            benchmark.save()
        else:
            benchmark.save()
        _apply_alias_suggestions(benchmark, row)

    batch.rows_created = created_count
    batch.rows_updated = updated_count
    batch.rows_unchanged = unchanged_count
    batch.save(
        update_fields=[
            "rows_created",
            "rows_updated",
            "rows_unchanged",
        ],
    )
    return batch


@transaction.atomic
def restore_benchmark_import_batch(batch: TechniqueBenchmarkImportBatch) -> dict[str, int]:
    payload = batch.preview_payload or {}
    old_rows = payload.get("old_rows") or {}
    new_rows = payload.get("new_rows") or {}
    restored = 0
    deleted = 0
    skipped = 0

    for row_key in new_rows:
        kind, label_key = parse_benchmark_row_key(row_key)
        benchmark = TechniqueBenchmark.objects.filter(kind=kind, label_key=label_key).first()
        old_snapshot = old_rows.get(row_key)
        if old_snapshot is None:
            if benchmark is None:
                skipped += 1
                continue
            benchmark.delete()
            deleted += 1
            continue
        if benchmark is None:
            benchmark = TechniqueBenchmark(kind=kind, label_key=label_key)
        _apply_snapshot_to_benchmark(benchmark, old_snapshot)
        benchmark.save()
        restored += 1

    _restore_alias_snapshots(payload)

    batch.status = TechniqueBenchmarkImportBatch.Status.RESTORED
    batch.restored_at = timezone.now()
    batch.save(update_fields=["status", "restored_at"])
    return {
        "restored": restored,
        "deleted": deleted,
        "skipped": skipped,
    }


def snapshot_benchmark(benchmark: TechniqueBenchmark | None) -> dict[str, Any] | None:
    if benchmark is None:
        return None
    snapshot = {
        "kind": benchmark.kind,
        "label_key": benchmark.label_key,
    }
    for field_name in MODEL_UPDATE_FIELDS:
        value = getattr(benchmark, field_name)
        if isinstance(value, Decimal):
            value = str(value)
        snapshot[field_name] = value
    return snapshot


def snapshot_alias(alias: TechniqueBenchmarkAlias | None) -> dict[str, Any] | None:
    if alias is None:
        return None
    return {
        "kind": alias.kind,
        "alias_label": alias.alias_label,
        "alias_key": alias.alias_key,
        "benchmark_row_key": build_benchmark_row_key(alias.benchmark.kind, alias.benchmark.label_key),
        "reason": alias.reason,
    }


def _alias_snapshots_from_import_row(
    row: dict[str, Any],
) -> tuple[dict[str, dict[str, Any] | None], dict[str, dict[str, Any]]]:
    old_aliases: dict[str, dict[str, Any] | None] = {}
    new_aliases: dict[str, dict[str, Any]] = {}
    for alias_label in row.get("alias_suggestions") or []:
        alias_key = normalize_benchmark_key(alias_label)
        if not alias_key or alias_key == row["label_key"]:
            continue
        alias_row_key = build_benchmark_row_key(row["kind"], alias_key)
        alias = TechniqueBenchmarkAlias.objects.select_related("benchmark").filter(
            kind=row["kind"],
            alias_key=alias_key,
        ).first()
        old_aliases[alias_row_key] = snapshot_alias(alias)
        new_aliases[alias_row_key] = {
            "kind": row["kind"],
            "alias_label": alias_label,
            "alias_key": alias_key,
            "benchmark_row_key": row["row_key"],
            "reason": "Imported benchmark alias suggestion.",
        }
    return old_aliases, new_aliases


def _apply_alias_suggestions(benchmark: TechniqueBenchmark, row: dict[str, Any]) -> None:
    for alias_label in row.get("alias_suggestions") or []:
        alias_key = normalize_benchmark_key(alias_label)
        if not alias_key or alias_key == benchmark.label_key:
            continue
        TechniqueBenchmarkAlias.objects.update_or_create(
            kind=benchmark.kind,
            alias_key=alias_key,
            defaults={
                "alias_label": alias_label,
                "benchmark": benchmark,
                "reason": "Imported benchmark alias suggestion.",
            },
        )


def _restore_alias_snapshots(payload: dict[str, Any]) -> None:
    old_aliases = payload.get("old_aliases") or {}
    new_aliases = payload.get("new_aliases") or {}
    for alias_row_key in new_aliases:
        kind, alias_key = parse_benchmark_row_key(alias_row_key)
        if not kind or not alias_key:
            continue
        alias = TechniqueBenchmarkAlias.objects.filter(kind=kind, alias_key=alias_key).first()
        old_snapshot = old_aliases.get(alias_row_key)
        if old_snapshot is None:
            if alias is not None:
                alias.delete()
            continue

        benchmark = _benchmark_from_row_key(str(old_snapshot.get("benchmark_row_key") or ""))
        if benchmark is None:
            if alias is not None:
                alias.delete()
            continue
        TechniqueBenchmarkAlias.objects.update_or_create(
            kind=old_snapshot["kind"],
            alias_key=old_snapshot["alias_key"],
            defaults={
                "alias_label": old_snapshot["alias_label"],
                "benchmark": benchmark,
                "reason": old_snapshot.get("reason") or "",
            },
        )


def _benchmark_from_row_key(row_key: str) -> TechniqueBenchmark | None:
    kind, label_key = parse_benchmark_row_key(row_key)
    if not kind or not label_key:
        return None
    return TechniqueBenchmark.objects.filter(kind=kind, label_key=label_key).first()


def _parse_json_payload(raw_text: str) -> Any | None:
    candidates = [raw_text.strip()]
    fenced_match = re.search(r"```(?:json)?\s*(?P<payload>.*?)```", raw_text, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match is not None:
        candidates.insert(0, fenced_match.group("payload").strip())
    extracted_payload = _extract_json_from_prose(raw_text)
    if extracted_payload:
        candidates.append(extracted_payload)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _parse_supported_payload(raw_text: str) -> Any | None:
    for parser in (
        _parse_json_payload,
        _parse_jsonl_payload,
        _parse_markdown_table_payload,
        _parse_tsv_payload,
        _parse_csv_payload,
    ):
        parsed_payload = parser(raw_text)
        if parsed_payload is not None:
            return parsed_payload
    return None


def _extract_json_from_prose(raw_text: str) -> str:
    decoder = json.JSONDecoder()
    for index, character in enumerate(raw_text):
        if character not in "[{":
            continue
        try:
            _payload, end = decoder.raw_decode(raw_text[index:])
        except json.JSONDecodeError:
            continue
        return raw_text[index : index + end]
    return ""


def _parse_jsonl_payload(raw_text: str) -> list[dict[str, Any]] | None:
    rows = []
    for line in raw_text.splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            continue
        try:
            row = json.loads(stripped_line)
        except json.JSONDecodeError:
            return None
        if not isinstance(row, dict):
            return None
        rows.append(row)
    return rows or None


def _parse_markdown_table_payload(raw_text: str) -> list[dict[str, Any]] | None:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip().startswith("|")]
    if len(lines) < MIN_MARKDOWN_TABLE_LINES:
        return None
    header_cells = _markdown_cells(lines[0])
    separator_cells = _markdown_cells(lines[1])
    if not header_cells or "row_key" not in {_normalize_header(cell) for cell in header_cells}:
        return None
    if not all(set(cell.replace(":", "").strip()) <= {"-"} for cell in separator_cells):
        return None

    headers = [_normalize_header(cell) for cell in header_cells]
    rows = []
    for line in lines[2:]:
        cells = _markdown_cells(line)
        if len(cells) != len(headers):
            return None
        row = {
            header: cell
            for header, cell in zip(headers, cells, strict=True)
            if header
        }
        rows.append(row)
    return rows or None


def _markdown_cells(line: str) -> list[str]:
    stripped_line = line.strip()
    if stripped_line.startswith("|"):
        stripped_line = stripped_line[1:]
    if stripped_line.endswith("|"):
        stripped_line = stripped_line[:-1]
    return [cell.strip() for cell in stripped_line.split("|")]


def _normalize_header(header: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(header or "").strip().casefold()).strip("_")
    aliases = {
        "action": "training_type",
        "mohs_min": "typical_mohs_min",
        "mohs_max": "typical_mohs_max",
        "confidence": "benchmark_confidence",
    }
    return aliases.get(normalized, normalized)


def _parse_tsv_payload(raw_text: str) -> list[dict[str, Any]] | None:
    if "\t" not in raw_text:
        return None
    return _parse_delimited_payload(raw_text, delimiter="\t")


def _parse_csv_payload(raw_text: str) -> list[dict[str, Any]] | None:
    first_line = next((line for line in raw_text.splitlines() if line.strip()), "")
    if "," not in first_line:
        return None
    return _parse_delimited_payload(raw_text, delimiter=",")


def _parse_delimited_payload(raw_text: str, *, delimiter: str) -> list[dict[str, Any]] | None:
    reader = csv.DictReader(io.StringIO(raw_text), delimiter=delimiter)
    if not reader.fieldnames:
        return None
    normalized_fieldnames = [_normalize_header(field_name) for field_name in reader.fieldnames]
    if "row_key" not in normalized_fieldnames and "area" not in normalized_fieldnames:
        return None
    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        row: dict[str, Any] = {}
        for field_name, value in raw_row.items():
            normalized_field_name = _normalize_header(field_name)
            if normalized_field_name:
                row[normalized_field_name] = value
        if any(_clean_text(value) for value in row.values()):
            rows.append(row)
    return rows


def _rows_from_payload(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(payload, dict):
        schema_version = str(payload.get("schema_version") or "")
        rows = payload.get("rows")
    elif isinstance(payload, list):
        rows = payload
        schema_version = str(
            rows[0].get("schema_version") or SCHEMA_VERSION
            if rows and isinstance(rows[0], dict)
            else SCHEMA_VERSION,
        )
    else:
        rows = None
        schema_version = ""
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        msg = "Benchmark response must contain a rows array."
        raise BenchmarkImportValidationError(msg)
    return schema_version or SCHEMA_VERSION, rows


def _looks_like_source_export_rows(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    source_fields = {"completed", "total", "remaining", "coverage_percent"}
    benchmark_fields = {"syllabus_core", "concept_load", "recognition_burden"}
    source_like_count = 0
    benchmark_like_count = 0
    for row in rows:
        row_fields = set(row)
        if source_fields & row_fields:
            source_like_count += 1
        if benchmark_fields & row_fields:
            benchmark_like_count += 1
    return source_like_count > 0 and benchmark_like_count == 0


def _import_row_key(raw_row: dict[str, Any], *, inference_row_keys: set[str]) -> tuple[str, list[str]]:
    raw_row_key = _clean_text(raw_row.get("row_key"))
    if ":" in raw_row_key:
        return _normalize_row_key(raw_row_key), []

    label = raw_row_key or _clean_text(raw_row.get("area")) or _clean_text(raw_row.get("normalized_label"))
    label_key = normalize_benchmark_key(label)
    if not label_key:
        return "", ["row_key or area is required."]

    kind = _benchmark_kind_from_import_context(raw_row)
    if not kind:
        kind = _benchmark_kind_from_known_rows(label_key, inference_row_keys)
    if not kind:
        kind = _benchmark_kind_from_existing_rows(label_key)
    if not kind:
        kind = _benchmark_kind_from_title_label_row(raw_row)
    if not kind:
        return "", [
            "Bare row_key values require Practice URL, Type, a current gap-row match, "
            "an existing unique benchmark match, or a title-label canonical subtopic row.",
        ]
    return build_benchmark_row_key(kind, label_key), []


def _benchmark_kind_from_import_context(raw_row: dict[str, Any]) -> str:
    practice_url = _clean_text(raw_row.get("practice_url"))
    if practice_url:
        query = parse_qs(urlparse(practice_url).query)
        layer_kind = str((query.get("layer_kind") or [""])[0]).strip().casefold()
        if layer_kind in LAYER_KIND_TO_BENCHMARK_KIND:
            return str(LAYER_KIND_TO_BENCHMARK_KIND[layer_kind])

    raw_type = _clean_text(raw_row.get("type")).casefold()
    if raw_type in TYPE_TO_BENCHMARK_KIND:
        return str(TYPE_TO_BENCHMARK_KIND[raw_type])
    normalized_type = re.sub(r"[^a-z0-9]+", " ", raw_type).strip()
    return str(TYPE_TO_BENCHMARK_KIND.get(normalized_type, ""))


def _benchmark_kind_from_known_rows(label_key: str, normalized_known_keys: set[str]) -> str:
    matches = {
        kind
        for row_key in normalized_known_keys
        for kind, known_label_key in [parse_benchmark_row_key(row_key)]
        if known_label_key == label_key
    }
    return matches.pop() if len(matches) == 1 else ""


def _benchmark_kind_from_existing_rows(label_key: str) -> str:
    matches = set(TechniqueBenchmark.objects.filter(label_key=label_key).values_list("kind", flat=True))
    matches.update(
        TechniqueBenchmarkAlias.objects.filter(alias_key=label_key).values_list("kind", flat=True),
    )
    return matches.pop() if len(matches) == 1 else ""


def _benchmark_kind_from_title_label_row(raw_row: dict[str, Any]) -> str:
    raw_row_key = _clean_text(raw_row.get("row_key"))
    normalized_label = (
        _clean_text(raw_row.get("normalized_label"))
        or _clean_text(raw_row.get("area"))
        or raw_row_key
    )
    raw_row_key_label_key = normalize_benchmark_key(raw_row_key)
    normalized_label_key = normalize_benchmark_key(normalized_label)
    if raw_row_key_label_key and raw_row_key_label_key == normalized_label_key:
        return str(TechniqueBenchmark.Kind.CANONICAL_SUBTOPIC)
    return ""


def _primary_area_from_topic(value: Any) -> str:
    topic = _clean_text(value)
    if not topic:
        return ""
    topic_parts = [part.strip() for part in topic.split(",") if part.strip()]
    return topic_parts[0] if len(topic_parts) == 1 else "Mixed"


def _mohs_bounds_from_import_row(raw_row: dict[str, Any]) -> tuple[int | None, int | None]:
    mohs_min = _coerce_optional_int(raw_row.get("typical_mohs_min"))
    mohs_max = _coerce_optional_int(raw_row.get("typical_mohs_max"))
    if mohs_min is not None or mohs_max is not None:
        return mohs_min, mohs_max

    raw_band = _clean_text(raw_row.get("mohs_band"))
    match = re.search(r"(?P<min>\d+)\s*M?\s*-\s*(?P<max>\d+)\s*M?", raw_band, flags=re.IGNORECASE)
    if match is None:
        return None, None
    return int(match.group("min")), int(match.group("max"))


def _alias_suggestions_from_import_row(raw_row: dict[str, Any], *, label_key: str) -> list[str]:
    raw_values: list[Any] = []
    alias_suggestions = raw_row.get("alias_suggestions")
    if isinstance(alias_suggestions, list):
        raw_values.extend(alias_suggestions)
    elif alias_suggestions:
        raw_values.extend(_split_alias_suggestions(alias_suggestions))

    for field_name, value in raw_row.items():
        if _normalize_header(field_name).startswith("alias_suggestions_"):
            raw_values.append(value)

    aliases: list[str] = []
    seen_alias_keys = {label_key}
    for raw_value in raw_values:
        alias_label = _clean_text(raw_value)
        alias_key = normalize_benchmark_key(alias_label)
        if not alias_label or not alias_key or alias_key in seen_alias_keys:
            continue
        aliases.append(alias_label)
        seen_alias_keys.add(alias_key)
    return aliases


def _split_alias_suggestions(value: Any) -> list[str]:
    raw_value = str(value)
    delimiter = ";" if ";" in raw_value else ","
    return raw_value.split(delimiter)


def _validate_raw_row(  # noqa: C901, PLR0912, PLR0915
    raw_row: dict[str, Any],
    *,
    index: int,
    inference_row_keys: set[str],
    expected_row_keys: set[str],
    seen_row_keys: set[str],
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    row_key, row_key_errors = _import_row_key(raw_row, inference_row_keys=inference_row_keys)
    errors.extend(row_key_errors)
    kind, label_key = parse_benchmark_row_key(row_key)
    if not row_key or not kind or not label_key:
        errors.append("row_key is required.")
    elif expected_row_keys and row_key not in expected_row_keys:
        errors.append(f"Unknown row_key: {row_key}.")
    elif row_key in seen_row_keys:
        errors.append(f"Duplicate row_key: {row_key}.")
    else:
        seen_row_keys.add(row_key)

    normalized_label = _clean_text(raw_row.get("normalized_label")) or _clean_text(raw_row.get("area"))
    raw_row_key = _clean_text(raw_row.get("row_key"))
    if not normalized_label and kind == TechniqueBenchmark.Kind.CANONICAL_SUBTOPIC and ":" not in raw_row_key:
        normalized_label = raw_row_key
    primary_area = _clean_text(raw_row.get("primary_area")) or _primary_area_from_topic(raw_row.get("topic"))
    typical_mohs_min, typical_mohs_max = _mohs_bounds_from_import_row(raw_row)
    normalized_row: dict[str, Any] = {
        "row_key": row_key,
        "kind": kind,
        "label_key": label_key,
        "normalized_label": normalized_label,
        "parent_family": _clean_text(raw_row.get("parent_family")),
        "primary_area": primary_area,
        "source_version": SCHEMA_VERSION,
    }
    if not normalized_row["normalized_label"]:
        errors.append("normalized_label is required.")
    if not normalized_row["parent_family"]:
        errors.append("parent_family is required.")
    for field_name, max_chars in MODEL_TEXT_LIMIT_FIELDS.items():
        if len(str(normalized_row.get(field_name) or "")) > max_chars:
            errors.append(f"{field_name} must be {max_chars} characters or fewer.")

    for field_name in SCORE_FIELDS:
        normalized_row[field_name] = _coerce_int(raw_row.get(field_name))
        if normalized_row[field_name] is None or not SCORE_MIN <= normalized_row[field_name] <= SCORE_MAX:
            errors.append(f"{field_name} must be between {SCORE_MIN} and {SCORE_MAX}.")

    normalized_row["typical_mohs_min"] = typical_mohs_min
    normalized_row["typical_mohs_max"] = typical_mohs_max
    for field_name in ("typical_mohs_min", "typical_mohs_max"):
        value = normalized_row[field_name]
        if value is not None and not MOHS_MIN <= value <= MOHS_MAX:
            errors.append(f"{field_name} must be between {MOHS_MIN} and {MOHS_MAX}.")
    if (
        normalized_row["typical_mohs_min"] is not None
        and normalized_row["typical_mohs_max"] is not None
        and normalized_row["typical_mohs_min"] > normalized_row["typical_mohs_max"]
    ):
        errors.append("typical_mohs_min cannot exceed typical_mohs_max.")

    for field_name in WEIGHT_FIELDS:
        normalized_row[field_name] = _coerce_decimal(raw_row.get(field_name), default=Decimal("1.00"))
        if normalized_row[field_name] <= 0 or normalized_row[field_name] > MAX_PROFILE_WEIGHT:
            errors.append(f"{field_name} must be greater than 0 and at most {MAX_PROFILE_WEIGHT}.")

    normalized_row["training_type"] = _clean_text(raw_row.get("training_type"))
    if normalized_row["training_type"] not in TRAINING_TYPES:
        errors.append("training_type is invalid.")
    normalized_row["target_level"] = _clean_text(raw_row.get("target_level"))
    if normalized_row["target_level"] not in TARGET_LEVELS:
        errors.append("target_level is invalid.")
    normalized_row["benchmark_confidence"] = _coerce_optional_int(raw_row.get("benchmark_confidence"))
    if (
        normalized_row["benchmark_confidence"] is not None
        and not CONFIDENCE_MIN <= normalized_row["benchmark_confidence"] <= CONFIDENCE_MAX
    ):
        errors.append(f"benchmark_confidence must be between {CONFIDENCE_MIN} and {CONFIDENCE_MAX}.")

    for field_name in TEXT_LIMIT_FIELDS:
        value = _clean_text(raw_row.get(field_name))
        normalized_row[field_name] = value
        if len(value) > MAX_LONG_TEXT_CHARS:
            errors.append(f"{field_name} must be {MAX_LONG_TEXT_CHARS} characters or fewer.")
    if not normalized_row["rationale"]:
        errors.append("rationale is required.")

    area_labels = raw_row.get("area_labels")
    normalized_row["area_labels"] = area_labels if isinstance(area_labels, list) else []
    normalized_row["alias_suggestions"] = _alias_suggestions_from_import_row(raw_row, label_key=label_key)
    for alias_label in normalized_row["alias_suggestions"]:
        alias_key = normalize_benchmark_key(alias_label)
        if len(alias_label) > MAX_BENCHMARK_TEXT_CHARS or len(alias_key) > MAX_BENCHMARK_TEXT_CHARS:
            errors.append(f"alias_suggestions entries must be {MAX_BENCHMARK_TEXT_CHARS} characters or fewer.")
            break
    normalized_row["index"] = index
    return normalized_row, errors


def _snapshot_from_import_row(
    row: dict[str, Any],
    *,
    existing_benchmark: TechniqueBenchmark | None,
) -> dict[str, Any]:
    benchmark = TechniqueBenchmark(
        kind=row["kind"],
        label_key=row["label_key"],
        label=(existing_benchmark.label if existing_benchmark is not None else row["normalized_label"]),
        normalized_label=row["normalized_label"],
        parent_family=row["parent_family"],
        primary_area=row["primary_area"],
        area_labels=row["area_labels"],
        syllabus_core=row["syllabus_core"],
        contest_frequency=row["contest_frequency"],
        transfer_value=row["transfer_value"],
        prerequisite_value=row["prerequisite_value"],
        concept_load=row["concept_load"],
        recognition_burden=row["recognition_burden"],
        execution_load=row["execution_load"],
        proof_fragility=row["proof_fragility"],
        cross_topic_dependency=row["cross_topic_dependency"],
        typical_mohs_min=row["typical_mohs_min"],
        typical_mohs_max=row["typical_mohs_max"],
        jbmo_weight=row["jbmo_weight"],
        national_weight=row["national_weight"],
        imo_tst_weight=row["imo_tst_weight"],
        training_type=row["training_type"],
        target_level=row["target_level"],
        benchmark_confidence=row["benchmark_confidence"],
        quality_flags=list(getattr(existing_benchmark, "quality_flags", []) or []),
        rationale=row["rationale"],
        pitfalls=row["pitfalls"],
        recommended_sequence=row["recommended_sequence"],
        source_version=SCHEMA_VERSION,
    )
    benchmark.importance_score = calculate_static_importance_score(benchmark)
    benchmark.difficulty_score = calculate_static_difficulty_score(benchmark)
    if benchmark.typical_mohs_min is not None and benchmark.typical_mohs_max is not None:
        benchmark.typical_mohs_center = Decimal(benchmark.typical_mohs_min + benchmark.typical_mohs_max) / Decimal("2")
    return snapshot_benchmark(benchmark) or {}


def _preview_status(
    old_snapshot: dict[str, Any] | None,
    new_snapshot: dict[str, Any],
) -> str:
    if old_snapshot is None:
        return "new"
    return "unchanged" if old_snapshot == new_snapshot else "changed"


def _preview_details(
    old_snapshot: dict[str, Any] | None,
    new_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return {
        "primary_area": new_snapshot.get("primary_area") or "",
        "target_level": new_snapshot.get("target_level") or "",
        "training_type": new_snapshot.get("training_type") or "",
        "benchmark_confidence": new_snapshot.get("benchmark_confidence"),
        "typical_mohs_band": _mohs_band(new_snapshot),
        "importance_score": _decimal_display(new_snapshot.get("importance_score")),
        "difficulty_score": _decimal_display(new_snapshot.get("difficulty_score")),
        "importance_inputs": (
            f"Syllabus {new_snapshot.get('syllabus_core')} · "
            f"Frequency {new_snapshot.get('contest_frequency')} · "
            f"Transfer {new_snapshot.get('transfer_value')} · "
            f"Prerequisite {new_snapshot.get('prerequisite_value')}"
        ),
        "difficulty_inputs": (
            f"Concept {new_snapshot.get('concept_load')} · "
            f"Recognition {new_snapshot.get('recognition_burden')} · "
            f"Execution {new_snapshot.get('execution_load')} · "
            f"Fragility {new_snapshot.get('proof_fragility')} · "
            f"Dependency {new_snapshot.get('cross_topic_dependency')}"
        ),
        "profile_weights": (
            f"JBMO {_decimal_display(new_snapshot.get('jbmo_weight'))} · "
            f"National {_decimal_display(new_snapshot.get('national_weight'))} · "
            f"IMO/TST {_decimal_display(new_snapshot.get('imo_tst_weight'))}"
        ),
        "rationale": new_snapshot.get("rationale") or "",
        "pitfalls": new_snapshot.get("pitfalls") or "",
        "recommended_sequence": new_snapshot.get("recommended_sequence") or "",
        "changed_fields": _changed_field_labels(old_snapshot, new_snapshot),
    }


def _mohs_band(snapshot: dict[str, Any]) -> str:
    mohs_min = snapshot.get("typical_mohs_min")
    mohs_max = snapshot.get("typical_mohs_max")
    if mohs_min is None or mohs_max is None:
        return ""
    return f"{mohs_min}M-{mohs_max}M"


def _decimal_display(value: object) -> str:
    if value is None:
        return ""
    return f"{Decimal(str(value)):.2f}"


def _changed_field_labels(
    old_snapshot: dict[str, Any] | None,
    new_snapshot: dict[str, Any],
) -> list[str]:
    if old_snapshot is None:
        return []
    changed_fields = []
    for field_name, label in PREVIEW_CHANGED_FIELD_LABELS.items():
        if old_snapshot.get(field_name) != new_snapshot.get(field_name):
            changed_fields.append(label)
    return changed_fields


def _apply_snapshot_to_benchmark(benchmark: TechniqueBenchmark, snapshot: dict[str, Any]) -> None:
    benchmark.kind = snapshot["kind"]
    benchmark.label_key = snapshot["label_key"]
    for field_name in MODEL_UPDATE_FIELDS:
        value = snapshot.get(field_name)
        if field_name in {
            "difficulty_score",
            "importance_score",
            "typical_mohs_center",
            *WEIGHT_FIELDS,
        } and value is not None:
            value = Decimal(str(value))
        setattr(benchmark, field_name, value)


def _inference_row_keys(
    *,
    known_row_keys: set[str] | None,
    export_batch: TechniqueBenchmarkExportBatch | None,
) -> set[str]:
    if export_batch is not None:
        return _normalized_row_key_set(export_batch.frozen_row_keys)
    if known_row_keys is not None:
        return _normalized_row_key_set(known_row_keys)
    return set()


def _expected_row_keys(
    *,
    export_batch: TechniqueBenchmarkExportBatch | None,
) -> set[str]:
    if export_batch is not None:
        return _normalized_row_key_set(export_batch.frozen_row_keys)
    return set()


def _normalized_row_key_set(row_keys: object) -> set[str]:
    return {
        normalized_row_key
        for row_key in row_keys or []
        for normalized_row_key in [_normalize_row_key(row_key)]
        if normalized_row_key
    }


def _quality_flags_with(raw_flags: object, flag: str) -> list[str]:
    flags = [str(value) for value in raw_flags or [] if str(value or "").strip()]
    if flag not in flags:
        flags.append(flag)
    return flags


def _known_row_keys_from_database() -> set[str]:
    benchmark_keys = {
        build_benchmark_row_key(benchmark.kind, benchmark.label_key)
        for benchmark in TechniqueBenchmark.objects.only("kind", "label_key")
    }
    alias_keys = {
        build_benchmark_row_key(alias.kind, alias.alias_key)
        for alias in TechniqueBenchmarkAlias.objects.only("kind", "alias_key")
    }
    return benchmark_keys | alias_keys


def _normalize_row_key(row_key: str) -> str:
    kind, label_key = parse_benchmark_row_key(row_key)
    return build_benchmark_row_key(kind, label_key) if kind and label_key else ""


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return _coerce_int(value)


def _coerce_decimal(value: Any, *, default: Decimal) -> Decimal:
    if value in (None, ""):
        return default
    return Decimal(str(value))
