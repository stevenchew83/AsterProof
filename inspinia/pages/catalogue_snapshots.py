"""Publish shared memberships off-request; cache progress from existing completions."""

import hashlib
import json
from collections import defaultdict
from statistics import mean
from statistics import median

from django.conf import settings
from django.db import transaction
from django.db.models import Q

from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueProblem
from inspinia.pages.catalogue_models import CatalogueProblemConcept
from inspinia.pages.catalogue_models import CatalogueState
from inspinia.pages.catalogue_models import ConceptLibrarySnapshot
from inspinia.pages.catalogue_models import UserConceptProgressSummary
from inspinia.pages.completion_record_fields import SOLVED_STATUSES
from inspinia.pages.concept_assignment_models import ConceptAssignmentState
from inspinia.pages.models import UserProblemCompletion


class SnapshotChangedError(RuntimeError):
    """Inputs changed during a rebuild; keep the previously published generation."""


def membership_scopes(cid, area, subject):
    return ("all", f"s:{subject}", f"a:{area}", f"c:{cid}", f"cs:{subject}:{cid}", f"ca:{area}:{cid}")


def assignment_signature():
    state = (
        ConceptAssignmentState.objects.filter(singleton_key=1)
        .values(
            "revision",
            "enabled",
            "initial_seed_complete",
            "registry_fingerprint",
            "needs_refresh",
        )
        .first()
    )
    return hashlib.sha256(
        json.dumps(
            {
                "enabled": getattr(settings, "CONCEPT_ASSIGNMENTS_ENABLED", False),
                "state": state,
            },
            sort_keys=True,
        ).encode(),
    ).hexdigest()


def current_snapshot():
    state = CatalogueState.objects.select_related("snapshot").filter(pk=1).first()
    if (
        state
        and state.snapshot
        and state.snapshot.source_revision == state.source_revision
        and state.snapshot.assignment_signature == assignment_signature()
    ):
        return state.snapshot
    return None


def rebuild_library_snapshot(*, force=False):  # noqa: C901, PLR0912, PLR0915
    """Explicit maintenance only. Never write an original problem or user record."""
    from inspinia.pages.catalogue_sources import iter_catalogue_sources

    state = CatalogueState.objects.get(pk=1)
    assignment_marker = assignment_signature()
    if not force and state.snapshot_id:
        snapshot = ConceptLibrarySnapshot.objects.get(pk=state.snapshot_id)
        if snapshot.source_revision == state.source_revision and snapshot.assignment_signature == assignment_marker:
            return snapshot
    concepts = dict(CatalogueConcept.objects.values_list("id", "redirect_id"))
    areas = dict(CatalogueArea.objects.values_list("id", "subject__name"))
    area_labels = {
        (subject, label): key
        for key, subject, label in CatalogueArea.objects.values_list(
            "id",
            "subject__name",
            "name",
        )
    }
    problems, links = {}, set()
    unmapped = defaultdict(int)
    for source in iter_catalogue_sources():
        uuid = str(source["problem_uuid"])
        if uuid in problems:
            continue
        source_links = set()
        for item in source.pop("coverage"):
            cid = item["id"]
            if cid not in concepts:
                message = f"Unknown catalogue concept: {cid}"
                raise ValueError(message)
            seen = set()
            while concepts[cid]:
                if cid in seen:
                    message = "Catalogue redirect cycle."
                    raise ValueError(message)
                seen.add(cid)
                cid = concepts[cid]
            subject = item["subject"]
            area = f"{subject}:{item['area_id']}" if item.get("area_id") else area_labels.get((subject, item["area"]))
            if area not in areas:
                message = f"Unknown catalogue area: {area}"
                raise ValueError(message)
            source_links.add((uuid, cid, area))
        problems[uuid] = source
        links.update(source_links)
        if not source_links:
            unmapped["all"] += 1
            unmapped[source["subject"]] += 1
    scope_problems = defaultdict(set)
    for uuid, cid, area in links:
        for scope in membership_scopes(cid, area, areas[area]):
            scope_problems[scope].add(uuid)
    totals = {}
    for key, ids in scope_problems.items():
        difficulties = [problems[uuid]["mohs"] for uuid in ids if problems[uuid]["mohs"] is not None]
        totals[key] = {"total": len(ids), "median_mohs": median(difficulties) if difficulties else None}
    # All staging writes and the publication pointer commit together. A source
    # mutation invalidates the revision in the same transaction as that mutation.
    with transaction.atomic():
        snapshot = ConceptLibrarySnapshot.objects.create(
            source_revision=state.source_revision,
            catalogue_version=state.catalogue_version,
            assignment_signature=assignment_marker,
            totals=totals,
            unmapped=dict(unmapped),
        )
        CatalogueProblem.objects.bulk_create(
            [CatalogueProblem(snapshot=snapshot, **row) for row in problems.values()],
            batch_size=256,
        )
        problem_ids = dict(snapshot.problems.values_list("problem_uuid", "id"))
        CatalogueProblemConcept.objects.bulk_create(
            [
                CatalogueProblemConcept(
                    problem_id=problem_ids[problems[uuid]["problem_uuid"]],
                    concept_id=cid,
                    area_id=area,
                )
                for uuid, cid, area in sorted(links)
            ],
            batch_size=256,
        )
        locked = CatalogueState.objects.select_for_update().get(pk=1)
        if (
            locked.source_revision != state.source_revision
            or locked.catalogue_version != state.catalogue_version
            or assignment_signature() != assignment_marker
        ):
            message = "Catalogue sources changed during the refresh."
            raise SnapshotChangedError(message)
        locked.snapshot = snapshot
        locked.save(update_fields=["snapshot"])
    return snapshot


