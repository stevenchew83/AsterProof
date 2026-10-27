"""Personal progress over canonical areas and concepts, using current source mappings."""

import csv
from collections import defaultdict
from io import StringIO
from statistics import mean
from statistics import median

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.urls import reverse
from django.utils.http import urlencode

from inspinia.pages.completion_record_fields import is_completion_status_solved
from inspinia.pages.concept_analytics import PAGE_SIZE
from inspinia.pages.concept_analytics import SUBJECTS
from inspinia.pages.concept_analytics import library_coverage_rows
from inspinia.pages.concept_analytics import library_problem_url
from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.technique_concepts import CONCEPTS
from inspinia.pages.technique_progress import resolve_technique_progress_user
from inspinia.pages.technique_progress import technique_progress_user_options

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


def _completed_library(user):
    library, _ = library_coverage_rows({"contest": "", "year": ""})
    statement_ids = {p["statement_id"] for p in library.values() if p["statement_id"]}
    problem_ids = {p["problem_id"] for p in library.values() if p["problem_id"]}
    by_statement, by_problem = {}, {}
    # The indexed user scope is already narrow. Avoid sending the whole library
    # back to the database as two potentially enormous IN clauses.
    for completion in UserProblemCompletion.objects.filter(user=user).values(
        "statement_id", "problem_id", "status", "completion_date",
    ).iterator(chunk_size=256):
        if completion["statement_id"] in statement_ids:
            by_statement[completion["statement_id"]] = completion
        if completion["problem_id"] in problem_ids:
            by_problem[completion["problem_id"]] = completion
    status_labels = dict(UserProblemCompletion.Status.choices)
    for problem in library.values():
        completion = by_statement.get(problem["statement_id"], by_problem.get(problem["problem_id"])) or {}
        status = completion.get("status", UserProblemCompletion.Status.UNATTEMPTED)
        problem.update(
            is_solved=is_completion_status_solved(status),
            status=status,
            status_label=status_labels.get(status, "Unattempted"),
            completion_date=completion.get("completion_date"),
        )
    return library


def _catalogue_rows(library):
    by_concept = defaultdict(dict)
    for uuid, problem in library.items():
        for concept in problem["concept_coverage"]:
            by_concept[concept["id"]][uuid] = problem
    areas, concepts, subjects = {}, [], {s: {} for s in SUBJECTS}
    for cid, definition in CONCEPTS.items():
        subject = definition.get("subject", "Algebra")
        key = f"{subject}:{definition['area']}"
        row = {
            "id": cid,
            "label": definition["label"],
            "search_text": " ".join([cid, *(caption for _, caption in definition["aliases"])]).casefold(),
            "subject": subject,
            "area_key": key,
            "area": definition["area_label"],
            **_counts(by_concept[cid]),
        }
        concepts.append(row)
        area = areas.setdefault(
            key,
            {
                "id": key,
                "label": row["area"],
                "subject": subject,
                "problems": {},
                "concepts": 0,
                "available": 0,
                "practiced": 0,
            },
        )
        area["concepts"] += 1
        area["available"] += bool(row["total"])
        area["practiced"] += bool(row["solved"])
        area["problems"].update(by_concept[cid])
        subjects[subject].update(by_concept[cid])
    for area in areas.values():
        area.update(_counts(area.pop("problems")))
    return concepts, list(areas.values()), subjects, by_concept


def _state_matches(row, state):
    return {
        "available": row["total"] > 0,
        "remaining": row["remaining"] > 0,
        "completed": row["total"] > 0 and row["remaining"] == 0,
        "empty": row["total"] == 0,
    }[state]


def _explorer_rows(rows, filters):
    tokens = filters["q"].casefold().split()
    matching = [
        r
        for r in rows
        if _state_matches(r, filters["state"])
        and all(
            t in f"{r['label']} {r['subject']} {r.get('area', '')} {r.get('search_text', '')}".casefold()
            for t in tokens
        )
    ]
    sort_keys = {
        "remaining": lambda r: (-r["remaining"], r["label"].casefold()),
        "progress": lambda r: (-r["percent"], -r["solved"], r["label"].casefold()),
        "name": lambda r: (r["label"].casefold(), r["subject"]),
    }
    return sorted(matching, key=sort_keys[filters["sort"]])


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


