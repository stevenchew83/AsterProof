from collections import Counter
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from inspinia.pages.contest_names import PROJECT_CONTEST_NAME_MAX_LENGTH
from inspinia.pages.contest_names import STATEMENT_CONTEST_NAME_MAX_LENGTH
from inspinia.pages.contest_names import normalize_contest_name
from inspinia.pages.contest_names import normalize_text_list
from inspinia.pages.models import ContestMetadata
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import UserProblemCompletion


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


@dataclass(frozen=True, slots=True)
class StatementRenamePlan:
    rename_rows: tuple[ContestProblemStatement, ...]
    merge_pairs: tuple[tuple[ContestProblemStatement, ContestProblemStatement], ...]


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
) -> tuple[list[ProblemSolveRecord], list[ContestProblemStatement], list[ContestMetadata]]:
    problem_rows = list(
        ProblemSolveRecord.objects.filter(contest__in=source_contests).order_by("contest", "pk"),
    )
    statement_rows = list(
        ContestProblemStatement.objects.filter(contest_name__in=source_contests).order_by(
            "contest_name",
            "pk",
        ),
    )
    contest_metadata_rows = list(
        ContestMetadata.objects.filter(contest__in=source_contests).order_by("contest", "pk"),
    )

    found_contests = {record.contest for record in problem_rows} | {
        statement.contest_name for statement in statement_rows
    }
    found_contests |= {metadata.contest for metadata in contest_metadata_rows}
    missing_contests = [source_contest for source_contest in source_contests if source_contest not in found_contests]
    if missing_contests:
        if len(missing_contests) == 1:
            msg = f'Contest "{missing_contests[0]}" was not found.'
        else:
            quoted_contests = ", ".join(f'"{contest}"' for contest in missing_contests)
            msg = f"These contests were not found: {quoted_contests}."
        raise ContestRenameValidationError(msg)
    return problem_rows, statement_rows, contest_metadata_rows


def _problem_conflict_labels(
    problem_rows: list[ProblemSolveRecord],
    target_contest: str,
) -> list[str]:
    source_problem_key_counts: Counter[tuple[int, str]] = Counter(
        (record.year, record.problem)
        for record in problem_rows
    )
    target_problem_keys = set(
        ProblemSolveRecord.objects.filter(contest=target_contest).values_list("year", "problem"),
    )
    return sorted(
        {
            f"{year} {problem}"
            for (year, problem), count in source_problem_key_counts.items()
            if count > 1 or (year, problem) in target_problem_keys
        },
    )


def _statement_key(statement: ContestProblemStatement) -> tuple[int, str, str]:
    return (statement.contest_year, statement.day_label, statement.problem_code)


def _statement_conflict_label_from_key(statement_key: tuple[int, str, str]) -> str:
    contest_year, day_label, problem_code = statement_key
    display_day_label = day_label or "No day label"
    return f"{contest_year} {display_day_label} {problem_code}"


def _statement_merge_text_value(target_value: str | None, source_value: str | None) -> str:
    normalized_target = str(target_value or "").strip()
    return normalized_target or str(source_value or "").strip()


def _statement_merge_optional_int_value(target_value: int | None, source_value: int | None) -> int | None:
    return target_value if target_value is not None else source_value


def _statement_rows_are_merge_compatible(
    source_statement: ContestProblemStatement,
    target_statement: ContestProblemStatement,
) -> bool:
    if source_statement.problem_number != target_statement.problem_number:
        return False
    if source_statement.statement_latex != target_statement.statement_latex:
        return False
    if (
        source_statement.linked_problem_id is not None
        and target_statement.linked_problem_id is not None
        and source_statement.linked_problem_id != target_statement.linked_problem_id
    ):
        return False

    text_fields = (
        "topic",
        "source_contest",
        "source_problem",
        "workbook_contest_year_problem",
        "confidence",
        "imo_slot_guess",
        "topic_tags",
        "rationale",
        "pitfalls",
    )
    for field_name in text_fields:
        source_value = str(getattr(source_statement, field_name) or "").strip()
        target_value = str(getattr(target_statement, field_name) or "").strip()
        if source_value and target_value and source_value != target_value:
            return False

    return not (
        source_statement.mohs is not None
        and target_statement.mohs is not None
        and source_statement.mohs != target_statement.mohs
    )


