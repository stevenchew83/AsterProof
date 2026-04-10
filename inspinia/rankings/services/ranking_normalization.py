from __future__ import annotations

from decimal import Decimal

from inspinia.rankings.models import RankingFormulaItem
from inspinia.rankings.models import StudentResult

SCORE_QUANTUM = Decimal("0.0001")
HUNDRED = Decimal("100")
ZERO = Decimal("0")


def quantize_score(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM)


def normalize_formula_item_score(
    item: RankingFormulaItem,
    result: StudentResult | None,
) -> Decimal | None:
    if result is None:
        return None

    if item.normalization_method == RankingFormulaItem.NormalizationMethod.RAW:
        return _normalize_raw(result)

    if item.normalization_method == RankingFormulaItem.NormalizationMethod.PERCENT_OF_MAX:
        return _normalize_percent_of_max(result, item)

    if item.normalization_method == RankingFormulaItem.NormalizationMethod.FIXED_SCALE:
        return _normalize_fixed_scale(result, item)

    if item.normalization_method == RankingFormulaItem.NormalizationMethod.ZSCORE:
        return _normalize_zscore_placeholder(result)

    return _normalize_raw(result)


def _normalize_raw(result: StudentResult) -> Decimal | None:
    if result.raw_score is None:
        return None
    return quantize_score(result.raw_score)


def _normalize_percent_of_max(
    result: StudentResult,
    item: RankingFormulaItem,
) -> Decimal | None:
    if result.raw_score is None:
        return None

    max_score = item.assessment.max_score
    if not max_score:
        return quantize_score(result.raw_score)

    return quantize_score((result.raw_score / max_score) * HUNDRED)


def _normalize_fixed_scale(
    result: StudentResult,
    item: RankingFormulaItem,
) -> Decimal | None:
    if result.normalized_score is not None:
        return quantize_score(result.normalized_score)

    percent_score = _normalize_percent_of_max(result, item)
    if percent_score is not None:
        return percent_score

    return _normalize_raw(result)


def _normalize_zscore_placeholder(result: StudentResult) -> Decimal | None:
    # Task 4 placeholder: true cohort z-score normalization needs the full
    # assessment distribution. Until that lands, use raw_score when present so
    # ranking stays deterministic, otherwise treat the result as missing.
    if result.raw_score is None:
        return None

    return quantize_score(result.raw_score)
