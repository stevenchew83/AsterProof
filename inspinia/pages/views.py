from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.db.models import Max
from django.db.models import Min
from django.shortcuts import render

from inspinia.pages.forms import ProblemXlsxImportForm
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.problem_import import ProblemImportValidationError
from inspinia.pages.problem_import import build_parsed_preview_payload
from inspinia.pages.problem_import import dataframe_from_excel
from inspinia.pages.problem_import import import_problem_dataframe
from inspinia.users.roles import user_has_admin_role


def root_page_view(request):
    return render(request, "pages/index.html")


def _rows_to_bar_payload(rows: list[dict], label_key: str, *, value_key: str = "c") -> dict:
    return {
        "labels": [str(r[label_key]) for r in rows],
        "values": [int(r[value_key]) for r in rows],
    }


def _require_admin_tools_access(request) -> None:
    if not settings.DEBUG and not user_has_admin_role(request.user):
        raise PermissionDenied


def dashboard_analytics_view(request):
    """Problem analytics: charts plus searchable table."""
    _require_admin_tools_access(request)

    base = ProblemSolveRecord.objects.all()
    total = base.count()

    stats = base.aggregate(
        year_min=Min("year"),
        year_max=Max("year"),
        contest_n=Count("contest", distinct=True),
        topic_n=Count("topic", distinct=True),
    )
    technique_total = ProblemTopicTechnique.objects.count()

    by_year = list(base.values("year").annotate(c=Count("id")).order_by("year"))
    by_topic = list(base.values("topic").annotate(c=Count("id")).order_by("-c")[:18])
    by_contest = list(base.values("contest").annotate(c=Count("id")).order_by("-c")[:12])
    by_mohs = list(base.values("mohs").annotate(c=Count("id")).order_by("mohs"))
    top_techniques = list(
        ProblemTopicTechnique.objects.values("technique")
        .annotate(c=Count("id"))
        .order_by("-c")[:18],
    )

    charts_payload = {
        "byYear": _rows_to_bar_payload(by_year, "year"),
        "byTopic": _rows_to_bar_payload(by_topic, "topic"),
        "byContest": _rows_to_bar_payload(by_contest, "contest"),
        "byMohs": _rows_to_bar_payload(by_mohs, "mohs"),
        "topTechniques": _rows_to_bar_payload(top_techniques, "technique"),
    }

    table_rows = list(
        base.annotate(technique_count=Count("topic_techniques")).values(
            "year",
            "topic",
            "mohs",
            "contest",
            "problem",
            "contest_year_problem",
            "technique_count",
        ),
    )

    context = {
        "analytics_total": total,
        "analytics_stats": stats,
        "analytics_technique_total": technique_total,
        "charts_payload": charts_payload,
        "table_rows": table_rows,
    }
    return render(request, "pages/dashboard-analytics.html", context)


def _preview_problem_import(request, workbook_df) -> dict:
    preview_data = build_parsed_preview_payload(workbook_df)
    skip_warnings = preview_data.pop("warnings", [])
    msg = (
        f"Parsed preview: {preview_data['total_prepared_problems']} problem row(s) and "
        f"{preview_data['total_parsed_techniques']} technique row(s) from "
        f"{preview_data['total_sheet_rows']} sheet row(s). Tables below match what Import will write "
        "(not raw Excel). Re-upload the same file and click Import to save."
    )
    if preview_data["problems_truncated"] or preview_data["techniques_truncated"]:
        msg += (
            f" Showing first {preview_data['preview_problems_count']} problems and "
            f"{preview_data['preview_techniques_count']} techniques in the browser."
        )
    messages.info(request, msg)
    _emit_warning_messages(request, skip_warnings, overflow_label="skip warnings")
    return preview_data


def _emit_warning_messages(request, warnings: list[str], *, overflow_label: str) -> None:
    max_warn = 25
    for warning in warnings[:max_warn]:
        messages.warning(request, warning)
    if len(warnings) > max_warn:
        messages.warning(request, f"...and {len(warnings) - max_warn} more {overflow_label}.")


def _import_problem_workbook(request, workbook_df, *, replace_tags: bool) -> None:
    result = import_problem_dataframe(workbook_df, replace_tags=replace_tags)
    messages.success(
        request,
        f"Import finished. Upserted {result.n_records} problem record(s); "
        f"touched {result.n_techniques} technique row(s).",
    )
    _emit_warning_messages(
        request,
        result.warnings,
        overflow_label="warnings (see server logs if needed)",
    )


def problem_import_view(request):
    """Upload analytics .xlsx, preview it, and upsert problems plus topic techniques."""
    _require_admin_tools_access(request)

    replace_tags_initial = request.method == "POST" and bool(request.POST.get("replace_tags"))
    preview_payload: dict | None = None
    form = ProblemXlsxImportForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action") or "import"
        replace_tags = form.cleaned_data["replace_tags"]
        replace_tags_initial = replace_tags

        try:
            workbook_df = dataframe_from_excel(form.cleaned_data["file"].read())
        except ProblemImportValidationError as exc:
            messages.error(request, str(exc))
        else:
            if action == "preview":
                preview_payload = _preview_problem_import(request, workbook_df)
            else:
                _import_problem_workbook(request, workbook_df, replace_tags=replace_tags)
        form = ProblemXlsxImportForm(initial={"replace_tags": replace_tags_initial})

    if request.method == "GET":
        form = ProblemXlsxImportForm(initial={"replace_tags": replace_tags_initial})

    return render(
        request,
        "pages/problem-import.html",
        {"form": form, "preview_payload": preview_payload},
    )
