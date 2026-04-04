from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from dataclasses import field
from typing import TypedDict

from django.db import transaction

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.statement_analytics_sync import sync_statement_analytics_from_linked_problem

PdfReader = None

IGNORED_STATEMENT_LINES = {
    "Stuttgarden",
    "Click to reveal hidden text",
    "view topic",
}
HEADER_LINE_RE = re.compile(
    r"^\s*(?P<year_start>\d{4})(?:\s*(?:/|-)\s*(?P<year_end>\d{4}))?\s+(?P<contest>.+?)\s*$",
)
HEADER_YEAR_SUFFIX_RE = re.compile(
    r"^\s*(?P<contest>.+?)\s+(?P<year>\d{4})(?:\d)?\s*$",
)
HEADER_YEAR_MIDDLE_RE = re.compile(
    r"^\s*(?P<prefix>.+?)\s+(?P<year>\d{4})(?:\d)?\s+(?P<suffix>.+?)\s*$",
)
YEAR_PREFIXED_SECTION_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s+(?P<label>[A-Za-z].+?)\s*$",
)
DAY_LABEL_RE = re.compile(
    r"^Day\s*(?P<token>\d+|[IVXLCDM]+)(?:(?:\s*[,:-]\s*|\s+)(?P<detail>.+))?$",
    flags=re.IGNORECASE,
)
TST_DAY_LABEL_RE = re.compile(
    r"^TST\s*#?\s*(?P<number>\d+)(?:\s+(?P<detail>.+))?$",
    flags=re.IGNORECASE,
)
ROUND_LABEL_RE = re.compile(r"^(?:\d+\s+)?(?P<label>Round\s+[A-Za-z0-9].*)$", flags=re.IGNORECASE)
SOLUTION_LINE_RE = re.compile(r"^Solution$", flags=re.IGNORECASE)
TEST_LABEL_RE = re.compile(
    r"^Test\s+(?P<number>\d+|[IVXLCDM]+)(?:\s+(?P<detail>.+))?$",
    flags=re.IGNORECASE,
)
PART_LABEL_RE = re.compile(
    r"^Part\s+(?P<number>\d+|[IVXLCDM]+)(?:\s+(?P<detail>.+))?$",
    flags=re.IGNORECASE,
)
SEASON_SECTION_RE = re.compile(
    r"^(?P<season>Fall|Autumn|Spring)\s+(?P<year>\d{4})$",
    flags=re.IGNORECASE,
)
YEAR_FIRST_SEASON_SECTION_RE = re.compile(
    r"^(?P<year>\d{4})\s+(?P<season>Fall|Autumn|Spring)$",
    flags=re.IGNORECASE,
)
LEVEL_SECTION_RE = re.compile(
    r"^(?P<division>Junior|Senior)\s+(?P<track>[AO])-Level$",
    flags=re.IGNORECASE,
)
DIVISION_SECTION_RE = re.compile(r"^(?P<division>Junior|Juniors|Senior|Seniors)$", flags=re.IGNORECASE)
TRACK_SECTION_RE = re.compile(r"^(?P<track>[AO])(?:\s*-\s*|\s+)Level$", flags=re.IGNORECASE)
GRADE_SECTION_RE = re.compile(r"^Grade\s+(?P<number>\d{1,2})$", flags=re.IGNORECASE)
GRADE_LEVEL_SECTION_RE = re.compile(r"^Grade\s+level\s+(?P<number>\d{1,2})$", flags=re.IGNORECASE)
INLINE_SEASON_LEVEL_SECTION_RE = re.compile(
    r"^(?P<season>Fall|Autumn|Spring)\s+(?P<year>\d{4})\s+(?P<track>[AO])-level\s+(?P<division>Junior|Senior)$",
    flags=re.IGNORECASE,
)
HYPHENATED_SEASON_LEVEL_SECTION_RE = re.compile(
    r"^(?P<season>Fall|Autumn|Spring)\s+(?P<year>\d{4})\s*-\s*(?P<division>Junior|Senior)\s+(?P<track>[AO])-level$",
    flags=re.IGNORECASE,
)
YEARLESS_HYPHENATED_SEASON_LEVEL_SECTION_RE = re.compile(
    r"^(?P<season>Fall|Autumn|Spring)\s*-\s*(?P<division>Junior|Senior)\s+(?P<track>[AO])-level$",
    flags=re.IGNORECASE,
)
YEARLESS_SEASON_LEVEL_SECTION_RE = re.compile(
    r"^(?P<season>Fall|Autumn|Spring)\s+(?P<division>Junior|Senior)\s+(?P<track>[AO])-level(?:\s+Paper)?$",
    flags=re.IGNORECASE,
)
ROUND_PREFIXED_YEARLESS_SEASON_LEVEL_SECTION_RE = re.compile(
    r"^(?P<round>[IVXLCDM]+)\.\s*(?P<season>Fall|Autumn|Spring)\s*-\s*(?P<division>Junior|Senior)(?:\s*-\s*|\s+)(?P<track>[AO])-level(?:\s+Paper)?$",
    flags=re.IGNORECASE,
)
ROUND_AND_SECTION_RE = re.compile(
    r"^(?P<round>First|Second|Third|Final)\s+Round\s+(?P<label>.+)$",
    flags=re.IGNORECASE,
)
EXAM_AND_DAY_LABEL_RE = re.compile(
    r"^(?P<exam>First|Second|Third|Final)\s+exam\s*,\s*(?P<day>Day\s*(?:\d+|[IVXLCDM]+)(?:(?:\s*[,:-]\s*|\s+).+)?)$",
    flags=re.IGNORECASE,
)
PROBLEM_START_RE = re.compile(
    r"^(?:\((?P<catalog_number>\d{1,4})\)\s*)?(?:#\s*)?(?:(?P<prefix>[A-Za-z]{1,4})\s*)?(?P<number>\d{1,3})[.)]?(?:\s+(?P<statement>.+))?$",
    flags=re.IGNORECASE,
)
ALPHA_PROBLEM_CODE_RE = re.compile(r"^(?P<code>[A-Z])(?:[.)])?\s+(?P<statement>.+)$")
TEXT_ONLY_EMPH_INLINE_RE = re.compile(r"\$(?P<content>\\emph\{[^$]+?\})\$")
TEXT_ONLY_EMPH_PAREN_RE = re.compile(r"\\\((?P<content>\\emph\{.*?\})\\\)", flags=re.DOTALL)
TEXT_ONLY_EMPH_DISPLAY_RE = re.compile(r"\$\$(?P<content>\\emph\{.*?\})\$\$", flags=re.DOTALL)
TEXT_ONLY_EMPH_BRACKET_RE = re.compile(r"\\\[(?P<content>\\emph\{.*?\})\\\]", flags=re.DOTALL)
SHORT_SECTION_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9][A-Za-z0-9]*){0,3}$")
PAPER_SECTION_RE = re.compile(
    r"^(?:Junior|Senior)\s+[AO]-Level\s+Paper,\s+(?:Fall|Autumn|Spring)\s+\d{4}$",
    flags=re.IGNORECASE,
)
SEASON_FIRST_PAPER_SECTION_RE = re.compile(
    r"^(?:Fall|Autumn|Spring)\s+\d{4},\s+(?:Junior|Senior)\s+[AO]-level$",
    flags=re.IGNORECASE,
)
SPECIAL_PROBLEM_CODE_RE = re.compile(r"^(?P<code>Bonus)[.)]?\s+(?P<statement>.+)$", flags=re.IGNORECASE)
INNER_NUMBERED_STATEMENT_RE = re.compile(r"^(?P<number>\d{1,3})[.)]\s+(?P<statement>.+)$")
TRAILING_AUTHOR_LINE_RE = re.compile(
    r"^[A-Z][A-Za-z'.-]*(?: [A-Z][A-Za-z'.-]*)*(?: and [A-Z][A-Za-z'.-]*(?: [A-Z][A-Za-z'.-]*)*)?$",
)
TRAILING_PROPOSED_BY_LINE_RE = re.compile(
    r"^(?:\(?\s*)(?:proposed|created)(?: by)?\b.+$",
    flags=re.IGNORECASE,
)
USERNAME_LINE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
NOTE_METADATA_LINE_RE = re.compile(
    r"^(?:note|junior version (?:posted )?here|senior version (?:posted )?here|\(translated from here\.\))$",
    flags=re.IGNORECASE,
)
SECTION_DATE_LINE_RE = re.compile(
    r"^(?:"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}"
    r"|[A-Za-z]+\s+\d{1,2},\s+\d{4}"
    r")$",
    flags=re.IGNORECASE,
)
SECTION_TIME_LINE_RE = re.compile(r"^Time:\s+.+$", flags=re.IGNORECASE)
SECTION_HEADER_LABELS = frozenset(
    {
        "Algebra",
        "Combinatorics",
        "Geometry",
        "Number Theory",
    },
)
LATEX_STATEMENT_SAMPLE = (
    "2026 Spain Mathematical Olympiad3\n"
    "Day 1\n"
    "1\tFind the value of a positive integer $N$ such that"
    "\\[2026<\\frac{1}{\\sqrt{1}}+\\frac{1}{\\sqrt{2}}+\\frac{1}{\\sqrt{3}}"
    "+\\dots+\\frac{1}{\\sqrt{N}}<2027.\\]\n"
    "\n"
    "Stuttgarden\n"
    "\n"
    "2\tLet $ABC$ be a triangle with $AB<BC$. The perpendicular bisector of $AC$ intersects $BC$ "
    "in $D$. The circle passing through $A,C,D$ contains a point $E\\neq D$ such that $DE$ is "
    "parallel to $AB$. Prove that $AE^2+BC^2=BE^2$.\n"
    "\n"
    "Stuttgarden\n"
    "\n"
    "3\tWe say that a sequence $a_1, a_2, \\dots$ of positive integers is roceña if, for all "
    "$n\\geq 4$,\\[a_n=a_{n-1}+\\gcd(a_{n-2},a_{n-3})-1.\\]Does there exist any roceña sequence "
    "such that $2\\leq a_n\\leq 100\\cdot n^{100}$ for all $n\\geq 1$?\n"
    "\n"
    "Stuttgarden\n"
    "\n"
    "Day 2\n"
    "4\tFor each positive integer $n$, let $a(n)$ be the largest value of $k$ such that $n$ is "
    "a multiple of all of $1, 2, \\dots, k$. Prove that if $\\sqrt[3]{a(n)}$ is an integer, "
    "then $\\sqrt[3]{a(n+2520)}$ is an integer.\n"
    "\n"
    "Stuttgarden\n"
    "\n"
    "5\tThe restaurant of the Hotel Las Rozas has three signature dishes: artichokes, beef and "
    "cod. Every evening the restaurant cooks one instance of each dish, so two guests cannot eat "
    "the same dish on the same evening. Let $n\\geq 3$. $n$ guests $H_1, H_2, \\dots, H_n$ will "
    "stay at the hotel, where for each $1\\leq k\\leq n$ the guest $H_k$ stays from the day $k$ "
    "at noon until the day $k+3$ at noon. Every guest wishes to try all three dishes, one on "
    "each evening of their stay.\n"
    "\n"
    "Determine, as a function of $n$, the number of ways to arrange the dish that each guest will "
    "eat on each dinner, from the evening of the first day until the evening of the $(n+2)$-th "
    "day, fulfilling the wishes of every guest.\n"
    "\n"
    "Stuttgarden\n"
    "\n"
    "6\tIn the scalene triangle $ABC$, the incircle $\\omega$ touches $BC, CA, AB$ at $D, E, F$ "
    "respectively. Let $G$ be the point on the line $EF$ such that $AG$ is parallel to $BC$. "
    "Prove that $\\omega$ contains the orthocenter of the triangle $ADG$."
)


