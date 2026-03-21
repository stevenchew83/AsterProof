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
from inspinia.solutions.forms import ProblemSolutionBlockFormSet
from inspinia.solutions.forms import ProblemSolutionForm
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock


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
    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(
        list(ProblemSolveRecord.objects.values_list("contest", flat=True)),
    )
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
def problem_solution_list_view(request, problem_uuid):
    problem = get_object_or_404(ProblemSolveRecord, problem_uuid=problem_uuid)
    problem_data = _problem_context(problem)
    solution_queryset = (
        ProblemSolution.objects.filter(problem=problem)
        .select_related("author", "problem")
        .prefetch_related(_problem_solution_prefetch())
    )
    my_solution = solution_queryset.filter(author=request.user).first()
    published_solutions = list(
        solution_queryset.filter(status=ProblemSolution.Status.PUBLISHED)
        .exclude(author=request.user)
        .order_by("-published_at", "-updated_at", "-id"),
    )
    published_total = solution_queryset.filter(status=ProblemSolution.Status.PUBLISHED).count()
    context = {
        "my_solution_row": _solution_card_rows([my_solution])[0] if my_solution is not None else None,
        "problem_data": problem_data,
        "published_solution_rows": _solution_card_rows(published_solutions),
        "solution_stats": {
            "published_total": published_total,
            "visible_total": len(published_solutions) + (1 if my_solution is not None else 0),
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
