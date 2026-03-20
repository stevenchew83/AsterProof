from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Min
from django.shortcuts import render
from django.template import TemplateDoesNotExist

from inspinia.users.roles import user_has_admin_role

from pages.forms import ProblemXlsxImportForm
from pages.models import ProblemSolveRecord, ProblemTopicTechnique
from pages.problem_import import (
    ProblemImportValidationError,
    build_parsed_preview_payload,
    dataframe_from_excel,
    import_problem_dataframe,
)

# Create your views here.


def root_page_view(request):
    try:
        return render(request, "pages/index.html")
    except TemplateDoesNotExist:
        return render(request, "pages/error-404.html")


def _rows_to_bar_payload(rows: list[dict], label_key: str, *, value_key: str = "c") -> dict:
    return {
        "labels": [str(r[label_key]) for r in rows],
        "values": [int(r[value_key]) for r in rows],
    }


def dashboard_analytics_view(request):
    """Problem analytics: charts + searchable table.

    When ``DEBUG`` is off, only users with the **admin** role (or superusers) may access.
    """
    if not settings.DEBUG and not user_has_admin_role(request.user):
        raise PermissionDenied

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
        .order_by("-c")[:18]
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
            "solve_date",
            "technique_count",
        )
    )
    for row in table_rows:
        sd = row.get("solve_date")
        if sd is not None:
            row["solve_date"] = sd.isoformat()

    context = {
        "analytics_total": total,
        "analytics_stats": stats,
        "analytics_technique_total": technique_total,
        "charts_payload": charts_payload,
        "table_rows": table_rows,
    }
    return render(request, "pages/dashboard-analytics.html", context)


def dynamic_pages_view(request, template_name):
    try:
        return render(request, f'pages/{template_name}.html')
    except TemplateDoesNotExist:
        return render(request, f'pages/error-404.html')


def problem_import_view(request):
    """Upload analytics .xlsx, preview in a table, and/or upsert problems + topic techniques."""
    preview_payload: dict | None = None
    replace_tags_initial = request.method == "POST" and bool(request.POST.get("replace_tags"))

    if request.method == "POST":
        form = ProblemXlsxImportForm(request.POST, request.FILES)
        action = request.POST.get("action") or "import"

        if form.is_valid():
            uploaded = form.cleaned_data["file"]
            replace_tags = form.cleaned_data["replace_tags"]
            replace_tags_initial = replace_tags

            try:
                raw = uploaded.read()
                df = dataframe_from_excel(raw)
            except ProblemImportValidationError as exc:
                messages.error(request, str(exc))
            else:
                if action == "preview":
                    preview_payload = build_parsed_preview_payload(df)
                    skip_warnings = preview_payload.pop("warnings", [])
                    msg = (
                        f"Parsed preview: {preview_payload['total_prepared_problems']} problem row(s) "
                        f"and {preview_payload['total_parsed_techniques']} technique row(s) "
                        f"from {preview_payload['total_sheet_rows']} sheet row(s). "
                        "Tables below match what Import will write (not raw Excel). "
                        "Re-upload the same file and click Import to save."
                    )
                    if preview_payload["problems_truncated"] or preview_payload["techniques_truncated"]:
                        msg += (
                            f" Showing first {preview_payload['preview_problems_count']} problems and "
                            f"{preview_payload['preview_techniques_count']} techniques in the browser."
                        )
                    messages.info(request, msg)
                    max_warn = 25
                    for w in skip_warnings[:max_warn]:
                        messages.warning(request, w)
                    if len(skip_warnings) > max_warn:
                        messages.warning(
                            request,
                            f"…and {len(skip_warnings) - max_warn} more skip warnings.",
                        )
                else:
                    result = import_problem_dataframe(df, replace_tags=replace_tags)
                    messages.success(
                        request,
                        f"Import finished. Upserted {result.n_records} problem record(s); "
                        f"touched {result.n_techniques} technique row(s).",
                    )
                    max_warn = 25
                    for w in result.warnings[:max_warn]:
                        messages.warning(request, w)
                    if len(result.warnings) > max_warn:
                        messages.warning(
                            request,
                            f"…and {len(result.warnings) - max_warn} more warnings (see server logs if needed).",
                        )

        form = ProblemXlsxImportForm(initial={"replace_tags": replace_tags_initial})
    else:
        form = ProblemXlsxImportForm()

    return render(
        request,
        "pages/problem-import.html",
        {"form": form, "preview_payload": preview_payload},
    )
