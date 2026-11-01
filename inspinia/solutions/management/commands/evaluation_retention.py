"""Bounded, explicitly invoked removal of expired private benchmark copies."""

import json
import uuid
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from inspinia.solutions import evaluation as ev
from inspinia.solutions.evaluation_models import EvaluationCase

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def _deadline(case):
    try:
        value = datetime.fromisoformat(case.provenance["retention_until"])
    except (KeyError, TypeError, ValueError):
        return None
    return None if timezone.is_naive(value) else value


def _curator(actor_id, *, lock=False):
    users = get_user_model()
    query = users.objects.select_for_update() if lock else users.objects
    actor = query.filter(pk=actor_id).first()
    if actor is None or not ev.assignments(actor).filter(role="curator").exists():
        message = "An active actor with an explicit curator assignment is required."
        raise CommandError(message)
    return actor


def _purge(actor_id, identifiers, cutoff):
    purged = []
    with transaction.atomic():
        ev.decision_lock()
        actor = _curator(actor_id, lock=True)
        for identifier in identifiers:
            case = EvaluationCase.objects.select_related("bundle", "family").get(pk=identifier)
            if not ev.allowed(actor, "curator", case):
                message = "Curator authority changed; no cases in this batch were purged."
                raise CommandError(message)
            deadline = _deadline(case)
            if deadline is None or deadline > cutoff:
                continue
            # Expiry must erase copies even after a separate eligibility invalidation.
            ev._invalidate(actor, case, "revocation", purge=True)  # noqa: SLF001 - capability checked above
            ev.audit(
                actor, case, "retention_expired", {"deadline": deadline.isoformat(), "cutoff": cutoff.isoformat()},
            )
            purged.append(str(case.pk))
    return purged


class Command(BaseCommand):
    help = (
        "Preview expired benchmark copies assigned to --actor. --apply erases only those private copies; "
        "never enables AI, contacts providers, deletes authored revisions or starts a scheduler."
    )

    def add_arguments(self, parser):
        parser.add_argument("--actor", type=int, required=True)
        parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
        parser.add_argument("--after", type=uuid.UUID)
        parser.add_argument("--apply", action="store_true")

    def handle(self, **options):
        limit = options["limit"]
        if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
            message = "--limit must be between 1 and 500."
            raise CommandError(message)
        actor = _curator(options["actor"])
        scopes = ev.assignments(actor).filter(role="curator").values_list("scope_id", flat=True)
        cases = (
            EvaluationCase.objects.filter(Q(pk__in=scopes) | Q(family_id__in=scopes))
            .filter(provenance__has_key="retention_until")
            .only("pk", "family_id", "provenance")
            .order_by("pk")
        )
        if options["after"] is not None:
            cases = cases.filter(pk__gt=options["after"])
        selected = list(cases[: limit + 1])
        has_more = len(selected) > limit
        selected = selected[:limit]
        cutoff = timezone.now()
        expired, invalid = [], 0
        for case in selected:
            deadline = _deadline(case)
            if deadline is None:
                invalid += 1
            elif deadline <= cutoff:
                expired.append(str(case.pk))
        purged = _purge(actor.pk, expired, cutoff) if options["apply"] else []
        self.stdout.write(
            json.dumps(
                {
                    "schema_version": 1,
                    "mode": "apply" if options["apply"] else "preview",
                    "as_of": cutoff.isoformat(),
                    "scanned": len(selected),
                    "expired_count": len(expired),
                    "expired_case_ids": expired,
                    "purged_count": len(purged),
                    "purged_case_ids": purged,
                    "invalid_deadline_count": invalid,
                    "has_more": has_more,
                    "next_after": str(selected[-1].pk) if has_more else None,
                    "provider_calls": 0,
                },
                sort_keys=True,
            ),
        )