class PreviewDayRow(TypedDict):
    label: str
    problem_count: int


class PreviewProblemRow(TypedDict):
    contest_year_problem: str
    day_label: str
    problem_code: str
    problem_number: int
    statement_latex: str
    linked_problem_label: str


class ProblemStatementPreviewPayload(TypedDict):
    contest_name: str
    contest_year: int
    day_rows: list[PreviewDayRow]
    problem_count: int
    problems: list[PreviewProblemRow]


class ProblemStatementSavePreviewPayload(TypedDict):
    create_count: int
    update_count: int
    unchanged_count: int
    existing_count: int
    existing_problem_codes: list[str]
    update_problem_codes: list[str]
    unchanged_problem_codes: list[str]


class ProblemStatementImportValidationError(ValueError):
    """Raised when pasted contest statement text cannot be parsed reliably."""


def extract_statement_text_from_pdf(uploaded_file) -> str:
    with contextlib.suppress(AttributeError, OSError):
        uploaded_file.seek(0)

    reader_cls = PdfReader
    if reader_cls is None:
        with contextlib.suppress(ImportError):
            from pypdf import PdfReader as installed_reader_cls

            reader_cls = installed_reader_cls

    if reader_cls is None:
        msg = "PDF parsing dependency is unavailable. Install pypdf and try again."
        raise ProblemStatementImportValidationError(msg)

    try:
        reader = reader_cls(uploaded_file)
    except Exception as exc:
        msg = "Could not read the uploaded PDF. Please upload a valid text-based PDF file."
        raise ProblemStatementImportValidationError(msg) from exc

    page_chunks: list[str] = []
    for page in reader.pages:
        try:
            raw_text = page.extract_text() or ""
        except Exception as exc:
            msg = "Could not extract text from one or more PDF pages."
            raise ProblemStatementImportValidationError(msg) from exc

        normalized = raw_text.replace("\x00", "")
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.strip()
        if normalized:
            page_chunks.append(normalized)

    extracted_text = "\n\n".join(page_chunks).strip()
    if not extracted_text:
        msg = "No extractable text was found in the uploaded PDF. The file may be image-only."
        raise ProblemStatementImportValidationError(msg)

    return extracted_text


@dataclass(frozen=True)
class ParsedContestProblemStatement:
    day_label: str
    problem_code: str
    problem_number: int
    statement_latex: str


@dataclass(frozen=True)
class ParsedContestStatementImport:
    contest_year: int
    contest_name: str
    problems: tuple[ParsedContestProblemStatement, ...]


@dataclass(frozen=True)
class ProblemStatementImportResult:
    created_count: int
    updated_count: int
    linked_problem_count: int


@dataclass(frozen=True)
class ProblemStatementRelinkResult:
    checked_count: int
    linked_count: int
    newly_linked_count: int
    skipped_count: int
    unlinked_count: int
    updated_count: int


@dataclass
class _StatementParseState:
    contest_year: int | None = None
    contest_name: str = ""
    current_day: str = ""
    current_primary_section: str = ""
    current_secondary_section: str = ""
    allows_section_date_metadata: bool = False
    allows_day_subsection: bool = False
    current_problem_code: str | None = None
    current_problem_number: int | None = None
    awaiting_new_problem: bool = False
    current_statement_lines: list[str] = field(default_factory=list)
    parsed_problems: list[ParsedContestProblemStatement] = field(default_factory=list)


def _clean_contest_name(raw_name: str) -> str:
    cleaned_name = re.sub(r"(?<!\s)\d+$", "", raw_name.strip())
    return cleaned_name.strip()


def _parse_header_line(header_line: str) -> tuple[int, str]:
    match = HEADER_LINE_RE.match(header_line)
    if match:
        contest_year = int(match.group("year_end") or match.group("year_start"))
        contest_name = _clean_contest_name(match.group("contest"))
        if not contest_name:
            msg = "Contest name is empty after parsing the header line."
            raise ProblemStatementImportValidationError(msg)
        return contest_year, contest_name

    match = HEADER_YEAR_MIDDLE_RE.match(header_line)
    if match:
        contest_year = int(match.group("year"))
        contest_name = _clean_contest_name(
            f"{match.group('prefix')} {match.group('suffix')}",
        )
        if not contest_name:
            msg = "Contest name is empty after parsing the header line."
            raise ProblemStatementImportValidationError(msg)
        return contest_year, contest_name

    match = HEADER_YEAR_SUFFIX_RE.match(header_line)
    if not match:
        msg = "Could not parse the contest header. Expected a line like '2026 Spain Mathematical Olympiad'."
        raise ProblemStatementImportValidationError(msg)

    contest_year = int(match.group("year"))
    contest_name = _clean_contest_name(match.group("contest"))
    if not contest_name:
        msg = "Contest name is empty after parsing the header line."
        raise ProblemStatementImportValidationError(msg)
    return contest_year, contest_name


