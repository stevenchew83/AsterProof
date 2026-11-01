"""Migration-safe navigation visibility; capability services remain authoritative."""

from django.db import OperationalError
from django.db import ProgrammingError
from django.db import transaction

from . import evaluation as ev


def evaluation_workspace(request):
    user = getattr(request, "user", None)
    visible = False
    if getattr(user, "is_authenticated", False) and getattr(user, "is_active", False):
        try:
            # A missing table must roll back its own savepoint, not the surrounding request transaction.
            with transaction.atomic():
                visible = ev.assignments(user).exists()
        except (OperationalError, ProgrammingError):
            visible = False
    return {"evaluation_workspace_available": visible}
