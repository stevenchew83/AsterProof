"""Authenticated contest browsing and statement-first contest papers."""

import re
from collections import defaultdict
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.db.models import Max
from django.db.models import Min
from django.db.models import Q
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from inspinia.pages.asymptote_render import build_statement_render_segments
from inspinia.pages.models import ContestMetadata
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.statement_analytics import effective_mohs
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.topic_labels import display_topic_label
from inspinia.solutions.models import ProblemSolution


def _papers_url(**params):
    query = urlencode(params)
    return reverse("pages:contest_papers") + (f"?{query}" if query else "")


def _sequence_key(value):
    return [(0, int(part)) if part.isdecimal() else (1, part.casefold()) for part in re.split(r"(\d+)", value) if part]


def _directory_context(base, params):
    search = str(params.get("q") or "").strip()[:160]
    for term in search.split():
        full_names = ContestMetadata.objects.filter(full_name__icontains=term).values("contest")
        base = base.filter(Q(contest_name__icontains=term) | Q(contest_name__in=full_names))
    contests = (
        base.values("contest_name")
        .annotate(
            problem_count=Count("id"),
            year_count=Count("contest_year", distinct=True),
            first_year=Min("contest_year"),
            last_year=Max("contest_year"),
        )
        .order_by("contest_name")
    )
    page = Paginator(contests, 30).get_page(params.get("page"))
    names = {
        row.contest: row.full_name
        for row in ContestMetadata.objects.filter(
            contest__in=[row["contest_name"] for row in page],
        )
    }
    for row in page:
        row["url"] = _papers_url(contest=row["contest_name"])
        row["full_name"] = names.get(row["contest_name"], "")
    return {"contest_page": page, "search_query": search, "directory_url": _papers_url(q=search)}


def _paper_groups(statements, user):
    started_problems = set(
        ProblemSolution.objects.filter(
            author=user,
            problem_id__in=[row.linked_problem_id for row in statements if row.linked_problem_id],
        ).values_list("problem_id", flat=True),
    )
    groups = defaultdict(list)
    for statement in statements:
        code = statement.problem_code
        number = code[1:] if re.fullmatch(r"P\d+", code) else code
        groups[statement.day_label.strip()].append(
            {
                "statement": statement,
                "heading": f"Problem {number}",
                "segments": build_statement_render_segments(statement.statement_latex),
                "topic": display_topic_label(effective_topic(statement)),
                "mohs": effective_mohs(statement),
                "write_solution_url": reverse("solutions:statement_solution_start", args=[statement.statement_uuid]),
                "write_solution_label": (
                    "Continue solution" if statement.linked_problem_id in started_problems else "Write solution"
                ),
                "solutions_url": (
                    reverse("solutions:problem_solution_list", args=[statement.linked_problem.problem_uuid])
                    if statement.linked_problem is not None and statement.linked_problem.is_active
                    else ""
                ),
            },
        )
    return [
        {
            "label": label or ("Other problems" if len(groups) > 1 else "Problems"),
            "problems": groups[label],
        }
        for label in sorted(groups, key=lambda label: (not bool(label), _sequence_key(label)))
    ]


@login_required
@never_cache
def contest_papers_view(request):
    base = ContestProblemStatement.objects.filter(is_active=True)
    contest = (request.GET.get("contest") or "").strip()
    year = (request.GET.get("year") or "").strip()
    context = {"browser_url": _papers_url(), "selected_contest": contest, "selected_year": year}
    if not contest:
        if year:
            message = "Select a contest first."
            raise Http404(message)
        context.update(_directory_context(base, request.GET))
    else:
        contest_base = base.filter(contest_name=contest)
        years = list(
            contest_base.values("contest_year").annotate(problem_count=Count("id")).order_by("-contest_year"),
        )
        if not years:
            message = "Contest not found."
            raise Http404(message)
        for row in years:
            row["url"] = _papers_url(contest=contest, year=row["contest_year"])
        context.update({"year_rows": years, "contest_url": _papers_url(contest=contest)})
        if year:
            if not re.fullmatch(r"[0-9]{1,4}", year) or int(year) not in {row["contest_year"] for row in years}:
                message = "Contest paper not found."
                raise Http404(message)
            statements = list(contest_base.filter(contest_year=int(year)).select_related("linked_problem"))
            statements.sort(key=lambda row: (row.problem_number, _sequence_key(row.problem_code), row.pk))
            groups = _paper_groups(statements, request.user)
            context.update(
                {
                    "selected_year": str(int(year)),
                    "paper_title": f"{contest} {int(year)}",
                    "paper_groups": groups,
                    "paper_section_count": len(groups),
                    "paper_problem_count": len(statements),
                },
            )
    return render(request, "pages/contest-papers.html", context)