def _collapse_statement_lines(lines: list[str]) -> str:
    trimmed_lines = [line.rstrip() for line in lines]
    while trimmed_lines and not trimmed_lines[0].strip():
        trimmed_lines.pop(0)
    while trimmed_lines and not trimmed_lines[-1].strip():
        trimmed_lines.pop()

    collapsed_lines: list[str] = []
    previous_blank = False
    for line in trimmed_lines:
        if not line.strip():
            if previous_blank:
                continue
            collapsed_lines.append("")
            previous_blank = True
            continue
        collapsed_lines.append(line.strip())
        previous_blank = False

    return _normalize_statement_latex("\n".join(collapsed_lines).strip())


def _supports_trailing_credit_cleanup(day_label: str, *, contest_name: str) -> bool:
    normalized_contest_name = contest_name.casefold()
    normalized_day_label = day_label.casefold()
    return (
        normalized_contest_name.endswith(" tst")
        or "team selection test" in normalized_contest_name
        or "training camp" in normalized_contest_name
        or "practice test" in normalized_contest_name
        or normalized_day_label.startswith(
            (
                "tst #",
                "test ",
                "first exam",
                "second exam",
                "third exam",
                "final exam",
            ),
        )
        or " · test " in normalized_day_label
        or "selection test" in normalized_day_label
        or "training camp" in normalized_day_label
    )


def _is_trailing_credit_line(line: str, *, day_label: str, contest_name: str) -> bool:
    if line.strip().casefold() == "unavailable":
        return False
    if not _supports_trailing_credit_cleanup(day_label, contest_name=contest_name):
        return False
    return bool(
        TRAILING_PROPOSED_BY_LINE_RE.fullmatch(line)
        or TRAILING_AUTHOR_LINE_RE.fullmatch(line),
    )


def _is_generic_trailing_metadata_line(line: str) -> bool:
    stripped_line = line.strip()
    if not stripped_line:
        return False
    if stripped_line.casefold() == "unavailable":
        return False
    if stripped_line in IGNORED_STATEMENT_LINES:
        return True
    if NOTE_METADATA_LINE_RE.fullmatch(stripped_line):
        return True
    if USERNAME_LINE_RE.fullmatch(stripped_line):
        return True
    return _looks_like_author_credit_line(stripped_line)


def _looks_like_inline_author_credit_suffix(line: str) -> bool:
    candidate = " ".join(line.split())
    if not _looks_like_author_credit_line(candidate):
        return False
    return "," in candidate or " and " in candidate or len(candidate.split()) >= 2


def _looks_like_inline_trailing_credit_suffix(
    line: str,
    *,
    day_label: str,
    contest_name: str,
) -> bool:
    candidate = " ".join(line.split())
    return _looks_like_inline_author_credit_suffix(candidate) or _is_trailing_credit_line(
        candidate,
        day_label=day_label,
        contest_name=contest_name,
    )


def _trim_trailing_inline_author_suffix(
    line: str,
    *,
    day_label: str,
    contest_name: str,
) -> str:
    stripped_line = line.rstrip()
    for separator in (r"\]", "$$", ".", "?", "!"):
        separator_index = stripped_line.rfind(separator)
        if separator_index < 0:
            continue
        candidate = stripped_line[separator_index + len(separator) :].strip()
        if not _looks_like_inline_trailing_credit_suffix(
            candidate,
            day_label=day_label,
            contest_name=contest_name,
        ):
            continue
        return stripped_line[: separator_index + len(separator)].rstrip()
    return stripped_line


def _trim_trailing_problem_metadata(lines: list[str], *, day_label: str, contest_name: str) -> list[str]:
    trimmed_lines = list(lines)

    while trimmed_lines and not trimmed_lines[-1].strip():
        trimmed_lines.pop()

    if trimmed_lines:
        trimmed_lines[-1] = _trim_trailing_inline_author_suffix(
            trimmed_lines[-1],
            day_label=day_label,
            contest_name=contest_name,
        )
        while trimmed_lines and not trimmed_lines[-1].strip():
            trimmed_lines.pop()

    while trimmed_lines and _is_trailing_credit_line(
        trimmed_lines[-1].strip(),
        day_label=day_label,
        contest_name=contest_name,
    ):
        trimmed_lines.pop()
        while trimmed_lines and not trimmed_lines[-1].strip():
            trimmed_lines.pop()

    while trimmed_lines and _is_generic_trailing_metadata_line(trimmed_lines[-1]):
        trimmed_lines.pop()
        while trimmed_lines and not trimmed_lines[-1].strip():
            trimmed_lines.pop()

    return trimmed_lines


def _normalize_statement_latex(statement_latex: str) -> str:
    normalized = TEXT_ONLY_EMPH_INLINE_RE.sub(
        lambda match: f"$\\text{{{match.group('content')}}}$",
        statement_latex,
    )
    normalized = TEXT_ONLY_EMPH_PAREN_RE.sub(
        lambda match: f"\\(\\text{{{match.group('content')}}}\\)",
        normalized,
    )
    normalized = TEXT_ONLY_EMPH_DISPLAY_RE.sub(
        lambda match: f"$$\\text{{{match.group('content')}}}$$",
        normalized,
    )
    return TEXT_ONLY_EMPH_BRACKET_RE.sub(
        lambda match: f"\\[\\text{{{match.group('content')}}}\\]",
        normalized,
    )


def _normalized_statement_lines(raw_text: str) -> list[str]:
    stripped_text = raw_text.strip()
    if not stripped_text:
        msg = "Paste contest text before parsing."
        raise ProblemStatementImportValidationError(msg)
    return [line.rstrip() for line in stripped_text.splitlines()]


def _parse_contest_header(lines: list[str]) -> tuple[int, str, list[str]]:
    header_index = next((index for index, line in enumerate(lines) if line.strip()), None)
    if header_index is None:
        msg = "Paste contest text before parsing."
        raise ProblemStatementImportValidationError(msg)

    first_header_line = lines[header_index].strip()
    try:
        contest_year, contest_name = _parse_header_line(first_header_line)
        return contest_year, contest_name, lines[header_index + 1 :]
    except ProblemStatementImportValidationError:
        next_header_index = next(
            (index for index in range(header_index + 1, len(lines)) if lines[index].strip()),
            None,
        )
        if next_header_index is None:
            raise
        next_header_line = lines[next_header_index].strip()
        if _looks_like_post_header_content(next_header_line):
            contest_year, contest_name = _parse_header_line(first_header_line)
            return contest_year, contest_name, lines[header_index + 1 :]
        contest_year, _ = _parse_header_line(lines[next_header_index].strip())
        contest_name = _clean_contest_name(first_header_line)
        if not contest_name:
            raise
        return contest_year, contest_name, lines[header_index + 1 :]


def _flush_problem(state: _StatementParseState) -> None:
    if state.current_problem_number is None:
        return

    statement_latex = _collapse_statement_lines(
        _trim_trailing_problem_metadata(
            state.current_statement_lines,
            day_label=state.current_day,
            contest_name=state.contest_name,
        ),
    )
    if not statement_latex:
        msg = f"Problem {state.current_problem_number} does not have any statement text."
        raise ProblemStatementImportValidationError(msg)

    state.parsed_problems.append(
        ParsedContestProblemStatement(
            day_label=state.current_day,
            problem_code=state.current_problem_code or f"P{state.current_problem_number}",
            problem_number=state.current_problem_number,
            statement_latex=statement_latex,
        ),
    )
    state.current_problem_code = None
    state.current_problem_number = None
    state.awaiting_new_problem = False
    state.current_statement_lines = []


