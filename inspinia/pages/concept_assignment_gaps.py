"""Legacy gap URLs retain access controls while using accepted canonical coverage."""

from io import BytesIO

from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import render

from inspinia.pages.concept_progress import SUBJECT_SLUGS
from inspinia.pages.concept_progress import build_concept_progress_context
from inspinia.pages.concept_progress import concept_progress_csv


def assignment_gaps_response(request):
    slug = str(request.GET.get("topic") or "")
    slug = slug if slug in SUBJECT_SLUGS else ""
    params = {
        "mode": "concepts",
        "state": "remaining",
        "user": request.GET.get("user", ""),
        "q": request.GET.get("q") or request.GET.get("search[value]") or request.GET.get("canonical_subtopic", ""),
    }
    context = build_concept_progress_context(request_user=request.user, params=params, topic_slug=slug)
    minimum = str(request.GET.get("min_total") or "")
    rows = [row for row in context["export_rows"] if not minimum.isdigit() or row["total"] >= int(minimum)]
    if request.GET.get("format") == "datatable":

        def number(key, default):
            raw = str(request.GET.get(key, default))
            return int(raw) if raw.isdigit() else default

        start, length = number("start", 0), min(number("length", 25), 250)
        data = []
        for index, row in enumerate(rows[start : start + length], start=start + 1):
            data.append(
                {
                    **row,
                    "type": "Concept",
                    "canonical_subtopic_label": row["area"],
                    "main_topic_label": row["subject"],
                    "priority_rank": index,
                    "priority_score": None,
                    "efficiency_score": None,
                    "gap_pressure": None,
                    "importance_score": None,
                    "difficulty_score": None,
                    "parent_family": row["area"],
                    "final_training_type": "",
                    "typical_mohs_band": "",
                    "benchmark_confidence": None,
                    "solved_total_label": row["solved"],
                    "average_solved_mohs": row["solved_average_mohs"],
                    "completion_percent": row["percent"],
                    "coverage_label": str(row["percent"]) + "%",
                    "practice_url": row["url"],
                },
            )
        return JsonResponse(
            {"draw": number("draw", 0), "recordsTotal": len(rows), "recordsFiltered": len(rows), "data": data},
        )
    if request.GET.get("export") == "csv":
        context["export_rows"] = rows
        response = HttpResponse(concept_progress_csv(context), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="accepted-concept-gaps.csv"'
        return response
    if request.GET.get("export") == "xlsx":
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = "Accepted concept gaps"
        sheet.append(["Concept", "Subject", "Area", "Problems", "Completed", "Remaining"])
        for row in rows:
            values = [row["label"], row["subject"], row["area"], row["total"], row["solved"], row["remaining"]]
            sheet.append(
                [
                    "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value
                    for value in values
                ],
            )
        stream = BytesIO()
        book.save(stream)
        response = HttpResponse(
            stream.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="accepted-concept-gaps.xlsx"'
        return response
    return render(request, "pages/technique-progress.html", context)
