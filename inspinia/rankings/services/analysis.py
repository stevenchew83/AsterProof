"""Descriptive analysis over raw results, with explicit cohorts and safe projections.

This module deliberately does not use formula snapshots or normalized_score.
All rank references are computed before demographic or school filtering.
"""

from collections import Counter
from collections import defaultdict
from decimal import Decimal
from itertools import combinations
from statistics import correlation
from unicodedata import normalize
from urllib.parse import urlencode

from django.db.models import Count
from django.urls import reverse

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import AssessmentCategoryScale
from inspinia.rankings.models import OutcomeAlias
from inspinia.rankings.models import RankingCorrection
from inspinia.rankings.models import RankingImportConflict
from inspinia.rankings.models import School
from inspinia.rankings.models import SchoolAlias
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentIdentityReview
from inspinia.rankings.models import StudentResult
from inspinia.rankings.models import normalize_name

HISTOGRAM_BINS = 10
MIN_CORRELATION_PAIRS = 10
MIN_SCHOOL_SCORES = 5
MAX_APPROXIMATE_AGE = 100
ZERO = Decimal(0)
HUNDRED = Decimal(100)
SAFE_VALUES = (
    "id",
    "student_id",
    "student__full_name",
    "student__birth_year",
    "student__school_id",
    "student__school__name",
    "student__school__normalized_name",
    "assessment_id",
    "assessment__display_name",
    "assessment__season_year",
    "assessment__assessment_date",
    "assessment__sort_order",
    "assessment__analysis_metadata__family",
    "assessment__analysis_metadata__definition_verified",
    "assessment__analysis_metadata__date_verified",
    "raw_score",
    "medal",
    "band",
    "status_text",
    "source_file_name",
    "imported_at",
    "updated_at",
    "school_attribution__verified",
    "school_attribution__school_id",
    "school_attribution__school__name",
    "school_attribution__school__normalized_name",
)


def quantile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = Decimal(len(values) - 1) * Decimal(str(fraction))
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def score_summary(values):
    values = sorted(value for value in values if value is not None)
    return {
        "count": len(values),
        "mean": sum(values, ZERO) / len(values) if values else None,
        "median": quantile(values, 0.5),
        "q1": quantile(values, 0.25),
        "q3": quantile(values, 0.75),
        "minimum": values[0] if values else None,
        "maximum": values[-1] if values else None,
    }