def _compose_section_label(primary: str, secondary: str) -> str:
    if primary and secondary:
        return f"{primary} · {secondary}"
    return primary or secondary


def _compose_nested_section_label(*parts: str) -> str:
    return " · ".join(part for part in parts if part)


def _set_primary_section(
    state: _StatementParseState,
    label: str,
    *,
    allows_section_date_metadata: bool = False,
    allows_day_subsection: bool = False,
) -> None:
    state.current_primary_section = label
    state.current_secondary_section = ""
    state.current_day = _compose_section_label(
        state.current_primary_section,
        state.current_secondary_section,
    )
    state.allows_section_date_metadata = allows_section_date_metadata
    state.allows_day_subsection = allows_day_subsection


def _set_secondary_section(state: _StatementParseState, label: str) -> None:
    state.current_secondary_section = label
    state.current_day = _compose_section_label(
        state.current_primary_section,
        state.current_secondary_section,
    )
    state.allows_section_date_metadata = False
    state.allows_day_subsection = False


def _set_division_section(state: _StatementParseState, label: str) -> None:
    _set_secondary_section(state, label)


def _division_from_secondary_label(label: str) -> str:
    stripped_label = label.strip()
    if stripped_label.startswith("Junior"):
        return "Junior"
    if stripped_label.startswith("Senior"):
        return "Senior"
    return ""


def _set_track_section(state: _StatementParseState, label: str) -> None:
    division = _division_from_secondary_label(state.current_secondary_section)
    _set_secondary_section(state, f"{division} {label}".strip())


def _is_structured_day_subsection_part(label: str) -> bool:
    candidate = " ".join(label.split())
    return bool(
        _normalized_day_label(candidate)
        or _normalized_test_label(candidate)
        or _normalized_exam_day_label(candidate)
    )


def _set_day_subsection(state: _StatementParseState, day_label: str) -> None:
    if not state.current_secondary_section:
        _set_secondary_section(state, day_label)
        return

    secondary_parts = [part for part in state.current_secondary_section.split(" · ") if part]
    if (
        len(secondary_parts) >= 2
        and _is_structured_day_subsection_part(secondary_parts[-2])
        and _normalized_section_date_label(secondary_parts[-1]) is not None
    ):
        secondary_parts = secondary_parts[:-2]
    elif secondary_parts and _is_structured_day_subsection_part(secondary_parts[-1]):
        secondary_parts = secondary_parts[:-1]
    secondary_parts.append(day_label)
    _set_secondary_section(state, _compose_nested_section_label(*secondary_parts))


def _next_nonempty_lines(lines: list[str], current_index: int, *, limit: int = 1) -> list[str]:
    candidates: list[str] = []
    for raw_line in lines[current_index + 1 :]:
        candidate = raw_line.strip()
        if not candidate:
            continue
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def _is_scrape_metadata_line(
    line: str,
    *,
    next_nonempty_line: str | None,
    following_nonempty_line: str | None,
    third_nonempty_line: str | None,
) -> bool:
    if line in IGNORED_STATEMENT_LINES:
        return True
    if SOLUTION_LINE_RE.fullmatch(line):
        return True
    if (
        following_nonempty_line == "view topic"
        and next_nonempty_line is not None
        and USERNAME_LINE_RE.fullmatch(next_nonempty_line)
        and _looks_like_author_credit_line(line)
    ):
        return True
    if (
        _looks_like_author_credit_line(line)
        and next_nonempty_line is not None
        and NOTE_METADATA_LINE_RE.fullmatch(next_nonempty_line)
        and following_nonempty_line is not None
        and USERNAME_LINE_RE.fullmatch(following_nonempty_line)
        and third_nonempty_line == "view topic"
    ):
        return True
    if (
        NOTE_METADATA_LINE_RE.fullmatch(line)
        and next_nonempty_line is not None
        and USERNAME_LINE_RE.fullmatch(next_nonempty_line)
        and following_nonempty_line == "view topic"
    ):
        return True
    return next_nonempty_line == "view topic"


def _normalized_section_label(line: str) -> str | None:
    candidate = " ".join(line.split())
    for label in SECTION_HEADER_LABELS:
        if candidate.casefold() == label.casefold():
            return label
    return None


def _normalized_section_date_label(line: str) -> str | None:
    candidate = " ".join(line.split())
    if SECTION_DATE_LINE_RE.fullmatch(candidate) is None:
        return None
    return candidate


