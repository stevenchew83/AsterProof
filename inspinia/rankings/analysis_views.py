"""Private, server-rendered ranking analysis and complete filtered exports."""

import csv
import io
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from inspinia.rankings.analysis_forms import TABS
from inspinia.rankings.analysis_forms import RankingAnalysisFilterForm
from inspinia.rankings.models import School
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.analysis import alias_maps
from inspinia.rankings.services.analysis import available_assessments
from inspinia.rankings.services.analysis import build_workspace
from inspinia.rankings.services.analysis import display
from inspinia.rankings.services.analysis import link
from inspinia.rankings.views import _require_rankings_access
from inspinia.users.roles import user_has_admin_role

MAX_PK_DIGITS = 19
HTTP_OK = 200
DEFAULT_ORDERS = {
    "overview": "-score",
    "students": "name",
    "schools": "-records",
    "compare": "name",
    "quality": "label",
}


def filter_form(params):
    assessments = available_assessments()
    data = params.copy()
    if "tab" not in data:
        data["tab"] = "overview"
    if "school_basis" not in data:
        data["school_basis"] = "assessment"
    if "compare_mode" not in data:
        data["compare_mode"] = "percentile"
    if "season" not in data and assessments:
        data["season"] = str(assessments[0].season_year)
    if "assessment" not in data:
        candidates = [row for row in assessments if not data.get("season") or str(row.season_year) == data["season"]]
        selected = next(
            (row for row in candidates if row.code == f"IMONST2_{row.season_year}"),
            candidates[0] if candidates else None,
        )
        data["assessment"] = str(selected.pk) if selected else ""
    _, aliases = alias_maps()

    def bands(key):
        value = data.get(key, "")
        if (
            not value.isascii()
            or not value.isdecimal()
            or len(value) > MAX_PK_DIGITS
            or not 0 < int(value) <= 2**63 - 1
        ):
            return []
        assessment_id = int(value)
        original = StudentResult.objects.filter(assessment_id=assessment_id).values_list("band", flat=True).distinct()
        return sorted({aliases.get((assessment_id, "band", band.casefold()), band) for band in original})

    schools = list(School.objects.values("id", "name").order_by("name", "id"))
    form = RankingAnalysisFilterForm(
        data,
        assessments=assessments,
        schools=schools,
        bands=bands("assessment"),
        compare_bands=bands("compare_assessment"),
    )
    if form.is_valid():
        selected = next((row for row in assessments if str(row.pk) == form.cleaned_data.get("assessment")), None)
        if selected and form.cleaned_data.get("season") and str(selected.season_year) != form.cleaned_data["season"]:
            form.add_error("assessment", "Choose an assessment in the selected season, or choose All seasons.")
    return form, assessments


def ordered_rows(content, order):
    valid = {key for key, _ in content["columns"] if key}
    key = order.lstrip("-")
    if key not in valid:
        message = "Choose one of the sortable table columns."
        raise ValueError(message)
    rows = content["rows"]
    known = [row for row in rows if row.get(key) is not None]
    empty = [row for row in rows if row.get(key) is None]

    def value(row):
        item = row.get(key)
        return item.casefold() if isinstance(item, str) else item

    return sorted(known, key=value, reverse=order.startswith("-")) + empty


