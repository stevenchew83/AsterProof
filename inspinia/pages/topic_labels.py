"""Display helpers for normalized topic labels."""

from __future__ import annotations

FULL_TOPIC_LABEL_MAP = {
    "A": "Algebra",
    "ALG": "Algebra",
    "ALGEBRA": "Algebra",
    "C": "Combinatorics",
    "COMB": "Combinatorics",
    "COMBINATORICS": "Combinatorics",
    "G": "Geometry",
    "GEO": "Geometry",
    "GEOMETRY": "Geometry",
    "N": "Number Theory",
    "NT": "Number Theory",
    "NUMBER THEORY": "Number Theory",
    "NUMBER_THEORY": "Number Theory",
    "NUMBER-THEORY": "Number Theory",
}


def display_topic_label(topic: str | None) -> str:
    normalized = (topic or "").strip()
    if not normalized:
        return ""
    return FULL_TOPIC_LABEL_MAP.get(normalized.upper(), normalized)
