"""Copy legacy ProblemSolveRecord analytics onto ContestProblemStatement rows."""

from __future__ import annotations

from django.db import transaction

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique

TEXT_ANALYTICS_FIELD_PAIRS = (
    ("topic", "topic"),
    ("source_contest", "contest"),
    ("source_problem", "problem"),
    ("confidence", "confidence"),
    ("imo_slot_guess", "imo_slot_guess"),
    ("topic_tags", "topic_tags"),
    ("core_ideas", "core_ideas"),
    ("rationale", "rationale"),
    ("pitfalls", "pitfalls"),
)


def _is_blank_str(value: str | None) -> bool:
    return value is None or not str(value).strip()


def _copy_text_if_blank(statement: ContestProblemStatement, record, statement_field: str, record_field: str) -> bool:
    if not _is_blank_str(getattr(statement, statement_field)):
        return False
    setattr(statement, statement_field, getattr(record, record_field) or None)
    return True


def _copy_mohs_if_missing(statement: ContestProblemStatement, record) -> bool:
    if statement.mohs is not None:
        return False
    statement.mohs = record.mohs
    return True


def _copy_workbook_label_if_missing(statement: ContestProblemStatement, record) -> bool:
    if statement.workbook_contest_year_problem is not None or not record.contest_year_problem:
        return False
    statement.workbook_contest_year_problem = record.contest_year_problem
    return True


def _fill_statement_analytics_gaps(statement: ContestProblemStatement, record) -> bool:
    changed = False
    for statement_field, record_field in TEXT_ANALYTICS_FIELD_PAIRS:
        changed = _copy_text_if_blank(statement, record, statement_field, record_field) or changed
    changed = _copy_mohs_if_missing(statement, record) or changed
    return _copy_workbook_label_if_missing(statement, record) or changed


@transaction.atomic
def sync_statement_analytics_from_linked_problem(statement: ContestProblemStatement) -> bool:
    """
    Fill empty statement analytics from linked ProblemSolveRecord and copy techniques
    when the statement has none. Safe to call multiple times (idempotent gaps only).
    """
    if statement.linked_problem_id is None:
        return False
    record = statement.linked_problem
    if record is None:
        return False

    changed = _fill_statement_analytics_gaps(statement, record)
    if changed:
        statement.save()

    techniques_changed = False
    if not StatementTopicTechnique.objects.filter(statement_id=statement.pk).exists():
        for pt in ProblemTopicTechnique.objects.filter(record_id=record.id):
            st = StatementTopicTechnique(
                statement=statement,
                technique=pt.technique,
                domains=list(pt.domains or []),
            )
            st.save()
            techniques_changed = True

    return changed or techniques_changed
