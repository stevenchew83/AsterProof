import re
from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from inspinia.pages.asymptote_render import build_statement_render_segments
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.topic_labels import display_topic_label
from inspinia.solutions.forms import ProblemSolutionBlockFormSet
from inspinia.solutions.forms import ProblemSolutionForm
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.users.roles import user_has_admin_role


def _build_contest_slug_maps(contest_names: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    contest_to_slug: dict[str, str] = {}
    slug_to_contest: dict[str, str] = {}

    for contest_name in sorted({name for name in contest_names if name}):
        base_slug = slugify(contest_name) or "contest"
        contest_slug = base_slug
        suffix = 2
        while contest_slug in slug_to_contest:
            contest_slug = f"{base_slug}-{suffix}"
            suffix += 1
        contest_to_slug[contest_name] = contest_slug
        slug_to_contest[contest_slug] = contest_name

    return contest_to_slug, slug_to_contest


def _problem_anchor(problem_label: str, fallback: str) -> str:
    return slugify(problem_label) or slugify(fallback) or "problem"


def _problem_solution_prefetch():
    return Prefetch(
        "blocks",
        queryset=ProblemSolutionBlock.objects.select_related("block_type").order_by("position", "id"),
    )


def _problem_context(problem: ProblemSolveRecord) -> dict:
    # Distinct active contests only — avoid scanning every ProblemSolveRecord row
    # (matches pages.contest_problem_list_view slug generation).
    contest_names = list(
        ProblemSolveRecord.objects.filter(is_active=True)
        .values_list("contest", flat=True)
        .distinct(),
    )
    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(contest_names)
    problem_label = problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"
    contest_slug = contest_to_slug.get(problem.contest)
    contest_url = ""
    if contest_slug is not None:
        contest_url = reverse("pages:contest_problem_list", args=[contest_slug])

    statement_entry = (
        ContestProblemStatement.objects.filter(linked_problem=problem)
        .order_by("-updated_at", "-id")
        .first()
    )
    return {
        "contest_archive_url": contest_url,
        "editor_url": reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]),
        "problem": problem,
        "problem_anchor": _problem_anchor(problem_label, f"{problem.year}-{problem.problem}"),
        "problem_label": problem_label,
        "solutions_url": reverse("solutions:problem_solution_list", args=[problem.problem_uuid]),
        "statement_entry": statement_entry,
        "statement_render_segments": (
            build_statement_render_segments(statement_entry.statement_latex) if statement_entry else []
        ),
    }


def _solution_status_badge(status: str) -> str:
    return {
        ProblemSolution.Status.ARCHIVED: "text-bg-secondary",
        ProblemSolution.Status.DRAFT: "text-bg-warning",
        ProblemSolution.Status.PUBLISHED: "text-bg-success",
        ProblemSolution.Status.SUBMITTED: "text-bg-info",
    }.get(status, "text-bg-light")


def _solution_card_rows(solutions: list[ProblemSolution]) -> list[dict]:
    return [
        {
            "author_label": solution.author.name or solution.author.email,
            "blocks": list(solution.blocks.all()),
            "edit_url": reverse("solutions:problem_solution_edit", args=[solution.problem.problem_uuid]),
            "id": solution.id,
            "is_published": solution.status == ProblemSolution.Status.PUBLISHED,
            "problem_label": (
                solution.problem.contest_year_problem
                or f"{solution.problem.contest} {solution.problem.year} {solution.problem.problem}"
            ),
            "problem_url": reverse("solutions:problem_solution_list", args=[solution.problem.problem_uuid]),
            "status": solution.status,
            "status_badge_class": _solution_status_badge(solution.status),
            "status_label": solution.get_status_display(),
            "summary": solution.summary,
            "title": solution.title or "Untitled solution",
            "updated_at_label": timezone.localtime(solution.updated_at).strftime("%Y-%m-%d %H:%M"),
        }
        for solution in solutions
    ]


def _statement_preview_text(statement_latex: str, *, max_length: int = 220) -> str:
    collapsed = re.sub(r"\s+", " ", (statement_latex or "").strip())
    if len(collapsed) <= max_length:
        return collapsed
    return f"{collapsed[: max_length - 1].rstrip()}…"


