"""Shared logic for importing user problem completion dates from Excel."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Any
from typing import BinaryIO
from uuid import UUID

import pandas as pd
from django.contrib.auth import get_user_model
from django.db import transaction

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.problem_import import ProblemImportValidationError
from inspinia.pages.problem_import import _cell_int
from inspinia.pages.problem_import import _cell_str
from inspinia.pages.topic_tags_parse import parse_contest_problem_string

if TYPE_CHECKING:
    from pathlib import Path


COMPLETION_REQUIRED_COLUMNS = frozenset({"USER EMAIL", "COMPLETION DATE"})
COMPLETION_STATEMENT_UUID_COLUMN = "STATEMENT UUID"
COMPLETION_UUID_COLUMN = "PROBLEM UUID"
COMPLETION_CONTEST_PROBLEM_COLUMN = "CONTEST PROBLEM"
COMPLETION_NATURAL_KEY_COLUMNS = frozenset({"YEAR", "CONTEST", "PROBLEM"})
UNKNOWN_COMPLETION_TOKENS = {"done", "complete", "completed"}
COMPLETION_HEADER_UUID_TOKENS = {"problem uuid", "uuid"}
COMPLETION_HEADER_DATE_TOKENS = {"date", "completion date"}
COMPLETION_TEXT_PART_COUNT = 2
COMPLETION_TEXT_HEADER_LINES = frozenset(
    {
        "problem uuid date",
        "problem uuid completion date",
        "statement uuid date",
        "statement uuid completion date",
        "uuid date",
        "uuid completion date",
    },
)


@dataclass
class PreparedCompletionImportRow:
    user_email: str
    completion_date: date | None
    date_unknown: bool
    statement_uuid: UUID | None
    problem_uuid: UUID | None
    year: int | None
    contest: str | None
    problem: str | None


@dataclass
class ProblemCompletionImportResult:
    n_completions: int = 0
    n_unknown_dates: int = 0
    warnings: list[str] = field(default_factory=list)


def _parse_completion_value(value: Any) -> tuple[bool, date | None, bool]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return (False, None, False)

    parsed_date: date | None
    if isinstance(value, datetime):
        parsed_date = value.date()
    elif isinstance(value, date):
        parsed_date = value
    else:
        text = _cell_str(value)
        if not text:
            return (False, None, False)
        if text.casefold() in UNKNOWN_COMPLETION_TOKENS:
            return (True, None, True)

        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            return (False, None, False)
        parsed_date = parsed.date()

    return (True, parsed_date, False)


def _parse_problem_uuid(value: Any) -> UUID | None:
    text = _cell_str(value)
    if not text:
        return None
    try:
        return UUID(text)
    except (TypeError, ValueError):
        return None


def completion_dataframe_from_excel(source: Path | str | BinaryIO | bytes) -> pd.DataFrame:
    """Load completion workbook; normalize column headers (strip)."""
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    try:
        dataframe = pd.read_excel(source)
    except Exception as exc:
        msg = "Could not read Excel file. Is it a valid .xlsx?"
        raise ProblemImportValidationError(msg) from exc

    dataframe.columns = [str(column).strip() for column in dataframe.columns]
    missing = COMPLETION_REQUIRED_COLUMNS - set(dataframe.columns)
    if missing:
        msg = (
            f"Missing required column(s): {', '.join(sorted(missing))}. "
            f"Found columns: {list(dataframe.columns)}"
        )
        raise ProblemImportValidationError(msg)

    has_statement_uuid = COMPLETION_STATEMENT_UUID_COLUMN in dataframe.columns
    has_uuid = COMPLETION_UUID_COLUMN in dataframe.columns
    has_natural_key = COMPLETION_NATURAL_KEY_COLUMNS.issubset(dataframe.columns)
    has_contest_problem = COMPLETION_CONTEST_PROBLEM_COLUMN in dataframe.columns
    if not has_statement_uuid and not has_uuid and not has_natural_key and not has_contest_problem:
        msg = (
            "Workbook must include either STATEMENT UUID, PROBLEM UUID, YEAR+CONTEST+PROBLEM, "
            "or CONTEST PROBLEM so completion rows can be matched to imported problems."
        )
        raise ProblemImportValidationError(msg)

    return dataframe


def prepare_problem_completion_rows(
    df: pd.DataFrame,
) -> tuple[list[PreparedCompletionImportRow], list[str]]:
    prepared: list[PreparedCompletionImportRow] = []
    warnings: list[str] = []

    for _, row in df.iterrows():
        user_email = _cell_str(row.get("USER EMAIL"))
        is_valid_completion, completion_date, date_unknown = _parse_completion_value(
            row.get("COMPLETION DATE"),
        )
        statement_uuid = _parse_problem_uuid(row.get(COMPLETION_STATEMENT_UUID_COLUMN))
        problem_uuid = _parse_problem_uuid(row.get(COMPLETION_UUID_COLUMN))

        if not user_email:
            warnings.append("Skipped row: missing USER EMAIL.")
            continue
        if not is_valid_completion:
            warnings.append(f"Skipped row for {user_email}: invalid COMPLETION DATE.")
            continue

        year = _cell_int(row.get("YEAR"))
        contest = _cell_str(row.get("CONTEST"))
        problem = _cell_str(row.get("PROBLEM"))
        if (not contest or not problem) and COMPLETION_CONTEST_PROBLEM_COLUMN in df.columns:
            combined = _cell_str(row.get(COMPLETION_CONTEST_PROBLEM_COLUMN))
            if combined:
                parsed_year, parsed_contest, parsed_problem = parse_contest_problem_string(
                    combined,
                    year_hint=year,
                )
                year = year if year is not None else parsed_year
                contest = contest or parsed_contest or None
                problem = problem or parsed_problem or None

        if statement_uuid is None and problem_uuid is None and (year is None or not contest or not problem):
            warnings.append(
                f"Skipped row for {user_email}: unable to resolve problem without STATEMENT UUID, PROBLEM UUID "
                "or a valid YEAR/CONTEST/PROBLEM reference.",
            )
            continue

        prepared.append(
            PreparedCompletionImportRow(
                user_email=user_email,
                completion_date=completion_date,
                date_unknown=date_unknown,
                statement_uuid=statement_uuid,
                problem_uuid=problem_uuid,
                year=year,
                contest=contest,
                problem=problem,
            ),
        )

    return prepared, warnings


def import_problem_completion_dataframe(df: pd.DataFrame) -> ProblemCompletionImportResult:
    result = ProblemCompletionImportResult()
    prepared, warnings = prepare_problem_completion_rows(df)
    result.warnings.extend(warnings)

    user_model = get_user_model()
    user_cache: dict[str, Any | None] = {}
    statement_by_uuid_cache: dict[UUID, ContestProblemStatement | None] = {}
    problem_by_uuid_cache: dict[UUID, ProblemSolveRecord | None] = {}
    problem_by_natural_key_cache: dict[tuple[int, str, str], ProblemSolveRecord | None] = {}

    with transaction.atomic():
        for row in prepared:
            email_key = row.user_email.casefold()
            if email_key not in user_cache:
                user_cache[email_key] = user_model.objects.filter(email__iexact=row.user_email).first()
            user = user_cache[email_key]
            if user is None:
                result.warnings.append(f"Skipped row for {row.user_email}: user not found.")
                continue

            statement: ContestProblemStatement | None = None
            problem: ProblemSolveRecord | None
            if row.statement_uuid is not None:
                if row.statement_uuid not in statement_by_uuid_cache:
                    statement_by_uuid_cache[row.statement_uuid] = (
                        ContestProblemStatement.objects.select_related("linked_problem")
                        .filter(statement_uuid=row.statement_uuid)
                        .first()
                    )
                statement = statement_by_uuid_cache[row.statement_uuid]
                problem = statement.linked_problem if statement is not None else None
            elif row.problem_uuid is not None:
                if row.problem_uuid not in problem_by_uuid_cache:
                    problem_by_uuid_cache[row.problem_uuid] = (
                        ProblemSolveRecord.objects.filter(problem_uuid=row.problem_uuid).first()
                    )
                problem = problem_by_uuid_cache[row.problem_uuid]
            else:
                assert row.year is not None
                assert row.contest is not None
                assert row.problem is not None
                natural_key = (row.year, row.contest, row.problem)
                if natural_key not in problem_by_natural_key_cache:
                    problem_by_natural_key_cache[natural_key] = (
                        ProblemSolveRecord.objects.filter(
                            year=row.year,
                            contest=row.contest,
                            problem=row.problem,
                        ).first()
                    )
                problem = problem_by_natural_key_cache[natural_key]

            if statement is None and problem is None:
                problem_label = (
                    str(row.statement_uuid)
                    if row.statement_uuid is not None
                    else (
                    str(row.problem_uuid)
                    if row.problem_uuid is not None
                    else f"{row.year} {row.contest} {row.problem}"
                    )
                )
                result.warnings.append(
                    f"Skipped row for {row.user_email}: problem not found ({problem_label}).",
                )
                continue

            if statement is not None:
                UserProblemCompletion.objects.update_or_create(
                    user=user,
                    statement=statement,
                    defaults={"completion_date": row.completion_date, "problem": None},
                )
            else:
                UserProblemCompletion.objects.update_or_create(
                    user=user,
                    problem=problem,
                    defaults={"completion_date": row.completion_date},
                )
            result.n_completions += 1
            if row.date_unknown:
                result.n_unknown_dates += 1

    return result


@dataclass
class PreparedCurrentUserCompletionTextRow:
    statement_uuid: UUID | None
    problem_uuid: UUID
    completion_date: date | None
    date_unknown: bool


def _split_completion_text_line(line: str) -> tuple[str | None, str | None]:
    stripped = line.strip()
    if not stripped:
        return (None, None)
    if "\t" in stripped:
        parts = [part.strip() for part in stripped.split("\t") if part.strip()]
        if len(parts) >= COMPLETION_TEXT_PART_COUNT:
            return (parts[0], parts[1])
    parts = re.split(r"\s+", stripped, maxsplit=1)
    if len(parts) == COMPLETION_TEXT_PART_COUNT:
        return (parts[0].strip(), parts[1].strip())
    return (None, None)


def _is_completion_text_header(line: str) -> bool:
    normalized = " ".join(line.strip().casefold().split())
    return normalized in COMPLETION_TEXT_HEADER_LINES


def prepare_problem_completion_text_rows(
    source_text: str,
) -> tuple[list[PreparedCurrentUserCompletionTextRow], list[str]]:
    prepared: list[PreparedCurrentUserCompletionTextRow] = []
    warnings: list[str] = []

    for line_number, raw_line in enumerate(source_text.splitlines(), start=1):
        if _is_completion_text_header(raw_line):
            continue
        uuid_text, completion_text = _split_completion_text_line(raw_line)
        if uuid_text is None and completion_text is None:
            continue
        if (
            uuid_text
            and completion_text
            and uuid_text.casefold() in COMPLETION_HEADER_UUID_TOKENS
            and completion_text.casefold() in COMPLETION_HEADER_DATE_TOKENS
        ):
            continue

        problem_uuid = _parse_problem_uuid(uuid_text)
        if problem_uuid is None:
            warnings.append(f"Skipped line {line_number}: invalid PROBLEM UUID.")
            continue

        is_valid_completion, completion_date, date_unknown = _parse_completion_value(completion_text)
        if not is_valid_completion:
            warnings.append(
                f"Skipped line {line_number}: invalid date value {completion_text!r}.",
            )
            continue

        prepared.append(
            PreparedCurrentUserCompletionTextRow(
                statement_uuid=problem_uuid,
                problem_uuid=problem_uuid,
                completion_date=completion_date,
                date_unknown=date_unknown,
            ),
        )

    return prepared, warnings


def import_problem_completion_text_for_user(user, source_text: str) -> ProblemCompletionImportResult:
    result = ProblemCompletionImportResult()
    prepared, warnings = prepare_problem_completion_text_rows(source_text)
    result.warnings.extend(warnings)

    statement_cache: dict[UUID, ContestProblemStatement | None] = {}
    problem_cache: dict[UUID, ProblemSolveRecord | None] = {}
    with transaction.atomic():
        for row in prepared:
            if row.statement_uuid is not None and row.statement_uuid not in statement_cache:
                statement_cache[row.statement_uuid] = (
                    ContestProblemStatement.objects.select_related("linked_problem")
                    .filter(statement_uuid=row.statement_uuid)
                    .first()
                )
            statement = statement_cache.get(row.statement_uuid) if row.statement_uuid is not None else None
            if row.problem_uuid not in problem_cache:
                problem_cache[row.problem_uuid] = (
                    ProblemSolveRecord.objects.filter(problem_uuid=row.problem_uuid).first()
                )
            problem = problem_cache[row.problem_uuid]
            if statement is None and problem is None:
                result.warnings.append(
                    f"Skipped UUID {row.problem_uuid}: statement/problem not found.",
                )
                continue

            if statement is not None:
                UserProblemCompletion.objects.update_or_create(
                    user=user,
                    statement=statement,
                    defaults={"completion_date": row.completion_date, "problem": None},
                )
            else:
                UserProblemCompletion.objects.update_or_create(
                    user=user,
                    problem=problem,
                    defaults={"completion_date": row.completion_date},
                )
            result.n_completions += 1
            if row.date_unknown:
                result.n_unknown_dates += 1

    return result
