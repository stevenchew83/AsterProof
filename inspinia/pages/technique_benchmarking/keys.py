from __future__ import annotations

import re
import unicodedata

BENCHMARK_KIND_CANONICAL_SUBTOPIC = "canonical_subtopic"
BENCHMARK_KIND_TECHNIQUE = "technique"
BENCHMARK_KIND_OBJECT = "object"
BENCHMARK_KIND_METHOD = "method"
BENCHMARK_KIND_LEMMA = "lemma"
BENCHMARK_KIND_PROOF_ROLE = "proof_role"
BENCHMARK_KIND_PARENT_FAMILY = "parent_family"

GAP_LAYER_KIND_TO_BENCHMARK_KIND = {
    "subtopics": BENCHMARK_KIND_CANONICAL_SUBTOPIC,
    "techniques": BENCHMARK_KIND_TECHNIQUE,
    "objects": BENCHMARK_KIND_OBJECT,
    "methods": BENCHMARK_KIND_METHOD,
    "lemmas": BENCHMARK_KIND_LEMMA,
    "proof_roles": BENCHMARK_KIND_PROOF_ROLE,
}

GAP_TYPE_TO_BENCHMARK_KIND = {
    "subtopic": BENCHMARK_KIND_CANONICAL_SUBTOPIC,
    "technique": BENCHMARK_KIND_TECHNIQUE,
    "object": BENCHMARK_KIND_OBJECT,
    "lemma/theorem": BENCHMARK_KIND_LEMMA,
    "proof role": BENCHMARK_KIND_PROOF_ROLE,
}


def normalize_benchmark_key(label: str) -> str:
    value = unicodedata.normalize("NFKC", str(label or "").strip().lower())
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")


def benchmark_kind_for_gap_row(row: dict[str, object]) -> str:
    layer_kind = str(row.get("layer_kind") or "").strip().casefold()
    if layer_kind in GAP_LAYER_KIND_TO_BENCHMARK_KIND:
        return GAP_LAYER_KIND_TO_BENCHMARK_KIND[layer_kind]

    row_type = str(row.get("type") or "").strip().casefold()
    if row_type == "technique" and str(row.get("canonical_subtopic") or "").strip():
        return BENCHMARK_KIND_METHOD if layer_kind == "methods" else BENCHMARK_KIND_TECHNIQUE
    return GAP_TYPE_TO_BENCHMARK_KIND.get(row_type, BENCHMARK_KIND_CANONICAL_SUBTOPIC)


def benchmark_label_key_for_gap_row(row: dict[str, object]) -> str:
    return normalize_benchmark_key(str(row.get("label") or ""))


def benchmark_row_key(row: dict[str, object]) -> str:
    return build_benchmark_row_key(
        benchmark_kind_for_gap_row(row),
        benchmark_label_key_for_gap_row(row),
    )


def build_benchmark_row_key(kind: str, label_key: str) -> str:
    return f"{kind}:{normalize_benchmark_key(label_key)}"


def parse_benchmark_row_key(row_key: str) -> tuple[str, str]:
    raw_key = str(row_key or "").strip()
    if ":" not in raw_key:
        return "", ""
    kind, label_key = raw_key.split(":", 1)
    return kind.strip(), normalize_benchmark_key(label_key)