def completion_rows(user):
    return list(
        UserProblemCompletion.objects.filter(user=user)
        .order_by("id")
        .values(
            "id",
            "statement_id",
            "problem_id",
            "status",
            "completion_date",
        ),
    )


def completion_fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def user_progress_summary(user, snapshot):  # noqa: C901
    """A cold user cache reads only that user's completions and matching published links."""
    rows = completion_rows(user)
    fingerprint = completion_fingerprint(rows)
    cached = UserConceptProgressSummary.objects.filter(
        user=user,
        snapshot=snapshot,
        completion_fingerprint=fingerprint,
    ).first()
    if cached:
        return cached.progress
    by_statement = {r["statement_id"]: r for r in rows if r["statement_id"]}
    by_problem = {r["problem_id"]: r for r in rows if r["problem_id"]}
    practiced = {}
    if rows:
        candidates = CatalogueProblem.objects.filter(snapshot=snapshot).filter(
            Q(statement_id__in=by_statement) | Q(problem_id__in=by_problem),
        )
        for problem in candidates.values("id", "statement_id", "problem_id", "mohs"):
            record = by_statement.get(problem["statement_id"], by_problem.get(problem["problem_id"]))
            status = str(record["status"]).strip().casefold() if record else "unattempted"
            if record and status != UserProblemCompletion.Status.UNATTEMPTED:
                practiced[problem["id"]] = {**record, "status": status, "mohs": problem["mohs"]}
    buckets = defaultdict(dict)
    if practiced:
        for pid, cid, area, subject in CatalogueProblemConcept.objects.filter(problem_id__in=practiced).values_list(
            "problem_id",
            "concept_id",
            "area_id",
            "area__subject__name",
        ):
            for scope in membership_scopes(cid, area, subject):
                buckets[scope][pid] = practiced[pid]
    progress = {}
    for key, records in buckets.items():
        solved = [r for r in records.values() if r["status"] in SOLVED_STATUSES]
        difficulties = [r["mohs"] for r in solved if r["mohs"] is not None]
        dates = [r["completion_date"] for r in records.values() if r["completion_date"]]
        progress[key] = {
            "solved": len(solved),
            "attempted": len(records) - len(solved),
            "solved_average_mohs": round(mean(difficulties), 1) if difficulties else None,
            "last_practiced": max(dates).isoformat() if dates else None,
        }
    with transaction.atomic():
        if completion_fingerprint(completion_rows(user)) != fingerprint:
            message = "Completion records changed during the refresh."
            raise SnapshotChangedError(message)
        if not CatalogueState.objects.filter(
            pk=1,
            snapshot=snapshot,
            source_revision=snapshot.source_revision,
        ).exists():
            message = "Library mappings changed during the refresh."
            raise SnapshotChangedError(message)
        if assignment_signature() != snapshot.assignment_signature:
            message = "Assignment decisions changed during the refresh."
            raise SnapshotChangedError(message)
        UserConceptProgressSummary.objects.get_or_create(
            user=user,
            snapshot=snapshot,
            completion_fingerprint=fingerprint,
            defaults={"progress": progress},
        )
    return progress


def scope_counts(snapshot, progress, scope):
    shared = snapshot.totals.get(scope, {})
    personal = progress.get(scope, {})
    total, solved = shared.get("total", 0), personal.get("solved", 0)
    percent = round(100 * solved / total, 1) if total else 0
    if solved < total:
        percent = min(percent, 99.9)
    return {
        **shared,
        **personal,
        "total": total,
        "solved": solved,
        "remaining": total - solved,
        "percent": percent,
        "median_mohs": shared.get("median_mohs"),
        "solved_average_mohs": personal.get("solved_average_mohs"),
    }
