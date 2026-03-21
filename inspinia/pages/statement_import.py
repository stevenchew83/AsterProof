from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field
from typing import TypedDict

from django.db import transaction

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord

IGNORED_STATEMENT_LINES = {
    "Stuttgarden",
    "view topic",
}
DAY_LABEL_RE = re.compile(
    r"^Day\s+(?P<token>\d+|[IVXLCDM]+)(?:\s+(?P<detail>.+))?$",
    flags=re.IGNORECASE,
)
TST_DAY_LABEL_RE = re.compile(
    r"^TST\s*#\s*(?P<number>\d+)(?:\s+(?P<detail>.+))?$",
    flags=re.IGNORECASE,
)
ROUND_LABEL_RE = re.compile(r"^(?:\d+\s+)?(?P<label>Round\s+[A-Za-z0-9].*)$", flags=re.IGNORECASE)
SOLUTION_LINE_RE = re.compile(r"^Solution$", flags=re.IGNORECASE)
TEST_LABEL_RE = re.compile(r"^Test\s+\d+$", flags=re.IGNORECASE)
PROBLEM_START_RE = re.compile(
    r"^(?:(?P<prefix>[A-Za-z]{1,4})\s*)?(?P<number>\d{1,3})[.)]?\s+(?P<statement>.+)$",
    flags=re.IGNORECASE,
)
TEXT_ONLY_EMPH_INLINE_RE = re.compile(r"\$(?P<content>\\emph\{[^$]+?\})\$")
TEXT_ONLY_EMPH_PAREN_RE = re.compile(r"\\\((?P<content>\\emph\{.*?\})\\\)", flags=re.DOTALL)
TEXT_ONLY_EMPH_DISPLAY_RE = re.compile(r"\$\$(?P<content>\\emph\{.*?\})\$\$", flags=re.DOTALL)
TEXT_ONLY_EMPH_BRACKET_RE = re.compile(r"\\\[(?P<content>\\emph\{.*?\})\\\]", flags=re.DOTALL)
SECTION_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9][A-Za-z0-9]*){0,3}$")
SPECIAL_PROBLEM_CODE_RE = re.compile(r"^(?P<code>Bonus)[.)]?\s+(?P<statement>.+)$", flags=re.IGNORECASE)
TRAILING_AUTHOR_LINE_RE = re.compile(
    r"^[A-Z][A-Za-z'.-]*(?: [A-Z][A-Za-z'.-]*)*(?: and [A-Z][A-Za-z'.-]*(?: [A-Z][A-Za-z'.-]*)*)?$",
)
TRAILING_PROPOSED_BY_LINE_RE = re.compile(r"^(?:\(?\s*)proposed by\b.+$", flags=re.IGNORECASE)
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
    current_day: str = ""
    current_primary_section: str = ""
    current_secondary_section: str = ""
    current_problem_code: str | None = None
    current_problem_number: int | None = None
    awaiting_new_problem: bool = False
    current_statement_lines: list[str] = field(default_factory=list)
    parsed_problems: list[ParsedContestProblemStatement] = field(default_factory=list)


def _clean_contest_name(raw_name: str) -> str:
    cleaned_name = re.sub(r"(?<!\s)\d+$", "", raw_name.strip())
    return cleaned_name.strip()


def _parse_header_line(header_line: str) -> tuple[int, str]:
    match = re.match(r"^\s*(?P<year>\d{4})\s+(?P<contest>.+?)\s*$", header_line)
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


def _supports_trailing_credit_cleanup(day_label: str) -> bool:
    return day_label.upper().startswith("TST #")


def _is_trailing_credit_line(line: str, *, day_label: str) -> bool:
    if not _supports_trailing_credit_cleanup(day_label):
        return False
    return bool(
        TRAILING_PROPOSED_BY_LINE_RE.fullmatch(line)
        or TRAILING_AUTHOR_LINE_RE.fullmatch(line),
    )


def _trim_trailing_problem_metadata(lines: list[str], *, day_label: str) -> list[str]:
    trimmed_lines = list(lines)

    while trimmed_lines and not trimmed_lines[-1].strip():
        trimmed_lines.pop()

    while trimmed_lines and _is_trailing_credit_line(trimmed_lines[-1].strip(), day_label=day_label):
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

    contest_year, contest_name = _parse_header_line(lines[header_index].strip())
    return contest_year, contest_name, lines[header_index + 1 :]


