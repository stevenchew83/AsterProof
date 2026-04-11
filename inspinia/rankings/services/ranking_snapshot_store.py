from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from typing import TYPE_CHECKING

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import RankingFormula
from inspinia.rankings.models import RankingFormulaItem
from inspinia.rankings.models import RankingSnapshot

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Iterator

    from inspinia.rankings.services.ranking_compute import ComputedRankRow


@contextmanager
def lock_formula_for_snapshot_refresh(*, formula_id: int) -> Iterator[RankingFormula]:
    with transaction.atomic():
        formula = RankingFormula.objects.select_for_update().get(pk=formula_id)
        # Lock child rows so formula-item edits cannot race snapshot recomputation.
        list(
            RankingFormulaItem.objects.select_for_update()
            .filter(ranking_formula_id=formula_id)
            .order_by("id")
            .values_list("id", flat=True),
        )
        assessment_ids = list(
            RankingFormulaItem.objects.filter(ranking_formula_id=formula_id)
            .order_by("assessment_id")
            .values_list("assessment_id", flat=True)
            .distinct(),
        )
        list(
            Assessment.objects.select_for_update()
            .filter(id__in=assessment_ids)
            .order_by("id")
            .values_list("id", flat=True),
        )
        yield formula


def store_ranking_snapshots(
    *,
    formula: RankingFormula,
    rows: Iterable[ComputedRankRow],
    formula_locked: bool = False,
) -> int:
    if formula_locked and not transaction.get_connection().in_atomic_block:
        msg = "formula_locked=True requires an active atomic transaction."
        raise RuntimeError(msg)

    row_list = list(rows)
    computed_at = timezone.now()
    version_label = f"v{formula.version}"
    version_hash = _build_formula_version_hash(formula)

    snapshots = [
        RankingSnapshot(
            ranking_formula=formula,
            student_id=row.student_id,
            season_year=formula.season_year,
            division=formula.division,
            total_score=row.total_score,
            rank_overall=index,
            rank_within_division=index,
            score_breakdown_json=_serialize_breakdown(row.breakdown),
            last_computed_at=computed_at,
            formula_version_label=version_label,
            formula_version_hash=version_hash,
        )
        for index, row in enumerate(row_list, start=1)
    ]

    if formula_locked:
        RankingSnapshot.objects.filter(ranking_formula=formula).delete()
        if snapshots:
            RankingSnapshot.objects.bulk_create(snapshots)
        return len(snapshots)

    with transaction.atomic():
        RankingFormula.objects.select_for_update().get(pk=formula.pk)
        RankingSnapshot.objects.filter(ranking_formula=formula).delete()
        if snapshots:
            RankingSnapshot.objects.bulk_create(snapshots)

    return len(snapshots)


def clear_ranking_snapshots(
    *,
    formula: RankingFormula,
    formula_locked: bool = False,
) -> int:
    if formula_locked and not transaction.get_connection().in_atomic_block:
        msg = "formula_locked=True requires an active atomic transaction."
        raise RuntimeError(msg)

    if formula_locked:
        deleted_count, _ = RankingSnapshot.objects.filter(ranking_formula=formula).delete()
        return deleted_count

    with transaction.atomic():
        RankingFormula.objects.select_for_update().get(pk=formula.pk)
        deleted_count, _ = RankingSnapshot.objects.filter(ranking_formula=formula).delete()
    return deleted_count


def _build_formula_version_hash(formula: RankingFormula) -> str:
    formula_items = list(
        formula.items.select_related("assessment").order_by("sort_order", "id"),
    )
    payload = {
        "formula_id": formula.id,
        "season_year": formula.season_year,
        "division": formula.division,
        "purpose": formula.purpose,
        "missing_score_policy": formula.missing_score_policy,
        "tiebreak_policy": formula.tiebreak_policy if isinstance(formula.tiebreak_policy, dict) else {},
        "version": formula.version,
        "items": [
            {
                "assessment_id": item.assessment_id,
                "assessment_code": item.assessment.code,
                "weight": str(item.weight),
                "normalization_method": item.normalization_method,
                "is_required": item.is_required,
                "sort_order": item.sort_order,
            }
            for item in formula_items
        ],
    }
    serialized_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()


def _serialize_breakdown(breakdown: dict) -> dict:
    return json.loads(json.dumps(breakdown, cls=DjangoJSONEncoder))
