"""Explicit invalidation for maintenance requests without a source-row change.

Migration 0039 installs SQLite/PostgreSQL triggers for source and catalogue writes,
including QuerySet.update, bulk imports, published evidence and raw maintenance SQL.
Completion records use a separate per-user content fingerprint.
"""

from django.db import OperationalError
from django.db import ProgrammingError
from django.db.models import F

from inspinia.pages.catalogue_models import CatalogueState


def invalidate_catalogue_snapshot(*args, using="default", **kwargs):
    try:
        CatalogueState.objects.using(using).filter(pk=1).update(source_revision=F("source_revision") + 1)
    except (OperationalError, ProgrammingError) as exc:
        message = str(exc).lower()
        if "cataloguestate" not in message or not any(t in message for t in ("no such table", "does not exist")):
            raise
