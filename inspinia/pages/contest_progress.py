"""Read-only learner selection and the contest progress matrix."""

import re
from collections import defaultdict
from dataclasses import dataclass
from http import HTTPStatus
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import InvalidPage
from django.core.paginator import Paginator
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models.functions import Lower
from django.db.models.functions import Trim
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from inspinia.users.models import User
from inspinia.users.roles import user_has_admin_role

LEARNER_LIMIT = 20
LEARNER_MIN_SEARCH = 2
LEARNER_MAX_SEARCH = 254
LOW_SCORE_MAX = 2
MID_SCORE_MAX = 5
YEARS_PER_PAGE = 8
SHORTLIST_GROUPS = {"A": "Algebra", "C": "Combinatorics", "G": "Geometry", "N": "Number theory"}


@dataclass(frozen=True)
class ContestProgressDisplay:
    mode: str
    focus: str
    year_page: str
    read_only: bool

    @classmethod
    def from_query(cls, query, *, read_only):
        mode = "completion" if query.get("mode") == "completion" else "score"
        focus = query.get("focus", "")
        if mode != "score" or focus not in {"low", "unscored"}:
            focus = ""
        return cls(mode, focus, query.get("year_page", "1"), read_only)


def can_select_contest_learner(user):
    return user.is_active and user_has_admin_role(user)


def _eligible_learners():
    eligible = User.objects.filter(is_active=True).filter(
        Q(is_approved=True) | Q(role=User.Role.ADMIN) | Q(is_superuser=True),
    ).alias(_name_key=Lower(Trim("name")))
    return eligible.annotate(
        _duplicate_name=Exists(eligible.filter(_name_key=OuterRef("_name_key")).exclude(pk=OuterRef("pk"))),
    ).only("id", "name", "email", "is_active", "is_approved", "role", "is_superuser")


def contest_learner_label(learner):
    name = learner.name.strip()
    if not name:
        return learner.email
    if learner._duplicate_name:  # noqa: SLF001 - Projected by _eligible_learners.
        return f"{name} ({learner.email})"
    return name


def find_contest_learner(value):
    if not re.fullmatch(r"[0-9]{1,19}", value):
        return None
    pk = int(value)
    if not 0 < pk <= 2**63 - 1:
        return None
    return _eligible_learners().filter(pk=pk).first()


@never_cache
@login_required
@require_GET
def contest_progress_learner_options_view(request):
    if not can_select_contest_learner(request.user):
        return JsonResponse({"error": "Forbidden."}, status=HTTPStatus.FORBIDDEN)

    term = request.GET.get("q", "").strip()
    learners = []
    if LEARNER_MIN_SEARCH <= len(term) <= LEARNER_MAX_SEARCH:
        learners = list(
            _eligible_learners()
            .exclude(pk=request.user.pk)
            .filter(Q(name__icontains=term) | Q(email__icontains=term))
            .order_by("_name_key", "pk")[:LEARNER_LIMIT + 1],
        )
    return JsonResponse({
        "results": [
            {"id": learner.pk, "label": contest_learner_label(learner)}
            for learner in learners[:LEARNER_LIMIT]
        ],
        "has_more": len(learners) > LEARNER_LIMIT,
    })


def contest_progress_url(contest, *, learner="", mode="score", focus="", page=1):
    query = {"contest": contest} if contest else {}
    if learner:
        query["learner"] = learner
    if mode == "completion":
        query["mode"] = mode
    if mode == "score" and focus:
        query["focus"] = focus
    if page > 1:
        query["year_page"] = page
    path = reverse("pages:contest_advanced_dashboard")
    return f"{path}?{urlencode(query)}" if query else path


def problem_sort_key(problem_label: str | None) -> list[tuple[int, int | str]]:
    parts = re.split(r"(\d+)", str(problem_label or ""))
    return [(0, int(part)) if part.isdigit() else (1, part.lower()) for part in parts if part]


def _group_label(contest, code):
    if contest.casefold() == "imo shortlist":
        shortlist_match = re.fullmatch(r"([ACGN])\s*\d+", code)
        return SHORTLIST_GROUPS[shortlist_match[1]] if shortlist_match else "Other"
    grade = re.match(r"^(9|10|11)\.", code)
    if grade:
        return f"Grade {grade[1]}"
    return "P-codes" if re.match(r"^P\d+", code, flags=re.IGNORECASE) else "Other"


def _group_columns(contest, codes):
    groups = []
    for index, code in enumerate(codes):
        label = _group_label(contest, code)
        if groups and groups[-1]["label"] == label:
            groups[-1]["span"] += 1
        else:
            groups.append({"label": label, "start_index": index, "span": 1})
    return groups


