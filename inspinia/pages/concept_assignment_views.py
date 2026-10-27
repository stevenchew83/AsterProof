"""Admin review and read-only tracing; every write uses a signed fresh preview."""

import csv
import json
from io import StringIO

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from inspinia.pages.concept_assignment_registry import REASON_LABELS
from inspinia.pages.concept_assignment_registry import REGISTRY
from inspinia.pages.concept_assignment_service import AssignmentConflictError
from inspinia.pages.concept_assignment_service import apply_review
from inspinia.pages.concept_assignment_service import audit_sources
from inspinia.pages.concept_assignment_service import preview_review
from inspinia.pages.concept_assignment_service import project_source
from inspinia.pages.concept_assignment_service import published_solution_evidence
from inspinia.pages.concept_assignment_service import storage_ready
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.concept_assignment_trace import source_uuid_query
from inspinia.pages.concept_assignment_trace import trace_source
from inspinia.pages.models import ConceptAssignmentReviewBatch
from inspinia.pages.models import ConceptAssignmentReviewEvent
from inspinia.pages.models import ProblemConceptAssignment
from inspinia.users.roles import user_has_admin_role

SALT = "problem-concept-review-v1"
SUBJECTS = ("Algebra", "Number Theory", "Geometry", "Combinatorics")


def _admin(request):
    from inspinia.pages.views import _require_admin_tools_access

    _require_admin_tools_access(request)
    if not user_has_admin_role(request.user):
        raise PermissionDenied


def _safe_csv(value):
    text = str(value if value is not None else "")
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else text


def report_csv(report):
    stream = StringIO()
    writer = csv.writer(stream)
    writer.writerow(
        [
            "Problem UUID",
            "Problem",
            "Concept ID",
            "Concept",
            "Disposition",
            "Source model",
            "Source row",
            "Source caption",
            "Field",
            "Caption",
            "Role",
            "Rule",
            "Reasons",
        ],
    )
    for trace in report["traces"]:
        for candidate in trace["candidates"]:
            for evidence in candidate["evidence"]:
                writer.writerow(
                    [
                        _safe_csv(value)
                        for value in [
                            trace["problem_uuid"],
                            trace["label"],
                            candidate["id"],
                            candidate["label"],
                            candidate["disposition"],
                            evidence["source_model"],
                            evidence["source_row_id"],
                            evidence["source_caption"],
                            evidence["field"],
                            evidence["caption"],
                            evidence["role"],
                            evidence["rule"],
                            ", ".join(evidence["reasons"]),
                        ]
                    ],
                )
    return stream.getvalue()


