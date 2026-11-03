"""Conservative suggestions from pasted prose; the untouched source is kept separately."""

from __future__ import annotations

import re
from decimal import Decimal
from decimal import InvalidOperation
from unicodedata import normalize

MAX_SOURCE_BYTES = 200_000
MAX_ROWS = 80
MAX_LINES = 2000
MAX_TITLE = 255
MAX_OUTCOME = 64
MAX_SCORE = 100_000_000
SCORE_PRECISION = -2
MIN_TABLE_COLUMNS = 3
MAX_HEADING = 180
KIND = "achievement_text_v1"
EVIDENCE_CHOICES = (
    ("reported", "Reported source"),
    ("family", "Family record"),
    ("pending", "Pending verification"),
    ("family_pending", "Family record — pending verification"),
    ("conflicting", "Conflicting evidence"),
    ("family_conflicting", "Family record — conflicting evidence"),
)
YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
UNKNOWN_YEAR = re.compile(
    r"\byear(?:\s+is)?\s+(?:not (?:yet )?(?:established|recorded)|unknown|unspecified)|"
    r"\b(?:unknown|unspecified) year\b|\bundated\b", re.I,
)
AWARD = re.compile(
    r"silver ruler|individual merit|mathematics medal winner|high distinction|honou?rable mention|"
    r"junior secondary outstanding award|male model student(?: award)?|best mathematics(?: subject)?(?: award)?|"
    r"graduating.class representative|joint school contribution|class first place|overall second place|"
    r"(?:national )?team runner.up|individual champion|champion(?:ship)?|achievement(?: award)?|"
    r"platinum(?: award)?|\b(?:gold|silver|bronze)(?: medal| award)?\b|\bdistinction\b|\bmerit\b|"
    r"金牌|银牌|銅牌|铜牌|冠军|冠軍|亚军|亞軍",
    re.IGNORECASE,
)
SCORE = re.compile(r"(?<![\w.])(\d+(?:\.\d{1,2})?)\s*(?:/\s*\d+|points?\b|分)", re.IGNORECASE)
RANK = re.compile(
    r"\b(?:Malaysia|national|global|world)\s+(?:rank\s*)?#\s*\d+|"
    r"\b(?:Malaysia\s+)?(?:national\s+)?rank\s*#?\s*\d+|"
    r"\b\d+(?:st|nd|rd|th) place\b|\boverall first place\b", re.IGNORECASE,
)
FAMILY = re.compile(r"family|家长|家長|家庭", re.IGNORECASE)
UNCERTAIN = re.compile(
    r"unverified|not (?:yet )?(?:independently )?verified|need(?:s)? .*certificate|unconfirmed|not established", re.I,
)
HEADERS = {
    "year": "year", "年份": "year", "competition": "title", "competition / programme": "title",
    "competition / event": "title", "assessment": "title", "event": "title",
    "achievement": "outcome", "award": "outcome", "reported achievement": "outcome",
    "score": "score", "rank": "ranking", "ranking": "ranking", "category": "band", "division": "band",
    "details": "notes", "details and source": "notes", "detailed result": "notes", "verification gap": "notes",
}
SERIES = (
    ("mco_qualifiers", r"mco.*qualif|computing olympiad.*qualif"),
    ("imonst2", r"imonst\s*2|national selection test.*(?:round|stage)\s*2"),
    ("imonst1", r"imonst\s*1|national selection test.*(?:round|stage)\s*1"),
    ("sasmo", r"\bsasmo\b|singapore and asian schools math"),
    ("amc8", r"amc.?8|american mathematics competitions?.*8"),
    ("apmops", r"\bapmops\b|asia.pacific mathematical olympiad for primary"),
    ("apmo", r"\bapmo\b|asian? pacific mathematical olympiad"),
    ("jbmo", r"\bjbmo\b|junior balkan mathematical"),
    ("mcc", r"\bmcc\b|malaysian computing challenge"),
    ("mco", r"\bmco\b|malaysian computing olympiad"),
    ("igo", r"\bigo\b|iranian geometry olympiad"),
    ("amo", r"\bamo\b|american mathematics olympiad"),
    ("doka", r"\bdoka\b|depth of knowledge assessment"),
    ("noi", r"\bnoi\b|national olympiad in informatics"),
    ("wmi", r"\bwmi\b|world mathematics invitational"),
    ("jom", r"\bjom\b|junior olympiad of mathematics"),
)


