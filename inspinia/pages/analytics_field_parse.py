"""Shared parsing for analytics text fields (IMO slot, rationale, pitfalls)."""

from __future__ import annotations

import re


def parse_imo_slot_guess_value(raw: str | None) -> str | None:
    """
    Parse many free-form "IMO slot guess" cell variants into candidate slot numbers.

    Output format:
    - NULL if no slot candidates found
    - Otherwise a comma-separated list of numbers extracted from (Problem, Slot) pairs.
    """
    if not raw:
        return None

    text = str(raw).strip()
    if not text or text in {"\u2014", "-", "\u2013"}:
        return None

    text = re.sub(r"[\u2013\u2014\u2212]", "-", text)

    extracted_numbers: list[int] = []

    pair_re = re.compile(r"\bP(?P<a>\d+)\s*/\s*(?:P)?(?P<b>\d+)\b")
    seen_pairs: set[tuple[int, int]] = set()
    for m in pair_re.finditer(text):
        problem = int(m.group("a"))
        slot = int(m.group("b"))
        pair = (problem, slot)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        extracted_numbers.extend([problem, slot])

    text_without_pairs = pair_re.sub("", text)
    standalone_re = re.compile(r"\bP(?P<slot>[1-9])\b")
    seen_standalone_slots: set[int] = set()
    for m in standalone_re.finditer(text_without_pairs):
        slot_only = int(m.group("slot"))
        if slot_only in seen_standalone_slots:
            continue
        seen_standalone_slots.add(slot_only)
        extracted_numbers.append(slot_only)

    if not extracted_numbers:
        return None

    return ",".join(str(n) for n in extracted_numbers)


def parse_rationale_value(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    normalized = re.sub(r"[\u2013\u2014\u2212]", "-", text)

    rationale_re = re.compile(
        r"^\s*Rationale(?:\s*\(\s*\d+\s*-\s*\d+\s*lines?\s*\))?\s*:\s*(?P<value>.+?)\s*$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = rationale_re.match(normalized)
    if m:
        return m.group("value").strip() or None

    return text


def parse_pitfalls_value(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    normalized = re.sub(r"[\u2013\u2014\u2212]", "-", text)
    pitfalls_re = re.compile(
        r"^\s*Common\s+pitfalls\s*:\s*(?P<value>.+?)\s*$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = pitfalls_re.match(normalized)
    if m:
        return m.group("value").strip() or None

    return text