@login_required
@require_GET
def concept_assignment_review_list(request):  # noqa: C901, PLR0912
    _admin(request)
    filters = {
        key: str(request.GET.get(key) or "").strip()
        for key in ("subject", "year", "contest", "q", "concept", "state", "reason")
    }
    if filters["subject"] not in SUBJECTS:
        filters["subject"] = ""
    if filters["year"] and not filters["year"].isdigit():
        return HttpResponseBadRequest("Year must be a number.")
    ready = storage_ready()
    excluded = (
        ProblemConceptAssignment.objects.filter(is_current=True).values("problem_uuid")
        if ready and filters["state"] == "unmapped"
        else None
    )
    uuid_query = source_uuid_query(
        **{k: filters[k] for k in ("subject", "year", "contest", "q")},
        exclude_uuids=excluded,
    )
    rows = []
    materialized = (
        ready and filters["state"] != "unmapped" and ProblemConceptAssignment.objects.filter(is_current=True).exists()
    )
    if materialized:
        query = ProblemConceptAssignment.objects.filter(problem_uuid__in=uuid_query, is_current=True).order_by(
            "problem_uuid",
            "concept_id",
        )
        if filters["state"] in {"accepted", "suggested", "rejected"}:
            query = query.filter(disposition=filters["state"])
        elif filters["state"] == "stale":
            query = query.filter(is_stale=True)
        if filters["concept"]:
            cid = REGISTRY.canonical(filters["concept"])
            query = query.filter(
                concept_id__in=[
                    key for key in [*REGISTRY.definitions, *REGISTRY.redirects] if REGISTRY.canonical(key) == cid
                ],
            )
        if filters["reason"]:
            query = query.filter(reasons__icontains=filters["reason"])
        page = Paginator(query, 25).get_page(request.GET.get("page"))
        sources = load_sources([record.problem_uuid for record in page.object_list])
        for record in page.object_list:
            source = sources[str(record.problem_uuid)]
            definition = REGISTRY.definitions.get(REGISTRY.canonical(record.concept_id), {})
            rows.append(
                {
                    "problem_uuid": str(record.problem_uuid),
                    "label": source["label"],
                    "subject": source["subject"],
                    "concept_id": record.concept_id,
                    "concept": definition.get("label", record.concept_id),
                    "state": "stale" if record.is_stale else record.disposition,
                    "reasons": record.reasons,
                    "basis": "Evidence reviewed"
                    if record.decision_origin == "reviewed"
                    else "Exact legacy tag"
                    if record.disposition == "accepted"
                    else "Source suggestion",
                },
            )
    else:
        page = Paginator(uuid_query, 25).get_page(request.GET.get("page"))
        sources = load_sources(page.object_list)
        for source in sources.values():
            for candidate in trace_source(source)["candidates"]:
                if filters["concept"] and candidate["id"] != REGISTRY.canonical(filters["concept"]):
                    continue
                if (
                    filters["state"] in {"accepted", "suggested", "rejected"}
                    and candidate["disposition"] != filters["state"]
                ):
                    continue
                if filters["reason"] and filters["reason"] not in candidate["reasons"]:
                    continue
                rows.append(
                    {
                        "problem_uuid": source["problem_uuid"],
                        "label": source["label"],
                        "subject": source["subject"],
                        "concept_id": candidate["id"],
                        "concept": candidate["label"],
                        "state": "preview: " + candidate["disposition"],
                        "reasons": candidate["reasons"],
                        "basis": candidate["support_basis"],
                    },
                )
            if not trace_source(source)["candidates"] and not filters["concept"] and not filters["reason"]:
                rows.append(
                    {
                        "problem_uuid": source["problem_uuid"],
                        "label": source["label"],
                        "subject": source["subject"],
                        "concept_id": "",
                        "concept": "No mapped concepts",
                        "state": "unmapped",
                        "basis": "Inspect source captions",
                        "reasons": [],
                    },
                )
    for row in rows:
        row["reason_labels"] = [REASON_LABELS.get(reason, reason) for reason in row["reasons"]]
    if request.GET.get("export") in {"json", "csv"}:
        report = audit_sources(sources)
        if request.GET["export"] == "json":
            response = JsonResponse(report)
        else:
            response = HttpResponse(report_csv(report), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            'attachment; filename="concept-assignment-audit.' + request.GET["export"] + '"'
        )
        response["Cache-Control"] = "private, no-store"
        return response
    context = {
        "filters": filters,
        "subjects": SUBJECTS,
        "rows": rows,
        "page": page,
        "storage_ready": ready,
        "materialized": materialized,
        "identity_proposals": REGISTRY.identity_proposals(),
        "registry_fingerprint": REGISTRY.fingerprint,
    }
    response = render(request, "pages/concept-assignment-review.html", context)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def concept_assignment_review_detail(request, problem_uuid):
    _admin(request)
    sources = load_sources([problem_uuid])
    source = sources.get(str(problem_uuid))
    if source is None:
        raise Http404
    trace = trace_source(source)
    ready = storage_ready()
    records = (
        list(ProblemConceptAssignment.objects.filter(problem_uuid=problem_uuid, is_current=True)) if ready else []
    )
    proofs = published_solution_evidence([problem_uuid])
    coverage = project_source(source, records, proofs)
    candidates = {row["id"]: row for row in trace["candidates"]}
    for record in records:
        cid = REGISTRY.canonical(record.concept_id)
        if cid not in candidates and cid in REGISTRY.definitions:
            candidates[cid] = {
                **REGISTRY.presentation(cid, source["subject"], record.roles),
                "evidence": [],
                "reasons": record.reasons,
            }
        if cid in candidates:
            candidates[cid]["record"] = record
    for candidate in candidates.values():
        candidate["area_options"] = [
            {**area, "key": key}
            for key, area in sorted(REGISTRY.areas.items())
            if area["subject"] in REGISTRY.definitions[candidate["id"]]["subjects"]
        ]
    from inspinia.pages.asymptote_render import build_statement_render_segments

    context = {
        "source": source,
        "trace": trace,
        "candidates": list(candidates.values()),
        "coverage": coverage,
        "proofs": proofs.values(),
        "storage_ready": ready,
        "concept_options": sorted(REGISTRY.definitions.values(), key=lambda d: d["label"].casefold()),
        "events": ConceptAssignmentReviewEvent.objects.filter(problem_uuid=problem_uuid)
        .select_related("actor")
        .order_by("-id")[:50]
        if ready
        else [],
        "statement_segments": build_statement_render_segments(source["statement_text"]),
        "area_options": [{**area, "key": key} for key, area in sorted(REGISTRY.areas.items())],
    }
    response = render(request, "pages/concept-assignment-detail.html", context)
    response["Cache-Control"] = "private, no-store"
    return response


