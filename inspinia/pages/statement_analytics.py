"""Effective analytics for ContestProblemStatement (CPS first, legacy link fallback)."""

from __future__ import annotations

from django.db.models import CharField
from django.db.models import F
from django.db.models import IntegerField
from django.db.models import TextField
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.db.models.functions import NullIf

from inspinia.pages.models import ContestProblemStatement


def annotate_effective_statement_analytics(queryset):
    """SQL coalesce of CPS columns over linked_problem for dashboard aggregates."""
    return queryset.annotate(
        _eff_topic=Coalesce(
            NullIf(F("topic"), Value("")),
            NullIf(F("linked_problem__topic"), Value("")),
            Value(""),
            output_field=CharField(max_length=32),
        ),
        _eff_mohs=Coalesce(
            F("mohs"),
            F("linked_problem__mohs"),
            output_field=IntegerField(null=True),
        ),
        _eff_confidence=Coalesce(
            NullIf(F("confidence"), Value("")),
            NullIf(F("linked_problem__confidence"), Value("")),
            Value(""),
            output_field=TextField(),
        ),
        _eff_imo_slot_guess_value=Coalesce(
            NullIf(F("imo_slot_guess_value"), Value("")),
            NullIf(F("linked_problem__imo_slot_guess_value"), Value("")),
            Value(""),
            output_field=TextField(),
        ),
    )


def effective_topic(statement: ContestProblemStatement) -> str:
    if (statement.topic or "").strip():
        return str(statement.topic).strip()
    linked = statement.linked_problem
    if linked is not None and (linked.topic or "").strip():
        return str(linked.topic).strip()
    return ""


def effective_mohs(statement: ContestProblemStatement) -> int | None:
    if statement.mohs is not None:
        return statement.mohs
    linked = statement.linked_problem
    if linked is not None:
        return linked.mohs
    return None


def effective_confidence(statement: ContestProblemStatement) -> str:
    if (statement.confidence or "").strip():
        return str(statement.confidence).strip()
    linked = statement.linked_problem
    if linked is not None and (linked.confidence or "").strip():
        return str(linked.confidence).strip()
    return ""


def effective_imo_slot_guess_value(statement: ContestProblemStatement) -> str:
    if (statement.imo_slot_guess_value or "").strip():
        return str(statement.imo_slot_guess_value).strip()
    linked = statement.linked_problem
    if linked is not None and (linked.imo_slot_guess_value or "").strip():
        return str(linked.imo_slot_guess_value).strip()
    return ""


def contest_key_for_public_slug(statement: ContestProblemStatement) -> str:
    """Short contest key used for public contest_problem_list slug maps."""
    if (statement.source_contest or "").strip():
        return str(statement.source_contest).strip()
    linked = statement.linked_problem
    if linked is not None and (linked.contest or "").strip():
        return str(linked.contest).strip()
    return str(statement.contest_name or "").strip()