def workspace(params):
    form, assessments = filter_form(params)
    context = {"filter_form": form, "tabs": [], "valid": False, "can_apply_corrections": False}
    if not form.is_valid():
        return context, 400
    filters = form.cleaned_data
    if filters.get("student") and not Student.objects.filter(pk=filters["student"]).exists():
        form.add_error("student", "The selected student does not exist.")
        return context, 400
    content = build_workspace(filters, assessments)
    order = filters.get("order") or DEFAULT_ORDERS[filters["tab"]]
    # A comparison without selected assessments has no sortable table yet.
    if content["columns"]:
        try:
            rows = ordered_rows(content, order)
        except ValueError as error:
            form.add_error("order", str(error))
            return context, 400
    else:
        rows = []
    filters["order"] = order
    context.update(content)
    context["valid"] = True
    context["all_rows"] = rows
    context["tabs"] = [
        {"key": key, "label": label, "url": link(filters, tab=key, order=None, student=None, issue=None)}
        for key, label in TABS
    ]
    context["columns"] = [
        {
            "key": key,
            "label": label,
            "numeric": key in {
                "rank", "score", "percentile", "birth", "records", "scored",
                "median", "mean", "left", "right", "delta",
            },
            "aria_sort": "ascending" if order == key else "descending" if order == "-" + key else "none",
            "url": link(filters, order="-" + key if order == key else key) if key else None,
        }
        for key, label in content["columns"]
    ]
    page = Paginator(rows, 50).get_page(filters.get("page"))
    context["page_obj"] = page
    context["pagination_query"] = urlencode(
        {
            key: value for key, value in filters.items()
            if value not in (None, "") and value is not False and key != "page"
        },
    )
    context["export_query"] = urlencode(
        {
            key: value for key, value in filters.items()
            if value not in (None, "") and value is not False and key != "page"
        },
    )
    context["export_csv_url"] = "?" + context["export_query"] + "&format=csv"
    context["export_xlsx_url"] = "?" + context["export_query"] + "&format=xlsx"
    for panel in content.get("panels", []):
        panel["exact_rows"] = (
            [
                [point["name"], display(Decimal(str(point["x"]))), display(Decimal(str(point["y"])))]
                for point in panel["points"]
            ]
            if panel["type"] == "scatter"
            else [
                [label, display(Decimal(str(value)))]
                for label, value in zip(panel["labels"], panel["values"], strict=True)
            ]
        )
    context["charts_payload"] = content.get("panels", [])
    context["clear_drilldown"] = link(
        filters, score_min=None, score_max=None, score_end=None, outcome_field=None,
        outcome_value=None, issue=None, band_missing=None,
    )
    context["has_drilldown"] = any(
        filters.get(key) not in (None, "") and filters.get(key) is not False
        for key in ("score_min", "score_max", "outcome_field", "issue", "band_missing")
    )
    context["more_filters_open"] = bool(filters.get("q") or filters.get("birth_year") or filters.get("band_missing"))
    return context, 200


@login_required
@never_cache
@require_GET
def ranking_analysis_view(request):
    _require_rankings_access(request)
    context, status = workspace(request.GET)
    context["can_apply_corrections"] = user_has_admin_role(request.user)
    response = render(request, "pages/rankings/analysis.html", context, status=status)
    response["Cache-Control"] = "private, no-store, no-cache, must-revalidate"
    return response


def spreadsheet_value(value):
    if value is None:
        return ""
    if isinstance(value, (Decimal, int, float)):
        return value
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


@login_required
@never_cache
@require_GET
def ranking_analysis_export_view(request):
    _require_rankings_access(request)
    requested_format = request.GET.get("format", "csv")
    if requested_format not in {"csv", "xlsx"}:
        raise Http404
    context, status = workspace(request.GET)
    if status != HTTP_OK:
        response = HttpResponse(
            "Invalid analysis filters. Return to Ranking analysis and correct the highlighted fields.",
            status=400,
            content_type="text/plain",
        )
        response["Cache-Control"] = "private, no-store"
        return response
    headings = [column["label"] for column in context["columns"]]
    # Action/link-only columns carry no analytical data and are omitted.
    keep = [index for index, heading in enumerate(headings) if heading not in {"Correction", "Review"}]
    headings = [headings[index] for index in keep]
    values = [[spreadsheet_value(row["cells"][index]["value"]) for index in keep] for row in context["all_rows"]]
    generated = timezone.now().isoformat()
    metadata = [
        ("Report", context.get("table_title", "Ranking analysis")),
        ("Generated at", generated),
        ("Scope", "Full filtered table, all pages"),
        ("Rows", len(values)),
        ("Filters", context["export_query"]),
        ("School basis", context["filters"]["school_basis"]),
        ("Rank definition", "1 + higher scores in the full assessment/category"),
        ("Percentile definition", "100 * (scores below + half tied scores) / numeric category cohort"),
        ("Missing data", "Blank or dash means not recorded, never a measured zero or established absence"),
        ("Coverage", "Records describe imported/recorded coverage, not an eligible population or attendance"),
        (
            "Comparability",
            "Relative standing is not measured ability growth; "
            "verified scales do not establish equal paper difficulty",
        ),
        ("Latest imported record", display(context["latest_import"])),
    ]
    if requested_format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headings)
        writer.writerows(values)
        writer.writerow([])
        writer.writerow(["Report metadata", "Value"])
        writer.writerows([[spreadsheet_value(value) for value in row] for row in metadata])
        response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    else:
        from openpyxl import Workbook

        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet("Analysis")
        sheet.append(headings)
        for row in values:
            sheet.append(row)
        details = workbook.create_sheet("Report metadata")
        details.append(["Property", "Value"])
        for row in metadata:
            details.append([spreadsheet_value(value) for value in row])
        output = io.BytesIO()
        workbook.save(output)
        response = HttpResponse(
            output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    filename = f"ranking-analysis-{context['filters']['tab']}-{timezone.now():%Y%m%d-%H%M%S}.{requested_format}"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store, no-cache, must-revalidate"
    return response