def _score_tone(score):
    if score <= LOW_SCORE_MAX:
        return "low"
    return "mid" if score <= MID_SCORE_MAX else "high"


def _entry(record, solved_ids, reviews, *, read_only):
    review = reviews.get(record["id"], {})
    score = review.get("score")
    workspace_uuid = record["linked_problem__problem_uuid"]
    return {
        "day_label": record["day_label"],
        "completed": record["id"] in solved_ids,
        "score": score,
        "review_label": (
            f"{score}/7" if score is not None else
            ("Earlier version" if review.get("state") == "earlier" else "No published score")
        ),
        "statement_url": reverse("pages:problem_statement_detail", args=[record["statement_uuid"]]),
        "workspace_url": (
            reverse("solutions:problem_solution_list", args=[workspace_uuid])
            if workspace_uuid and not read_only else ""
        ),
    }


def _heatmap_cell(key, records, solved_ids, reviews, options):
    year, code = key
    label = f"{year} {code}"
    if not records:
        return {"problem_code": code, "state": "empty", "tone": "empty", "title": f"{label}: no statement"}

    entries = [_entry(record, solved_ids, reviews, read_only=options.read_only) for record in records]
    solved = sum(entry["completed"] for entry in entries)
    total = len(entries)
    state = "unsolved" if not solved else ("solved" if solved == total else "partial")
    score = entries[0]["score"] if total == 1 else None

    if total > 1:
        display, tone = f"{solved}/{total}", "multiple"
        title = f"{label}: {solved} of {total} completed; multiple statements"
    else:
        entry = entries[0]
        progress = "completed" if solved else "incomplete"
        day = f" ({entry['day_label']})" if entry["day_label"] else ""
        review_label = f"AI score {score} out of 7" if score is not None else entry["review_label"]
        title = f"{label}{day}: {progress}; {review_label}"
        if options.mode == "score" and score is not None:
            display, tone = score, _score_tone(score)
        else:
            display = "✓" if solved else "·"
            tone = ("complete" if options.mode == "completion" else "unscored") if solved else "incomplete"

    return {
        "problem_code": code, "state": state, "tone": tone, "title": title, "display": display,
        "score": score, "show_completion_mark": options.mode == "score" and score is not None and bool(solved),
        "highlighted": bool(options.focus) and any(
            _matches_focus(entry["completed"], entry["score"], options.focus) for entry in entries
        ),
        "detail_id": f"contest-cell-{records[0]['id']}",
        "entries": entries,
    }


def _matches_focus(completed, score, focus):
    if focus == "low":
        return score is not None and _score_tone(score) == "low"
    return focus == "unscored" and completed and score is None


def contest_completion_heatmap(statements, solved_ids, reviews, contest, options):
    counts = defaultdict(list)
    matching_years = set()
    scores = []
    low_total = unscored_total = 0
    for record in statements:
        record_id = record["id"]
        code, year = record["problem_code"].strip(), record["contest_year"]
        completed = record_id in solved_ids
        score = reviews.get(record_id, {}).get("score")
        if score is not None:
            scores.append(score)
        low_total += _matches_focus(completed, score, "low")
        unscored_total += _matches_focus(completed, score, "unscored")
        if code:
            counts[(year, code)].append(record)
            if not options.focus or _matches_focus(completed, score, options.focus):
                matching_years.add(year)

    codes = sorted({code for _, code in counts}, key=problem_sort_key)
    if contest.casefold() == "imo shortlist":
        group_order = {label: index for index, label in enumerate(SHORTLIST_GROUPS.values())}
        codes.sort(key=lambda code: group_order.get(_group_label(contest, code), len(group_order)))

    paginator = Paginator(sorted(matching_years, reverse=True), YEARS_PER_PAGE)
    try:
        page = paginator.page(options.year_page)
    except InvalidPage:
        page = paginator.page(1)

    rows = [
        {
            "year": year,
            "cells": [
                _heatmap_cell((year, code), counts.get((year, code)), solved_ids, reviews, options)
                for code in codes
            ],
        }
        for year in page
    ]
    return {
        "problem_code_groups": _group_columns(contest, codes),
        "problem_code_total": len(codes),
        "problem_codes": codes,
        "rows": rows,
        "year_total": paginator.count,
        "page_start": page.start_index(),
        "page_end": page.end_index(),
        "page": page,
        "ai_reviewed_total": len(scores),
        "average_ai_score": round(sum(scores) / len(scores), 1) if scores else None,
        "low_score_total": low_total,
        "unscored_completed_total": unscored_total,
    }
