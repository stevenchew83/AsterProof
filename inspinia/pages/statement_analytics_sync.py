"""Copy legacy ProblemSolveRecord analytics onto ContestProblemStatement rows."""

from __future__ import annotations

from django.db import transaction

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique


def _is_blank_str(value: str | None) -> bool:
    return value is None or not str(value).strip()


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

    changed = False
    if _is_blank_str(statement.topic):
        statement.topic = record.topic
        changed = True
    if statement.mohs is None:
        statement.mohs = record.mohs
        changed = True
    if _is_blank_str(statement.source_contest):
        statement.source_contest = record.contest
        changed = True
    if _is_blank_str(statement.source_problem):
        statement.source_problem = record.problem
        changed = True
    if statement.workbook_contest_year_problem is None and record.contest_year_problem:
        statement.workbook_contest_year_problem = record.contest_year_problem
        changed = True
    if _is_blank_str(statement.confidence):
        statement.confidence = record.confidence or None
        changed = True
    if _is_blank_str(statement.imo_slot_guess):
        statement.imo_slot_guess = record.imo_slot_guess
        changed = True
    if _is_blank_str(statement.topic_tags):
        statement.topic_tags = record.topic_tags
        changed = True
    if _is_blank_str(statement.rationale):
        statement.rationale = record.rationale
        changed = True
    if _is_blank_str(statement.pitfalls):
        statement.pitfalls = record.pitfalls
        changed = True

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
