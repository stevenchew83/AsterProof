import re
from collections import Counter
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord

PROJECT_CONTEST_NAME_MAX_LENGTH = 64
STATEMENT_CONTEST_NAME_MAX_LENGTH = 128


def normalize_contest_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


class ContestRenameValidationError(ValueError):
    """Raised when a contest rename request is invalid."""


@dataclass(frozen=True, slots=True)
class ContestRenameResult:
    source_contests: tuple[str, ...]
    target_contest: str
    problem_count: int
    statement_count: int
    merged_into_existing: bool

    @property
    def source_contest(self) -> str:
        if len(self.source_contests) == 1:
            return self.source_contests[0]
        return ", ".join(self.source_contests)


def _dedupe_contest_names(source_contests: list[str]) -> list[str]:
    ordered_contests: list[str] = []
    seen_contests: set[str] = set()
    for source_contest in source_contests:
        if not source_contest or source_contest in seen_contests:
            continue
        ordered_contests.append(source_contest)
        seen_contests.add(source_contest)
    return ordered_contests


def _validate_target_contest_name(source_contests: list[str], target_contest: str) -> None:
    if not source_contests:
        msg = "Select at least one contest to update."
        raise ContestRenameValidationError(msg)
    if not target_contest:
        msg = "Enter the new contest name."
        raise ContestRenameValidationError(msg)
    if target_contest in source_contests:
        msg = (
            "Pick a different contest name."
            if len(source_contests) == 1
            else "Uncheck the target contest name from the source selections."
        )
        raise ContestRenameValidationError(msg)
    if len(target_contest) > PROJECT_CONTEST_NAME_MAX_LENGTH:
        msg = (
            f"Contest names must be at most {PROJECT_CONTEST_NAME_MAX_LENGTH} characters so they fit "
            "the archive problem rows."
        )
        raise ContestRenameValidationError(msg)
    if len(target_contest) > STATEMENT_CONTEST_NAME_MAX_LENGTH:
        msg = f"Contest names must be at most {STATEMENT_CONTEST_NAME_MAX_LENGTH} characters."
        raise ContestRenameValidationError(msg)


def _load_source_rows(
    source_contests: list[str],
) -> tuple[list[ProblemSolveRecord], list[ContestProblemStatement]]:
    problem_rows = list(
        ProblemSolveRecord.objects.filter(contest__in=source_contests).order_by("contest", "pk"),
    )
    statement_rows = list(
        ContestProblemStatement.objects.filter(contest_name__in=source_contests).order_by(
            "contest_name",
            "pk",
        ),
    )

    found_contests = {record.contest for record in problem_rows} | {
        statement.contest_name for statement in statement_rows
    }
    missing_contests = [source_contest for source_contest in source_contests if source_contest not in found_contests]
    if missing_contests:
        if len(missing_contests) == 1:
            msg = f'Contest "{missing_contests[0]}" was not found.'
        else:
            quoted_contests = ", ".join(f'"{contest}"' for contest in missing_contests)
            msg = f"These contests were not found: {quoted_contests}."
        raise ContestRenameValidationError(msg)
    return problem_rows, statement_rows


def _problem_conflict_labels(
    problem_rows: list[ProblemSolveRecord],
    target_contest: str,
) -> list[str]:
    problem_key_counts: Counter[tuple[int, str]] = Counter(
        (record.year, record.problem) for record in problem_rows
    )
    problem_key_counts.update(
        ProblemSolveRecord.objects.filter(contest=target_contest).values_list("year", "problem"),
    )
    return sorted(
        {
            f"{year} {problem}"
            for (year, problem), count in problem_key_counts.items()
            if count > 1
        },
    )


