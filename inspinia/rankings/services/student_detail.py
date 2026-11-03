"""Read-only, student-scoped presentation for the student record explorer.

Dates, recorded labels and source identities stay distinct: this page does not
infer a current squad, historical school, contest date or comparable score.
"""

from __future__ import annotations

import re
from collections import Counter
from collections import defaultdict
from datetime import date
from unicodedata import normalize
from urllib.parse import urlencode
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import URLValidator

from inspinia.rankings.forms import StudentDetailFilterForm
from inspinia.rankings.imports.olympiad_sheet import HISTORY_COLUMNS
from inspinia.rankings.models import OutcomeAlias
from inspinia.rankings.models import SchoolAlias
from inspinia.rankings.models import StudentSelectionStatus
from inspinia.rankings.models import normalize_name
from inspinia.rankings.services.school_display import SOURCE_SCHOOL_PREFIX

PAGE_SIZE = 50
TIMELINE_BUCKET_LIMIT = 6
LEGACY_GROUP_CODES = frozenset(column[1] for column in HISTORY_COLUMNS if column[4] == "status_text")
GROUP_LABELS = frozenset(
    {
        *(value for value in StudentSelectionStatus.Status.values if value != "none"),
        "junior squad",
        "senior squad",
        "primary squad",
        "junior team",
        "senior team",
        "primary team",
    },
)
LEGACY_NAME = re.compile(r"(?P<title>.+) \(legacy source(?: (?P<date>\d{4}-\d{2}-\d{2}))?\)")
SOURCE_TRAILER = re.compile(r"(?P<file>.+) \[Sheet1 row (?P<row>\d+); sha256 (?P<sha>[0-9a-f]{64})\]")
MEDAL_LABEL = re.compile(r"(gold|silver|bronze)(?: medal| award| medalist)?")
QUALIFIED_MEDAL = re.compile(r"(?:high distinction|distinction) (gold|silver|bronze)(?: medal| award)?")


def search_text(value):
    return " ".join(normalize("NFKC", str(value)).casefold().split())


def _source(value):
    original = value or ""
    match = SOURCE_TRAILER.fullmatch(original)
    return {
        "label": match["file"] if match else original,
        "original": original,
        "row": match["row"] if match else "",
        "checksum": match["sha"] if match else "",
        "key": (match["file"], match["sha"]) if match else (original, ""),
    }


def _legacy_name(assessment):
    match = LEGACY_NAME.fullmatch(assessment.display_name) if assessment.code.startswith("LH_") else None
    source_date = None
    if match and match["date"]:
        try:
            source_date = date.fromisoformat(match["date"])
        except ValueError:
            return assessment.display_name, None
        if source_date.year != assessment.season_year:
            return assessment.display_name, None
    return match["title"] if match else assessment.display_name, source_date


def _event_time(assessment):
    metadata = getattr(assessment, "analysis_metadata", None)
    if metadata and metadata.date_verified and assessment.assessment_date:
        value = assessment.assessment_date
        return (value.year, value.month, value.day), value.strftime("%-d %b %Y"), "Verified date"
    # Only mappings from the reviewed history adapter establish month precision.
    if assessment.code in LEGACY_GROUP_CODES:
        match = re.fullmatch(r"SELECTION_(\d{4})_(\d{2})", assessment.code)
        if match and int(match[1]) == assessment.season_year and 1 <= int(match[2]) <= 12:  # noqa: PLR2004
            value = date(int(match[1]), int(match[2]), 1)
            return (value.year, value.month, 0), value.strftime("%b %Y"), "Month recorded"
    return (assessment.season_year, 0, 0), str(assessment.season_year), "Year only"


def _group_labels(assessment, band, status):
    labels = []
    for value in (band, status):
        if value and search_text(value) in GROUP_LABELS and value not in labels:
            labels.append(value)
    if assessment.code in LEGACY_GROUP_CODES and status and status not in labels:
        labels.append(status)
    return labels


def _outcomes(medal, status):
    def item(label):
        match = MEDAL_LABEL.fullmatch(search_text(label))
        tone = match[1] if match else "neutral"
        if not match:
            words = re.findall(r"\b(gold|silver|bronze)\b", search_text(label))
            if len(set(words)) == 1:
                tone = words[0]
        return {"label": label, "tone": tone}

    if not medal:
        return [item(status)] if status else []
    if not status or search_text(medal) == search_text(status):
        return [item(medal)]
    medal_match = MEDAL_LABEL.fullmatch(search_text(medal))
    status_match = MEDAL_LABEL.fullmatch(search_text(status))
    if medal_match and status_match and medal_match[1] == status_match[1]:
        return [item(medal)]
    qualified = QUALIFIED_MEDAL.fullmatch(search_text(status))
    if medal_match and qualified and medal_match[1] == qualified[1]:
        return [item(status)]
    return [item(medal), item(status)]


