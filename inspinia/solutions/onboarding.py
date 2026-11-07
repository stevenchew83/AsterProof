"""Choose a starting point and resume the author's saved work."""

from django.db.models import Case
from django.db.models import F
from django.db.models import Q
from django.db.models import When
from django.db.models.functions import Coalesce
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.solutions.models import ProblemSolution
from inspinia.users.models import User


def _starter_problem_url():
    # IMO 1959 P1 can be started by testing small cases and looking for common divisors.
    # Fall back to the lowest available catalogue difficulty.
    problem_uuid = ContestProblemStatement.objects.filter(
        is_active=True, linked_problem__is_active=True, statement_latex__regex=r"\S",
    ).order_by(
        Case(When(contest_name__iexact="IMO", contest_year=1959, problem_code="P1", then=0), default=1),
        Coalesce("mohs", "linked_problem__mohs").asc(nulls_last=True),
        F("contest_year").desc(), "pk",
    ).values_list("linked_problem__problem_uuid", flat=True).first()
    return reverse("solutions:problem_solution_edit", args=[problem_uuid]) if problem_uuid else ""


def needs_private_first_save(user, solution, saved_source):
    return (
        user.solution_guide_status == User.SolutionGuideStatus.ACTIVE
        and solution.status == ProblemSolution.Status.DRAFT
        and not saved_source.strip()
        and not ProblemSolution.objects.filter(author=user).filter(
            Q(current_revision__body_source__regex=r"\S")
            | Q(current_revision__isnull=True, blocks__isnull=False)
            | Q(public_share__is_active=True),
        ).exists()
    )


def solution_guide_context(user, solutions, *, writer_draft):
    visible = user.solution_guide_status == User.SolutionGuideStatus.ACTIVE
    shared = next((solution for solution in solutions if solution.public_share_count), None)
    # An image upload can create an empty placeholder. Prefer a draft with writing.
    saved = next((solution for solution in solutions if solution.block_count), None)
    draft = next((
        solution for solution in solutions
        if solution.status == ProblemSolution.Status.DRAFT and solution.block_count and not solution.public_share_count
    ), None)
    current = draft or shared or saved or next(iter(solutions), None)
    is_shared = bool(current and current.public_share_count)
    has_saved_content = bool(current and (current.block_count or is_shared))
    create_url = reverse("solutions:problem_solution_create")
    if writer_draft:
        from inspinia.solutions.writer_drafts import writer_handoff_url

        create_url = writer_handoff_url()
    editor_url = reverse("solutions:problem_solution_edit", args=[current.problem.problem_uuid]) if current else ""
    share_url = reverse("solutions:problem_solution_share", args=[current.problem.problem_uuid]) if current else ""
    problem_label = (
        current.problem.contest_year_problem
        or f"{current.problem.contest} {current.problem.year} {current.problem.problem}"
    ) if current else ""
    return {
        "visible": visible,
        "chosen": bool(current),
        "saved": has_saved_content,
        "shared": is_shared,
        "private_draft": bool(current and current.status == ProblemSolution.Status.DRAFT and not is_shared),
        "completed_steps": int(bool(current)) + int(has_saved_content),
        "solution_title": (current.title.strip() or problem_label) if current else "",
        "problem_label": problem_label,
        "start_url": create_url,
        "starter_url": _starter_problem_url() if visible and not current and not writer_draft else "",
        "editor_url": editor_url,
        "share_url": share_url,
    }
