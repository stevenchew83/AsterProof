from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypedDict


class HandleSummaryParseValidationError(ValueError):
    """Raised when pasted handle-summary text cannot be parsed reliably."""


@dataclass(frozen=True)
class ParsedHandleSummaryRow:
    handle: str
    mohs: int
    confidence: str
    imo_slot: str
    topic_tags: str
    core_ideas: str
    rationale: str
    common_pitfalls: str


class HandleSummaryPreviewRow(TypedDict):
    handle: str
    mohs: int
    confidence: str
    imo_slot: str
    topic_tags: str
    core_ideas: str
    rationale: str
    common_pitfalls: str


class HandleSummaryPreviewPayload(TypedDict):
    export_tsv: str
    row_count: int
    rows: list[HandleSummaryPreviewRow]


FIELD_PATTERNS = (
    (re.compile(r"^Confidence\s*:\s*(?P<value>.*)$", flags=re.IGNORECASE), "confidence"),
    (re.compile(r"^Estimated\s+MOHS\s*:\s*(?P<value>.*)$", flags=re.IGNORECASE), "mohs"),
    (re.compile(r"^IMO\s+slot\s+guess\s*:\s*(?P<value>.*)$", flags=re.IGNORECASE), "imo_slot"),
    (re.compile(r"^Topic\s+tags\s*:\s*(?P<value>.*)$", flags=re.IGNORECASE), "topic_tags"),
    (re.compile(r"^Core\s+ideas\s*:\s*(?P<value>.*)$", flags=re.IGNORECASE), "core_ideas"),
    (
        re.compile(
            r"^Rationale(?:\s*\(\s*\d+\s*[-\u2013\u2014\u2212]\s*\d+\s*lines?\s*\))?\s*:\s*(?P<value>.*)$",
            flags=re.IGNORECASE,
        ),
        "rationale",
    ),
    (
        re.compile(r"^Common\s+pitfalls\s*:\s*(?P<value>.*)$", flags=re.IGNORECASE),
        "common_pitfalls",
    ),
)
MULTILINE_FIELDS = frozenset({"core_ideas", "rationale", "common_pitfalls"})
MOHS_RE = re.compile(
    r"^(?P<lower>\d+)(?:\s*M)?(?P<plus>\+)?"
    r"(?:(?:\s*[-\u2013]\s*|\s+to\s+)(?P<upper>\d+)(?:\s*M)?)?$",
    flags=re.IGNORECASE,
)
ANNOTATED_MOHS_RE = re.compile(r"\b(?P<value>\d+)\s*M\b", flags=re.IGNORECASE)
HANDLE_LINE_PREFIX = "Handle:"


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _normalize_multiline_text(value: str) -> str:
    return "\n".join(line.strip() for line in value.strip().splitlines() if line.strip())


def _export_text(value: str) -> str:
    return _normalize_text(value)


def _parse_mohs_value(raw_value: str, *, handle: str) -> int:
    normalized_value = _normalize_text(raw_value)
    match = MOHS_RE.fullmatch(normalized_value)
    if match is None:
        annotated_match = ANNOTATED_MOHS_RE.search(normalized_value)
        if annotated_match is not None:
            return int(annotated_match.group("value"))

        msg = f'Handle "{handle}" has an invalid Estimated MOHS value: "{raw_value.strip()}".'
        raise HandleSummaryParseValidationError(msg)

    lower_bound = int(match.group("lower"))
    upper_bound = match.group("upper")
    if match.group("plus") is not None:
        if upper_bound is not None:
            msg = (
                f'Handle "{handle}" has an invalid Estimated MOHS value: '
                f'"{raw_value.strip()}".'
            )
            raise HandleSummaryParseValidationError(msg)
        return lower_bound

    if upper_bound is None:
        return lower_bound

    upper_bound_value = int(upper_bound)
    if upper_bound_value < lower_bound:
        msg = (
            f'Handle "{handle}" has a reversed Estimated MOHS range: '
            f'"{raw_value.strip()}".'
        )
        raise HandleSummaryParseValidationError(msg)
    return lower_bound