def _safe_url(value):
    if not value:
        return ""
    try:
        URLValidator(schemes=["http", "https"])(value)
        parsed = urlsplit(value)
        if parsed.username or parsed.password:
            return ""
    except (ValidationError, ValueError):
        return ""
    return value


def _record(result, aliases, schools):
    assessment = result.assessment
    values = {
        field: aliases.get((assessment.pk, field, normalize_name(getattr(result, field))), getattr(result, field))
        for field in ("band", "medal", "status_text")
    }
    title, source_date = _legacy_name(assessment)
    metadata = getattr(assessment, "analysis_metadata", None)
    attribution = getattr(result, "school_attribution", None)
    historical_school = ""
    school_basis = "Not recorded"
    if attribution and attribution.verified:
        historical_school = attribution.school.name
        school_basis = "Reviewed attribution"
    elif result.remarks.startswith(SOURCE_SCHOOL_PREFIX):
        historical_school = result.remarks[len(SOURCE_SCHOOL_PREFIX) :].strip()
        school_basis = "Recorded in source"
    display_school = schools.get(normalize_name(historical_school), historical_school)
    group_labels = _group_labels(assessment, values["band"], values["status_text"])
    outcomes = _outcomes(values["medal"], values["status_text"])
    return {
        "id": result.pk,
        "year": assessment.season_year,
        "assessment_id": assessment.pk,
        "title": title,
        "full_title": assessment.display_name,
        "code": assessment.code,
        "band": values["band"],
        "medal": values["medal"],
        "status": values["status_text"],
        "original_band": result.band,
        "original_medal": result.medal,
        "original_status": result.status_text,
        "has_alias": any(values[field] != getattr(result, field) for field in values),
        "score": result.raw_score,
        "outcomes": outcomes,
        "is_group": bool(group_labels),
        "has_outcome": bool(values["medal"] or (values["status_text"] and values["status_text"] not in group_labels)),
        "group_labels": group_labels,
        "time": _event_time(assessment),
        "division": assessment.division_scope,
        "verified_date": assessment.assessment_date if metadata and metadata.date_verified else None,
        "unverified_date": assessment.assessment_date if not metadata or not metadata.date_verified else None,
        "source_date": source_date,
        "source": _source(result.source_file_name),
        "school": display_school,
        "original_school": historical_school,
        "school_basis": school_basis,
        "notes": "" if result.remarks.startswith(SOURCE_SCHOOL_PREFIX) else result.remarks,
        "url": _safe_url(result.source_url),
        "imported_at": result.imported_at,
        "updated_at": result.updated_at,
        "search": search_text(
            " ".join(
                [
                    assessment.display_name,
                    assessment.code,
                    *values.values(),
                    result.band,
                    result.medal,
                    result.status_text,
                ],
            ),
        ),
        "sort_order": assessment.sort_order,
    }


def _timeline(records, statuses):
    buckets = {}

    def append(time, event):
        key, label, precision = time
        bucket = buckets.setdefault(key, {"label": label, "precision": precision, "events": []})
        bucket["events"].append(event)

    for row in records:
        if row["is_group"]:
            append(
                row["time"],
                {
                    "label": " · ".join(row["group_labels"]),
                    "assessment": row["full_title"],
                    "division": row["division"],
                    "source": row["source"]["label"],
                    "origin": "Assessment record",
                },
            )
    for status in statuses:
        append(
            ((status.season_year, 0, 0), str(status.season_year), "Year only"),
            {
                "label": status.get_status_display(),
                "assessment": "Structured group / selection record",
                "division": status.division,
                "source": "Student selection status",
                "origin": "Structured record",
            },
        )
    ordered = [buckets[key] for key in sorted(buckets)]
    for bucket in ordered:
        bucket["count"] = len(bucket["events"])
        bucket["summary"] = (
            bucket["events"][0]["label"] if bucket["count"] == 1 else f"{bucket['count']} recorded labels"
        )
    return ordered