def _build_statement_rename_plan(
    statement_rows: list[ContestProblemStatement],
    target_contest: str,
) -> StatementRenamePlan:
    source_statement_key_counts: Counter[tuple[int, str, str]] = Counter(
        _statement_key(statement)
        for statement in statement_rows
    )
    target_statements_by_key = {
        _statement_key(statement): statement
        for statement in ContestProblemStatement.objects.filter(contest_name=target_contest).order_by("pk")
    }

    conflict_labels: set[str] = set()
    rename_rows: list[ContestProblemStatement] = []
    merge_pairs: list[tuple[ContestProblemStatement, ContestProblemStatement]] = []
    for statement in statement_rows:
        statement_key = _statement_key(statement)
        if source_statement_key_counts[statement_key] > 1:
            conflict_labels.add(_statement_conflict_label_from_key(statement_key))
            continue

        target_statement = target_statements_by_key.get(statement_key)
        if target_statement is None:
            rename_rows.append(statement)
            continue

        if not _statement_rows_are_merge_compatible(statement, target_statement):
            conflict_labels.add(_statement_conflict_label_from_key(statement_key))
            continue

        merge_pairs.append((statement, target_statement))

    if conflict_labels:
        msg = (
            f'Cannot update contest names to "{target_contest}" because these statement rows would '
            "collide after the update: "
            f"{_preview_conflict_text(sorted(conflict_labels))}."
        )
        raise ContestRenameValidationError(msg)

    return StatementRenamePlan(
        rename_rows=tuple(rename_rows),
        merge_pairs=tuple(merge_pairs),
    )


def _preview_conflict_text(conflicts: list[str]) -> str:
    preview_limit = 5
    preview = ", ".join(conflicts[:preview_limit])
    if len(conflicts) > preview_limit:
        return f"{preview}, and {len(conflicts) - preview_limit} more"
    return preview


def _validate_target_merge(
    problem_rows: list[ProblemSolveRecord],
    target_contest: str,
) -> bool:
    target_exists = ProblemSolveRecord.objects.filter(contest=target_contest).exists() or (
        ContestProblemStatement.objects.filter(contest_name=target_contest).exists()
    )
    target_exists = target_exists or ContestMetadata.objects.filter(contest=target_contest).exists()

    problem_conflicts = _problem_conflict_labels(problem_rows, target_contest)
    if problem_conflicts:
        msg = (
            f'Cannot update contest names to "{target_contest}" because these problem rows would '
            "collide after the update: "
            f"{_preview_conflict_text(problem_conflicts)}."
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
    statement_plan: StatementRenamePlan,
    target_contest: str,
) -> None:
    rename_timestamp = timezone.now()
    for statement in statement_plan.rename_rows:
        statement.contest_name = target_contest
        statement.contest_year_problem = f"{target_contest} {statement.contest_year} {statement.problem_code}"
        statement.updated_at = rename_timestamp
    if statement_plan.rename_rows:
        ContestProblemStatement.objects.bulk_update(
            list(statement_plan.rename_rows),
            ["contest_name", "contest_year_problem", "updated_at"],
            batch_size=200,
        )

    source_statement_ids_to_delete = [
        _merge_statement_row_into_target(
            source_statement=source_statement,
            target_statement=target_statement,
        )
        for source_statement, target_statement in statement_plan.merge_pairs
    ]

    if source_statement_ids_to_delete:
        ContestProblemStatement.objects.filter(pk__in=source_statement_ids_to_delete).delete()


