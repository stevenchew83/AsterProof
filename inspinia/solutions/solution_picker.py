"""Statement-first solution picker, separate from the frozen document reader."""

from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from inspinia.pages.contest_links import contest_dashboard_listing_url
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.statement_analytics import effective_mohs
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.topic_labels import display_topic_label
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.views import STATEMENT_BACKED_PROBLEM_LIST_LIMIT
from inspinia.solutions.views import _build_contest_slug_maps
from inspinia.solutions.views import _problem_anchor
from inspinia.solutions.views import _solution_status_badge
from inspinia.solutions.views import _statement_preview_text
from inspinia.solutions.writer_drafts import get_writer_draft


def _statement_backed_problem_rows(user) -> tuple[list[dict], dict[str, bool | int]]:
    statements = list(
        ContestProblemStatement.objects.filter(is_active=True)
        .select_related("linked_problem")
        .order_by("-updated_at", "-id")[:STATEMENT_BACKED_PROBLEM_LIST_LIMIT + 1],
    )
    list_is_capped = len(statements) > STATEMENT_BACKED_PROBLEM_LIST_LIMIT
    statements = statements[:STATEMENT_BACKED_PROBLEM_LIST_LIMIT]
    problem_ids = [statement.linked_problem_id for statement in statements if statement.linked_problem_id is not None]
    solution_status_by_problem_id = {
        row["problem_id"]: row["status"]
        for row in ProblemSolution.objects.filter(
            author=user,
            problem_id__in=problem_ids,
        ).values("problem_id", "status")
    }
    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(
        [statement.contest_name for statement in statements],
    )

    rows: list[dict] = []
    for statement in sorted(
        statements,
        key=lambda row: (
            -int(row.contest_year),
            row.contest_name,
            row.problem_code,
        ),
    ):
        problem = statement.linked_problem
        problem_label = statement.contest_year_problem
        solution_status = solution_status_by_problem_id.get(statement.linked_problem_id, "")
        contest_slug = contest_to_slug.get(statement.contest_name)
        contest_archive_url = ""
        if contest_slug:
            contest_archive_url = contest_dashboard_listing_url(
                statement.contest_name,
                year=int(statement.contest_year),
            ) + "#" + _problem_anchor(
                problem_label,
                f"statement-{statement.id}",
            )

        rows.append(
            {
                "contest_archive_url": contest_archive_url,
                "editor_button_label": "Continue solution" if solution_status else "Start solution",
                "editor_url": (
                    reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]) if problem else ""
                ),
                "solution_start_url": (
                    reverse("solutions:statement_solution_start", args=[statement.statement_uuid])
                    if not problem else ""
                ),
                "has_solution": bool(solution_status),
                "problem_label": problem_label,
                "problem_topic": display_topic_label(effective_topic(statement)),
                "problem_mohs": effective_mohs(statement),
                "problem_url": (
                    reverse("solutions:problem_solution_list", args=[problem.problem_uuid]) if problem else ""
                ),
                "solution_status_badge_class": (
                    _solution_status_badge(solution_status) if solution_status else "text-bg-light"
                ),
                "solution_status_label": (
                    ProblemSolution.Status(solution_status).label if solution_status else "Not started"
                ),
                "statement_label": (
                    f"{statement.problem_code} · {statement.day_label}"
                    if statement.day_label
                    else statement.problem_code
                ),
                "statement_preview": _statement_preview_text(statement.statement_latex),
                "statement_updated_at_label": timezone.localtime(statement.updated_at).strftime("%Y-%m-%d"),
            },
        )

    return rows, {
        "is_capped": list_is_capped,
        "limit": STATEMENT_BACKED_PROBLEM_LIST_LIMIT,
    }



@login_required
@never_cache
def problem_solution_create_view(request):
    statement_problem_rows, statement_problem_list_meta = _statement_backed_problem_rows(request.user)
    writer_draft = get_writer_draft(request) if request.GET.get("from_writer") == "1" else None
    if writer_draft:
        for row in statement_problem_rows:
            if not row["has_solution"]:
                if row["editor_url"]:
                    row["editor_url"] += "?" + urlencode({"from_writer": writer_draft["token"]})
                row["editor_button_label"] = "Continue with this problem"
    started_total = sum(1 for row in statement_problem_rows if row["has_solution"])
    context = {
        "create_stats": {
            "ready_total": len(statement_problem_rows) - started_total,
            "started_total": started_total,
            "statement_problem_total": len(statement_problem_rows),
        },
        "statement_problem_list_is_capped": statement_problem_list_meta["is_capped"],
        "statement_problem_list_limit": statement_problem_list_meta["limit"],
        "statement_problem_rows": statement_problem_rows,
        "writer_draft": writer_draft,
    }
    return render(request, "solutions/problem-solution-create.html", context)
