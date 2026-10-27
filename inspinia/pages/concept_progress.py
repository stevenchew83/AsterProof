"""Personal progress over canonical areas and concepts, using current source mappings."""

import csv
from io import StringIO
from statistics import mean
from statistics import median

from django.http import HttpResponse

from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.technique_concepts import CONCEPTS

SUBJECT_SLUGS = {
    "algebra": "Algebra",
    "combinatorics": "Combinatorics",
    "geometry": "Geometry",
    "number-theory": "Number Theory",
}


def _counts(problems):
    total = len(problems)
    solved = sum(p["is_solved"] for p in problems.values())
    difficulties = [p["mohs"] for p in problems.values() if p["mohs"] is not None]
    solved_difficulties = [p["mohs"] for p in problems.values() if p["is_solved"] and p["mohs"] is not None]
    percent = round(100 * solved / total, 1) if total else 0
    if solved < total:
        percent = min(percent, 99.9)
    return {
        "total": total,
        "solved": solved,
        "remaining": total - solved,
        "percent": percent,
        "median_mohs": median(difficulties) if difficulties else None,
        "solved_average_mohs": round(mean(solved_difficulties), 1) if solved_difficulties else None,
    }


def _study_notes(cid):
    reference = CONCEPTS[cid].get("canonical_benchmark_id")
    if not reference:
        return None
    notes = (
        TechniqueBenchmark.objects.filter(pk=reference)
        .values(
            "key_insight_spoiler_free",
            "rationale",
            "pitfalls",
            "recommended_sequence",
        )
        .first()
    )
    return notes if notes and any(notes.values()) else None


def build_concept_progress_context(*, request_user, params, topic_slug=""):
    from inspinia.pages.catalogue_progress import build_progress_context

    return build_progress_context(request_user=request_user, params=params, topic_slug=topic_slug)


def _csv_row(values):
    return [
        "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value
        for value in values
    ]


def concept_progress_csv(context):
    if context.get("progress_unavailable"):
        return HttpResponse(
            "Progress summaries are updating. Please try again shortly.",
            status=503,
            content_type="text/plain",
        )
    output = StringIO()
    writer = csv.writer(output)
    if context["filters"]["mode"] == "problems":
        writer.writerow(["Problem", "Status", "MOHS", "Completion date"])
        writer.writerows(
            _csv_row([p["label"], p["status_label"], p["mohs"], p["completion_date"]]) for p in context["export_rows"]
        )
    else:
        writer.writerow(["Name", "Subject", "Area", "Problems", "Completed", "Remaining", "Progress (%)"])
        writer.writerows(
            _csv_row(
                [
                    r["label"],
                    r["subject"],
                    r.get("area", r["label"]),
                    r["total"],
                    r["solved"],
                    r["remaining"],
                    r["percent"] if r["total"] else "",
                ],
            )
            for r in context["export_rows"]
        )
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="area-concept-progress.csv"'
    return response