def _merge_statement_topic_techniques(
    *,
    source_statement: ContestProblemStatement,
    target_statement: ContestProblemStatement,
) -> None:
    for source_technique in source_statement.statement_topic_techniques.all():
        target_technique = StatementTopicTechnique.objects.filter(
            statement=target_statement,
            technique=source_technique.technique,
        ).first()
        if target_technique is None:
            source_technique.statement = target_statement
            source_technique.save(update_fields=["statement"])
            continue

        merged_domains = normalize_text_list(
            [*(target_technique.domains or []), *(source_technique.domains or [])],
        )
        if merged_domains != list(target_technique.domains or []):
            target_technique.domains = merged_domains
            target_technique.save(update_fields=["domains"])
        source_technique.delete()


def _merge_statement_completion_rows(
    *,
    source_statement: ContestProblemStatement,
    target_statement: ContestProblemStatement,
) -> None:
    for source_completion in source_statement.user_completions.select_related("user").all():
        target_completion = UserProblemCompletion.objects.filter(
            user=source_completion.user,
            statement=target_statement,
        ).first()
        if target_completion is None:
            source_completion.statement = target_statement
            source_completion.save(update_fields=["statement"])
            continue

        completion_dates = [
            completion_date
            for completion_date in (
                target_completion.completion_date,
                source_completion.completion_date,
            )
            if completion_date is not None
        ]
        merged_completion_date = min(completion_dates) if completion_dates else None
        if target_completion.completion_date != merged_completion_date:
            target_completion.completion_date = merged_completion_date
            target_completion.save(update_fields=["completion_date"])
        source_completion.delete()


def _merge_statement_row_into_target(
    *,
    source_statement: ContestProblemStatement,
    target_statement: ContestProblemStatement,
) -> int:
    target_statement.linked_problem = target_statement.linked_problem or source_statement.linked_problem
    target_statement.is_active = target_statement.is_active or source_statement.is_active
    target_statement.topic = _statement_merge_text_value(target_statement.topic, source_statement.topic)
    target_statement.mohs = _statement_merge_optional_int_value(target_statement.mohs, source_statement.mohs)
    target_statement.source_contest = _statement_merge_text_value(
        target_statement.source_contest,
        source_statement.source_contest,
    )
    target_statement.source_problem = _statement_merge_text_value(
        target_statement.source_problem,
        source_statement.source_problem,
    )
    target_statement.workbook_contest_year_problem = _statement_merge_text_value(
        target_statement.workbook_contest_year_problem,
        source_statement.workbook_contest_year_problem,
    )
    target_statement.confidence = _statement_merge_text_value(
        target_statement.confidence,
        source_statement.confidence,
    )
    target_statement.imo_slot_guess = _statement_merge_text_value(
        target_statement.imo_slot_guess,
        source_statement.imo_slot_guess,
    )
    target_statement.topic_tags = _statement_merge_text_value(
        target_statement.topic_tags,
        source_statement.topic_tags,
    )
    target_statement.rationale = _statement_merge_text_value(
        target_statement.rationale,
        source_statement.rationale,
    )
    target_statement.pitfalls = _statement_merge_text_value(
        target_statement.pitfalls,
        source_statement.pitfalls,
    )
    target_statement.save()

    _merge_statement_topic_techniques(
        source_statement=source_statement,
        target_statement=target_statement,
    )
    _merge_statement_completion_rows(
        source_statement=source_statement,
        target_statement=target_statement,
    )
    return source_statement.pk


def _resolve_metadata_scalar_value(
    *,
    field_name: str,
    field_label: str,
    source_metadata_rows: list[ContestMetadata],
    target_metadata_row: ContestMetadata | None,
    target_contest: str,
) -> str:
    target_value = str(getattr(target_metadata_row, field_name) or "").strip() if target_metadata_row else ""
    if target_value:
        return target_value

    source_value_to_contests: dict[str, list[str]] = {}
    for metadata_row in source_metadata_rows:
        source_value = str(getattr(metadata_row, field_name) or "").strip()
        if not source_value:
            continue
        source_value_to_contests.setdefault(source_value, []).append(metadata_row.contest)

    if len(source_value_to_contests) <= 1:
        return next(iter(source_value_to_contests), "")

    conflicting_contests = sorted(
        {
            contest_name
            for contest_names in source_value_to_contests.values()
            for contest_name in contest_names
        },
    )
    msg = (
        f'Cannot update contest names to "{target_contest}" because contest metadata has '
        f'conflicting {field_label} values across: {_preview_conflict_text(conflicting_contests)}.'
    )
    raise ContestRenameValidationError(msg)


