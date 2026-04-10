from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from inspinia.rankings.services.ranking_normalization import ZERO

if TYPE_CHECKING:
    from decimal import Decimal

    from inspinia.rankings.models import RankingFormula
    from inspinia.rankings.models import RankingFormulaItem
    from inspinia.rankings.services.ranking_compute import ComputedRankRow


@dataclass(frozen=True, slots=True)
class TieBreakCriterion:
    kind: str
    assessment_id: int | None = None


def build_rank_sort_key(
    *,
    formula: RankingFormula,
    row: ComputedRankRow,
    formula_items: list[RankingFormulaItem],
) -> tuple[object, ...]:
    sort_key: list[object] = []
    for criterion in resolve_tiebreak_criteria(formula=formula, formula_items=formula_items):
        if criterion.kind == "total_score":
            sort_key.append(-row.total_score)
            continue
        if criterion.kind == "assessment_score":
            sort_key.append(-_assessment_score_for_row(row=row, assessment_id=criterion.assessment_id))
            continue
        if criterion.kind == "alphabetical":
            sort_key.append(row.normalized_name)

    sort_key.append(row.student_id)
    return tuple(sort_key)


def resolve_tiebreak_criteria(
    *,
    formula: RankingFormula,
    formula_items: list[RankingFormulaItem],
) -> list[TieBreakCriterion]:
    criteria = [TieBreakCriterion(kind="total_score")]
    criteria.extend(_criteria_from_policy(formula=formula, formula_items=formula_items))
    if not any(criterion.kind == "assessment_score" for criterion in criteria):
        fallback_item = formula_items[0] if formula_items else None
        if fallback_item is not None:
            criteria.append(
                TieBreakCriterion(
                    kind="assessment_score",
                    assessment_id=fallback_item.assessment_id,
                ),
            )
    criteria.append(TieBreakCriterion(kind="alphabetical"))
    return criteria


def _criteria_from_policy(
    *,
    formula: RankingFormula,
    formula_items: list[RankingFormulaItem],
) -> list[TieBreakCriterion]:
    policy = formula.tiebreak_policy if isinstance(formula.tiebreak_policy, dict) else {}
    policy_criteria = policy.get("criteria")
    if isinstance(policy_criteria, list):
        criteria = [
            _criterion_from_policy_entry(entry=entry, formula_items=formula_items)
            for entry in policy_criteria
        ]
        return [criterion for criterion in criteria if criterion is not None]

    priority_item = _resolve_formula_item_from_policy(policy=policy, formula_items=formula_items)
    if priority_item is None:
        return []
    return [
        TieBreakCriterion(
            kind="assessment_score",
            assessment_id=priority_item.assessment_id,
        ),
    ]


def _criterion_from_policy_entry(
    *,
    entry: object,
    formula_items: list[RankingFormulaItem],
) -> TieBreakCriterion | None:
    if not isinstance(entry, dict):
        return None

    criterion_type = entry.get("type")
    if criterion_type == "alphabetical":
        return TieBreakCriterion(kind="alphabetical")
    if criterion_type != "assessment_score":
        return None

    formula_item = _resolve_formula_item(
        formula_items=formula_items,
        assessment_id=entry.get("assessment_id"),
        assessment_code=entry.get("assessment_code"),
    )
    if formula_item is None:
        return None

    return TieBreakCriterion(kind="assessment_score", assessment_id=formula_item.assessment_id)


def _resolve_formula_item_from_policy(
    *,
    policy: dict,
    formula_items: list[RankingFormulaItem],
) -> RankingFormulaItem | None:
    return _resolve_formula_item(
        formula_items=formula_items,
        assessment_id=policy.get("priority_assessment_id"),
        assessment_code=policy.get("priority_assessment_code"),
    )


def _resolve_formula_item(
    *,
    formula_items: list[RankingFormulaItem],
    assessment_id: object,
    assessment_code: object,
) -> RankingFormulaItem | None:
    if assessment_id is not None:
        try:
            assessment_id_value = int(assessment_id)
        except (TypeError, ValueError):
            assessment_id_value = None
        else:
            for item in formula_items:
                if item.assessment_id == assessment_id_value:
                    return item

    if isinstance(assessment_code, str):
        normalized_code = assessment_code.strip().upper()
        for item in formula_items:
            if item.assessment.code == normalized_code:
                return item

    return None


def _assessment_score_for_row(
    *,
    row: ComputedRankRow,
    assessment_id: int | None,
) -> Decimal:
    if assessment_id is None:
        return ZERO

    for breakdown_item in row.breakdown.values():
        if breakdown_item.get("assessment_id") == assessment_id:
            score = breakdown_item.get("normalized_score")
            return score if score is not None else ZERO

    return ZERO
