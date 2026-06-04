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


def _statement_completion_exists_for_user(*, user_id: int, statement: ContestProblemStatement) -> bool:
    if UserProblemCompletion.objects.filter(user_id=user_id, statement=statement).exists():
        return True
    if statement.linked_problem_id is None:
        return False
    return UserProblemCompletion.objects.filter(
        user_id=user_id,
        statement__isnull=True,
        problem_id=statement.linked_problem_id,
    ).exists()


def backfill_exact_duplicate_statement_completions(*, dry_run: bool = False) -> DuplicateCompletionBackfillResult:
    scanned_completion_count = 0
    eligible_source_count = 0
    created_count = 0
    existing_count = 0
    target_count = 0
    planned_keys: set[tuple[int, int]] = set()

    completions = UserProblemCompletion.objects.filter(status__in=SOLVED_STATUSES).select_related(
        "problem",
        "statement",
        "user",
    )
    with transaction.atomic():
        for completion in completions.iterator():
            scanned_completion_count += 1
            source_statement = completion.statement
            if source_statement is None:
                source_statement = linked_statement_for_completion_problem(completion.problem)
            if source_statement is None:
                continue

            duplicate_statements = list(
                ContestProblemStatement.objects.only("id", "linked_problem_id")
                .filter(id__in=_exact_duplicate_statement_ids(source_statement))
                .exclude(id=source_statement.id),
            )
            if not duplicate_statements:
                continue

            eligible_source_count += 1
            defaults = _completion_defaults_from_source(completion)
            for target_statement in duplicate_statements:
                target_count += 1
                statement_id = target_statement.id
                key = (completion.user_id, statement_id)
                if key in planned_keys:
                    existing_count += 1
                    continue

                already_exists = _statement_completion_exists_for_user(
                    user_id=completion.user_id,
                    statement=target_statement,
                )
                if already_exists:
                    existing_count += 1
                    planned_keys.add(key)
                    continue

                created_count += 1
                planned_keys.add(key)
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