def _statement_backed_problem_rows(user) -> list[dict]:
    latest_statement_by_problem_id: dict[int, ContestProblemStatement] = {}
    for statement in (
        ContestProblemStatement.objects.filter(linked_problem__isnull=False)
        .select_related("linked_problem")
        .order_by("-updated_at", "-id")
    ):
        if statement.linked_problem_id in latest_statement_by_problem_id:
            continue
        latest_statement_by_problem_id[statement.linked_problem_id] = statement

    if not latest_statement_by_problem_id:
        return []

    statements = list(latest_statement_by_problem_id.values())
    problem_ids = [statement.linked_problem_id for statement in statements if statement.linked_problem_id is not None]
    solution_status_by_problem_id = {
        row["problem_id"]: row["status"]
        for row in ProblemSolution.objects.filter(
            author=user,
            problem_id__in=problem_ids,
        ).values("problem_id", "status")
    }
    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(
        [statement.linked_problem.contest for statement in statements if statement.linked_problem is not None],
    )

    rows: list[dict] = []
    for statement in sorted(
        statements,
        key=lambda row: (
            -int(row.linked_problem.year),
            row.linked_problem.contest,
            row.linked_problem.problem,
            row.problem_code,
        ),
    ):
        problem = statement.linked_problem
        if problem is None:
            continue

        problem_label = problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"
        solution_status = solution_status_by_problem_id.get(problem.id, "")
        contest_slug = contest_to_slug.get(problem.contest)
        contest_archive_url = ""
        if contest_slug:
            contest_archive_url = reverse("pages:contest_problem_list", args=[contest_slug]) + "#" + _problem_anchor(
                problem_label,
                f"{problem.year}-{problem.problem}",
            )

        rows.append(
            {
                "contest_archive_url": contest_archive_url,
                "editor_button_label": "Continue solution" if solution_status else "Start solution",
                "editor_url": reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]),
                "has_solution": bool(solution_status),
                "problem_label": problem_label,
                "problem_topic": display_topic_label(problem.topic),
                "problem_mohs": problem.mohs,
                "problem_url": reverse("solutions:problem_solution_list", args=[problem.problem_uuid]),
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

    return rows


def _save_solution_blocks(formset, solution: ProblemSolution) -> None:
    ordered_forms = [
        form
        for form in formset.ordered_forms
        if getattr(form, "cleaned_data", None) and not form.cleaned_data.get("DELETE")
    ]
    deleted_blocks = [
        form.instance
        for form in formset.forms
        if getattr(form, "cleaned_data", None) and form.cleaned_data.get("DELETE") and form.instance.pk
    ]
    existing_blocks = [form.instance for form in ordered_forms if form.instance.pk]
    if existing_blocks:
        max_position = solution.blocks.aggregate(max_position=Max("position"))["max_position"] or 0
        temp_base = max_position + len(existing_blocks) + 1000
        for offset, block in enumerate(existing_blocks, start=1):
            block.position = temp_base + offset
        ProblemSolutionBlock.objects.bulk_update(existing_blocks, ["position"])

    for deleted_block in deleted_blocks:
        deleted_block.delete()

    for position, form in enumerate(ordered_forms, start=1):
        block = form.save(commit=False)
        block.solution = solution
        block.parent_block = None
        block.position = position
        block.save()


def _apply_editor_action(solution: ProblemSolution, action: str) -> tuple[str, str]:
    now = timezone.now()
    if action == "publish":
        solution.status = ProblemSolution.Status.PUBLISHED
        solution.published_at = now
        if solution.submitted_at is None:
            solution.submitted_at = now
        return "Published solution.", "success"
    if action == "save_draft":
        solution.status = ProblemSolution.Status.DRAFT
        solution.published_at = None
        solution.submitted_at = None
        return "Saved draft.", "success"
    if not solution.status:
        solution.status = ProblemSolution.Status.DRAFT
    return "Saved changes.", "success"


@login_required
def my_solution_list_view(request):
    solutions = list(
        ProblemSolution.objects.filter(author=request.user)
        .select_related("problem", "author")
        .prefetch_related(_problem_solution_prefetch())
        .order_by("-updated_at", "-id"),
    )
    status_counts = Counter(solution.status for solution in solutions)
    context = {
        "my_solution_rows": _solution_card_rows(solutions),
        "my_solution_stats": {
            "draft_total": status_counts[ProblemSolution.Status.DRAFT],
            "published_total": status_counts[ProblemSolution.Status.PUBLISHED],
            "submitted_total": status_counts[ProblemSolution.Status.SUBMITTED],
            "total": len(solutions),
        },
    }
    return render(request, "solutions/my-solution-list.html", context)