def _looks_like_author_credit_line(line: str) -> bool:
    candidate = " ".join(line.split())
    candidate = re.sub(
        r"\s*\((?:Junior|Senior) version (?:posted )?here\)\s*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    if not candidate or len(candidate) > 120:
        return False
    if "proposed by" in candidate.casefold():
        return False
    if candidate.startswith("http"):
        return False
    if any(character.isdigit() for character in candidate):
        return False
    if any(character in candidate for character in "$\\=<>/?{}[]_"):
        return False

    for segment in re.split(r",| and ", candidate):
        segment = segment.strip()
        if not segment:
            return False
        tokens = segment.split()
        if len(tokens) > 4:
            return False
        for token in tokens:
            normalized_token = token.strip("().").replace("’", "'")
            if not normalized_token:
                return False
            if not any(character.isalpha() for character in normalized_token):
                return False
            if not all(character.isalpha() or character in ".'-" for character in normalized_token):
                return False
            first_alpha = next(
                (character for character in normalized_token if character.isalpha()),
                "",
            )
            if not first_alpha or first_alpha != first_alpha.upper():
                return False
    return True


def _normalized_paper_section_label(line: str) -> str | None:
    candidate = " ".join(line.split())
    if PAPER_SECTION_RE.fullmatch(candidate) or SEASON_FIRST_PAPER_SECTION_RE.fullmatch(candidate):
        return candidate
    return None


def _normalized_season_section_label(line: str) -> str | None:
    candidate = " ".join(line.split())
    match = SEASON_SECTION_RE.fullmatch(candidate)
    if match is None:
        match = YEAR_FIRST_SEASON_SECTION_RE.fullmatch(candidate)
    if match is None:
        return None
    return f"{match.group('season').title()} {match.group('year')}"


def _normalized_division_section_label(line: str) -> str | None:
    match = DIVISION_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    division = match.group("division").casefold()
    return "Junior" if division.startswith("junior") else "Senior"


def _normalized_level_section_label(line: str) -> str | None:
    match = LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return f"{match.group('division').title()} {match.group('track').upper()}-Level"


def _normalized_track_section_label(line: str) -> str | None:
    match = TRACK_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return f"{match.group('track').upper()}-Level"


def _normalized_grade_section_label(line: str) -> str | None:
    match = GRADE_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return f"Grade {int(match.group('number'))}"


def _normalized_grade_level_section_label(line: str) -> str | None:
    match = GRADE_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return f"Grade level {int(match.group('number'))}"


def _normalized_inline_season_level_label(line: str) -> str | None:
    match = INLINE_SEASON_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return (
        f"{match.group('season').title()} {match.group('year')}"
        f" · {match.group('division').title()} {match.group('track').upper()}-Level"
    )


def _normalized_hyphenated_season_level_label(line: str) -> str | None:
    match = HYPHENATED_SEASON_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return (
        f"{match.group('season').title()} {match.group('year')}"
        f" · {match.group('division').title()} {match.group('track').upper()}-Level"
    )


def _normalized_yearless_hyphenated_season_level_label(
    line: str,
    *,
    contest_year: int | None,
) -> str | None:
    if contest_year is None:
        return None
    match = YEARLESS_HYPHENATED_SEASON_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return (
        f"{match.group('season').title()} {contest_year}"
        f" · {match.group('division').title()} {match.group('track').upper()}-Level"
    )


def _normalized_yearless_season_level_label(
    line: str,
    *,
    contest_year: int | None,
) -> str | None:
    if contest_year is None:
        return None
    match = YEARLESS_SEASON_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return (
        f"{match.group('season').title()} {contest_year}"
        f" · {match.group('division').title()} {match.group('track').upper()}-Level"
    )


def _normalized_round_prefixed_yearless_season_level_label(
    line: str,
    *,
    contest_year: int | None,
) -> str | None:
    if contest_year is None:
        return None
    match = ROUND_PREFIXED_YEARLESS_SEASON_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return (
        f"{match.group('season').title()} {contest_year}"
        f" · {match.group('division').title()} {match.group('track').upper()}-Level"
    )


def _normalized_problem_statement_text(statement: str, *, number: int) -> str:
    candidate = statement.strip()
    inner_match = INNER_NUMBERED_STATEMENT_RE.match(candidate)
    if inner_match is not None and int(inner_match.group("number")) == number:
        return inner_match.group("statement").strip()
    return candidate


def _is_section_metadata_line(line: str | None) -> bool:
    if line is None:
        return False
    return bool(
        SECTION_DATE_LINE_RE.fullmatch(line)
        or SECTION_TIME_LINE_RE.fullmatch(line),
    )


def _looks_like_generic_section_header_candidate(candidate: str) -> bool:
    if not candidate or not candidate[0].isalpha():
        return False
    if len(candidate) > 120:
        return False
    if candidate.endswith((".", "!", "?", ":", ";")):
        return False
    if any(character in candidate for character in "$\\=<>/?{}[]_"):
        return False
    return all(
        character.isalnum() or character.isspace() or character in "(),'&#-"
        for character in candidate
    )


def _supports_named_day_subsections(candidate: str) -> bool:
    normalized_candidate = candidate.casefold()
    return any(
        keyword in normalized_candidate
        for keyword in ("test", "selection", "squad", "camp", "exam")
    )


def _is_problem_start_candidate(line: str | None) -> bool:
    if line is None:
        return False
    return bool(
        PROBLEM_START_RE.match(line)
        or SPECIAL_PROBLEM_CODE_RE.match(line)
        or ALPHA_PROBLEM_CODE_RE.match(line),
    )


def _looks_like_post_header_content(line: str | None) -> bool:
    if line is None:
        return False
    normalized_line = " ".join(line.split())
    return bool(
        _normalized_day_label(normalized_line)
        or _normalized_tst_day_label(normalized_line)
        or _normalized_exam_day_label(normalized_line)
        or _normalized_part_label(normalized_line)
        or TEST_LABEL_RE.fullmatch(normalized_line)
        or ROUND_LABEL_RE.fullmatch(normalized_line)
        or _is_problem_start_candidate(line)
    )


def _is_structured_section_header(line: str | None) -> bool:
    if line is None:
        return False
    normalized_line = " ".join(line.split())
    return bool(
        _normalized_day_label(normalized_line)
        or _normalized_tst_day_label(normalized_line)
        or _normalized_exam_day_label(normalized_line)
        or _normalized_part_label(normalized_line)
        or _normalized_test_label(normalized_line)
        or ROUND_LABEL_RE.fullmatch(normalized_line)
        or _normalized_round_and_section_label(normalized_line)
    )


def _is_generic_section_header(
    line: str,
    *,
    next_nonempty_line: str | None,
    following_nonempty_line: str | None,
    third_nonempty_line: str | None,
) -> bool:
    candidate = " ".join(line.split())
    normalized_next_line = " ".join((next_nonempty_line or "").split())
    candidate_problem_match = PROBLEM_START_RE.match(candidate)
    if _is_section_metadata_line(candidate):
        return False
    if (
        candidate_problem_match is not None
        and candidate_problem_match.group("statement")
        and not _is_structured_section_header(candidate)
        and not (
            _is_section_metadata_line(next_nonempty_line)
            and _is_problem_start_candidate(following_nonempty_line)
        )
    ):
        return False
    if SHORT_SECTION_HEADER_RE.fullmatch(candidate) and _is_problem_start_candidate(next_nonempty_line):
        return True
    if (
        " " in candidate
        and SHORT_SECTION_HEADER_RE.fullmatch(candidate)
        and _looks_like_generic_section_header_candidate(normalized_next_line)
        and (
            _is_problem_start_candidate(following_nonempty_line)
            or (
                _is_section_metadata_line(following_nonempty_line)
                and _is_problem_start_candidate(third_nonempty_line)
            )
        )
    ):
        return True
    if _is_problem_start_candidate(candidate):
        return False
    if (
        SHORT_SECTION_HEADER_RE.fullmatch(candidate)
        and _looks_like_generic_section_header_candidate(normalized_next_line)
        and (
            _is_problem_start_candidate(following_nonempty_line)
            or (
                _is_section_metadata_line(following_nonempty_line)
                and _is_problem_start_candidate(third_nonempty_line)
            )
        )
    ):
        return True
    if not _looks_like_generic_section_header_candidate(candidate):
        return False
    if (
        _supports_named_day_subsections(candidate)
        and DAY_LABEL_RE.fullmatch(" ".join((next_nonempty_line or "").split()))
        and (
            _is_problem_start_candidate(following_nonempty_line)
            or (
                _is_section_metadata_line(following_nonempty_line)
                and _is_problem_start_candidate(third_nonempty_line)
            )
        )
    ):
        return True
    if _is_section_metadata_line(next_nonempty_line) and _is_problem_start_candidate(following_nonempty_line):
        return True
    return bool(
        _is_section_metadata_line(next_nonempty_line)
        and _is_section_metadata_line(following_nonempty_line)
        and _is_problem_start_candidate(third_nonempty_line)
    )


def _next_problem_number_for_current_section(state: _StatementParseState) -> int:
    section_problem_numbers = [
        problem.problem_number
        for problem in state.parsed_problems
        if problem.day_label == state.current_day
    ]
    return max(section_problem_numbers, default=0) + 1


def _normalized_day_label(line: str) -> str | None:
    match = DAY_LABEL_RE.fullmatch(line)
    if match is None:
        return None
    token = match.group("token")
    normalized_token = token if token.isdigit() else token.upper()
    label = f"Day {normalized_token}"
    detail = " ".join((match.group("detail") or "").split())
    if not detail:
        return label
    return f"{label} · {detail}"


def _normalized_tst_day_label(line: str) -> str | None:
    match = TST_DAY_LABEL_RE.fullmatch(line)
    if match is None:
        return None
    label = f"TST #{int(match.group('number'))}"
    detail = " ".join((match.group("detail") or "").split())
    detail = re.sub(r"(?<=\d)\(", " (", detail)
    if not detail:
        return label
    return f"{label} · {detail}"


def _normalized_exam_day_label(line: str) -> str | None:
    match = EXAM_AND_DAY_LABEL_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    day_label = _normalized_day_label(match.group("day"))
    if day_label is None:
        return None
    return f"{match.group('exam').title()} exam · {day_label}"


def _normalized_year_prefixed_section_label(
    line: str,
    *,
    contest_year: int | None,
    next_nonempty_line: str | None,
) -> str | None:
    if contest_year is None or next_nonempty_line is None:
        return None
    match = YEAR_PREFIXED_SECTION_RE.fullmatch(line)
    if match is None or int(match.group("year")) != contest_year:
        return None
    if not _is_problem_start_candidate(next_nonempty_line):
        return None
    return _clean_contest_name(match.group("label"))


def _normalized_test_label(line: str) -> str | None:
    match = TEST_LABEL_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    token = match.group("number")
    normalized_token = str(int(token)) if token.isdigit() else token.upper()
    label = f"Test {normalized_token}"
    detail = " ".join((match.group("detail") or "").split())
    if not detail:
        return label
    if detail.startswith("(") and detail.endswith(")"):
        return f"{label} {detail}"
    return f"{label} · {detail}"


def _normalized_part_label(line: str) -> str | None:
    match = PART_LABEL_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    token = match.group("number")
    normalized_token = str(int(token)) if token.isdigit() else token.upper()
    label = f"Part {normalized_token}"
    detail = " ".join((match.group("detail") or "").split())
    if not detail:
        return label
    return f"{label} · {detail}"


def _normalized_round_and_section_label(line: str) -> str | None:
    match = ROUND_AND_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return f"{match.group('round').title()} Round · {match.group('label')}"


def _start_special_problem(state: _StatementParseState, match: re.Match[str]) -> None:
    _flush_problem(state)
    state.current_problem_code = match.group("code").upper()
    state.current_problem_number = _next_problem_number_for_current_section(state)
    state.awaiting_new_problem = False
    state.current_statement_lines = [match.group("statement").strip()]


def _start_alpha_problem(state: _StatementParseState, match: re.Match[str]) -> None:
    _flush_problem(state)
    state.current_problem_code = match.group("code").upper()
    state.current_problem_number = _next_problem_number_for_current_section(state)
    state.awaiting_new_problem = False
    state.current_statement_lines = [match.group("statement").strip()]


def _start_numbered_problem(state: _StatementParseState, match: re.Match[str]) -> None:
    _flush_problem(state)
    number = int(match.group("number"))
    prefix = (match.group("prefix") or "P").upper()
    statement_text = (match.group("statement") or "").strip()
    state.current_problem_code = f"{prefix}{number}"
    state.current_problem_number = number
    state.awaiting_new_problem = False
    state.current_statement_lines = (
        [_normalized_problem_statement_text(statement_text, number=number)]
        if statement_text
        else []
    )


def _can_start_inline_numbered_problem(
    state: _StatementParseState,
    problem_match: re.Match[str],
) -> bool:
    if state.current_problem_number is None:
        return True
    if state.awaiting_new_problem:
        return True
    if problem_match.group("catalog_number"):
        return True

    prefix = (problem_match.group("prefix") or "").strip()
    if prefix:
        return True

    number = int(problem_match.group("number"))
    statement = (problem_match.group("statement") or "").lstrip()
    if not statement:
        return False
    first_char = statement[:1]
    return number == state.current_problem_number + 1 and first_char.isalpha()


def _can_start_alpha_problem(state: _StatementParseState) -> bool:
    return state.current_problem_number is None or state.awaiting_new_problem


def _consume_header_or_problem_line(
    line: str,
    *,
    next_nonempty_line: str | None,
    following_nonempty_line: str | None,
    third_nonempty_line: str | None,
    state: _StatementParseState,
) -> bool:
    consumed = True
    if exam_day_label := _normalized_exam_day_label(line):
        _flush_problem(state)
        state.current_primary_section = exam_day_label.split(" · ", 1)[0]
        state.current_secondary_section = exam_day_label.split(" · ", 1)[1]
        state.current_day = exam_day_label
    elif day_label := _normalized_day_label(line):
        _flush_problem(state)
        if state.current_primary_section.startswith("TST #") or (
            state.current_primary_section
            and not state.current_primary_section.startswith("Day ")
            and (state.allows_day_subsection or bool(state.current_secondary_section))
        ):
            _set_day_subsection(state, day_label)
        else:
            _set_primary_section(state, day_label)
    elif tst_day_label := _normalized_tst_day_label(line):
        _flush_problem(state)
        _set_primary_section(state, tst_day_label)
    elif year_prefixed_section_label := _normalized_year_prefixed_section_label(
        line,
        contest_year=state.contest_year,
        next_nonempty_line=next_nonempty_line,
    ):
        _flush_problem(state)
        _set_primary_section(state, year_prefixed_section_label)
    elif round_and_section_label := _normalized_round_and_section_label(line):
        _flush_problem(state)
        state.current_primary_section = round_and_section_label.split(" · ", 1)[0]
        state.current_secondary_section = round_and_section_label.split(" · ", 1)[1]
        state.current_day = round_and_section_label
    elif inline_season_level_label := _normalized_inline_season_level_label(line):
        _flush_problem(state)
        state.current_primary_section = inline_season_level_label.split(" · ", 1)[0]
        state.current_secondary_section = inline_season_level_label.split(" · ", 1)[1]
        state.current_day = inline_season_level_label
    elif hyphenated_season_level_label := _normalized_hyphenated_season_level_label(line):
        _flush_problem(state)
        state.current_primary_section = hyphenated_season_level_label.split(" · ", 1)[0]
        state.current_secondary_section = hyphenated_season_level_label.split(" · ", 1)[1]
        state.current_day = hyphenated_season_level_label
    elif yearless_hyphenated_season_level_label := _normalized_yearless_hyphenated_season_level_label(
        line,
        contest_year=state.contest_year,
    ):
        _flush_problem(state)
        state.current_primary_section = yearless_hyphenated_season_level_label.split(" · ", 1)[0]
        state.current_secondary_section = yearless_hyphenated_season_level_label.split(" · ", 1)[1]
        state.current_day = yearless_hyphenated_season_level_label
    elif yearless_season_level_label := _normalized_yearless_season_level_label(
        line,
        contest_year=state.contest_year,
    ):
        _flush_problem(state)
        state.current_primary_section = yearless_season_level_label.split(" · ", 1)[0]
        state.current_secondary_section = yearless_season_level_label.split(" · ", 1)[1]
        state.current_day = yearless_season_level_label
    elif round_prefixed_yearless_season_level_label := _normalized_round_prefixed_yearless_season_level_label(
        line,
        contest_year=state.contest_year,
    ):
        _flush_problem(state)
        state.current_primary_section = round_prefixed_yearless_season_level_label.split(" · ", 1)[0]
        state.current_secondary_section = round_prefixed_yearless_season_level_label.split(" · ", 1)[1]
        state.current_day = round_prefixed_yearless_season_level_label
    elif season_label := _normalized_season_section_label(line):
        _flush_problem(state)
        _set_primary_section(state, season_label)
    elif division_label := _normalized_division_section_label(line):
        _flush_problem(state)
        _set_division_section(state, division_label)
    elif track_label := _normalized_track_section_label(line):
        _flush_problem(state)
        _set_track_section(state, track_label)
    elif grade_label := _normalized_grade_section_label(line):
        _flush_problem(state)
        _set_primary_section(state, grade_label)
    elif grade_level_label := _normalized_grade_level_section_label(line):
        _flush_problem(state)
        _set_primary_section(state, grade_level_label)
    elif round_match := ROUND_LABEL_RE.fullmatch(line):
        _flush_problem(state)
        _set_primary_section(state, round_match.group("label").title())
    elif part_label := _normalized_part_label(line):
        _flush_problem(state)
        _set_primary_section(state, part_label)
    elif test_label := _normalized_test_label(line):
        _flush_problem(state)
        if (
            (
                state.current_primary_section
                and not state.current_secondary_section
                and _normalized_test_label(state.current_primary_section) is None
                and _is_problem_start_candidate(next_nonempty_line)
            )
            or state.current_primary_section.startswith("Round ")
            or state.current_primary_section.startswith("TST #")
        ):
            _set_secondary_section(state, test_label)
        else:
            _set_primary_section(
                state,
                test_label,
                allows_day_subsection=(
                    DAY_LABEL_RE.fullmatch(" ".join((next_nonempty_line or "").split())) is not None
                ),
            )
    elif (
        state.current_primary_section
        and state.allows_section_date_metadata
        and not state.current_secondary_section
        and (section_date_label := _normalized_section_date_label(line))
        and (
            _is_problem_start_candidate(next_nonempty_line)
            or (
                _is_section_metadata_line(next_nonempty_line)
                and _is_problem_start_candidate(following_nonempty_line)
            )
        )
    ):
        _flush_problem(state)
        _set_secondary_section(state, section_date_label)
    elif level_label := _normalized_level_section_label(line):
        _flush_problem(state)
        _set_secondary_section(state, level_label)
    elif paper_label := _normalized_paper_section_label(line):
        _flush_problem(state)
        _set_primary_section(state, paper_label)
    elif section_label := _normalized_section_label(line):
        _flush_problem(state)
        _set_primary_section(state, section_label)
    elif _is_generic_section_header(
        line,
        next_nonempty_line=next_nonempty_line,
        following_nonempty_line=following_nonempty_line,
        third_nonempty_line=third_nonempty_line,
    ):
        _flush_problem(state)
        generic_section_label = " ".join(line.split())
        if (
            state.current_primary_section
            and not state.current_secondary_section
            and " " in generic_section_label
            and _is_problem_start_candidate(next_nonempty_line)
            and not _is_structured_section_header(next_nonempty_line)
        ):
            _set_secondary_section(state, generic_section_label)
        else:
            _set_primary_section(
                state,
                generic_section_label,
                allows_section_date_metadata=(
                    SHORT_SECTION_HEADER_RE.fullmatch(generic_section_label) is None
                    or any(character.isdigit() for character in generic_section_label)
                ),
                allows_day_subsection=(
                    _supports_named_day_subsections(generic_section_label)
                    and DAY_LABEL_RE.fullmatch(" ".join((next_nonempty_line or "").split())) is not None
                ),
            )
    elif (
        (state.current_problem_number is None or state.awaiting_new_problem)
        and (special_problem_match := SPECIAL_PROBLEM_CODE_RE.match(line))
    ):
        _start_special_problem(state, special_problem_match)
    elif (alpha_problem_match := ALPHA_PROBLEM_CODE_RE.match(line)) and _can_start_alpha_problem(state):
        _start_alpha_problem(state, alpha_problem_match)
    elif (problem_match := PROBLEM_START_RE.match(line)) and _can_start_inline_numbered_problem(
        state,
        problem_match,
    ):
        _start_numbered_problem(state, problem_match)
    else:
        consumed = False
    return consumed


def _consume_statement_line(
    raw_line: str,
    *,
    next_nonempty_line: str | None,
    following_nonempty_line: str | None,
    third_nonempty_line: str | None,
    state: _StatementParseState,
) -> None:
    line = raw_line.strip()
    if not line:
        if state.current_problem_number is not None:
            state.current_statement_lines.append("")
        return

    if _is_scrape_metadata_line(
        line,
        next_nonempty_line=next_nonempty_line,
        following_nonempty_line=following_nonempty_line,
        third_nonempty_line=third_nonempty_line,
    ):
        if state.current_problem_number is not None:
            state.awaiting_new_problem = True
        return

    if _consume_header_or_problem_line(
        line,
        next_nonempty_line=next_nonempty_line,
        following_nonempty_line=following_nonempty_line,
        third_nonempty_line=third_nonempty_line,
        state=state,
    ):
        return

    if state.current_problem_number is not None:
        state.current_statement_lines.append(line)
        state.awaiting_new_problem = False


def parse_contest_problem_statements(raw_text: str) -> ParsedContestStatementImport:
    lines = _normalized_statement_lines(raw_text)
    contest_year, contest_name, remaining_lines = _parse_contest_header(lines)
    state = _StatementParseState(contest_year=contest_year, contest_name=contest_name)

    for index, raw_line in enumerate(remaining_lines):
        next_nonempty_lines = _next_nonempty_lines(remaining_lines, index, limit=3)
        _consume_statement_line(
            raw_line,
            next_nonempty_line=next_nonempty_lines[0] if next_nonempty_lines else None,
            following_nonempty_line=next_nonempty_lines[1] if len(next_nonempty_lines) > 1 else None,
            third_nonempty_line=next_nonempty_lines[2] if len(next_nonempty_lines) > 2 else None,
            state=state,
        )

    _flush_problem(state)

    if not state.parsed_problems:
        msg = "No numbered problems were detected in the pasted text."
        raise ProblemStatementImportValidationError(msg)

    parsed_problems = _promote_implicit_senior_sections(state.parsed_problems)

    return ParsedContestStatementImport(
        contest_year=contest_year,
        contest_name=contest_name,
        problems=tuple(parsed_problems),
    )


def _promote_implicit_senior_sections(
    parsed_problems: list[ParsedContestProblemStatement],
) -> list[ParsedContestProblemStatement]:
    primary_sections_with_explicit_junior = {
        label_parts[0]
        for problem in parsed_problems
        if problem.day_label
        for label_parts in [problem.day_label.split(" · ")]
        if len(label_parts) >= 2 and label_parts[1] == "Junior"
    }

    if not primary_sections_with_explicit_junior:
        return parsed_problems

    rewritten_problems: list[ParsedContestProblemStatement] = []
    for problem in parsed_problems:
        label_parts = [part for part in problem.day_label.split(" · ") if part]
        if (
            len(label_parts) >= 2
            and label_parts[0] in primary_sections_with_explicit_junior
            and not any(part in {"Junior", "Senior"} for part in label_parts[1:])
        ):
            label_parts.insert(1, "Senior")
            rewritten_problems.append(
                ParsedContestProblemStatement(
                    day_label=" · ".join(label_parts),
                    problem_code=problem.problem_code,
                    problem_number=problem.problem_number,
                    statement_latex=problem.statement_latex,
                ),
            )
            continue
        rewritten_problems.append(problem)
    return rewritten_problems


def _find_linked_problem(
    *,
    contest_year: int,
    contest_name: str,
    problem_code: str,
    problem_number: int,
) -> ProblemSolveRecord | None:
    linked_problem = ProblemSolveRecord.objects.filter(
        year=contest_year,
        contest=contest_name,
        problem__iexact=problem_code,
    ).first()
    if linked_problem is not None:
        return linked_problem
    if problem_code.upper() != f"P{problem_number}":
        return None
    return ProblemSolveRecord.objects.filter(
        year=contest_year,
        contest=contest_name,
        problem=str(problem_number),
    ).first()


def _problem_code_occurrences(
    parsed_import: ParsedContestStatementImport,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for problem in parsed_import.problems:
        counts[problem.problem_code] = counts.get(problem.problem_code, 0) + 1
    return counts


def _existing_statement_lookup(
    parsed_import: ParsedContestStatementImport,
) -> tuple[
    dict[tuple[str, str], ContestProblemStatement],
    dict[str, list[ContestProblemStatement]],
]:
    existing_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=parsed_import.contest_year,
            contest_name=parsed_import.contest_name,
            problem_code__in=[problem.problem_code for problem in parsed_import.problems],
        ),
    )
    existing_by_day_and_code = {
        (statement.day_label, statement.problem_code): statement
        for statement in existing_rows
    }
    existing_by_code: dict[str, list[ContestProblemStatement]] = {}
    for statement in existing_rows:
        existing_by_code.setdefault(statement.problem_code, []).append(statement)
    return existing_by_day_and_code, existing_by_code


