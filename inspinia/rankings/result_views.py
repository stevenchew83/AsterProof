"""Assessment results and a season history matrix, independent of ranking formulas."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case
from django.db.models import Count
from django.db.models import F
from django.db.models import IntegerField
from django.db.models import OuterRef
from django.db.models import Prefetch
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from inspinia.rankings.forms import OlympiadSheetImportForm
from inspinia.rankings.imports.olympiad_sheet import SHEET_KIND
from inspinia.rankings.imports.olympiad_sheet import apply_sheet_preview
from inspinia.rankings.imports.olympiad_sheet import parse_olympiad_sheet
from inspinia.rankings.imports.olympiad_sheet import prepare_sheet_preview
from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.school_display import SOURCE_SCHOOL_PREFIX
from inspinia.rankings.services.school_display import with_school_display
from inspinia.rankings.views import _log_import_complete_event
from inspinia.rankings.views import _log_import_preview_event
from inspinia.rankings.views import _require_rankings_access

PAGE_SIZE = 50
MAX_PK = 2**63 - 1
MAX_PK_DIGITS = 19
YEAR_DIGITS = 4


def _positive_pk(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > MAX_PK_DIGITS or not 0 < int(value) <= MAX_PK:
        raise Http404
    return int(value)


def _page_context(request, queryset) -> dict:
    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return {"page_obj": page, "pagination_query": params.urlencode()}


def _search_students(queryset, *, query: str, school: str, prefix: str = ""):
    if query:
        queryset = queryset.filter(**{f"{prefix}full_name__icontains": query})
    if school:
        queryset = queryset.filter(**{f"{prefix}school__name__icontains": school})
    return queryset


def _ranked_results(assessment: Assessment):
    higher_scores = (
        StudentResult.objects.filter(
            assessment_id=OuterRef("assessment_id"),
            band=OuterRef("band"),
            raw_score__gt=OuterRef("raw_score"),
        )
        .order_by()
        .values("assessment_id")
        .annotate(total=Count("id"))
        .values("total")
    )
    # The subquery keeps ranks relative to the full category even after search.
    return with_school_display(
        StudentResult.objects.filter(assessment=assessment)
        .select_related("student__school")
        .annotate(
            category_rank=Case(
                When(raw_score__isnull=True, then=Value(None)),
                default=Coalesce(Subquery(higher_scores[:1]), Value(0)) + Value(1),
                output_field=IntegerField(),
            ),
        ),
        results=True,
    )


@login_required
@never_cache
def assessment_results_view(request):
    _require_rankings_access(request)
    assessments = (
        Assessment.objects.annotate(result_count=Count("results"))
        .filter(result_count__gt=0)
        .order_by(
            "-season_year",
            "sort_order",
            "display_name",
            "id",
        )
    )
    selected_id = request.GET.get("assessment", "")
    if selected_id:
        assessment = get_object_or_404(assessments, pk=_positive_pk(selected_id))
    else:
        latest = assessments.first()
        assessment = latest
        if latest:
            assessment = assessments.filter(code=f"IMONST2_{latest.season_year}").first() or latest
    query = (request.GET.get("q") or "").strip()[:255]
    school = (request.GET.get("school") or "").strip()[:255]
    band = (request.GET.get("band") or "").strip()[:32]
    order = request.GET.get("order", "score")
    ordering = {
        "score": ("band", F("raw_score").desc(nulls_last=True), "student__normalized_name", "id"),
        "name": ("student__normalized_name", "id"),
        "school": ("school_display", "student__normalized_name", "id"),
    }
    if order not in ordering:
        order = "score"
    results = StudentResult.objects.none()
    bands = []
    if assessment:
        results = _ranked_results(assessment)
        bands = list(results.exclude(band="").order_by("band").values_list("band", flat=True).distinct())
        results = _search_students(results, query=query, school="", prefix="student__")
        if school:
            results = results.filter(Q(school_display__icontains=school) | Q(recorded_school__icontains=school))
        if band:
            results = results.filter(band=band)
        results = results.order_by(*ordering[order])
    context = {
        "assessment": assessment,
        "assessments": assessments,
        "bands": bands,
        "q": query,
        "school": school,
        "band": band,
        "order": order,
        **_page_context(request, results),
    }
    for result in context["page_obj"]:
        result.source_notes = "" if result.remarks.startswith(SOURCE_SCHOOL_PREFIX) else result.remarks
    return render(request, "pages/rankings/assessment-results.html", context)


@login_required
@never_cache
def result_history_view(request):
    _require_rankings_access(request)
    years = list(
        Assessment.objects.filter(results__isnull=False)
        .order_by("-season_year")
        .values_list(
            "season_year",
            flat=True,
        )
        .distinct(),
    )
    selected_year = request.GET.get("season", "")
    if selected_year and (
        len(selected_year) != YEAR_DIGITS or not selected_year.isdecimal() or int(selected_year) not in years
    ):
        raise Http404
    year = int(selected_year) if selected_year else (years[0] if years else None)
    assessments = list(
        Assessment.objects.filter(season_year=year, results__isnull=False)
        .distinct()
        .order_by(
            "sort_order",
            "display_name",
            "id",
        ),
    )
    query = (request.GET.get("q") or "").strip()[:255]
    school = (request.GET.get("school") or "").strip()[:255]
    students = Student.objects.filter(results__assessment__in=assessments).select_related("school").distinct()
    students = with_school_display(_search_students(students, query=query, school=""))
    if school:
        students = students.filter(Q(school_display__icontains=school) | Q(recorded_school__icontains=school))
    students = students.order_by("normalized_name", "id")
    students = students.prefetch_related(
        Prefetch(
            "results",
            queryset=StudentResult.objects.filter(assessment__in=assessments),
            to_attr="season_results",
        ),
    )
    context = _page_context(request, students)
    rows = []
    for student in context["page_obj"]:
        by_assessment = {result.assessment_id: result for result in student.season_results}
        rows.append({"student": student, "cells": [by_assessment.get(assessment.pk) for assessment in assessments]})
    return render(
        request,
        "pages/rankings/result-history.html",
        {
            **context,
            "rows": rows,
            "assessments": assessments,
            "years": years,
            "season": year,
            "q": query,
            "school": school,
        },
    )


def _sheet_batch(request, batch_id) -> ImportBatch:
    return get_object_or_404(
        ImportBatch,
        pk=_positive_pk(str(batch_id)),
        created_by=request.user,
        summary_json__kind=SHEET_KIND,
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def olympiad_sheet_import_view(request):  # noqa: C901
    _require_rankings_access(request)
    form = OlympiadSheetImportForm()
    batch = None
    if request.method == "POST":
        if request.POST.get("action") == "apply":
            batch = _sheet_batch(request, request.POST.get("batch_id", ""))
            if request.POST.get("confirm") != "yes":
                messages.error(request, "Confirm that you have reviewed the mapping, matches and score updates.")
            else:
                try:
                    batch = apply_sheet_preview(batch_id=batch.pk, actor=request.user)
                except ValueError as exc:
                    messages.error(request, str(exc))
                else:
                    _log_import_complete_event(request=request, batch=batch)
                    applied_rows = batch.summary_json.get("applied_rows", batch.summary_json["student_count"])
                    messages.success(
                        request,
                        f"Import recorded: {applied_rows} source rows applied; "
                        f"{batch.summary_json.get('held_count', 0)} rows held for correction review.",
                    )
                    return redirect("rankings:assessment_results")
        else:
            form = OlympiadSheetImportForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    summary = prepare_sheet_preview(parse_olympiad_sheet(form.cleaned_data["source_text"]))
                except ValueError as exc:
                    form.add_error(None, str(exc))
                else:
                    # Do not save the raw upload: it may contain NRICs and private notes.
                    batch = ImportBatch.objects.create(
                        import_type=ImportBatch.ImportType.LEGACY_WIDE_TABLE,
                        original_filename=form.cleaned_data["source_name"],
                        status=ImportBatch.Status.PREVIEWED,
                        created_by=request.user,
                        summary_json=summary,
                    )
                    _log_import_preview_event(request=request, batch=batch)
                    return redirect(f"{request.path}?batch={batch.pk}")
    elif request.GET.get("batch"):
        batch = _sheet_batch(request, request.GET["batch"])
    context = {"form": form, "batch": batch}
    if batch and batch.status == ImportBatch.Status.PREVIEWED:
        context.update(preview=batch.summary_json, **_page_context(request, batch.summary_json["rows"]))
        params = request.GET.copy()
        params.pop("page", None)
        params["batch"] = str(batch.pk)
        context["pagination_query"] = params.urlencode()
    return render(request, "pages/rankings/olympiad-sheet-import.html", context)