def normalized(value):
    return " ".join(re.sub(r"[^\w]+", " ", normalize("NFKC", value).casefold()).split())


def series_key(value):
    return next((key for key, pattern in SERIES if re.search(pattern, value, re.I)), "")


def score_value(value):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        message = "Enter a numeric score."
        raise ValueError(message) from exc
    if not number.is_finite() or number < 0 or number >= MAX_SCORE or number.as_tuple().exponent < SCORE_PRECISION:
        message = "Scores must be nonnegative with at most two decimal places."
        raise ValueError(message)
    return format(number, ".2f")


def _discipline(value):  # noqa: PLR0911 - Ordered discipline rules, never a confidence score.
    if re.search(r"piano|music|钢琴|鋼琴", value, re.I):
        return "music"
    if re.search(r"donat|contribution|捐", value, re.I):
        return "community"
    if re.search(
        r"model student|school award|class first|overall second|graduat|subject award|模范生|模範生", value, re.I,
    ):
        return "school"
    if re.search(r"hippo|english|spelling|英语|英語", value, re.I):
        return "english"
    if re.search(r"comput|programming|informatics|algorithm|\b(?:mcc|mco|noi)\b|程式|算法", value, re.I):
        return "computing"
    if series_key(value) or re.search(r"math|geometry|数学|數學|几何|幾何", value, re.I):
        return "mathematics"
    return "unknown"


def _cells(line):
    if "\t" in line:
        return [cell.strip() for cell in line.split("\t")]
    if "|" in line:
        return [cell.strip() for cell in line.strip("|").split("|")]
    return None


def _candidate(line, number, heading_year, evidence, columns):  # noqa: C901, PLR0912, PLR0915 - Extraction with warnings.
    cells = _cells(line)
    values = dict(zip(columns, cells, strict=False)) if columns and cells else {}
    if not values and cells and len(cells) >= MIN_TABLE_COLUMNS and YEAR.fullmatch(cells[0]):
        values = {"year": cells[0], "title": cells[1], "outcome": cells[2], "notes": " · ".join(cells[3:])}
    years = set(YEAR.findall(values.get("year", "") if values else line))
    year = int(next(iter(years))) if len(years) == 1 else heading_year if not (years or values) else None
    if UNKNOWN_YEAR.search(line):
        year = None
    award = AWARD.search(values.get("outcome", "") if values else line)
    score = SCORE.search(line)
    rank = RANK.search(values.get("ranking", "") or line)
    if not values and not (award or score or rank):
        return None
    outcome = values.get("outcome", "") if values else award[0] if award else ""
    title = values.get("title", "")
    if not title:
        title_line = re.sub(r"^(?:19|20)\d{2}\s*[-\u2013—]\s*(?:19|20)\d{2}\s*", "", line)
        title = re.split(r"\s*[—\u2013]\s*|\s+-\s+|:\s+", title_line, maxsplit=1)[0]
        if title == title_line and award:
            title = line[:award.start()]
        elif title == title_line and score:
            title = line[:score.start()]
        title = YEAR.sub("", title, count=1).strip(" .,:;()-\u2013—")
    if not title or normalized(title) in {"verified", "family record", "gold", "silver", "bronze"}:
        return None
    raw_score = values.get("score", "") or (score[1] if score else "")
    warnings = []
    try:
        raw_score = score_value(raw_score)
    except ValueError:
        raw_score = None
        warnings.append("The source score needs manual review.")
    if year is None:
        warnings.append("Choose an exact event year or exclude this row; year ranges are not expanded.")
    if not values and len(AWARD.findall(line)) > 1:
        warnings.append("More than one award is mentioned; review this as a single event or exclude it.")
    if "/" in (score[0] if score else ""):
        warnings.append("The denominator is retained in context; no scoring scale or perfect score is verified.")
    if len(title) > MAX_TITLE or len(outcome) > MAX_OUTCOME:
        warnings.append("Shorten the event or award label before including this row.")
    if not values and re.search(
        r"not established|no (?:medal|award)|not (?:a )?(?:gold|silver|bronze|medal)",
        UNKNOWN_YEAR.sub("", line), re.I,
    ):
        outcome = ""
        warnings.append("A medal or award is negated or unestablished in this line; review the score or context only.")
    is_family = evidence.startswith("family") or bool(FAMILY.search(line))
    uncertain = bool(UNCERTAIN.search(line))
    state = ("family_pending" if uncertain else "family") if is_family else "pending" if uncertain else "reported"
    if "conflict" in line.casefold():
        state = "family_conflicting" if is_family else "conflicting"
    if re.search(r"participation|score|qualif(?:ied|ication|ying)|not established", outcome, re.I):
        kind = "performance"
    elif award or rank:
        kind = "achievement"
    elif raw_score is not None:
        kind = "performance"
    elif re.search(r"selected|squad|selection|入选|入選", title, re.I):
        kind = "selection"
    else:
        kind = "achievement" if outcome else "performance"
    return {
        "include": bool(year and not warnings), "year": year, "title": title[:MAX_TITLE],
        "outcome": outcome[:MAX_OUTCOME], "score": raw_score,
        "ranking": (values.get("ranking") or (rank[0] if rank else ""))[:MAX_TITLE],
        "record_type": kind, "discipline": _discipline(line), "band": values.get("band", "")[:32],
        "evidence": state, "existing_result": "", "notes": values.get("notes", "")[:2000],
        "source_line": number, "excerpt": line[:4000], "warnings": warnings,
    }