def _find_existing_statement(
    *,
    day_label: str,
    problem_code: str,
    problem_code_counts: dict[str, int],
    existing_by_day_and_code: dict[tuple[str, str], ContestProblemStatement],
    existing_by_code: dict[str, list[ContestProblemStatement]],
) -> ContestProblemStatement | None:
    exact_match = existing_by_day_and_code.get((day_label, problem_code))
    if exact_match is not None or problem_code_counts[problem_code] != 1:
        return exact_match

    fallback_matches = existing_by_code.get(problem_code, [])
    if len(fallback_matches) == 1:
        return fallback_matches[0]
    return None


def build_problem_statement_preview_payload(
    parsed_import: ParsedContestStatementImport,
) -> ProblemStatementPreviewPayload:
    day_counts: dict[str, int] = {}
    problem_rows: list[PreviewProblemRow] = []
    problem_code_counts = _problem_code_occurrences(parsed_import)

    for parsed_problem in parsed_import.problems:
        day_key = parsed_problem.day_label or "Unlabeled"
        day_counts[day_key] = day_counts.get(day_key, 0) + 1
        linked_problem = None
        if problem_code_counts[parsed_problem.problem_code] == 1:
            linked_problem = _find_linked_problem(
                contest_year=parsed_import.contest_year,
                contest_name=parsed_import.contest_name,
                problem_code=parsed_problem.problem_code,
                problem_number=parsed_problem.problem_number,
            )
        problem_rows.append(
            {
                "contest_year_problem": (
                    f"{parsed_import.contest_name} {parsed_import.contest_year} {parsed_problem.problem_code}"
                ),
                "day_label": parsed_problem.day_label or "Unlabeled",
                "problem_code": parsed_problem.problem_code,
                "problem_number": parsed_problem.problem_number,
                "statement_latex": parsed_problem.statement_latex,
                "linked_problem_label": (
                    linked_problem.contest_year_problem or ""
                    if linked_problem
                    else ""
                ),
            },
        )

    day_rows: list[PreviewDayRow] = [
        {"label": label, "problem_count": count}
        for label, count in day_counts.items()
    ]

    return {
        "contest_name": parsed_import.contest_name,
        "contest_year": parsed_import.contest_year,
        "day_rows": day_rows,
        "problem_count": len(problem_rows),
        "problems": problem_rows,
    }


