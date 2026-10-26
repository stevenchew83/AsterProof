"""Bounded native source snapshots, independent of the new review schema."""

import hashlib
import json
import uuid
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.users.roles import user_has_admin_role

MAX_EXPORT_PROBLEMS = 50
TAG_FIELDS = (
    "technique",
    "canonical_subtopic",
    "main_topic",
    "domains",
    "normalization_status",
    "object_tags",
    "technique_tags",
    "lemma_theorem_tags",
    "proof_roles",
)
SUBJECTS = {
    "a": "Algebra",
    "alg": "Algebra",
    "algebra": "Algebra",
    "n": "Number Theory",
    "nt": "Number Theory",
    "number theory": "Number Theory",
    "number-theory": "Number Theory",
    "g": "Geometry",
    "geo": "Geometry",
    "geometry": "Geometry",
    "c": "Combinatorics",
    "comb": "Combinatorics",
    "combinatorics": "Combinatorics",
}


def source_digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(),
    ).hexdigest()


def tag_snapshot(tag):
    result = {}
    for key in TAG_FIELDS:
        value = tag.get(key) or (
            [] if key in {"object_tags", "technique_tags", "lemma_theorem_tags", "proof_roles"} else ""
        )
        result[key] = sorted(str(item) for item in value) if isinstance(value, list) else str(value)
    return result


def source_fingerprint(source):
    return source_digest(
        {
            "uuid": source["problem_uuid"],
            "subject": source["subject"],
            "active": source["active"],
            "source_owner_active": source.get("source_owner_active", source["active"]),
            "effective_source": source["effective_source"],
            "tags": sorted([tag_snapshot(t) for t in source["tags"]], key=source_digest),
        },
    )


def read_assignment_sources(uuids):
    """Four bounded ORM reads; preserve suppressed rows and exact ownership."""
    wanted = {str(value) for value in uuids}
    if not wanted:
        return {}
    statements = list(
        ContestProblemStatement.objects.filter(problem_uuid__in=wanted)
        .order_by("-updated_at", "-id")
        .values(
            "id",
            "statement_uuid",
            "problem_uuid",
            "linked_problem_id",
            "contest_year_problem",
            "topic",
            "contest_year",
            "contest_name",
            "is_active",
            "statement_latex",
            "linked_problem__topic",
        ),
    )
    linked_ids = {s["linked_problem_id"] for s in statements if s["linked_problem_id"]}
    problems = list(
        ProblemSolveRecord.objects.filter(Q(problem_uuid__in=wanted) | Q(pk__in=linked_ids)).values(
            "id",
            "problem_uuid",
            "contest_year_problem",
            "topic",
            "year",
            "contest",
            "problem",
            "is_active",
        ),
    )
    by_problem = {p["id"]: p for p in problems}
    own, linked = defaultdict(list), defaultdict(list)
    for tag in (
        StatementTopicTechnique.objects.filter(statement_id__in=[s["id"] for s in statements])
        .values(
            "id",
            "statement_id",
            *TAG_FIELDS,
        )
        .order_by("technique", "id")
    ):
        own[tag["statement_id"]].append(tag)
    for tag in (
        ProblemTopicTechnique.objects.filter(record_id__in=by_problem)
        .values(
            "id",
            "record_id",
            *TAG_FIELDS,
        )
        .order_by("technique", "id")
    ):
        linked[tag["record_id"]].append(tag)
    sources = {}
    for s in statements:
        key = str(s["problem_uuid"])
        if key in sources:
            continue
        problem = by_problem.get(s["linked_problem_id"])
        mismatch = problem is not None and str(problem["problem_uuid"]) != key
        statement_owned = bool(own[s["id"]])
        sources[key] = {
            "problem_uuid": key,
            "statement_id": s["id"],
            "statement_uuid": str(s["statement_uuid"]),
            "problem_id": s["linked_problem_id"],
            "label": s["contest_year_problem"],
            "subject": SUBJECTS.get(str(s["topic"] or s["linked_problem__topic"] or "").strip().casefold(), ""),
            "year": s["contest_year"],
            "contest": s["contest_name"],
            "active": s["is_active"],
            "linked_problem_active": problem["is_active"] if problem else None,
            "source_owner_active": s["is_active"] if statement_owned else bool(problem and problem["is_active"]),
            "statement_text": s["statement_latex"],
            "statement_hash": source_digest(s["statement_latex"].replace("\r\n", "\n").strip()),
            "effective_source": "statement" if statement_owned else "problem",
            "tags": own[s["id"]] or linked[s["linked_problem_id"]],
            "conflicts": ["PROBLEM_UUID_MISMATCH"] if mismatch else [],
        }
    for p in problems:
        key = str(p["problem_uuid"])
        if key not in wanted or key in sources:
            continue
        sources[key] = {
            "problem_uuid": key,
            "statement_id": None,
            "statement_uuid": None,
            "problem_id": p["id"],
            "label": p["contest_year_problem"] or f"{p['contest']} {p['year']} {p['problem']}",
            "subject": SUBJECTS.get(str(p["topic"] or "").strip().casefold(), ""),
            "year": p["year"],
            "contest": p["contest"],
            "active": p["is_active"],
            "linked_problem_active": p["is_active"],
            "source_owner_active": p["is_active"],
            "statement_text": "",
            "statement_hash": source_digest(""),
            "effective_source": "problem",
            "tags": linked[p["id"]],
            "conflicts": [],
        }
    for source in sources.values():
        source["source_fingerprint"] = source_fingerprint(source)
    return sources


