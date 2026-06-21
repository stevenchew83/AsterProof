"""Parse Excel \"Topic tags\" cells into technique tokens with domain lists."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pandas as pd

# En dash or hyphen surrounded by spaces (domain vs technique).
DASH_RE = re.compile(r"\s[\u2013-]\s")

# One cell may contain several blocks, each starting with \"Topic tags:\".
TOPIC_BLOCK_RE = re.compile(
    r"(?:^|\n)\s*Topic tags:\s*(.*?)(?=(?:\n\s*Topic tags:)|\Z)",
    flags=re.DOTALL,
)

# If a cell accidentally includes trailing columns as text, stop here.
TRUNCATE_RE = re.compile(r"\b(?:Core ideas|Rationale|Common pitfalls)\b", flags=re.IGNORECASE)

TOPIC_TAG_TEXT_REPAIRS: tuple[tuple[str, str], ...] = (
    ("\u221a\xf1", "\u00f6"),
    ("\u221a\xd1", "\u00d6"),
    ("\u221a\xe2", "\u00e9"),
    ("\u221a\xfa", "u"),
    ("\u221a\xf2", "\u00f3"),
    ("\u221a\u00c5", "A"),
    ("\u201a\xc4\xf4", "'"),
    ("\u201a\xc4\xf2", "'"),
    ("\u201a\xc4\xec", "-"),
    ("\u201a\xc4\xee", "-"),
    ("\u201a\xc4\u2039", ""),
    ("\u201a\xc4\xfa", '"'),
    ("\u201a\xc4\xf9", '"'),
    ("\u201a\xdc\xed", "->"),
    ("\u201a\xdc\x92", "->"),
    ("\u201a\xd1\xa4", "Z"),
    ("\u2248\u00ea", "O"),
    ("\u0152\u00b6", "PHI"),
    ("\u0152\u00a7", "TAU"),
    ("\u0152\u00a9", "OMEGA"),
    ("\u00ac\u221e", "\u00b0"),
    ("\u221a\xf32", "x2"),
    ("PPP", "P"),
    ("\u2014", "-"),
    ("\u2013", "-"),
)


TOPIC_TAG_WORD_REPAIRS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bHOLDER\b", flags=re.IGNORECASE), "H\u00d6LDER"),
    (re.compile(r"\bMOBIUS\b", flags=re.IGNORECASE), "M\u00d6BIUS"),
    (re.compile(r"\bORTHOCENTRE(S)?\b", flags=re.IGNORECASE), r"ORTHOCENTER\1"),
    (re.compile(r"\bCIRCUMCENTRE(S)?\b", flags=re.IGNORECASE), r"CIRCUMCENTER\1"),
    (re.compile(r"\bPARAMETERIZATION\b", flags=re.IGNORECASE), "PARAMETRIZATION"),
    (re.compile(r"\bCONCURRENCE\b", flags=re.IGNORECASE), "CONCURRENCY"),
    (re.compile(r"\bERD[O\u00d3]S\b", flags=re.IGNORECASE), "ERDOS"),
    (re.compile(r"\bTURAN\b", flags=re.IGNORECASE), "TURAN"),
    (re.compile(r"\bK[\u00d6O]NIG\b", flags=re.IGNORECASE), "KONIG"),
    (re.compile(r"\bBOLLOBAS\b", flags=re.IGNORECASE), "BOLLOBAS"),
    (re.compile(r"\bSZEMER[\u00c9E]DI\b", flags=re.IGNORECASE), "SZEMEREDI"),
    (
        re.compile(r"F2\\MATHBB\s+F_2F2\s*", flags=re.IGNORECASE),
        "F2 / F_2 ",
    ),
)


def clean_token(s: str) -> str:
    s = (s or "").strip()
    return re.sub(r"\s+", " ", s)


def repair_topic_tag_text(s: str | None) -> str:
    repaired = clean_token(s or "")
    for old, new in TOPIC_TAG_TEXT_REPAIRS:
        repaired = repaired.replace(old, new)
    for pattern, replacement in TOPIC_TAG_WORD_REPAIRS:
        repaired = pattern.sub(replacement, repaired)
    return clean_token(repaired)


def normalize_topic_tag(s: str | None) -> str:
    return clean_token(s or "").upper()


def _merge_parsed_topic_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_technique: dict[str, dict[str, Any]] = {}
    for entry in entries:
        technique = normalize_topic_tag(entry.get("technique"))
        if not technique:
            continue

        key = technique.casefold()
        domains = domains_dedup_preserve_order(entry.get("domains") or [])
        raw_tag = clean_token(entry.get("raw_tag") or entry.get("technique"))
        if key in by_technique:
            by_technique[key]["domains"] = merge_domain_lists(
                by_technique[key]["domains"],
                domains,
            )
            continue

        by_technique[key] = {"technique": technique, "domains": domains, "raw_tag": raw_tag}
    return list(by_technique.values())


def _multiline_topic_tag_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= 1:
        return []
    if normalize_topic_tag(lines[0]) in {"SUBTOPIC", "SUBTOPICS"}:
        lines = lines[1:]
    return lines


def _parse_topic_tag_text(text: str) -> list[dict[str, Any]]:
    lines = _multiline_topic_tag_lines(text)
    if not lines:
        return _merge_parsed_topic_entries(parse_topic_tags_value(text))

    entries: list[dict[str, Any]] = []
    for line in lines:
        entries.extend(parse_topic_tags_value(line))
    return _merge_parsed_topic_entries(entries)


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
        raw_tag = clean_token(s)
        t = normalize_topic_tag(repair_topic_tag_text(raw_tag))
        return [{"technique": t, "domains": [], "raw_tag": raw_tag}] if t else []

    domain_str = s[: m.start()].strip()
    rest = s[m.end() :].strip()

    initial_domains = domains_dedup_preserve_order(domain_str.split("/"))

    segments = [seg.strip() for seg in rest.split(";") if seg.strip()]
    out: list[dict[str, Any]] = []

    for seg in segments:
        m2 = DASH_RE.search(seg)
        if m2:
            seg_domain_str = seg[: m2.start()].strip()
            tech_str = seg[m2.end() :].strip()
            seg_domains = domains_dedup_preserve_order(seg_domain_str.split("/"))
        else:
            seg_domains = initial_domains
            tech_str = seg

        for raw_token in [clean_token(t) for t in tech_str.split(",")]:
            technique = normalize_topic_tag(repair_topic_tag_text(raw_token))
            if technique:
                out.append({"technique": technique, "domains": seg_domains, "raw_tag": raw_token})

    return out


def parse_topic_tags_cell(cell_text: Any) -> list[dict[str, Any]]:
    """Parse a full Excel cell value (may include multiple `Topic tags:` lines)."""
    if cell_text is None or (isinstance(cell_text, float) and pd.isna(cell_text)):
        return []

    text = str(cell_text)

    matches = list(TOPIC_BLOCK_RE.finditer(text))
    if not matches:
        text2 = TRUNCATE_RE.split(text, maxsplit=1)[0].strip()
        return _parse_topic_tag_text(text2)

    out: list[dict[str, Any]] = []
    for mm in matches:
        block = mm.group(1).strip()
        block = TRUNCATE_RE.split(block, maxsplit=1)[0].strip()
        out.extend(_parse_topic_tag_text(block))
    return _merge_parsed_topic_entries(out)


def domains_dedup_preserve_order(domains: list[str] | None) -> list[str]:
    if not domains:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for domain in domains:
        normalized_domain = normalize_topic_tag(domain)
        if not normalized_domain or normalized_domain in seen:
            continue
        seen.add(normalized_domain)
        out.append(normalized_domain)
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
