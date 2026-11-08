"""Solution selection from the shared library, separate from the frozen reader."""

from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.shared_library import library_rows
from inspinia.pages.shared_library import library_sources
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.views import STATEMENT_BACKED_PROBLEM_LIST_LIMIT
from inspinia.solutions.views import _solution_status_badge
from inspinia.solutions.views import _statement_preview_text
from inspinia.solutions.writer_drafts import get_writer_draft


def _statement_backed_problem_rows(user) -> tuple[list[dict], dict[str, bool | int]]:
    statements, problems = library_sources(active_only=True)
    candidates = library_rows(
        statements, problems, viewer=user, progress_user=user, limit=STATEMENT_BACKED_PROBLEM_LIST_LIMIT + 1,
    )
    capped = len(candidates) > STATEMENT_BACKED_PROBLEM_LIST_LIMIT
    candidates = candidates[:STATEMENT_BACKED_PROBLEM_LIST_LIMIT]
    statuses = {
        str(row["problem__problem_uuid"]): row["status"]
        for row in ProblemSolution.objects.filter(
            author=user, problem__problem_uuid__in=[row["problem_uuid"] for row in candidates],
        ).values("problem__problem_uuid", "status")
    }
    texts = dict(ContestProblemStatement.objects.filter(
        statement_uuid__in=[row["statement_uuid"] for row in candidates if row["statement_uuid"]],
    ).values_list("statement_uuid", "statement_latex"))
    texts = {str(key): value for key, value in texts.items()}
    rows = []
    for row in sorted(candidates, key=lambda row: (-row["contest_year"], row["contest_name"], row["problem_code"])):
        status = statuses.get(row["problem_uuid"], "")
        can_start = bool(row["solution_start_url"])
        rows.append({
            "contest_archive_url": (
                reverse("pages:problem_statement_list") + "?" + urlencode({"q": row["problem_uuid"]})
            ),
            "editor_button_label": "Continue solution" if status else "Start solution",
            "editor_url": (
                "" if can_start else reverse("solutions:problem_solution_edit", args=[row["problem_uuid"]])
            ),
            "solution_start_url": row["solution_start_url"],
            "has_solution": bool(status), "has_statement": row["has_statement"],
            "problem_label": row["contest_year_problem"],
            "problem_topic": row["linked_problem_topic"], "problem_mohs": row["linked_problem_mohs"],
            "problem_url": "" if can_start else reverse("solutions:problem_solution_list", args=[row["problem_uuid"]]),
            "solution_status_badge_class": _solution_status_badge(status) if status else "text-bg-light",
            "solution_status_label": ProblemSolution.Status(status).label if status else "Not started",
            "statement_label": row["problem_code"] if row["has_statement"] else "Statement missing",
            "statement_preview": (
                _statement_preview_text(texts.get(row["statement_uuid"], "")) if row["has_statement"]
                else "A statement has not been uploaded yet. Existing progress and solutions are retained."
            ),
            "statement_updated_at_label": row["updated_at"].split(" ")[0],
        })
    return rows, {"is_capped": capped, "limit": STATEMENT_BACKED_PROBLEM_LIST_LIMIT}


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