def review_storage_state():
    """Metadata/count reads only; no dependency on unreleased model classes."""
    expected = {
        "pages_problemconceptassignment",
        "pages_conceptassignmentreviewbatch",
        "pages_conceptassignmentreviewevent",
        "pages_conceptassignmentstate",
    }
    present = expected.intersection(connection.introspection.table_names())
    if not present:
        return {"state": "absent", "assignment_count": 0}
    if present != expected:
        return {"state": "partial_schema", "assignment_count": None}
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM pages_problemconceptassignment")
        count = cursor.fetchone()[0]
    return {"state": "empty_verified" if count == 0 else "nonempty_requires_live_review", "assignment_count": count}


@transaction.non_atomic_requests
@login_required
@require_GET
def assignment_source_export(request):
    """Read-only application export; works before review tables are installed."""
    from inspinia.pages.views import _require_admin_tools_access

    _require_admin_tools_access(request)
    if not user_has_admin_role(request.user):
        raise PermissionDenied
    values = request.GET.getlist("problem_uuid")
    if not 1 <= len(values) <= MAX_EXPORT_PROBLEMS:
        return HttpResponseBadRequest("Supply between 1 and 50 problem_uuid parameters.")
    try:
        keys = sorted({str(uuid.UUID(value)) for value in values})
    except (ValueError, TypeError, AttributeError):
        return HttpResponseBadRequest("Every problem_uuid must be a UUID.")
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute("SET LOCAL statement_timeout = '15s'")
                cursor.execute("SET LOCAL lock_timeout = '1s'")
        sources = read_assignment_sources(keys)
        payload = {
            "schema_version": 1,
            "kind": "asterproof-assignment-source-snapshot",
            "captured_at_utc": timezone.now().isoformat(),
            "requested_problem_uuids": keys,
            "missing_problem_uuids": sorted(set(keys) - sources.keys()),
            "transaction_read_only": connection.vendor == "postgresql",
            "sources": sources,
            "review_storage": review_storage_state(),
            "source_writes": 0,
        }
        payload["sha256"] = source_digest(payload)
    response = JsonResponse(payload)
    response["Cache-Control"] = "private, no-store"
    response["Content-Disposition"] = 'attachment; filename="assignment-sources-' + payload["sha256"][:16] + '.json"'
    return response