@login_required
def problem_solution_create_view(request):
    statement_problem_rows = _statement_backed_problem_rows(request.user)
    started_total = sum(1 for row in statement_problem_rows if row["has_solution"])
    context = {
        "create_stats": {
            "ready_total": len(statement_problem_rows) - started_total,
            "started_total": started_total,
            "statement_problem_total": len(statement_problem_rows),
        },
        "statement_problem_rows": statement_problem_rows,
    }
    return render(request, "solutions/problem-solution-create.html", context)


@login_required
def problem_solution_list_view(request, problem_uuid):
    problem = get_object_or_404(ProblemSolveRecord, problem_uuid=problem_uuid)
    problem_data = _problem_context(problem)
    solution_queryset = (
        ProblemSolution.objects.filter(problem=problem)
        .select_related("author", "problem")
        .prefetch_related(_problem_solution_prefetch())
    )
    selected_solution = None
    selected_solution_value = (request.GET.get("solution") or "").strip()
    if selected_solution_value.isdigit():
        selected_solution = solution_queryset.filter(pk=int(selected_solution_value)).first()
    admin_view = user_has_admin_role(request.user)
    my_solution = solution_queryset.filter(author=request.user).first()
    if admin_view:
        visible_solutions = list(
            solution_queryset.order_by("-published_at", "-updated_at", "-id"),
        )
        visible_solution_rows = _solution_card_rows(visible_solutions)
        visible_solution_title = "All user solutions"
        visible_solution_empty_message = "No saved solutions are available for this problem yet."
    else:
        visible_solutions = list(
            solution_queryset.filter(status=ProblemSolution.Status.PUBLISHED)
            .exclude(author=request.user)
            .order_by("-published_at", "-updated_at", "-id"),
        )
        visible_solution_rows = _solution_card_rows(visible_solutions)
        visible_solution_title = "Published solutions"
        visible_solution_empty_message = "No other published solutions are available for this problem yet."
    published_total = solution_queryset.filter(status=ProblemSolution.Status.PUBLISHED).count()
    context = {
        "admin_view": admin_view,
        "my_solution_row": _solution_card_rows([my_solution])[0] if my_solution is not None else None,
        "problem_data": problem_data,
        "selected_solution_id": selected_solution.id if selected_solution is not None else None,
        "visible_solution_empty_message": visible_solution_empty_message,
        "visible_solution_rows": visible_solution_rows,
        "visible_solution_title": visible_solution_title,
        "solution_stats": {
            "published_total": published_total,
            "visible_total": len(visible_solutions) + (0 if admin_view else (1 if my_solution is not None else 0)),
        },
    }
    return render(request, "solutions/problem-solution-list.html", context)


@login_required
def problem_solution_edit_view(request, problem_uuid):
    problem = get_object_or_404(ProblemSolveRecord, problem_uuid=problem_uuid)
    solution = ProblemSolution.objects.filter(problem=problem, author=request.user).first()
    if solution is None:
        solution = ProblemSolution(problem=problem, author=request.user, status=ProblemSolution.Status.DRAFT)

    form = ProblemSolutionForm(request.POST or None, instance=solution, prefix="solution")
    formset = ProblemSolutionBlockFormSet(request.POST or None, instance=solution, prefix="blocks")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        action = request.POST.get("action") or "save"
        with transaction.atomic():
            solution = form.save(commit=False)
            solution.problem = problem
            solution.author = request.user
            message_text, message_level = _apply_editor_action(solution, action)
            solution.save()
            formset.instance = solution
            _save_solution_blocks(formset, solution)
        getattr(messages, message_level)(request, message_text)
        return redirect("solutions:problem_solution_edit", problem.problem_uuid)

    current_status = solution.status or ProblemSolution.Status.DRAFT
    problem_data = _problem_context(problem)
    context = {
        "form": form,
        "formset": formset,
        "problem_data": problem_data,
        "solution_status_badge_class": _solution_status_badge(current_status),
        "solution_status_label": ProblemSolution.Status(current_status).label,
    }
    return render(request, "solutions/problem-solution-editor.html", context)
