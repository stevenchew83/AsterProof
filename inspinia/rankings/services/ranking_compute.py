from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingFormulaItem
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.ranking_normalization import ZERO
from inspinia.rankings.services.ranking_normalization import normalize_formula_item_score
from inspinia.rankings.services.ranking_normalization import quantize_score

if TYPE_CHECKING:
    from collections.abc import Iterable


def compute_rankings(
    formula: RankingFormula,
    students: Iterable[Student],
) -> list[dict[str, Any]]:
    formula_items = list(
        formula.items.select_related("assessment").order_by("sort_order", "id"),
    )
    student_list = list(students)
    results_by_key = _load_results(student_list, formula_items)

    rows: list[dict[str, Any]] = []
    for student in student_list:
        breakdown: dict[str, dict[str, Any]] = {}
        numerator = ZERO
        denominator = ZERO

        for item in formula_items:
            result = results_by_key.get((student.id, item.assessment_id))
            normalized_score = normalize_formula_item_score(item, result)
            is_missing = normalized_score is None
            counted_in_denominator = _count_item_in_denominator(
                formula=formula,
                item=item,
                is_missing=is_missing,
            )

            score_for_math = normalized_score if normalized_score is not None else ZERO
            contribution = quantize_score(score_for_math * item.weight)

            if counted_in_denominator:
                denominator += item.weight
            if normalized_score is not None:
                numerator += normalized_score * item.weight

            breakdown[item.assessment.code] = {
                "assessment_id": item.assessment_id,
                "weight": item.weight,
                "normalization_method": item.normalization_method,
                "is_required": item.is_required,
                "is_missing": is_missing,
                "counted_in_denominator": counted_in_denominator,
                "raw_score": result.raw_score if result and result.raw_score is not None else None,
                "normalized_score": quantize_score(score_for_math),
                "contribution": contribution,
            }

        total_score = ZERO if denominator == ZERO else quantize_score(numerator / denominator)
        rows.append(
            {
                "student_id": student.id,
                "total_score": total_score,
                "breakdown": breakdown,
                "_sort_name": student.normalized_name or str(student.id or ""),
                "_sort_id": student.id or 0,
            },
        )

    rows.sort(key=lambda row: (-row["total_score"], row["_sort_name"], row["_sort_id"]))
    for row in rows:
        row.pop("_sort_name")
        row.pop("_sort_id")
    return rows


def _count_item_in_denominator(
    *,
    formula: RankingFormula,
    item: RankingFormulaItem,
    is_missing: bool,
) -> bool:
    if not is_missing:
        return True

    if item.is_required:
        return True

    return formula.missing_score_policy == RankingFormula.MissingScorePolicy.ZERO


def _load_results(
    students: list[Student],
    formula_items: list[RankingFormulaItem],
) -> dict[tuple[int | None, int], StudentResult]:
    student_ids = [student.id for student in students if student.id is not None]
    assessment_ids = [item.assessment_id for item in formula_items]
    if not student_ids or not assessment_ids:
        return {}

    results = StudentResult.objects.filter(
        student_id__in=student_ids,
        assessment_id__in=assessment_ids,
    )
    return {
        (result.student_id, result.assessment_id): result
        for result in results
    }
