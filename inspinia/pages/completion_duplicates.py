from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from inspinia.pages.completion_record_fields import COMPLETION_METADATA_FIELDS
from inspinia.pages.completion_record_fields import SOLVED_STATUSES
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.statement_duplicates import normalize_exact_statement_text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from inspinia.pages.models import ProblemSolveRecord
    from inspinia.users.models import User


@dataclass(frozen=True)
class DuplicateCompletionBackfillResult:
    scanned_completion_count: int = 0
    eligible_source_count: int = 0
    created_count: int = 0
    existing_count: int = 0
    target_count: int = 0
    dry_run: bool = False


@dataclass(frozen=True)
class ExactDuplicateStatementIndex:
    statements_by_id: dict[int, ContestProblemStatement]
    exact_text_by_statement_id: dict[int, str]
    statement_ids_by_exact_text: dict[str, list[int]]
    statement_by_linked_problem_id: dict[int, ContestProblemStatement]

    def duplicate_statements_for(self, statement: ContestProblemStatement) -> list[ContestProblemStatement]:
        exact_text = self.exact_text_by_statement_id.get(statement.id, "")
        if not exact_text:
            return []
        return [
            self.statements_by_id[statement_id]
            for statement_id in self.statement_ids_by_exact_text[exact_text]
            if statement_id != statement.id
        ]

    def statement_for_problem_id(self, problem_id: int | None) -> ContestProblemStatement | None:
        if problem_id is None:
            return None
        return self.statement_by_linked_problem_id.get(problem_id)


def _build_exact_duplicate_statement_index() -> ExactDuplicateStatementIndex:
    statements_by_id: dict[int, ContestProblemStatement] = {}
    exact_text_by_statement_id: dict[int, str] = {}
    statement_ids_by_exact_text: dict[str, list[int]] = {}
    statement_by_linked_problem_id: dict[int, ContestProblemStatement] = {}
    for statement in ContestProblemStatement.objects.only(
        "id",
        "linked_problem_id",
        "statement_latex",
    ).order_by(
        "contest_year",
        "contest_name",
        "day_label",
        "problem_number",
        "problem_code",
        "id",
    ).iterator():
        statements_by_id[statement.id] = statement
        if statement.linked_problem_id is not None:
            statement_by_linked_problem_id.setdefault(statement.linked_problem_id, statement)
        exact_text = normalize_exact_statement_text(statement.statement_latex)
        if exact_text:
            exact_text_by_statement_id[statement.id] = exact_text
            statement_ids_by_exact_text.setdefault(exact_text, []).append(statement.id)
    return ExactDuplicateStatementIndex(
        statements_by_id=statements_by_id,
        exact_text_by_statement_id=exact_text_by_statement_id,
        statement_ids_by_exact_text=statement_ids_by_exact_text,
        statement_by_linked_problem_id=statement_by_linked_problem_id,
    )


def _exact_duplicate_statement_ids(statement: ContestProblemStatement) -> list[int]:
    normalized_statement = normalize_exact_statement_text(statement.statement_latex)
    if not normalized_statement:
        return []

    return [
        candidate.id
        for candidate in ContestProblemStatement.objects.only("id", "statement_latex").iterator()
        if normalize_exact_statement_text(candidate.statement_latex) == normalized_statement
    ]


def upsert_exact_duplicate_statement_completions(
    *,
    user: User,
    statement: ContestProblemStatement,
    defaults: Mapping[str, object],
) -> list[UserProblemCompletion]:
    statement_ids = _exact_duplicate_statement_ids(statement)
    if not statement_ids:
        return []

    completions: list[UserProblemCompletion] = []
    completion_defaults = {**dict(defaults), "problem": None}
    for duplicate_statement in ContestProblemStatement.objects.filter(id__in=statement_ids):
        completion, _created = UserProblemCompletion.objects.update_or_create(
            user=user,
            statement=duplicate_statement,
            defaults=completion_defaults,
        )
        completions.append(completion)
    return completions


def linked_statement_for_completion_problem(
    problem: ProblemSolveRecord | None,
) -> ContestProblemStatement | None:
    if problem is None:
        return None
    return (
        ContestProblemStatement.objects.select_related("linked_problem")
        .filter(linked_problem=problem)
        .order_by(
            "contest_year",
            "contest_name",
            "day_label",
            "problem_number",
            "problem_code",
            "id",
        )
        .first()
    )


def _completion_defaults_from_source(completion: UserProblemCompletion) -> dict[str, object]:
    defaults: dict[str, object] = {
        "completion_date": completion.completion_date,
    }
    for field_name in COMPLETION_METADATA_FIELDS:
        defaults[field_name] = getattr(completion, field_name)
    defaults["problem"] = None
    return defaults


def _covered_statement_completion_keys(index: ExactDuplicateStatementIndex) -> set[tuple[int, int]]:
    covered_keys = {
        (user_id, statement_id)
        for user_id, statement_id in UserProblemCompletion.objects.filter(
            statement_id__isnull=False,
        ).values_list("user_id", "statement_id")
    }
    for user_id, problem_id in UserProblemCompletion.objects.filter(
        statement__isnull=True,
        problem_id__isnull=False,
    ).values_list("user_id", "problem_id"):
        statement = index.statement_for_problem_id(problem_id)
        if statement is not None:
            covered_keys.add((user_id, statement.id))
    return covered_keys


def backfill_exact_duplicate_statement_completions(*, dry_run: bool = False) -> DuplicateCompletionBackfillResult:
    scanned_completion_count = 0
    eligible_source_count = 0
    created_count = 0
    existing_count = 0
    target_count = 0
    duplicate_index = _build_exact_duplicate_statement_index()
    covered_keys = _covered_statement_completion_keys(duplicate_index)

    completions = UserProblemCompletion.objects.filter(status__in=SOLVED_STATUSES).only(
        "user_id",
        "problem_id",
        "statement_id",
        "completion_date",
        *COMPLETION_METADATA_FIELDS,
    )
    with transaction.atomic():
        for completion in completions.iterator():
            scanned_completion_count += 1
            source_statement = duplicate_index.statements_by_id.get(completion.statement_id)
            if source_statement is None:
                source_statement = duplicate_index.statement_for_problem_id(completion.problem_id)
            if source_statement is None:
                continue

            duplicate_statements = duplicate_index.duplicate_statements_for(source_statement)
            if not duplicate_statements:
                continue

            eligible_source_count += 1
            defaults = _completion_defaults_from_source(completion)
            for target_statement in duplicate_statements:
                target_count += 1
                statement_id = target_statement.id
                key = (completion.user_id, statement_id)
                if key in covered_keys:
                    existing_count += 1
                    continue

                created_count += 1
                covered_keys.add(key)
                if not dry_run:
                    UserProblemCompletion.objects.create(
                        user_id=completion.user_id,
                        statement_id=statement_id,
                        **defaults,
                    )

        if dry_run:
            transaction.set_rollback(True)

    return DuplicateCompletionBackfillResult(
        scanned_completion_count=scanned_completion_count,
        eligible_source_count=eligible_source_count,
        created_count=created_count,
        existing_count=existing_count,
        target_count=target_count,
        dry_run=dry_run,
    )
