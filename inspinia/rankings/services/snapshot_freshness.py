"""Read-only freshness hints; never refresh or delete weighted snapshots."""

from django.db.models import Max
from django.db.models import Min

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import RankingSnapshot
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult


def snapshot_freshness(formula):
    if formula is None:
        return {}
    computed = RankingSnapshot.objects.filter(ranking_formula=formula).aggregate(value=Min("last_computed_at"))[
        "value"
    ]
    if computed is None:
        return {}
    assessment_ids = formula.items.values_list("assessment_id", flat=True)
    stamps = [
        formula.updated_at,
        Assessment.objects.filter(pk__in=assessment_ids).aggregate(value=Max("updated_at"))["value"],
        StudentResult.objects.filter(assessment_id__in=assessment_ids).aggregate(value=Max("updated_at"))["value"],
        Student.objects.aggregate(value=Max("updated_at"))["value"],
    ]
    latest = max(stamp for stamp in stamps if stamp is not None)
    return {
        "snapshots_stale": latest > computed,
        "snapshot_computed_at": computed,
        "snapshot_source_updated_at": latest,
    }