def parse_achievement_text(text, *, default_evidence="reported"):  # noqa: C901, PLR0912 - Bounded line parser.
    if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        message = "Paste between 1 and 200,000 UTF-8 bytes of achievement text."
        raise ValueError(message)
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        message = "Use at most 2,000 source lines per paste."
        raise ValueError(message)
    if default_evidence not in {"reported", "family"}:
        message = "Choose supplied research or a family record."
        raise ValueError(message)
    rows, warnings, seen = [], [], set()
    heading_year, evidence, columns = None, default_evidence, None
    for number, original in enumerate(lines, 1):
        line = re.sub(r"^\s*(?:[-*•]+|\d+[.)])\s+", "", original).strip(" \r").strip("# ")
        if not line:
            continue
        if YEAR.fullmatch(line):
            heading_year = int(line)
            continue
        if len(set(YEAR.findall(line))) > 1:
            heading_year = None
        cells = _cells(line)
        if cells:
            mapped = [HEADERS.get(cell.casefold(), "") for cell in cells]
            if "title" in mapped and "year" in mapped:
                columns = mapped
                continue
            if all(not cell.strip("-: ") for cell in cells):
                continue
        if len(line) < MAX_HEADING and not cells:
            family_heading = FAMILY.search(line) and (
                not YEAR.search(line)
                or re.match(r"^(?:additional\s+)?(?:family\b|achievements?.*family|awards?.*family)", line, re.I)
            )
            if family_heading:
                evidence = "family"
            elif (
                not YEAR.search(line) and not AWARD.search(line) and not SCORE.search(line) and not RANK.search(line)
                and re.search(r"verified|documented|mathematics|computing|music|school academic", line, re.I)
            ):
                evidence = default_evidence
        row = _candidate(line, number, heading_year, evidence, columns)
        if row is None:
            continue
        key = (row["year"], normalized(row["title"]), row["outcome"].casefold(), row["score"], row["ranking"])
        if key in seen:
            warnings.append(f"Repeated suggestion on line {number} remains in the original context.")
            continue
        seen.add(key)
        if len(rows) == MAX_ROWS:
            warnings.append("Only the first 80 suggestions are shown. All remaining text is preserved as context.")
            break
        rows.append(row)
    return {"rows": rows, "warnings": warnings, "source_lines": len(lines)}