def build_problem_statement_save_preview(
    parsed_import: ParsedContestStatementImport,
) -> ProblemStatementSavePreviewPayload:
    problem_code_counts = _problem_code_occurrences(parsed_import)
    existing_by_day_and_code, existing_by_code = _existing_statement_lookup(parsed_import)

    create_count = 0
    update_count = 0
    unchanged_count = 0
    existing_problem_codes: list[str] = []
    update_problem_codes: list[str] = []
    unchanged_problem_codes: list[str] = []

    for parsed_problem in parsed_import.problems:
        existing_statement = _find_existing_statement(
            day_label=parsed_problem.day_label,
            problem_code=parsed_problem.problem_code,
            problem_code_counts=problem_code_counts,
            existing_by_day_and_code=existing_by_day_and_code,
            existing_by_code=existing_by_code,
        )
        if existing_statement is None:
            create_count += 1
            continue

        existing_problem_codes.append(parsed_problem.problem_code)
        linked_problem = None
        if problem_code_counts[parsed_problem.problem_code] == 1:
            linked_problem = _find_linked_problem(
                contest_year=parsed_import.contest_year,
                contest_name=parsed_import.contest_name,
                problem_code=parsed_problem.problem_code,
                problem_number=parsed_problem.problem_number,
            )
        linked_problem_id = linked_problem.id if linked_problem is not None else None
        is_unchanged = (
            existing_statement.day_label == parsed_problem.day_label
            and existing_statement.statement_latex == parsed_problem.statement_latex
            and existing_statement.linked_problem_id == linked_problem_id
        )
        if is_unchanged:
            unchanged_count += 1
            unchanged_problem_codes.append(parsed_problem.problem_code)
        else:
            update_count += 1
            update_problem_codes.append(parsed_problem.problem_code)

    return {
        "create_count": create_count,
        "update_count": update_count,
        "unchanged_count": unchanged_count,
        "existing_count": len(existing_problem_codes),
        "existing_problem_codes": existing_problem_codes,
        "update_problem_codes": update_problem_codes,
        "unchanged_problem_codes": unchanged_problem_codes,
    }