def histogram(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return []
    low, high = values[0], values[-1]
    if low == high:
        return [{"low": low, "high": high, "count": len(values), "inclusive": True, "label": display(low)}]
    width = (high - low) / HISTOGRAM_BINS
    bins = [
        {"low": low + width * i, "high": low + width * (i + 1), "count": 0, "inclusive": i == HISTOGRAM_BINS - 1}
        for i in range(HISTOGRAM_BINS)
    ]
    for value in values:
        bins[min(int((value - low) / width), HISTOGRAM_BINS - 1)]["count"] += 1
    for item in bins:
        item["label"] = f"{display(item['low'])}-{display(item['high'])}"
    return bins


def cohort_ranks(records):
    groups = defaultdict(list)
    for row in records:
        if row["score"] is not None:
            groups[(row["assessment_id"], row["band"])].append(row)
    for rows in groups.values():
        counts = Counter(row["score"] for row in rows)
        below = 0
        references = {}
        for score, count in sorted(counts.items()):
            references[score] = (1 + len(rows) - below - count, HUNDRED * (below + Decimal(count) / 2) / len(rows))
            below += count
        for row in rows:
            row["rank"], row["percentile"] = references[row["score"]]
    return records


def spearman(left, right):
    if len(left) < MIN_CORRELATION_PAIRS:
        return None, "At least 10 matched numeric results are needed for correlation."
    if len(set(left)) <= 1 or len(set(right)) <= 1:
        return None, "Correlation is unavailable because one score set is constant."

    def ranks(values):
        ordered = sorted(values)
        indices = defaultdict(list)
        for index, value in enumerate(ordered, 1):
            indices[value].append(index)
        return [sum(indices[value]) / len(indices[value]) for value in values]

    return correlation(
        ranks(left), ranks(right),
    ), "Association among matched records; this does not establish causation or ability growth."


def display(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, Decimal):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def link(filters, **updates):
    params = {key: str(value) for key, value in filters.items() if value not in (None, "") and value is not False}
    params.pop("page", None)
    params.update({key: str(value) for key, value in updates.items() if value is not None and value is not False})
    for key, value in updates.items():
        if value is None or value is False:
            params.pop(key, None)
    return reverse("rankings:analysis") + "?" + urlencode(params)


def available_assessments():
    return list(
        Assessment.objects.annotate(result_count=Count("results"))
        .filter(result_count__gt=0)
        .order_by("-season_year", "sort_order", "display_name", "pk"),
    )


def alias_maps():
    schools = {row["id"]: row["name"] for row in School.objects.values("id", "name")}
    aliases = {
        row.normalized_name: (row.school_id, schools.get(row.school_id, "Unknown"))
        for row in SchoolAlias.objects.filter(active=True)
    }
    outcomes = {
        (row.assessment_id, row.field, row.normalized_alias): row.canonical
        for row in OutcomeAlias.objects.filter(active=True)
    }
    return aliases, outcomes


def load_records(*, assessment_ids=None, student_id=None):
    query = StudentResult.objects.all()
    if assessment_ids is not None:
        query = query.filter(assessment_id__in=assessment_ids)
    if student_id is not None:
        query = query.filter(student_id=student_id)
    schools, outcomes = alias_maps()
    scales = (
        {
            (scale.assessment_id, scale.band): scale
            for scale in AssessmentCategoryScale.objects.filter(assessment_id__in=assessment_ids)
            if assessment_ids is not None
        }
        if assessment_ids is not None
        else {(scale.assessment_id, scale.band): scale for scale in AssessmentCategoryScale.objects.all()}
    )
    rows = []
    for value in query.values(*SAFE_VALUES):

        def school(prefix, value=value):
            key = value[f"{prefix}__normalized_name"]
            school_id = (
                value["student__school_id"] if prefix == "student__school" else value["school_attribution__school_id"]
            )
            return schools.get(key, (school_id, value[f"{prefix}__name"]))

        current_id, current_name = school("student__school")
        assessment_id, assessment_name = school("school_attribution__school")
        if not value["school_attribution__verified"]:
            assessment_id, assessment_name = None, None
        row = {
            "id": value["id"],
            "student_id": value["student_id"],
            "name": value["student__full_name"],
            "birth_year": value["student__birth_year"],
            "assessment_id": value["assessment_id"],
            "assessment": value["assessment__display_name"],
            "season": value["assessment__season_year"],
            "date": value["assessment__assessment_date"]
            if value["assessment__analysis_metadata__date_verified"]
            else None,
            "sort_order": value["assessment__sort_order"],
            "family": value["assessment__analysis_metadata__family"] or "",
            "definition_verified": bool(value["assessment__analysis_metadata__definition_verified"]),
            "score": value["raw_score"],
            "current_school_id": current_id,
            "current_school": current_name or "Unknown",
            "assessment_school_id": assessment_id,
            "assessment_school": assessment_name or "Unknown / unverified",
            "source": value["source_file_name"].replace("\\", "/").rsplit("/", 1)[-1],
            "imported_at": value["imported_at"],
            "updated_at": value["updated_at"],
            "rank": None,
            "percentile": None,
        }
        for field in ("band", "medal", "status_text"):
            original = value[field]
            row[field] = outcomes.get((row["assessment_id"], field, normalize_name(original)), original)
            row[f"original_{field}"] = original
        scale = scales.get((row["assessment_id"], row["band"]))
        row["scale_verified"] = bool(scale and scale.verified and scale.max_score and scale.max_score > 0)
        row["max_score"] = scale.max_score if row["scale_verified"] else None
        row["comparable_scope"] = scale.comparable_scope if scale and scale.verified else ""
        row["percentage"] = (
            HUNDRED * row["score"] / row["max_score"] if row["score"] is not None and row["max_score"] else None
        )
        rows.append(row)
    return cohort_ranks(rows)


def filter_records(records, filters, *, assessment=True, band=True):  # noqa: C901 - independent optional filter predicates
    output = []
    basis = filters.get("school_basis", "assessment")
    for row in records:
        if assessment and filters.get("assessment") and row["assessment_id"] != int(filters["assessment"]):
            continue
        if band and filters.get("band_missing") and row["band"]:
            continue
        if band and filters.get("band") and row["band"] != filters["band"]:
            continue
        if filters.get("q") and normalize_name(filters["q"]) not in normalize_name(row["name"]):
            continue
        if filters.get("birth_year") and row["birth_year"] != filters["birth_year"]:
            continue
        school_id = row[f"{basis}_school_id"]
        if filters.get("school_id") == "unknown" and school_id is not None:
            continue
        if filters.get("school_id") not in (None, "", "unknown") and school_id != int(filters["school_id"]):
            continue
        if filters.get("score_min") is not None and (row["score"] is None or row["score"] < filters["score_min"]):
            continue
        if filters.get("score_max") is not None and (
            row["score"] is None
            or (
                row["score"] > filters["score_max"]
                if filters.get("score_end") == "inclusive"
                else row["score"] >= filters["score_max"]
            )
        ):
            continue
        if filters.get("outcome_field") and row[filters["outcome_field"]] != filters.get("outcome_value", ""):
            continue
        output.append(row)
    return output


def approximate_age(birth_year, season):
    age = season - birth_year if birth_year else None
    return age if age is not None and 0 <= age <= MAX_APPROXIMATE_AGE else None


def cell(value, href=None, *, hint=""):
    return {
        "text": display(value), "value": value, "href": href, "hint": hint,
        "numeric": isinstance(value, (Decimal, int, float)),
    }


def record_row(row, filters):
    school = row[f"{filters.get('school_basis', 'assessment')}_school"]
    return {
        "key": row["id"],
        "name": row["name"],
        "rank": row["rank"],
        "score": row["score"],
        "school": school,
        "percentile": row["percentile"],
        "band": row["band"],
        "outcome": " · ".join(filter(None, [row["medal"], row["status_text"]])),
        "cells": [
            cell(row["rank"]),
            cell(row["name"], link(filters, tab="students", student=row["student_id"])),
            cell(school),
            cell(row["band"]),
            cell(row["score"]),
            cell(row["percentile"].quantize(Decimal("0.1")) if row["percentile"] is not None else None),
            cell(" · ".join(filter(None, [row["medal"], row["status_text"]]))),
            cell("Review", reverse("rankings:correction_new") + f"?kind=result&target={row['id']}"),
        ],
    }


def overview(records, filters, season_records):
    groups = defaultdict(list)
    for row in records:
        groups[(row["assessment_id"], row["band"])].append(row)
    panels, cohorts = [], []
    for (assessment_id, band), rows in sorted(
        groups.items(), key=lambda group: (group[1][0]["assessment"], group[0][1]),
    ):
        stats = score_summary([row["score"] for row in rows])
        label = f"{rows[0]['assessment']} · {band or 'Category not recorded'}"
        bins = histogram([row["score"] for row in rows])
        cohorts.append(
            {
                "label": label,
                **stats,
                "records": len(rows),
                "verified": all(row["scale_verified"] for row in rows),
                "max_score": rows[0]["max_score"],
            },
        )
        if bins:
            panels.append(
                {
                    "id": f"hist-{assessment_id}-{len(panels)}",
                    "title": label,
                    "subtitle": "Score distribution · numeric records only",
                    "type": "bar",
                    "labels": [item["label"] for item in bins],
                    "values": [item["count"] for item in bins],
                    "unit": "records",
                    "links": [
                        link(
                            filters,
                            assessment=assessment_id,
                            band=band,
                            band_missing=not bool(band),
                            score_min=item["low"],
                            score_max=item["high"],
                            score_end="inclusive" if item["inclusive"] else "",
                            tab="overview",
                        )
                        for item in bins
                    ],
                },
            )
        ties = Counter(row["rank"] for row in rows if row["rank"] is not None)
        if ties:
            panels.append(
                {
                    "id": f"ranks-{assessment_id}-{len(panels)}",
                    "title": "Recorded category ranks",
                    "subtitle": label + " · rank references remain the full category",
                    "type": "bar",
                    "labels": [str(rank) for rank in sorted(ties)],
                    "values": [ties[rank] for rank in sorted(ties)],
                    "unit": "students",
                    "links": [
                        link(filters, assessment=assessment_id, band=band, band_missing=not bool(band),
                             score_min=next(row["score"] for row in rows if row["rank"] == rank),
                             score_max=next(row["score"] for row in rows if row["rank"] == rank),
                             score_end="inclusive")
                        for rank in sorted(ties)
                    ],
                },
            )
    for field, title in [("medal", "Medals"), ("band", "Categories"), ("status_text", "Recorded statuses")]:
        counts = Counter(row[field] or "Not recorded" for row in records)
        if any(row[field] for row in records):
            panels.append(
                {
                    "id": "outcome-" + field,
                    "title": title,
                    "subtitle": "Separate recorded dimension · a result may appear in several dimensions",
                    "type": "bar",
                    "labels": list(counts),
                    "values": list(counts.values()),
                    "unit": "records",
                    "links": [
                        link(
                            filters,
                            outcome_field=field,
                            outcome_value="" if value == "Not recorded" else value,
                            tab="overview",
                        )
                        for value in counts
                    ],
                },
            )
    coverage = []
    for assessment_id in dict.fromkeys(row["assessment_id"] for row in season_records):
        values = [row for row in season_records if row["assessment_id"] == assessment_id]
        coverage.append(
            {
                "label": values[0]["assessment"],
                "records": len(values),
                "students": len({row["student_id"] for row in values}),
                "scored": sum(row["score"] is not None for row in values),
                "outcomes": sum(bool(row["medal"] or row["band"] or row["status_text"]) for row in values),
                "url": link(
                    filters,
                    assessment=assessment_id,
                    band=None,
                    band_missing=None,
                    outcome_field=None,
                    outcome_value=None,
                    score_min=None,
                    score_max=None,
                ),
            },
        )
    return {
        "rows": [record_row(row, filters) for row in records],
        "columns": [
            ("rank", "Category rank"),
            ("name", "Student"),
            ("school", "School"),
            ("band", "Category"),
            ("score", "Raw score"),
            ("percentile", "Cohort percentile"),
            ("outcome", "Medal / status"),
            ("", "Correction"),
        ],
        "panels": panels,
        "cohorts": cohorts,
        "season_coverage": coverage,
        "table_title": "Assessment records",
        "table_note": "Ranks and percentiles refer to the full assessment/category; filters do not recalculate them.",
    }


def latest_recorded_outcome(rows):
    season = max(row["season"] for row in rows)
    recent = [row for row in rows if row["season"] == season]
    if len(recent) > 1 and any(row["date"] is None for row in recent):
        return f"{season} · chronological order not verified"
    latest_date = max((row["date"] for row in recent if row["date"]), default=None)
    latest = [row for row in recent if row["date"] == latest_date]
    if len(latest) > 1:
        return f"{season} · {len(latest)} outcomes on the latest recorded date"
    row = latest[0]
    return " · ".join(filter(None, [row["assessment"], row["medal"], row["band"], row["status_text"]]))


def students_tab(records, filters, assessment_ids):
    groups = defaultdict(list)
    for row in records:
        groups[row["student_id"]].append(row)
    rows = []
    for student_id, values in groups.items():
        latest = max(
            values,
            key=lambda row: (
                row["season"],
                row["date"] is not None,
                str(row["date"] or ""),
                row["sort_order"],
                row["assessment_id"],
            ),
        )
        scored = sum(row["score"] is not None for row in values)
        rows.append(
            {
                "key": student_id,
                "name": latest["name"],
                "birth": latest["birth_year"],
                "records": len(values),
                "scored": scored,
                "school": latest[f"{filters.get('school_basis', 'assessment')}_school"],
                "cells": [
                    cell(latest["name"], link(filters, student=student_id)),
                    cell(latest["birth_year"]),
                    cell(len(values)),
                    cell(scored),
                    cell(latest_recorded_outcome(values)),
                    cell("Review", reverse("rankings:correction_new") + f"?kind=student&target={student_id}"),
                ],
            },
        )
    selected = filters.get("student")
    panel = None
    charts = []
    if selected:
        # Load full assessment cohorts for every event recorded by this student;
        # otherwise their personal-history percentile would incorrectly become 50.
        history_ids = list(StudentResult.objects.filter(student_id=selected).values_list("assessment_id", flat=True))
        full_history = load_records(assessment_ids=history_ids)
        history = [row for row in full_history if row["student_id"] == selected]
        history.sort(
            key=lambda row: (
                row["season"],
                row["date"] is None,
                str(row["date"] or ""),
                row["sort_order"],
                row["assessment_id"],
            ),
        )
        if history:
            panel = {
                "name": history[0]["name"],
                "id": selected,
                "birth_year": history[0]["birth_year"],
                "url": reverse("rankings:student_detail", args=[selected]),
                "rows": [],
            }
            for row in history:
                panel["rows"].append(
                    {
                        "assessment": row["assessment"],
                        "season": row["season"],
                        "age": approximate_age(row["birth_year"], row["season"]),
                        "date": row["date"],
                        "score": row["score"],
                        "percentile": row["percentile"],
                        "rank": row["rank"],
                        "band": row["band"],
                        "outcome": " · ".join(filter(None, [row["medal"], row["status_text"]])),
                        "school": row[f"{filters.get('school_basis', 'assessment')}_school"],
                        "source": row["source"],
                        "imported_at": row["imported_at"],
                    },
                )
            numeric = [row for row in history if row["score"] is not None]
            if numeric:
                charts.append(
                    {
                        "id": "student-trend",
                        "title": "Recorded relative standing",
                        "subtitle": (
                            "Full category percentile · undated results are grouped by season, "
                            "not inferred dates"
                        ),
                        "type": "line",
                        "labels": [
                            row["assessment"] + (f" · {row['date']}" if row["date"] else " · date not recorded")
                            for row in numeric
                        ],
                        "values": [float(row["percentile"]) for row in numeric],
                        "unit": "percentile",
                        "breaks": [row["date"] is None for row in numeric],
                    },
                )
    return {
        "rows": rows,
        "columns": [
            ("name", "Student"),
            ("birth", "Birth year"),
            ("records", "Recorded assessments"),
            ("scored", "Numeric scores"),
            ("", "Latest recorded outcome"),
            ("", "Correction"),
        ],
        "panels": charts,
        "student_panel": panel,
        "table_title": "Students in the current filters",
        "table_note": (
            "Counts use the active filters. Select a student for complete history across seasons; "
            "no records are consolidated by name."
        ),
    }


def schools_tab(records, filters):
    groups = defaultdict(list)
    basis = filters.get("school_basis", "assessment")
    for row in records:
        groups[(row["assessment_id"], row["band"], row[f"{basis}_school_id"], row[f"{basis}_school"])].append(row)
    output, chart_groups = [], defaultdict(list)
    for (assessment_id, band, school_id, school), values in groups.items():
        stats = score_summary([row["score"] for row in values])
        medals = Counter(row["medal"] for row in values if row["medal"])
        sample = "Small sample" if stats["count"] < MIN_SCHOOL_SCORES else ""
        output.append(
            {
                "key": f"{assessment_id}-{school_id}-{band}",
                "school": school,
                "assessment": values[0]["assessment"],
                "band": band,
                "records": len(values),
                "scored": stats["count"],
                "median": stats["median"],
                "mean": stats["mean"],
                "cells": [
                    cell(
                        school,
                        link(
                            filters,
                            tab="overview",
                            assessment=assessment_id,
                            band=band,
                            band_missing=not bool(band),
                            school_id=school_id if school_id else "unknown",
                        ),
                    ),
                    cell(values[0]["assessment"]),
                    cell(band),
                    cell(len(values)),
                    cell(stats["count"], hint=sample),
                    cell(stats["median"]),
                    cell(stats["mean"]),
                    cell(f"{display(stats['minimum'])}-{display(stats['maximum'])}" if stats["count"] else None),
                    cell(" · ".join(f"{medal}: {count}" for medal, count in sorted(medals.items()))),
                ],
            },
        )
        if school_id and stats["count"] >= MIN_SCHOOL_SCORES:
            chart_groups[(assessment_id, band)].append(
                {"school": school, "school_id": school_id, "median": stats["median"], "records": len(values)},
            )
    panels = []
    for (assessment_id, band), values in chart_groups.items():
        top = sorted(values, key=lambda value: (-value["records"], value["school"]))[:10]
        name = next(row["assessment"] for row in records if row["assessment_id"] == assessment_id)
        panels.append(
            {
                "id": f"school-{assessment_id}-{len(panels)}",
                "title": f"{name} · {band or 'Category not recorded'}",
                "subtitle": "Median score · top ten by recorded-student count · at least five scored students",
                "type": "bar",
                "labels": [value["school"] for value in top],
                "values": [float(value["median"]) for value in top],
                "unit": "score",
                "links": [
                    link(
                        filters, tab="overview", assessment=assessment_id, band=band,
                        band_missing=not bool(band), school_id=value["school_id"],
                    )
                    for value in top
                ],
            },
        )
    known = sum(row[f"{basis}_school_id"] is not None for row in records)
    return {
        "rows": output,
        "columns": [
            ("school", "School"),
            ("assessment", "Assessment"),
            ("band", "Category"),
            ("records", "Recorded students"),
            ("scored", "Scored students"),
            ("median", "Median"),
            ("mean", "Mean"),
            ("", "Score range"),
            ("", "Recorded medals"),
        ],
        "panels": panels,
        "school_coverage": {
            "known": known,
            "total": len(records),
            "basis": "Verified school at assessment" if basis == "assessment" else "Current recorded school",
        },
        "table_title": "School comparison",
        "table_note": (
            "Each row is one school within one assessment/category. Samples below five scored students "
            "remain in this table but are excluded from headline charts."
        ),
    }


def compare_tab(all_records, filters):
    primary = filters.get("assessment")
    secondary = filters.get("compare_assessment")
    if not primary or not secondary:
        return {
            "rows": [],
            "columns": [],
            "panels": [],
            "comparison": {"note": "Choose a primary assessment and a comparison assessment."},
            "table_title": "Matched student records",
            "table_note": "Students match by persistent ID only.",
        }
    left = filter_records([row for row in all_records if row["assessment_id"] == int(primary)], filters)
    right_filters = {
        **filters,
        "assessment": secondary,
        "band": filters.get("compare_band", ""),
        "band_missing": filters.get("compare_band_missing", False),
        "score_min": None,
        "score_max": None,
        "outcome_field": "",
        "outcome_value": "",
    }
    right = filter_records([row for row in all_records if row["assessment_id"] == int(secondary)], right_filters)
    a, b = {row["student_id"]: row for row in left}, {row["student_id"]: row for row in right}
    matched = sorted(a.keys() & b.keys())
    pairs = [(a[student_id], b[student_id]) for student_id in matched]
    numeric = [(one, two) for one, two in pairs if one["score"] is not None and two["score"] is not None]
    corr, note = spearman([one["score"] for one, _ in numeric], [two["score"] for _, two in numeric])
    matched_category_pairs = {(one["band"], two["band"]) for one, two in pairs}
    comparable = bool(numeric) and len(matched_category_pairs) == 1 and all(
        one["definition_verified"]
        and two["definition_verified"]
        and one["family"]
        and one["family"] == two["family"]
        and one["scale_verified"]
        and two["scale_verified"]
        and one["comparable_scope"]
        and one["comparable_scope"] == two["comparable_scope"]
        for one, two in numeric
    )
    mode = filters.get("compare_mode") or "percentile"
    if mode == "raw" and comparable and any(one["max_score"] != two["max_score"] for one, two in numeric):
        comparable = False
    if mode != "percentile" and not comparable:
        mode = "percentile"
        requirement = (
            "Choose exactly one matched category pair for raw or percentage comparisons. "
            if len(matched_category_pairs) > 1
            else "Raw/percentage comparisons require verified scoring scales, definitions, family, "
                 "and comparable scope (with equal maxima for raw scores). "
        )
        note = requirement + "Showing category percentiles. " + note
    key = {"raw": "score", "percentage": "percentage", "percentile": "percentile"}[mode]
    rows = []
    for one, two in pairs:
        delta = (
            two["percentile"] - one["percentile"]
            if one["percentile"] is not None and two["percentile"] is not None
            else None
        )
        rows.append(
            {
                "key": one["student_id"],
                "name": one["name"],
                "left": one["score"],
                "right": two["score"],
                "delta": delta,
                "cells": [
                    cell(one["name"], link(filters, tab="students", student=one["student_id"])),
                    cell(one["band"]),
                    cell(one["score"]),
                    cell(one["percentile"]),
                    cell(two["band"]),
                    cell(two["score"]),
                    cell(two["percentile"]),
                    cell(delta),
                ],
            },
        )
    panels = []
    if numeric:
        # Never connect different students, and never compute a single pooled
        # correlation over different category scales.
        panels.append(
            {
                "id": "comparison-scatter",
                "title": "Matched numeric records",
                "subtitle": f"{mode.title()} · each point is one student · {len(numeric)} matched scores",
                "type": "scatter",
                "points": [{"x": float(one[key]), "y": float(two[key]), "name": one["name"]} for one, two in numeric],
                "x_label": left[0]["assessment"] if left else "Primary",
                "y_label": right[0]["assessment"] if right else "Comparison",
                "unit": mode,
            },
        )
    transitions = []
    for field, label in [("medal", "Medal"), ("band", "Category"), ("status_text", "Status")]:
        counts = Counter((one[field] or "Not recorded", two[field] or "Not recorded") for one, two in pairs)
        transitions.extend(
            {"field": label, "left": one, "right": two, "count": count} for (one, two), count in sorted(counts.items())
        )
    # The statistic uses a single pair of category cohorts only.
    if len({(one["band"], two["band"]) for one, two in numeric}) > 1:
        corr = None
        note += " Choose one category on each side to calculate a cohort-specific correlation."
    return {
        "rows": rows,
        "columns": [
            ("name", "Student"),
            ("", "Primary category"),
            ("left", "Primary score"),
            ("", "Primary percentile"),
            ("", "Comparison category"),
            ("right", "Comparison score"),
            ("", "Comparison percentile"),
            ("delta", "Percentile change"),
        ],
        "panels": panels,
        "comparison": {
            "matched": len(pairs),
            "numeric": len(numeric),
            "left_only": len(a.keys() - b.keys()),
            "right_only": len(b.keys() - a.keys()),
            "correlation": corr,
            "note": note,
            "comparable": comparable,
            "mode": mode,
            "transitions": transitions,
        },
        "table_title": "Matched student records",
        "table_note": (
            "Percentile change is change in relative standing within the recorded category cohorts, "
            "not measured ability growth."
        ),
    }


def quality_tab(records, filters):  # noqa: C901, PLR0912 - explicit, independent data-quality rules
    issues = []

    def add(code, label, subject, value, kind, target, *, assessment="", extra=""):  # noqa: PLR0913
        url = reverse("rankings:correction_new") + "?" + urlencode({"kind": kind, "target": target}) + extra
        issues.append(
            {
                "key": f"{code}-{len(issues)}",
                "issue": code,
                "name": subject,
                "label": label,
                "cells": [cell(label), cell(subject), cell(assessment), cell(value), cell("Propose correction", url)],
            },
        )

    seen_students, seen_assessments, seen_scales = set(), set(), set()
    for row in records:
        if row["student_id"] not in seen_students:
            seen_students.add(row["student_id"])
            if row["birth_year"] is None:
                add("birth", "Birth year missing", row["name"], None, "student", row["student_id"])
            if row["current_school_id"] is None:
                add("current_school", "Current school missing", row["name"], None, "student", row["student_id"])
        if row["assessment_school_id"] is None:
            add(
                "attribution",
                "School at assessment unverified",
                row["name"],
                "Unknown / unverified",
                "attribution",
                row["id"],
                assessment=row["assessment"],
            )
        scale_key = row["assessment_id"], row["band"]
        if row["score"] is not None and not row["scale_verified"] and scale_key not in seen_scales:
            seen_scales.add(scale_key)
            add(
                "scale",
                "Score maximum unverified",
                row["assessment"],
                row["band"] or "Category not recorded",
                "scale",
                row["assessment_id"],
                extra="&" + urlencode({"band": row["band"]}),
            )
        if row["assessment_id"] not in seen_assessments:
            seen_assessments.add(row["assessment_id"])
            if row["date"] is None:
                add(
                    "date",
                    "Assessment date unverified",
                    row["assessment"],
                    "Date not recorded / reviewed",
                    "metadata",
                    row["assessment_id"],
                )
            if not row["definition_verified"]:
                add(
                    "definition",
                    "Assessment definition unverified",
                    row["assessment"],
                    "Review the source column meaning",
                    "metadata",
                    row["assessment_id"],
                )
        if (
            row["score"] is not None
            and row["max_score"] is not None
            and (row["score"] < 0 or row["score"] > row["max_score"])
        ):
            add(
                "range",
                "Score outside verified range",
                row["name"],
                f"{display(row['score'])} / {display(row['max_score'])}",
                "result",
                row["id"],
                assessment=row["assessment"],
            )
    names = {normalize_name(row["name"]) for row in records}
    duplicates = defaultdict(list)
    for student in Student.objects.filter(normalized_name__in=names).values(
        "id", "full_name", "normalized_name", "birth_year",
    ):
        duplicates[student["normalized_name"]].append(student)
    reviews = {
        (review.first_student_id, review.second_student_id): review.decision
        for review in StudentIdentityReview.objects.filter(active=True)
    }
    for values in duplicates.values():
        for one, two in combinations(sorted(values, key=lambda value: value["id"]), 2):
            decision = reviews.get((one["id"], two["id"]))
            add(
                "duplicate",
                "Confirmed separate" if decision == "confirmed_separate" else "Possible duplicate name",
                one["full_name"],
                f"Student #{one['id']} ({display(one['birth_year'])}) / #{two['id']} ({display(two['birth_year'])})",
                "identity",
                one["id"],
                extra="&" + urlencode({"second_student_id": two["id"]}),
            )
    label_groups = defaultdict(set)
    for row in records:
        for field in ("band", "medal", "status_text"):
            if row[f"original_{field}"] == row[field] and row[field]:
                label_groups[(row["assessment_id"], row["assessment"], field, normalize_name(row[field]))].add(
                    row[field],
                )
    for (assessment_id, assessment, field, _), values in label_groups.items():
        if len(values) > 1:
            value = sorted(values)[0]
            add(
                "aliases",
                "Outcome labels differ in formatting",
                assessment,
                " / ".join(sorted(values)),
                "outcome_alias",
                assessment_id,
                extra="&" + urlencode({"field": field, "alias": value}),
            )
    school_groups = defaultdict(list)
    relevant_schools = {
        row[key] for row in records
        for key in ("current_school_id", "assessment_school_id") if row[key]
    }
    for school in School.objects.filter(pk__in=relevant_schools).values("id", "name", "normalized_name"):
        key = "".join(character for character in normalize("NFKC", school["normalized_name"]) if character.isalnum())
        if key:
            school_groups[key].append(school)
    for values in school_groups.values():
        if len(values) > 1:
            canonical = values[0]
            for other in values[1:]:
                add(
                    "aliases",
                    "Similar school labels",
                    canonical["name"],
                    other["name"],
                    "school_alias",
                    canonical["id"],
                    extra="&" + urlencode({"alias": other["name"]}),
                )
    counts = Counter(row["issue"] for row in issues)
    from inspinia.rankings.analysis_forms import ISSUES

    cards = [
        {"label": label, "count": counts[code], "url": link(filters, issue=code, tab="quality")}
        for code, label in ISSUES
        if code
    ]
    if filters.get("issue"):
        issues = [row for row in issues if row["issue"] == filters["issue"]]
    return {
        "rows": issues,
        "columns": [
            ("label", "Issue"),
            ("name", "Student / assessment"),
            ("", "Assessment"),
            ("", "Recorded value / context"),
            ("", "Review"),
        ],
        "panels": [],
        "quality_cards": cards,
        "table_title": "Data review queue",
        "table_note": (
            "Issues are review prompts. Similar names do not establish the same identity; "
            "confirmed separate students stay separate."
        ),
        "pending_corrections": RankingCorrection.objects.filter(status="submitted").count(),
        "held_imports": RankingImportConflict.objects.filter(status="pending").count(),
    }


def build_workspace(filters, assessments):
    season = filters.get("season")
    season_ids = [row.pk for row in assessments if not season or row.season_year == int(season)]
    ids = set(season_ids)
    if filters.get("compare_assessment"):
        ids.add(int(filters["compare_assessment"]))
    all_records = load_records(assessment_ids=ids)
    records = filter_records([row for row in all_records if row["assessment_id"] in season_ids], filters)
    season_records = filter_records(
        [row for row in all_records if row["assessment_id"] in season_ids],
        {
            **filters,
            "assessment": "",
            "band": "",
            "band_missing": False,
            "score_min": None,
            "score_max": None,
            "outcome_field": "",
            "outcome_value": "",
        },
        assessment=False,
        band=False,
    )
    tab = filters["tab"]
    if tab == "overview":
        content = overview(records, filters, season_records)
    elif tab == "students":
        content = students_tab(records, filters, ids)
    elif tab == "schools":
        content = schools_tab(records, filters)
    elif tab == "compare":
        content = compare_tab(all_records, filters)
    else:
        content = quality_tab(records, filters)
    scored = sum(row["score"] is not None for row in records)
    latest_import = max((row["imported_at"] for row in records if row["imported_at"]), default=None)
    latest_change = max((row["updated_at"] for row in records), default=None)
    content.update(
        {
            "summary": {
                "students": len({row["student_id"] for row in records}),
                "records": len(records),
                "assessments": len({row["assessment_id"] for row in records}),
                "score_coverage": round(scored * 100 / len(records), 1) if records else None,
                "scored": scored,
            },
            "latest_import": latest_import,
            "latest_change": latest_change,
            "records": records,
            "pending_count": RankingCorrection.objects.filter(status="submitted").count(),
            "filters": filters,
        },
    )
    return content
