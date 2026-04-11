from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingFormulaItem
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.ranking_normalization import ZERO
from inspinia.rankings.services.ranking_normalization import normalize_formula_item_score
from inspinia.rankings.services.ranking_normalization import quantize_score
from inspinia.rankings.services.ranking_tiebreak import build_rank_sort_key

if TYPE_CHECKING:
    from collections.abc import Iterable
    from decimal import Decimal


@dataclass(slots=True)
class ComputedRankRow:
    student_id: int
    total_score: Decimal
    breakdown: dict[str, dict[str, Any]]
    normalized_name: str


def compute_rank_rows(
    formula: RankingFormula,
    students: Iterable[Student],
) -> list[ComputedRankRow]:
    formula_items = list(
        formula.items.select_related("assessment").order_by("sort_order", "id"),
    )
    student_list = list(students)
    results_by_key = _load_results(student_list, formula_items)

    rows: list[ComputedRankRow] = []
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

            breakdown_key = _build_breakdown_key(item, breakdown)
            breakdown[breakdown_key] = {
                "assessment_id": item.assessment_id,
                "assessment_code": item.assessment.code,
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
            ComputedRankRow(
                student_id=student.id or 0,
                total_score=total_score,
                breakdown=breakdown,
                normalized_name=student.normalized_name or str(student.id or ""),
            ),
        )

    rows.sort(key=lambda row: build_rank_sort_key(formula=formula, row=row, formula_items=formula_items))
    return rows


def compute_rankings(
    formula: RankingFormula,
    students: Iterable[Student],
) -> list[dict[str, Any]]:
    """Compatibility wrapper retained while callers migrate to compute_rank_rows."""
    return [
        {
            "student_id": row.student_id,
            "total_score": row.total_score,
            "breakdown": row.breakdown,
        }
        for row in compute_rank_rows(formula=formula, students=students)
    ]


def _build_breakdown_key(
    item: RankingFormulaItem,
    breakdown: dict[str, dict[str, Any]],
) -> str:
    base_key = item.assessment.code or f"ASSESSMENT-{item.assessment_id}"
    if base_key not in breakdown:
        return base_key

    fallback_key = f"{base_key}__{item.assessment_id}"
    if fallback_key not in breakdown:
        return fallback_key

    suffix = 2
    while True:
        candidate_key = f"{fallback_key}_{suffix}"
        if candidate_key not in breakdown:
            return candidate_key
        suffix += 1


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

    prefetched_results = _load_prefetched_results(students=students, assessment_ids=assessment_ids)
    if prefetched_results is not None:
        return prefetched_results

    results = StudentResult.objects.filter(
        student_id__in=student_ids,
        assessment_id__in=assessment_ids,
    )
    return {
        (result.student_id, result.assessment_id): result
        for result in results
    }


def _load_prefetched_results(
    *,
    students: list[Student],
    assessment_ids: list[int],
) -> dict[tuple[int | None, int], StudentResult] | None:
    results_by_key: dict[tuple[int | None, int], StudentResult] = {}
    for student in students:
        prefetched_cache = getattr(student, "_prefetched_objects_cache", {})
        if "results" not in prefetched_cache:
            return None

        for result in prefetched_cache["results"]:
            if result.assessment_id in assessment_ids:
                results_by_key[(result.student_id, result.assessment_id)] = result

    return results_by_key