@transaction.atomic
def import_problem_statements(
    parsed_import: ParsedContestStatementImport,
) -> ProblemStatementImportResult:
    created_count = 0
    updated_count = 0
    linked_problem_count = 0
    problem_code_counts = _problem_code_occurrences(parsed_import)
    existing_by_day_and_code, existing_by_code = _existing_statement_lookup(parsed_import)

    for parsed_problem in parsed_import.problems:
        linked_problem = None
        if problem_code_counts[parsed_problem.problem_code] == 1:
            linked_problem = _find_linked_problem(
                contest_year=parsed_import.contest_year,
                contest_name=parsed_import.contest_name,
                problem_code=parsed_problem.problem_code,
                problem_number=parsed_problem.problem_number,
            )
        statement_entry = _find_existing_statement(
            day_label=parsed_problem.day_label,
            problem_code=parsed_problem.problem_code,
            problem_code_counts=problem_code_counts,
            existing_by_day_and_code=existing_by_day_and_code,
            existing_by_code=existing_by_code,
        )
        if statement_entry is None:
            statement_entry = ContestProblemStatement.objects.create(
                contest_year=parsed_import.contest_year,
                contest_name=parsed_import.contest_name,
                day_label=parsed_problem.day_label,
                linked_problem=linked_problem,
                problem_number=parsed_problem.problem_number,
                problem_code=parsed_problem.problem_code,
                statement_latex=parsed_problem.statement_latex,
            )
            existing_by_day_and_code[(statement_entry.day_label, statement_entry.problem_code)] = statement_entry
            existing_by_code.setdefault(statement_entry.problem_code, []).append(statement_entry)
            created_count += 1
        else:
            previous_key = (statement_entry.day_label, statement_entry.problem_code)
            statement_entry.day_label = parsed_problem.day_label
            statement_entry.linked_problem = linked_problem
            statement_entry.problem_number = parsed_problem.problem_number
            statement_entry.problem_code = parsed_problem.problem_code
            statement_entry.statement_latex = parsed_problem.statement_latex
            statement_entry.save()
            if previous_key != (statement_entry.day_label, statement_entry.problem_code):
                existing_by_day_and_code.pop(previous_key, None)
                existing_by_day_and_code[(statement_entry.day_label, statement_entry.problem_code)] = statement_entry
            updated_count += 1

        if statement_entry.linked_problem_id is not None:
            statement_entry.refresh_from_db()
            sync_statement_analytics_from_linked_problem(statement_entry)
            linked_problem_count += 1

    return ProblemStatementImportResult(
        created_count=created_count,
        updated_count=updated_count,
        linked_problem_count=linked_problem_count,
    )


@transaction.atomic
def relink_problem_statement_rows() -> ProblemStatementRelinkResult:
    checked_count = 0
    linked_count = 0
    newly_linked_count = 0
    skipped_count = 0
    unlinked_count = 0
    updated_count = 0
    statements = list(ContestProblemStatement.objects.select_related("linked_problem").order_by("id"))
    problem_code_counts: dict[tuple[int, str, str], int] = {}
    claimed_problem_uuids = {
        statement.problem_uuid: statement.id
        for statement in statements
    }

    for statement in statements:
        code_key = (
            statement.contest_year,
            statement.contest_name,
            statement.problem_code,
        )
        problem_code_counts[code_key] = problem_code_counts.get(code_key, 0) + 1

    for statement in statements:
        code_key = (
            statement.contest_year,
            statement.contest_name,
            statement.problem_code,
        )
        if problem_code_counts[code_key] != 1:
            skipped_count += 1
            checked_count += 1
            if statement.linked_problem_id is not None:
                linked_count += 1
            else:
                unlinked_count += 1
            continue

        linked_problem = _find_linked_problem(
            contest_year=statement.contest_year,
            contest_name=statement.contest_name,
            problem_code=statement.problem_code,
            problem_number=statement.problem_number,
        )
        previous_linked_problem_id = statement.linked_problem_id
        next_linked_problem_id = linked_problem.id if linked_problem is not None else None
        previous_problem_uuid = statement.problem_uuid

        if linked_problem is not None:
            conflicting_statement_id = claimed_problem_uuids.get(linked_problem.problem_uuid)
            if conflicting_statement_id not in (None, statement.id):
                skipped_count += 1
                checked_count += 1
                if statement.linked_problem_id is not None:
                    linked_count += 1
                else:
                    unlinked_count += 1
                continue

        if previous_linked_problem_id != next_linked_problem_id:
            statement.linked_problem = linked_problem
            statement.save(update_fields={"linked_problem", "updated_at"})
            updated_count += 1
            if previous_linked_problem_id is None and next_linked_problem_id is not None:
                newly_linked_count += 1
            claimed_problem_uuids.pop(previous_problem_uuid, None)
            claimed_problem_uuids[statement.problem_uuid] = statement.id
            if statement.linked_problem_id is not None:
                statement.refresh_from_db()
                sync_statement_analytics_from_linked_problem(statement)

        checked_count += 1
        if statement.linked_problem_id is not None:
            linked_count += 1
        else:
            unlinked_count += 1

    return ProblemStatementRelinkResult(
        checked_count=checked_count,
        linked_count=linked_count,
        newly_linked_count=newly_linked_count,
        skipped_count=skipped_count,
        unlinked_count=unlinked_count,
        updated_count=updated_count,
    )
