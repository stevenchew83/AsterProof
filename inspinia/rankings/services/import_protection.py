"""Shared transaction and reviewed-value protection for ranking writers.

Only the small allowlist below may enter a held-row receipt. Uploaded identity
numbers, free-form notes, and arbitrary source columns never enter this queue.
"""

from contextlib import contextmanager
from datetime import date
from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation

from django.db import transaction
from django.db.models import F

from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import OutcomeAlias
from inspinia.rankings.models import RankingCorrection
from inspinia.rankings.models import RankingCorrectionItem
from inspinia.rankings.models import RankingImportConflict
from inspinia.rankings.models import RankingWriteLock
from inspinia.rankings.models import School
from inspinia.rankings.models import SchoolAlias
from inspinia.rankings.models import Student
from inspinia.rankings.models import normalize_name

PROTECTED_FIELDS = {
    "student": frozenset({"full_name", "birth_year", "school_id"}),
    "result": frozenset({"raw_score", "medal", "band", "status_text"}),
    "assessment": frozenset({"display_name", "assessment_date"}),
}


@contextmanager
def ranking_write_lock():
    """Serialize short ranking write transactions, including object creation."""
    with transaction.atomic():
        RankingWriteLock.objects.get_or_create(pk=1)
        RankingWriteLock.objects.select_for_update().get(pk=1)
        yield


def begin_import(batch):
    """Require a fresh batch; callers hold ranking_write_lock for the apply."""
    current = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if current.status not in {ImportBatch.Status.UPLOADED, ImportBatch.Status.PREVIEWED}:
        msg = "This import batch has already been applied or consumed. Create a new preview instead."
        raise ValueError(msg)
    return current


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _equal(field, left, right):
    if field == "raw_score" and left is not None and right is not None:
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except InvalidOperation:
            return False
    return json_value(left) == json_value(right)


def safe_operations(operations):
    """Project reviewed fields, never retain a whole source row."""
    safe = []
    for operation in operations:
        kind = operation.get("kind")
        values = {
            name: json_value(value)
            for name, value in operation.get("values", {}).items()
            if name in PROTECTED_FIELDS.get(kind, ())
        }
        if values and operation.get("target_id"):
            safe.append({"kind": kind, "target_id": int(operation["target_id"]), "values": values})
    return safe


def protected_changes(kind, target_id, values):
    """Return differences from the latest applied correction for each field."""
    if not target_id or kind not in PROTECTED_FIELDS:
        return []
    approved = {}
    items = RankingCorrectionItem.objects.filter(
        kind=kind,
        target_id=target_id,
        correction__status=RankingCorrection.Status.APPLIED,
    ).order_by(F("correction__decided_at").desc(nulls_last=True), "-pk")
    for item in items:
        for name, value in item.changes.items():
            if name in PROTECTED_FIELDS[kind] and name not in approved:
                approved[name] = (value, item.correction_id)
    conflicts = []
    for name, value in values.items():
        if name in approved and not _equal(name, value, approved[name][0]):
            conflicts.append(
                {
                    "kind": kind,
                    "target_id": int(target_id),
                    "field": name,
                    "approved": json_value(approved[name][0]),
                    "incoming": json_value(value),
                    "correction_id": approved[name][1],
                },
            )
    return conflicts


def guard_import_row(batch, row_number, operations):
    """Hold the entire source row if any of its reviewed values would change."""
    operations = safe_operations(operations)
    conflicts = [
        conflict
        for operation in operations
        for conflict in protected_changes(operation["kind"], operation["target_id"], operation["values"])
    ]
    if not conflicts:
        return False
    RankingImportConflict.objects.get_or_create(
        batch=batch,
        row_number=row_number,
        defaults={"operations": operations, "conflicts": conflicts},
    )
    return True


def canonical_outcomes(assessment_id, values):
    """Apply explicit assessment-scoped aliases, never infer label meaning."""
    result = dict(values)
    aliases = OutcomeAlias.objects.filter(assessment_id=assessment_id, active=True)
    lookup = {(alias.field, alias.normalized_alias): alias.canonical for alias in aliases}
    for name in ("band", "medal", "status_text"):
        if result.get(name):
            result[name] = lookup.get((name, normalize_name(result[name])), result[name])
    return result


def canonical_school(name):
    """Resolve a reviewed school alias or existing name without creating data."""
    normalized = normalize_name(name)
    alias = SchoolAlias.objects.select_related("school").filter(normalized_name=normalized, active=True).first()
    if alias:
        return alias.school
    return School.objects.filter(normalized_name=normalized).first()


def reviewed_name_candidates(name):
    """Find old reviewed names without treating name equality as identity proof."""
    normalized = normalize_name(name)
    ids = set()
    items = RankingCorrectionItem.objects.filter(
        kind="student",
        correction__status=RankingCorrection.Status.APPLIED,
    )
    for item in items:
        previous = item.before.get("values", {}).get("full_name")
        identity_changed = {"full_name", "birth_year"}.intersection(item.changes)
        if identity_changed and previous and normalize_name(previous) == normalized:
            ids.add(item.target_id)
    return Student.objects.filter(pk__in=ids)