def _flush_problem(state: _StatementParseState) -> None:
    if state.current_problem_number is None:
        return

    statement_latex = _collapse_statement_lines(
        _trim_trailing_problem_metadata(
            state.current_statement_lines,
            day_label=state.current_day,
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


def _set_primary_section(state: _StatementParseState, label: str) -> None:
    state.current_primary_section = label
    state.current_secondary_section = ""
    state.current_day = _compose_section_label(
        state.current_primary_section,
        state.current_secondary_section,
    )


def _set_secondary_section(state: _StatementParseState, label: str) -> None:
    state.current_secondary_section = label
    state.current_day = _compose_section_label(
        state.current_primary_section,
        state.current_secondary_section,
    )


def _next_nonempty_line(lines: list[str], current_index: int) -> str | None:
    for raw_line in lines[current_index + 1 :]:
        candidate = raw_line.strip()
        if candidate:
            return candidate
    return None


def _is_scrape_metadata_line(line: str, *, next_nonempty_line: str | None) -> bool:
    if line in IGNORED_STATEMENT_LINES:
        return True
    if SOLUTION_LINE_RE.fullmatch(line):
        return True
    return next_nonempty_line == "view topic"


def _normalized_section_label(line: str) -> str | None:
    candidate = " ".join(line.split())
    for label in SECTION_HEADER_LABELS:
        if candidate.casefold() == label.casefold():
            return label
    return None


def _is_generic_section_header(line: str, *, next_nonempty_line: str | None) -> bool:
    if next_nonempty_line is None:
        return False
    candidate = " ".join(line.split())
    if not SECTION_HEADER_RE.fullmatch(candidate):
        return False
    return bool(PROBLEM_START_RE.match(next_nonempty_line) or SPECIAL_PROBLEM_CODE_RE.match(next_nonempty_line))


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
    if not detail:
        return label
    return f"{label} · {detail}"


def _start_special_problem(state: _StatementParseState, match: re.Match[str]) -> None:
    _flush_problem(state)
    state.current_problem_code = match.group("code").upper()
    state.current_problem_number = _next_problem_number_for_current_section(state)
    state.awaiting_new_problem = False
    state.current_statement_lines = [match.group("statement").strip()]


def _start_numbered_problem(state: _StatementParseState, match: re.Match[str]) -> None:
    _flush_problem(state)
    number = int(match.group("number"))
    prefix = (match.group("prefix") or "P").upper()
    state.current_problem_code = f"{prefix}{number}"
    state.current_problem_number = number
    state.awaiting_new_problem = False
    state.current_statement_lines = [match.group("statement").strip()]


def _can_start_inline_numbered_problem(
    state: _StatementParseState,
    problem_match: re.Match[str],
) -> bool:
    if state.current_problem_number is None:
        return True
    if state.awaiting_new_problem:
        return True

    prefix = (problem_match.group("prefix") or "").strip()
    if prefix:
        return True

    number = int(problem_match.group("number"))
    statement = problem_match.group("statement").lstrip()
    first_char = statement[:1]
    return number == state.current_problem_number + 1 and first_char.isalpha()


def _consume_header_or_problem_line(
    line: str,
    *,
    next_nonempty_line: str | None,
    state: _StatementParseState,
) -> bool:
    consumed = True
    if day_label := _normalized_day_label(line):
        _flush_problem(state)
        _set_primary_section(state, day_label)
    elif tst_day_label := _normalized_tst_day_label(line):
        _flush_problem(state)
        _set_primary_section(state, tst_day_label)
    elif round_match := ROUND_LABEL_RE.fullmatch(line):
        _flush_problem(state)
        _set_primary_section(state, round_match.group("label").title())
    elif test_match := TEST_LABEL_RE.fullmatch(line):
        _flush_problem(state)
        _set_secondary_section(state, test_match.group(0).title())
    elif section_label := _normalized_section_label(line):
        _flush_problem(state)
        _set_primary_section(state, section_label)
    elif _is_generic_section_header(line, next_nonempty_line=next_nonempty_line):
        _flush_problem(state)
        _set_primary_section(state, " ".join(line.split()))
    elif (
        (state.current_problem_number is None or state.awaiting_new_problem)
        and (special_problem_match := SPECIAL_PROBLEM_CODE_RE.match(line))
    ):
        _start_special_problem(state, special_problem_match)
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
    state: _StatementParseState,
) -> None:
    line = raw_line.strip()
    if not line:
        if state.current_problem_number is not None:
            state.current_statement_lines.append("")
        return

    if _is_scrape_metadata_line(line, next_nonempty_line=next_nonempty_line):
        if state.current_problem_number is not None:
            state.awaiting_new_problem = True
        return

    if _consume_header_or_problem_line(
        line,
        next_nonempty_line=next_nonempty_line,
        state=state,
    ):
        return

    if state.current_problem_number is not None:
        state.current_statement_lines.append(line)
        state.awaiting_new_problem = False


def parse_contest_problem_statements(raw_text: str) -> ParsedContestStatementImport:
    lines = _normalized_statement_lines(raw_text)
    contest_year, contest_name, remaining_lines = _parse_contest_header(lines)
    state = _StatementParseState()

    for index, raw_line in enumerate(remaining_lines):
        _consume_statement_line(
            raw_line,
            next_nonempty_line=_next_nonempty_line(remaining_lines, index),
            state=state,
        )

    _flush_problem(state)

    if not state.parsed_problems:
        msg = "No numbered problems were detected in the pasted text."
        raise ProblemStatementImportValidationError(msg)

    return ParsedContestStatementImport(
        contest_year=contest_year,
        contest_name=contest_name,
        problems=tuple(state.parsed_problems),
    )


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