def _build_row_from_block(block: dict[str, str]) -> ParsedHandleSummaryRow:
    handle = block.get("handle", "").strip()
    if not handle:
        msg = "A Handle block is missing its title."
        raise HandleSummaryParseValidationError(msg)

    missing_fields = [
        label
        for label, field_name in (
            ("Estimated MOHS", "mohs"),
            ("Confidence", "confidence"),
            ("IMO slot guess", "imo_slot"),
            ("Topic tags", "topic_tags"),
        )
        if not _normalize_text(block.get(field_name, ""))
    ]
    if missing_fields:
        msg = f'Handle "{handle}" is missing: {", ".join(missing_fields)}.'
        raise HandleSummaryParseValidationError(msg)

    return ParsedHandleSummaryRow(
        handle=handle,
        mohs=_parse_mohs_value(block["mohs"], handle=handle),
        confidence=_normalize_text(block["confidence"]),
        imo_slot=_normalize_text(block["imo_slot"]),
        topic_tags=_normalize_text(block["topic_tags"]),
        core_ideas=_normalize_multiline_text(block.get("core_ideas", "")),
        rationale=_normalize_multiline_text(block.get("rationale", "")),
        common_pitfalls=_normalize_multiline_text(block.get("common_pitfalls", "")),
    )


def _parse_handle_line(line: str) -> dict[str, str] | None:
    if not line.startswith(HANDLE_LINE_PREFIX):
        return None

    handle = line.partition(":")[2].strip()
    if not handle:
        msg = "Every Handle line needs a title after the colon."
        raise HandleSummaryParseValidationError(msg)
    return {"handle": handle}


def _extract_field_update(line: str) -> tuple[str, str] | None:
    for pattern, field_name in FIELD_PATTERNS:
        match = pattern.match(line)
        if match is not None:
            return field_name, match.group("value").strip()
    return None


def _append_multiline_field_value(
    current_block: dict[str, str],
    field_name: str,
    line: str,
) -> None:
    previous_value = current_block.get(field_name, "")
    current_block[field_name] = f"{previous_value}\n{line.strip()}".strip()


def _flush_handle_summary_block(
    rows: list[ParsedHandleSummaryRow],
    current_block: dict[str, str],
) -> dict[str, str]:
    if current_block:
        rows.append(_build_row_from_block(current_block))
    return {}


def parse_handle_summary_text(raw_text: str) -> tuple[ParsedHandleSummaryRow, ...]:
    if not raw_text.strip():
        msg = "Paste at least one Handle block."
        raise HandleSummaryParseValidationError(msg)

    rows: list[ParsedHandleSummaryRow] = []
    current_block: dict[str, str] = {}
    current_multiline_field: str | None = None

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        handle_block = _parse_handle_line(line)
        if handle_block is not None:
            current_block = _flush_handle_summary_block(rows, current_block)
            current_block = handle_block
            current_multiline_field = None
            continue

        if not current_block:
            continue

        field_update = _extract_field_update(line)
        if field_update is not None:
            field_name, field_value = field_update
            current_block[field_name] = field_value
            current_multiline_field = field_name if field_name in MULTILINE_FIELDS else None
            continue

        if current_multiline_field is not None:
            _append_multiline_field_value(current_block, current_multiline_field, line)

    _flush_handle_summary_block(rows, current_block)

    if not rows:
        msg = 'No "Handle:" blocks were detected in the pasted text.'
        raise HandleSummaryParseValidationError(msg)

    return tuple(rows)


def build_handle_summary_preview_payload(
    rows: tuple[ParsedHandleSummaryRow, ...],
) -> HandleSummaryPreviewPayload:
    preview_rows: list[HandleSummaryPreviewRow] = [
        {
            "confidence": row.confidence,
            "handle": row.handle,
            "imo_slot": row.imo_slot,
            "mohs": row.mohs,
            "topic_tags": row.topic_tags,
            "core_ideas": row.core_ideas,
            "rationale": row.rationale,
            "common_pitfalls": row.common_pitfalls,
        }
        for row in rows
    ]
    export_lines = [
        "MOHS\tCONFIDENCE\tIMO SLOT\tTOPICS TAG\tCORE IDEAS\tRATIONALE\tCOMMON PITFALLS",
    ]
    export_lines.extend(
        "\t".join(
            [
                str(row.mohs),
                row.confidence,
                row.imo_slot,
                row.topic_tags,
                _export_text(row.core_ideas),
                _export_text(row.rationale),
                _export_text(row.common_pitfalls),
            ],
        )
        for row in rows
    )
    return {
        "export_tsv": "\n".join(export_lines),
        "row_count": len(preview_rows),
        "rows": preview_rows,
    }