def _form_decisions(request):
    if request.content_type == "application/json":
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            message = "Send an object containing a decisions list."
            raise AssignmentConflictError(message)
        return payload.get("decisions")
    if request.POST.get("decisions_json"):
        return json.loads(request.POST["decisions_json"])
    if request.POST.getlist("selected"):
        if request.POST.get("action") not in {"hold", "reject"}:
            message = "Bulk confirmation needs individual evidence; use the reviewed JSON manifest."
            raise AssignmentConflictError(message)
        return [
            {
                "problem_uuid": value.split("|", 1)[0],
                "concept_id": value.split("|", 1)[1],
                "action": request.POST["action"],
                "rationale": request.POST.get("rationale", ""),
            }
            for value in request.POST.getlist("selected")
        ]
    reference = request.POST.get("evidence_reference", "statement")
    return [
        {
            "problem_uuid": request.POST.get("problem_uuid"),
            "concept_id": request.POST.get("concept_id"),
            "action": request.POST.get("action"),
            "replacement_concept_id": request.POST.get("replacement_concept_id"),
            "area_context": request.POST.get("area_context", ""),
            "rationale": request.POST.get("rationale"),
            "roles": request.POST.getlist("roles"),
            "evidence": {
                "kind": "published_solution" if reference.startswith("solution:") else "statement",
                "reference": reference.partition(":")[2],
                "quote": request.POST.get("evidence_quote"),
            },
        },
    ]


@login_required
@require_POST
def concept_assignment_review_preview(request):
    _admin(request)
    try:
        report = preview_review(_form_decisions(request))
        token = signing.dumps(
            {key: report[key] for key in ("decisions", "sha256", "operation_id")},
            salt=SALT,
            compress=True,
        )
    except (AssignmentConflictError, ValueError, KeyError, TypeError) as exc:
        return HttpResponseBadRequest(str(exc))
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"report": report, "token": token, "storage_ready": storage_ready()})
    return render(
        request,
        "pages/concept-assignment-preview.html",
        {"report": report, "token": token, "storage_ready": storage_ready()},
    )


@login_required
@require_POST
def concept_assignment_review_apply(request):
    _admin(request)
    try:
        value = json.loads(request.body) if request.content_type == "application/json" else request.POST
        report = signing.loads(value.get("token", ""), salt=SALT, max_age=1800)
        receipt = apply_review(report, request.user)
    except (signing.BadSignature, AssignmentConflictError, ValueError, KeyError, TypeError) as exc:
        return HttpResponse(str(exc), status=409)
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse(receipt)
    return render(
        request,
        "pages/concept-assignment-receipt.html",
        {
            "receipt": receipt,
            "receipt_url": reverse("pages:concept_assignment_receipt", args=[receipt["operation_id"]]),
        },
    )


@login_required
@require_GET
def concept_assignment_receipt(request, operation_id):
    _admin(request)
    if not storage_ready():
        raise Http404
    batch = ConceptAssignmentReviewBatch.objects.filter(operation_id=operation_id).first()
    if batch is None:
        raise Http404
    response = JsonResponse({"receipt": batch.receipt, "manifest": batch.manifest})
    response["Cache-Control"] = "private, no-store"
    return response