def build_concept_progress_context(*, request_user, params, topic_slug=""):  # noqa: C901, PLR0912, PLR0915
    if topic_slug and topic_slug not in SUBJECT_SLUGS:
        raise ValueError(topic_slug)
    selected_user, can_select = resolve_technique_progress_user(
        request_user=request_user,
        raw_user_id=str(params.get("user", "")),
    )
    subject = SUBJECT_SLUGS.get(topic_slug, "")
    filters = {key: str(params.get(key, "")).strip() for key in ("area", "concept", "q", "state", "mode", "sort")}
    filters["user"] = str(selected_user.pk) if can_select else ""
    if filters["mode"] not in {"areas", "concepts", "problems"}:
        filters["mode"] = "areas"
    if filters["state"] not in {"available", "remaining", "completed", "empty"}:
        filters["state"] = "available"
    if filters["sort"] not in {"name", "progress"}:
        filters["sort"] = "remaining"

    def link(*, slug=topic_slug, **changes):
        route = (
            reverse("pages:technique_progress_topic_detail", args=[slug])
            if slug
            else reverse("pages:technique_dashboard")
        )
        query = urlencode({k: v for k, v in {**filters, **changes}.items() if v})
        return route + (f"?{query}" if query else "")

    library = _completed_library(selected_user)
    from inspinia.pages.concept_assignment_registry import REGISTRY
    from inspinia.pages.concept_assignment_service import projection_enabled

    assignment_mode = projection_enabled()
    if assignment_mode:
        from inspinia.pages.concept_assignment_progress import assignment_catalogue_rows

        filters["concept"] = REGISTRY.canonical(filters["concept"])
        valid_areas = {
            f"{a['subject']}:{a['area']}"
            for d in REGISTRY.definitions.values()
            for a in d["area_memberships"]
            if not subject or a["subject"] == subject
        }
        if filters["area"] not in valid_areas:
            filters["area"] = ""
        concepts, areas, subjects, by_concept = assignment_catalogue_rows(
            library,
            _counts,
            SUBJECTS,
            subject=subject,
            area_key=filters["area"],
        )
    else:
        concepts, areas, subjects, by_concept = _catalogue_rows(library)
    scope_concepts = [c for c in concepts if not subject or subject in c.get("subjects", [c["subject"]])]
    scope_areas = [a for a in areas if not subject or a["subject"] == subject]
    if filters["area"] and filters["area"] not in {a["id"] for a in scope_areas}:
        filters["area"] = ""
    selected_area = next((a for a in scope_areas if a["id"] == filters["area"]), None)
    if selected_area:
        scope_concepts = [c for c in scope_concepts if selected_area["id"] in c.get("area_keys", [c["area_key"]])]
        scope_areas = [selected_area]
    scope_problems = {}
    for concept in scope_concepts:
        scope_problems.update(by_concept[concept["id"]])
    selected_concept = next((c for c in scope_concepts if c["id"] == filters["concept"]), None)
    if not selected_concept:
        filters["concept"] = ""
        if filters["mode"] == "problems":
            filters["mode"] = "concepts"
    for concept in concepts:
        concept["url"] = (
            link(
                concept=concept["id"],
                mode="problems",
                state="remaining" if concept["remaining"] else "completed" if concept["total"] else "available",
                q="",
            )
            + "#progress-explorer"
        )
    for area in areas:
        area["url"] = (
            link(area=area["id"], concept="", mode="concepts", state="available", q="") + "#progress-explorer"
        )
    subject_rows = [
        {
            "label": s,
            **_counts(subjects[s]),
            "url": link(
                slug=next(k for k, v in SUBJECT_SLUGS.items() if v == s),
                area="",
                concept="",
                mode="areas",
                state="available",
                q="",
            ),
            "active": subject == s,
        }
        for s in SUBJECTS
    ]
    stats = {
        **_counts(scope_problems),
        "practiced": sum(bool(c["solved"]) for c in scope_concepts),
        "concepts": sum(bool(c["total"]) for c in scope_concepts),
        "areas": sum(bool(a["total"]) for a in scope_areas),
    }
    candidates = sorted(
        (c for c in scope_concepts if c["remaining"]),
        key=lambda c: (not bool(c["solved"]), -c["remaining"], c["label"].casefold()),
    )[:4]
    mode_rows = scope_concepts if filters["mode"] == "concepts" else scope_areas
    state_tabs = [
        {
            "value": state,
            "label": label,
            "count": sum(_state_matches(r, state) for r in mode_rows),
            "url": link(state=state, concept="") + "#progress-explorer",
        }
        for state, label in (
            ("available", "With problems"),
            ("remaining", "To practice"),
            ("completed", "Completed"),
            ("empty", "No problems"),
        )
    ]
    if filters["mode"] == "problems":
        mode_rows = list(by_concept[selected_concept["id"]].values())
        state_tabs = [
            {
                "value": state,
                "label": label,
                "count": sum(state == "available" or p["is_solved"] == (state == "completed") for p in mode_rows),
                "url": link(state=state) + "#progress-explorer",
            }
            for state, label in (("available", "All problems"), ("remaining", "Remaining"), ("completed", "Completed"))
        ]
        if filters["state"] == "empty":
            filters["state"] = "available"
        matching = [
            p
            for p in mode_rows
            if (filters["state"] == "available" or p["is_solved"] == (filters["state"] == "completed"))
            and all(t in p["label"].casefold() for t in filters["q"].casefold().split())
        ]
        matching.sort(
            key=lambda p: (
                p["is_solved"],
                p["mohs"] if p["mohs"] is not None else float("inf"),
                -p["year"],
                p["label"],
            ),
        )
    else:
        matching = _explorer_rows(mode_rows, filters)
    page = Paginator(matching, PAGE_SIZE).get_page(params.get("page"))
    if filters["mode"] == "problems":
        for problem in page.object_list:
            problem["url"] = library_problem_url(problem)
    completion_query = {"target_user_id": selected_user.pk} if can_select else {}
    return {
        "selected_user": selected_user,
        "can_select_user": can_select,
        "user_options": technique_progress_user_options() if can_select else [],
        "filters": filters,
        "subject": subject,
        "stats": stats,
        "subject_rows": subject_rows,
        "scope_areas": sorted(
            (
                a
                for a in (
                    assignment_catalogue_rows(library, _counts, SUBJECTS, subject=subject)[1]
                    if assignment_mode
                    else areas
                )
                if not subject or a["subject"] == subject
            ),
            key=lambda a: a["label"],
        ),
        "selected_area": selected_area,
        "selected_concept": selected_concept,
        "selected_summary": _counts(by_concept[selected_concept["id"]]) if selected_concept else None,
        "study_notes": _study_notes(selected_concept["id"]) if selected_concept else None,
        "practice_rows": candidates,
        "progress_page": page,
        "state_tabs": state_tabs,
        "mode_tabs": [
            {
                "label": label,
                "value": mode,
                "url": link(mode=mode, concept="", state="available", q="") + "#progress-explorer",
            }
            for mode, label in (("areas", "Areas"), ("concepts", "Concepts"))
        ],
        "all_subjects_url": link(slug="", area="", concept="", mode="areas", q=""),
        "clear_area_url": link(area="", concept="", q="", mode="areas", state="available"),
        "back_to_concepts_url": link(concept="", mode="concepts", state="available", q="") + "#progress-explorer",
        "pagination_url": link(),
        "form_url": reverse("pages:technique_progress_topic_detail", args=[topic_slug])
        if topic_slug
        else reverse("pages:technique_dashboard"),
        "export_url": link(export="csv"),
        "export_rows": matching,
        "completion_url": reverse("pages:completion_quick_update")
        + ("?" + urlencode(completion_query) if completion_query else ""),
        "unmapped_total": sum(
            not p["concept_coverage"] and (not subject or p["subject"] == subject) for p in library.values()
        ),
    }


def _csv_row(values):
    return [
        "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value
        for value in values
    ]


def concept_progress_csv(context):
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
