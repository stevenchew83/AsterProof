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


class HandleSummaryPreviewRow(TypedDict):
    handle: str
    mohs: int
    confidence: str
    imo_slot: str
    topic_tags: str


class HandleSummaryPreviewPayload(TypedDict):
    export_tsv: str
    row_count: int
    rows: list[HandleSummaryPreviewRow]


FIELD_PREFIX_MAP = {
    "Confidence:": "confidence",
    "Estimated MOHS:": "mohs",
    "IMO slot guess:": "imo_slot",
    "Topic tags:": "topic_tags",
}
MOHS_RE = re.compile(r"^(?P<value>\d+)(?:\s*M)?$", flags=re.IGNORECASE)
HANDLE_LINE_PREFIX = "Handle:"


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _parse_mohs_value(raw_value: str, *, handle: str) -> int:
    normalized_value = _normalize_text(raw_value)
    match = MOHS_RE.fullmatch(normalized_value)
    if match is None:
        msg = f'Handle "{handle}" has an invalid Estimated MOHS value: "{raw_value.strip()}".'
        raise HandleSummaryParseValidationError(msg)
    return int(match.group("value"))


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
    for prefix, field_name in FIELD_PREFIX_MAP.items():
        if line.startswith(prefix):
            return field_name, line.partition(":")[2].strip()
    return None


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

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        handle_block = _parse_handle_line(line)
        if handle_block is not None:
            current_block = _flush_handle_summary_block(rows, current_block)
            current_block = handle_block
            continue

        if not current_block:
            continue

        field_update = _extract_field_update(line)
        if field_update is not None:
            field_name, field_value = field_update
            current_block[field_name] = field_value

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
        }
        for row in rows
    ]
    export_lines = ["MOHS\tCONFIDENCE\tIMO SLOT\tTOPICS TAG"]
    export_lines.extend(
        f"{row.mohs}\t{row.confidence}\t{row.imo_slot}\t{row.topic_tags}"
        for row in rows
    )
    return {
        "export_tsv": "\n".join(export_lines),
        "row_count": len(preview_rows),
        "rows": preview_rows,
    }