def _merge_metadata_list_values(
    *,
    field_name: str,
    source_metadata_rows: list[ContestMetadata],
    target_metadata_row: ContestMetadata | None,
) -> list[str]:
    merged_values: list[str] = []
    if target_metadata_row is not None:
        merged_values.extend(getattr(target_metadata_row, field_name) or [])
    for metadata_row in source_metadata_rows:
        merged_values.extend(getattr(metadata_row, field_name) or [])
    return normalize_text_list(merged_values)


def _merge_contest_metadata_rows(
    *,
    source_metadata_rows: list[ContestMetadata],
    target_contest: str,
) -> None:
    if not source_metadata_rows:
        return

    target_metadata_row = ContestMetadata.objects.filter(contest=target_contest).first()
    merged_full_name = _resolve_metadata_scalar_value(
        field_name="full_name",
        field_label="full name",
        source_metadata_rows=source_metadata_rows,
        target_metadata_row=target_metadata_row,
        target_contest=target_contest,
    )
    merged_description_markdown = _resolve_metadata_scalar_value(
        field_name="description_markdown",
        field_label="description",
        source_metadata_rows=source_metadata_rows,
        target_metadata_row=target_metadata_row,
        target_contest=target_contest,
    )
    merged_countries = _merge_metadata_list_values(
        field_name="countries",
        source_metadata_rows=source_metadata_rows,
        target_metadata_row=target_metadata_row,
    )
    merged_tags = _merge_metadata_list_values(
        field_name="tags",
        source_metadata_rows=source_metadata_rows,
        target_metadata_row=target_metadata_row,
    )

    primary_metadata_row = target_metadata_row or source_metadata_rows[0]
    duplicate_metadata_rows = [
        metadata_row
        for metadata_row in source_metadata_rows
        if metadata_row.pk != primary_metadata_row.pk
    ]

    primary_metadata_row.contest = target_contest
    primary_metadata_row.full_name = merged_full_name
    primary_metadata_row.description_markdown = merged_description_markdown
    primary_metadata_row.countries = merged_countries
    primary_metadata_row.tags = merged_tags
    primary_metadata_row.save()

    if duplicate_metadata_rows:
        ContestMetadata.objects.filter(pk__in=[row.pk for row in duplicate_metadata_rows]).delete()


def rename_contests(*, old_names: list[str], new_name: str) -> ContestRenameResult:
    source_contests = _dedupe_contest_names(list(old_names or []))
    target_contest = normalize_contest_name(new_name)
    _validate_target_contest_name(source_contests, target_contest)
    source_problem_rows, source_statement_rows, source_metadata_rows = _load_source_rows(source_contests)
    statement_plan = _build_statement_rename_plan(
        source_statement_rows,
        target_contest,
    )
    merged_into_existing = _validate_target_merge(
        source_problem_rows,
        target_contest,
    )
    with transaction.atomic():
        _update_problem_rows(source_problem_rows, target_contest)
        _update_statement_rows(statement_plan, target_contest)
        _merge_contest_metadata_rows(
            source_metadata_rows=source_metadata_rows,
            target_contest=target_contest,
        )

    return ContestRenameResult(
        source_contests=tuple(source_contests),
        target_contest=target_contest,
        problem_count=len(source_problem_rows),
        statement_count=len(source_statement_rows),
        merged_into_existing=merged_into_existing,
    )


def rename_contest(*, old_name: str, new_name: str) -> ContestRenameResult:
    return rename_contests(old_names=[old_name], new_name=new_name)