def _statement_conflict_labels(
    statement_rows: list[ContestProblemStatement],
    target_contest: str,
) -> list[str]:
    statement_key_counts: Counter[tuple[int, str, str]] = Counter(
        (statement.contest_year, statement.day_label, statement.problem_code)
        for statement in statement_rows
    )
    statement_key_counts.update(
        ContestProblemStatement.objects.filter(contest_name=target_contest).values_list(
            "contest_year",
            "day_label",
            "problem_code",
        ),
    )
    conflict_labels: set[str] = set()
    for (contest_year, day_label, problem_code), count in statement_key_counts.items():
        if count <= 1:
            continue
        display_day_label = day_label or "No day label"
        conflict_labels.add(f"{contest_year} {display_day_label} {problem_code}")
    return sorted(conflict_labels)


def _preview_conflict_text(conflicts: list[str]) -> str:
    preview_limit = 5
    preview = ", ".join(conflicts[:preview_limit])
    if len(conflicts) > preview_limit:
        return f"{preview}, and {len(conflicts) - preview_limit} more"
    return preview


def _validate_target_merge(
    problem_rows: list[ProblemSolveRecord],
    statement_rows: list[ContestProblemStatement],
    target_contest: str,
) -> bool:
    target_exists = ProblemSolveRecord.objects.filter(contest=target_contest).exists() or (
        ContestProblemStatement.objects.filter(contest_name=target_contest).exists()
    )

    problem_conflicts = _problem_conflict_labels(problem_rows, target_contest)
    if problem_conflicts:
        msg = (
            f'Cannot update contest names to "{target_contest}" because these problem rows would '
            "collide after the update: "
            f"{_preview_conflict_text(problem_conflicts)}."
        )
        raise ContestRenameValidationError(msg)

    statement_conflicts = _statement_conflict_labels(statement_rows, target_contest)
    if statement_conflicts:
        msg = (
            f'Cannot update contest names to "{target_contest}" because these statement rows would '
            "collide after the update: "
            f"{_preview_conflict_text(statement_conflicts)}."
        )
        raise ContestRenameValidationError(msg)

    return target_exists


def _update_problem_rows(problem_rows: list[ProblemSolveRecord], target_contest: str) -> None:
    for record in problem_rows:
        record.contest = target_contest
        if record.contest_year_problem:
            record.contest_year_problem = f"{target_contest} {record.year} {record.problem}"
    if problem_rows:
        ProblemSolveRecord.objects.bulk_update(
            problem_rows,
            ["contest", "contest_year_problem"],
            batch_size=200,
        )


def _update_statement_rows(
    statement_rows: list[ContestProblemStatement],
    target_contest: str,
) -> None:
    rename_timestamp = timezone.now()
    for statement in statement_rows:
        statement.contest_name = target_contest
        statement.contest_year_problem = f"{target_contest} {statement.contest_year} {statement.problem_code}"
        statement.updated_at = rename_timestamp
    if statement_rows:
        ContestProblemStatement.objects.bulk_update(
            statement_rows,
            ["contest_name", "contest_year_problem", "updated_at"],
            batch_size=200,
        )


def rename_contests(*, old_names: list[str], new_name: str) -> ContestRenameResult:
    source_contests = _dedupe_contest_names(list(old_names or []))
    target_contest = normalize_contest_name(new_name)
    _validate_target_contest_name(source_contests, target_contest)
    source_problem_rows, source_statement_rows = _load_source_rows(source_contests)
    merged_into_existing = _validate_target_merge(
        source_problem_rows,
        source_statement_rows,
        target_contest,
    )
    with transaction.atomic():
        _update_problem_rows(source_problem_rows, target_contest)
        _update_statement_rows(source_statement_rows, target_contest)

    return ContestRenameResult(
        source_contests=tuple(source_contests),
        target_contest=target_contest,
        problem_count=len(source_problem_rows),
        statement_count=len(source_statement_rows),
        merged_into_existing=merged_into_existing,
    )


def rename_contest(*, old_name: str, new_name: str) -> ContestRenameResult:
    return rename_contests(old_names=[old_name], new_name=new_name)
