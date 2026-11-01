"""Private server-rendered workspace; authority stays in the evidence services."""

import json
import uuid
from functools import wraps
from http import HTTPStatus
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods

from . import evaluation as ev
from .evaluation_forms import DOMAINS
from .evaluation_forms import MAX_DEFECTS
from .evaluation_forms import AdjudicationForm
from .evaluation_forms import AssetFormSet
from .evaluation_forms import CaseForm
from .evaluation_forms import DefectFormSet
from .evaluation_forms import FamilyForm
from .evaluation_forms import FindingAdjudicationForm
from .evaluation_forms import FindingAssessmentFormSet
from .evaluation_forms import FindingReviewForm
from .evaluation_forms import JudgmentForm
from .evaluation_forms import ProfileForm
from .evaluation_forms import RunImportForm
from .evaluation_forms import SnapshotForm
from .evaluation_models import EvaluationRun

PAGE_SIZE = 25
REQUIRED_FINDING_JUDGMENTS = 2


def _private(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _response(request, template, context, *, status=200):
    return _private(render(request, f"solutions/evaluation/{template}.html", context, status=status))


def _evidence_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ev.EvaluationError as error:
            text = (
                "Evidence is unavailable or permission is missing."
                if error.status == HTTPStatus.FORBIDDEN
                else str(error)
            )
            return _private(HttpResponse(text, status=error.status, content_type="text/plain; charset=utf-8"))

    return wrapped


def _case(user, case_id):
    return get_object_or_404(ev.visible_cases(user), pk=case_id)


def _assets(case_id, payload):
    return [
        {**item, "url": reverse("solutions:evaluation_asset", args=[case_id, item["id"]])}
        for item in payload.get("assets", [])
    ]


def _form_page(request, title, form, *, cancel_url=None, **context):
    return _response(
        request,
        "form",
        {
            "page_title": title,
            "form": form,
            "cancel_url": cancel_url or reverse("solutions:evaluation_workspace"),
            **context,
        },
        status=422
        if request.method == "POST"
        and (
            form.errors
            or any(group["forms"].errors or group["forms"].non_form_errors() for group in context.get("formsets", []))
        )
        else 200,
    )


def _error_on_form(form, error):
    if isinstance(error, ev.EvaluationError) and error.status == HTTPStatus.FORBIDDEN:
        raise error
    form.add_error(
        None,
        str(error) if isinstance(error, ev.EvaluationError) else "A selected evidence record is unavailable.",
    )


@login_required
@never_cache
@require_GET
@_evidence_errors
def evaluation_workspace(request):
    if not ev.assignments(request.user).exists():
        raise ev.EvaluationError
    query = request.GET.get("q", "").strip()[:100]
    domain = request.GET.get("domain", "")
    cases = ev.visible_cases(request.user)
    if query:
        try:
            cases = cases.filter(pk=uuid.UUID(query))
        except ValueError:
            cases = cases.none()
    if domain in dict(DOMAINS):
        cases = cases.filter(family__domain=domain)
    else:
        domain = ""
    curator_scopes = ev.assignments(request.user).filter(role="curator").values_list("scope_id", flat=True)
    families = ev.visible_families(request.user).filter(pk__in=curator_scopes).order_by("created_at")
    family_page = Paginator(families, PAGE_SIZE).get_page(request.GET.get("family_page"))
    snapshots = []
    for item in ev.visible_snapshots(request.user)[:100]:
        item.can_import = ev.allowed(request.user, "custodian", item)
        snapshots.append(item)
    return _response(
        request,
        "workspace",
        {
            "page_title": "Assigned evaluation work",
            "page_obj": Paginator(cases, PAGE_SIZE).get_page(request.GET.get("page")),
            "filters": {"q": query, "domain": domain},
            "domains": DOMAINS,
            "pagination_query": urlencode({"q": query, "domain": domain, "family_page": family_page.number}),
            "families": family_page,
            "family_page": family_page,
            "family_pagination_query": urlencode({"q": query, "domain": domain, "page": request.GET.get("page", "1")}),
            "snapshots": snapshots,
            "runs": ev.visible_runs(request.user).order_by("-created_at")[:100],
            "can_create": ev.allowed(request.user, "curator", ev.WORKSPACE),
            "can_freeze": ev.assignments(request.user).filter(role="custodian").exists(),
        },
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@_evidence_errors
def evaluation_family_create(request):
    ev.require(request.user, "curator", ev.WORKSPACE)
    form = FamilyForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            family = ev.create_family(request.user, form.cleaned_data)
        except ev.EvaluationError as error:
            _error_on_form(form, error)
        else:
            messages.success(request, "Problem family prepared.")
            return redirect("solutions:evaluation_case_create", family.pk)
    return _form_page(request, "Create problem family", form, submit_label="Create family")


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@_evidence_errors
def evaluation_case_create(request, family_id):
    family = get_object_or_404(ev.visible_families(request.user), pk=family_id)
    ev.require(request.user, "curator", family)
    form = CaseForm(request.POST if request.method == "POST" else None)
    images = AssetFormSet(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        prefix="assets",
    )
    if request.method == "POST":
        valid = form.is_valid()
        images_valid = images.is_valid()
        if valid and images_valid:
            assets = []
            for row in images:
                uploaded = row.cleaned_data.get("image")
                if uploaded:
                    assets.append(
                        {
                            "data": uploaded.read(),
                            "mime_type": uploaded.content_type,
                            "role": row.cleaned_data["role"],
                            "description": row.cleaned_data["description"],
                        },
                    )
            try:
                case = ev.create_case(request.user, family, form.payload(), assets=assets)
            except ev.EvaluationError as error:
                _error_on_form(form, error)
            else:
                messages.success(
                    request,
                    "Case and complete input bundle frozen. Mathematical review is still required.",
                )
                return redirect("solutions:evaluation_case_detail", case.pk)
    return _form_page(
        request,
        "Prepare evaluation case",
        form,
        submit_label="Freeze case input",
        introduction="Supply the exact statement, proof, permissions and any essential diagrams.",
        formsets=[
            {
                "title": "Managed images",
                "item_label": "Image",
                "forms": images,
                "help": (
                    "Optional PNG, JPEG, GIF or WebP images, at most 3 MB each. "
                    "Essential diagrams belong in this bundle."
                ),
            },
        ],
    )


@login_required
@never_cache
@require_GET
@_evidence_errors
def evaluation_case_detail(request, case_id):
    case = _case(request.user, case_id)
    payload = ev.case_payload(request.user, case)
    can_assess = ev.allowed(request.user, "finding_evaluator", case)
    can_adjudicate = ev.allowed(request.user, "adjudicator", case)
    finding_runs = list(ev.visible_case_runs(request.user, case)) if can_assess or can_adjudicate else []
    for run in finding_runs:
        run.can_assess = can_assess
        run.can_adjudicate = can_adjudicate
    return _response(
        request,
        "case_detail",
        {
            "page_title": "Evaluation case",
            "case": case,
            "case_data": payload,
            "bundle": payload["bundle"],
            "assets": _assets(case_id, payload),
            "judgments": payload.get("judgments", []),
            "finding_runs": finding_runs,
        },
    )


def _judgment(request, case_id, *, adjudication=False):
    case = _case(request.user, case_id)
    payload = ev.case_payload(request.user, case)
    ev.require(request.user, "adjudicator" if adjudication else "reviewer", case)
    if not payload["can_adjudicate" if adjudication else "can_judge"]:
        message = "This review round is not available for another submission."
        raise ev.EvaluationError(message, status=409)
    form_type = AdjudicationForm if adjudication else JudgmentForm
    form = form_type(
        request.POST if request.method == "POST" else None,
        initial={"expected_digest": payload["digest"]},
    )
    defects = DefectFormSet(
        request.POST if request.method == "POST" else None,
        prefix="defects",
        initial=[{"id": uuid.uuid4()} for _ in range(MAX_DEFECTS)],
    )
    if request.method == "POST":
        valid = form.is_valid()
        defects_valid = defects.is_valid()
        if valid and defects_valid:
            findings = [item for row in defects if (item := row.payload()) is not None]
            try:
                action = ev.adjudicate if adjudication else ev.submit_judgment
                action(request.user, case, form.payload(findings), form.cleaned_data["expected_digest"])
            except ev.EvaluationError as error:
                _error_on_form(form, error)
            else:
                messages.success(
                    request,
                    "Adjudication preserved." if adjudication else "Independent judgment preserved.",
                )
                return redirect("solutions:evaluation_case_detail", case.pk)
    return _form_page(
        request,
        "Adjudicate mathematical judgment" if adjudication else "Independent mathematical judgment",
        form,
        submit_label="Submit adjudication" if adjudication else "Submit independent judgment",
        cancel_url=reverse("solutions:evaluation_case_detail", args=[case.pk]),
        frozen_input=payload["bundle"],
        assets=_assets(case.pk, payload),
        judgments=payload.get("judgments", []) if adjudication else [],
        formsets=[
            {
                "title": "Mathematical defects",
                "item_label": "Defect",
                "forms": defects,
                "help": (
                    "Leave unused rows blank. Omissions may have no source quote. "
                    "Distinguish independent roots from downstream consequences."
                ),
            },
        ],
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@_evidence_errors
def evaluation_judgment(request, case_id):
    return _judgment(request, case_id)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@_evidence_errors
def evaluation_adjudication(request, case_id):
    return _judgment(request, case_id, adjudication=True)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@_evidence_errors
def evaluation_snapshot_create(request):
    if not ev.assignments(request.user).filter(role="custodian").exists():
        raise ev.EvaluationError
    initial = {}
    if request.method == "GET":
        cases = [
            case
            for case in ev.visible_cases(request.user)
            if ev.allowed(request.user, "custodian", case)
            and case.metadata.get("corpus") == "mathematical_challenge"
            and ev.case_state(case)["status"] in {"verified", "adjudicated"}
        ]
        membership = ev.default_membership(cases)
        historical = {
            key: value
            for snapshot in ev.visible_snapshots(request.user)
            for key, value in snapshot.manifest["families"].items()
        }
        by_case = {str(case.pk): str(case.family_id) for case in cases}
        for row in membership:
            row["partition"] = historical.get(by_case[row["case_id"]], row["partition"])
        initial = {
            "membership": membership,
            "protocol": {
                "rubric_version": "math-v1",
                "split_policy": "60/20/20 by family and domain",
                "seed": "math-v1",
            },
        }
    form = SnapshotForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            ev.freeze_dataset(
                request.user,
                form.cleaned_data["name"],
                form.cleaned_data["membership"],
                form.cleaned_data["protocol"],
            )
        except (ev.EvaluationError, ObjectDoesNotExist) as error:
            _error_on_form(form, error)
        else:
            messages.success(request, "Dataset snapshot frozen. This does not authorize an experiment or activation.")
            return redirect("solutions:evaluation_workspace")
    return _form_page(request, "Freeze dataset snapshot", form, submit_label="Freeze verified dataset")


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@_evidence_errors
def evaluation_profile_create(request):
    ev.require(request.user, "curator", ev.WORKSPACE)
    form = ProfileForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            ev.create_profile(request.user, form.cleaned_data["payload"])
        except ev.EvaluationError as error:
            _error_on_form(form, error)
        else:
            messages.success(request, "Reviewer profile frozen. No model request was made.")
            return redirect("solutions:evaluation_workspace")
    return _form_page(request, "Freeze reviewer profile", form, submit_label="Freeze profile")


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@_evidence_errors
def evaluation_run_import(request, snapshot_id):
    snapshot = get_object_or_404(ev.visible_snapshots(request.user), pk=snapshot_id)
    ev.require(request.user, "custodian", snapshot)
    form = RunImportForm(
        request.POST if request.method == "POST" else None,
        profiles=ev.visible_profiles(request.user),
    )
    if request.method == "POST" and form.is_valid():
        try:
            run = ev.import_run(
                request.user,
                snapshot,
                form.cleaned_data["profile"],
                form.cleaned_data["reports"],
                {**form.cleaned_data["protocol"], "partition": form.cleaned_data["partition"]},
            )
        except ev.EvaluationError as error:
            _error_on_form(form, error)
        else:
            messages.success(request, "Manual reports imported as unverified model evidence.")
            return redirect("solutions:evaluation_run_detail", run.pk)
    return _form_page(request, "Import offline reports", form, submit_label="Import unverified reports")


@login_required
@never_cache
@require_GET
@_evidence_errors
def evaluation_run_detail(request, run_id):
    run = get_object_or_404(ev.visible_runs(request.user), pk=run_id)
    payload = ev.run_payload(request.user, run)
    rows = []
    for case_id, report in payload.get("reports", {}).items():
        case = ev.visible_cases(request.user).filter(pk=case_id).first()
        rows.append(
            {
                "case_id": case_id,
                "report": report,
                "report_json": json.dumps(report, ensure_ascii=False, indent=2),
                "run_id": run.pk,
                "can_assess": bool(case and ev.allowed(request.user, "finding_evaluator", case)),
                "can_adjudicate": bool(case and ev.allowed(request.user, "adjudicator", case)),
            },
        )
    metrics = payload.get("metrics")
    metric_rows = [
        {"label": key.replace("_", " ").capitalize(), **value}
        for key, value in (metrics or {}).get("metrics", {}).items()
    ]
    return _response(
        request,
        "run_detail",
        {
            "page_title": "Evaluation report",
            "run_data": payload,
            "metrics_json": json.dumps(metrics, ensure_ascii=False, indent=2) if metrics else "",
            "metric_rows": metric_rows,
            "case_reports": rows,
        },
    )


def _finding_judgment(request, run_id, case_id, *, adjudication=False):
    case = _case(request.user, case_id)
    ev.require(request.user, "adjudicator" if adjudication else "finding_evaluator", case)
    run = get_object_or_404(EvaluationRun.objects.select_related("snapshot"), pk=run_id)
    payload = ev.finding_payload(request.user, run, case)
    if adjudication and len(payload.get("finding_judgments", [])) != REQUIRED_FINDING_JUDGMENTS:
        message = "Finding adjudication requires two preserved original report assessments."
        raise ev.EvaluationError(message, status=409)
    findings = payload["report"].get("findings", [])
    form_class = FindingAdjudicationForm if adjudication else FindingReviewForm
    form = form_class(request.POST if request.method == "POST" else None)
    judgments = FindingAssessmentFormSet(
        request.POST if request.method == "POST" else None,
        initial=[{"finding_id": item["id"]} for item in findings],
        prefix="findings",
    )
    if request.method == "POST":
        valid = form.is_valid()
        judgments_valid = judgments.is_valid()
        if valid and judgments_valid:
            annotation = {key: value for key, value in form.cleaned_data.items() if key != "reason"}
            annotation["findings"] = [row.cleaned_data for row in judgments]
            try:
                if adjudication:
                    from .evaluation_finding_adjudication import adjudicate_findings

                    adjudicate_findings(request.user, run, case, annotation, form.cleaned_data["reason"])
                else:
                    ev.assess_findings(request.user, run, case, annotation)
            except ev.EvaluationError as error:
                _error_on_form(form, error)
            else:
                messages.success(
                    request,
                    "Finding adjudication preserved."
                    if adjudication
                    else "Finding-level mathematical assessment preserved.",
                )
                return redirect("solutions:evaluation_case_detail", case.pk)
    return _form_page(
        request,
        "Adjudicate report findings" if adjudication else "Assess report findings",
        form,
        submit_label="Preserve finding adjudication" if adjudication else "Save finding assessment",
        frozen_input=payload["bundle"],
        assets=_assets(case.pk, payload),
        inspected_report=payload["report"],
        ground_truth=payload.get("ground_truth"),
        finding_judgments=payload.get("finding_judgments", []) if adjudication else [],
        formsets=[
            {
                "title": "Individual findings",
                "item_label": "Finding",
                "forms": judgments,
                "help": "Assess every material allegation, its context, mathematical hints and spoiler risk.",
            },
        ],
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@_evidence_errors
def evaluation_finding_judgment(request, run_id, case_id):
    return _finding_judgment(request, run_id, case_id)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@_evidence_errors
def evaluation_finding_adjudication(request, run_id, case_id):
    return _finding_judgment(request, run_id, case_id, adjudication=True)


@login_required
@never_cache
@require_GET
@_evidence_errors
def evaluation_asset(request, case_id, asset_id):
    case = _case(request.user, case_id)
    data, mime_type = ev.asset_payload(request.user, case, asset_id)
    response = HttpResponse(data, content_type=mime_type)
    response["Content-Disposition"] = f'inline; filename="diagram-{asset_id}.png"'
    return _private(response)
