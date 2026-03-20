"""Parse Excel \"Topic tags\" cells into technique tokens with domain lists."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pandas as pd

# En-dash (–) or hyphen (-) surrounded by spaces (domain vs technique).
DASH_RE = re.compile(r"\s[–-]\s")

# One cell may contain several blocks, each starting with \"Topic tags:\".
TOPIC_BLOCK_RE = re.compile(
    r"(?:^|\n)\s*Topic tags:\s*(.*?)(?=(?:\n\s*Topic tags:)|\Z)",
    flags=re.DOTALL,
)

# If a cell accidentally includes trailing columns as text, stop here.
TRUNCATE_RE = re.compile(r"\b(?:Rationale|Common pitfalls)\b", flags=re.IGNORECASE)


def clean_token(s: str) -> str:
    s = (s or "").strip()
    return re.sub(r"\s+", " ", s)


def compute_problem_key(year: int, contest: str, problem: str) -> str:
    """Stable opaque key from YEAR + CONTEST + PROBLEM (for exports or non-Django stores)."""
    key_str = f"{year}|{clean_token(contest)}|{clean_token(problem)}"
    return hashlib.sha256(key_str.encode()).hexdigest()


def parse_topic_tags_value(block_text: str) -> list[dict[str, Any]]:
    """Parse one `Topic tags: ...` block into [{'technique': str, 'domains': [str, ...]}, ...]."""
    if not block_text:
        return []

    s = block_text.strip()
    s = re.sub(r"^\s*Topic tags:\s*", "", s)

    m = DASH_RE.search(s)
    if not m:
        t = clean_token(s)
        return [{"technique": t, "domains": []}] if t else []

    domain_str = s[: m.start()].strip()
    rest = s[m.end() :].strip()

    initial_domains = [d.strip() for d in domain_str.split("/") if d.strip()]

    segments = [seg.strip() for seg in rest.split(";") if seg.strip()]
    out: list[dict[str, Any]] = []

    for seg in segments:
        m2 = DASH_RE.search(seg)
        if m2:
            seg_domain_str = seg[: m2.start()].strip()
            tech_str = seg[m2.end() :].strip()
            seg_domains = [d.strip() for d in seg_domain_str.split("/") if d.strip()]
        else:
            seg_domains = initial_domains
            tech_str = seg

        techniques = [clean_token(t) for t in tech_str.split(",")]
        techniques = [t for t in techniques if t]

        for t in techniques:
            out.append({"technique": t, "domains": seg_domains})

    return out


def parse_topic_tags_cell(cell_text: Any) -> list[dict[str, Any]]:
    """Parse a full Excel cell value (may include multiple `Topic tags:` lines)."""
    if cell_text is None or (isinstance(cell_text, float) and pd.isna(cell_text)):
        return []

    text = str(cell_text)

    matches = list(TOPIC_BLOCK_RE.finditer(text))
    if not matches:
        text2 = TRUNCATE_RE.split(text, maxsplit=1)[0].strip()
        return parse_topic_tags_value(text2)

    out: list[dict[str, Any]] = []
    for mm in matches:
        block = mm.group(1).strip()
        block = TRUNCATE_RE.split(block, maxsplit=1)[0].strip()
        out.extend(parse_topic_tags_value(block))
    return out


def domains_dedup_preserve_order(domains: list[str] | None) -> list[str]:
    if not domains:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for d in domains:
        d = clean_token(d)
        if not d or d in seen:
            continue
        seen.add(d)
        out.append(d)
    return out


def parse_contest_problem_string(
    s: str,
    year_hint: int | None = None,
) -> tuple[int | None, str, str]:
    """
    Parse a combined field like `ISRAEL TST 2026 P2` -> (year, contest, problem).

    Assumes the problem token is the trailing `P<digits>`.
    """
    s = clean_token(s)
    if not s:
        return (None, "", "")

    m = re.search(r"\b(P\d+)\s*$", s)
    if not m:
        return (year_hint, s, "")

    problem = m.group(1).strip()
    before = s[: m.start()].strip()

    tokens = before.split()
    year: int | None = None
    contest = before

    if tokens and re.fullmatch(r"\d{4}", tokens[-1]):
        maybe_year = int(tokens[-1])
        if year_hint is None or maybe_year == year_hint:
            year = maybe_year
            contest = " ".join(tokens[:-1]).strip()
        else:
            year = year_hint
            contest = before
    else:
        year = year_hint
        contest = before

    return (year, contest, problem)


def merge_domain_lists(a: list[str], b: list[str]) -> list[str]:
    """Union with stable order: keep `a` order, append new items from `b`."""
    a2 = domains_dedup_preserve_order(a)
    seen = set(a2)
    out = list(a2)
    for d in domains_dedup_preserve_order(b):
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out