def _sources(records):
    groups = {}
    for row in records:
        source = row["source"]
        if not source["label"]:
            continue
        group = groups.setdefault(
            source["key"],
            {
                "label": source["label"],
                "checksum": source["checksum"],
                "count": 0,
                "latest": None,
                "labels": set(),
            },
        )
        group["count"] += 1
        group["labels"].add(source["original"])
        if row["imported_at"] and (group["latest"] is None or row["imported_at"] > group["latest"]):
            group["latest"] = row["imported_at"]
    for group in groups.values():
        group["labels"] = sorted(group["labels"])
    return sorted(
        groups.values(),
        key=lambda group: (
            group["latest"] is None,
            -group["latest"].timestamp() if group["latest"] else 0,
            group["label"],
        ),
    )


def build_student_detail(student, params, path):
    """Build one student's complete summary and a filtered, paginated explorer."""
    results = list(
        student.results.select_related(
            "assessment",
            "assessment__analysis_metadata",
            "school_attribution__school",
        ),
    )
    assessment_ids = {result.assessment_id for result in results}
    aliases = {
        (alias.assessment_id, alias.field, alias.normalized_alias): alias.canonical
        for alias in OutcomeAlias.objects.filter(active=True, assessment_id__in=assessment_ids)
    }
    school_names = {
        normalize_name(result.remarks[len(SOURCE_SCHOOL_PREFIX) :].strip())
        for result in results
        if result.remarks.startswith(SOURCE_SCHOOL_PREFIX)
    }
    school_names.update(
        attribution.school.normalized_name
        for result in results
        if (attribution := getattr(result, "school_attribution", None)) and attribution.verified
    )
    schools = {
        alias.normalized_name: alias.school.name
        for alias in SchoolAlias.objects.filter(
            active=True,
            normalized_name__in=school_names,
        ).select_related("school")
    }
    records = [_record(result, aliases, schools) for result in results]
    records.sort(key=lambda row: (-row["year"], row["sort_order"], row["assessment_id"], row["id"]))
    titles = Counter((row["year"], row["title"]) for row in records)
    for row in records:
        row["disambiguation"] = row["full_title"] if titles[row["year"], row["title"]] > 1 else ""
    timeline = _timeline(records, student.selection_statuses.order_by("season_year", "pk"))
    sources = _sources(records)
    years = sorted({row["year"] for row in records}, reverse=True)
    form = StudentDetailFilterForm(params, years=years)
    valid = form.is_valid()
    filters = form.cleaned_data if valid else {}
    query = search_text(filters.get("q", ""))
    year = filters.get("year", "")
    kind = filters.get("type") or "all"
    active = bool(query or year or kind != "all")
    matched = [
        row
        for row in records
        if valid
        and (not year or row["year"] == int(year))
        and all(word in row["search"] for word in query.split())
        and (
            kind == "all"
            or (kind == "scores" and row["score"] is not None)
            or (kind == "outcomes" and row["has_outcome"])
            or (kind == "groups" and row["is_group"])
        )
    ]
    counts = Counter(row["year"] for row in matched)
    page = Paginator(matched, PAGE_SIZE).get_page(params.get("page"))
    groups = defaultdict(list)
    for row in page:
        groups[row["year"]].append(row)
    year_groups = [
        {"year": value, "rows": rows, "count": counts[value], "shown": len(rows), "open": active or index == 0}
        for index, (value, rows) in enumerate(groups.items())
    ]
    pagination = {
        key: value
        for key, value in {"q": filters.get("q", ""), "year": year, "type": kind if kind != "all" else ""}.items()
        if value
    }
    canonical = {**pagination, **({"page": page.number} if page.number > 1 else {})}
    canonical_query = urlencode(canonical) if valid else params.urlencode()
    return {
        "student": student,
        "form": form,
        "results": records,
        "page_obj": page,
        "year_groups": year_groups,
        "summary": {
            "count": len(records),
            "coverage": f"{min(years)}\u2013{max(years)}" if years else "Not recorded",
            "sources": len(sources),
            "initials": "".join(part[0] for part in student.full_name.split()[:2]).upper(),
        },
        "timeline": timeline,
        "timeline_preview": timeline[-TIMELINE_BUCKET_LIMIT:],
        "timeline_count": sum(bucket["count"] for bucket in timeline),
        "sources": sources,
        "rankings": list(
            student.ranking_snapshots.select_related("ranking_formula").order_by("-season_year", "division", "pk"),
        ),
        "filters_active": active,
        "filters_valid": valid,
        "pagination_query": urlencode(pagination),
        "canonical_url": path + ("?" + canonical_query if canonical_query else ""),
    }
