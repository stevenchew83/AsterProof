from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db import OperationalError
from django.db import ProgrammingError
from django.db.models import F
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render

from inspinia.backoffice.models import Report
from inspinia.backoffice.services import get_privacy_defaults
from inspinia.backoffice.services import validate_abuse_policy
from inspinia.core.permissions import is_moderator
from inspinia.core.permissions import require_posting_allowed
from inspinia.core.permissions import require_voting_allowed
from inspinia.community.models import Comment
from inspinia.community.models import PublicSolution
from inspinia.community.models import SolutionVote
from inspinia.community.models import TrustedSuggestion


def _visible_solutions(request, problem_id: int):  # noqa: ANN001
    qs = PublicSolution.objects.filter(problem_id=problem_id).select_related("author")
    if is_moderator(request.user):
        return qs
    if request.user.is_authenticated:
        return qs.filter(Q(is_hidden=False) | Q(author=request.user))
    return qs.filter(is_hidden=False)


def solutions_for_problem(request, problem_id: int):
    solutions = _visible_solutions(request, problem_id)
    comments = Comment.objects.filter(problem_id=problem_id, solution__isnull=True, parent__isnull=True).select_related("author")
    if not is_moderator(request.user):
        if request.user.is_authenticated:
            comments = comments.filter(Q(is_hidden=False) | Q(author=request.user))
        else:
            comments = comments.filter(is_hidden=False)
    return render(
        request,
        "community/solutions.html",
        {"solutions": solutions, "problem_id": problem_id, "comments": comments},
    )


@login_required
def create_solution(request, problem_id: int):
    blocked = require_posting_allowed(request.user)
    if blocked:
        return blocked
    if request.method == "POST":
        content = request.POST.get("content", "")
        policy_error = validate_abuse_policy(request.user, content)
        if policy_error:
            return HttpResponseForbidden(policy_error)
        try:
            privacy_defaults = get_privacy_defaults()
            default_unlisted = privacy_defaults.default_solution_unlisted
        except (OperationalError, ProgrammingError):
            default_unlisted = False
        PublicSolution.objects.create(
            problem_id=problem_id,
            author=request.user,
            title=request.POST.get("title", "Untitled"),
            content=content,
            solution_type=request.POST.get("solution_type", "sketch"),
            is_unlisted=default_unlisted,
            is_hidden=request.user.is_shadow_banned,
        )
    return redirect("community:problem_solutions", problem_id=problem_id)


@login_required
def vote_solution(request, solution_id: int):
    blocked = require_voting_allowed(request.user)
    if blocked:
        return blocked

    solution = get_object_or_404(PublicSolution, id=solution_id)
    if solution.is_hidden and not (is_moderator(request.user) or request.user == solution.author):
        return redirect("community:problem_solutions", problem_id=solution.problem_id)

    vote, created = SolutionVote.objects.get_or_create(solution=solution, user=request.user)
    if not created:
        vote.delete()
        PublicSolution.objects.filter(id=solution_id).update(helpful_count=F("helpful_count") - 1)
    else:
        PublicSolution.objects.filter(id=solution_id).update(helpful_count=F("helpful_count") + 1)
    return redirect("community:problem_solutions", problem_id=solution.problem_id)


@login_required
def add_comment(request, problem_id: int):
    blocked = require_posting_allowed(request.user)
    if blocked:
        return blocked

    if request.method == "POST":
        content = request.POST.get("content", "")
        policy_error = validate_abuse_policy(request.user, content)
        if policy_error:
            return HttpResponseForbidden(policy_error)
        Comment.objects.create(
            problem_id=problem_id,
            author=request.user,
            content=content,
            is_hidden=request.user.is_shadow_banned,
        )
    return redirect("catalog:detail", problem_id=problem_id)


@login_required
def submit_trusted_suggestion(request, problem_id: int):
    blocked = require_posting_allowed(request.user)
    if blocked:
        return blocked
    if not request.user.is_trusted_user:
        return redirect("catalog:detail", problem_id=problem_id)
    if request.method == "POST":
        TrustedSuggestion.objects.create(
            user=request.user,
            problem_id=problem_id,
            suggestion_type=request.POST.get("suggestion_type", "tag"),
            payload=request.POST.get("payload", ""),
        )
    return redirect("catalog:detail", problem_id=problem_id)


@login_required
def report_solution(request, solution_id: int):
    solution = get_object_or_404(PublicSolution, id=solution_id)
    if request.method == "POST":
        try:
            severity = int(request.POST.get("severity", "1"))
        except (TypeError, ValueError):
            severity = 1
        Report.objects.create(
            reporter=request.user,
            content_type=ContentType.objects.get_for_model(PublicSolution),
            object_id=solution.id,
            reason_code=request.POST.get("reason_code", "other"),
            details=request.POST.get("details", ""),
            severity=severity,
        )
    return redirect("community:problem_solutions", problem_id=solution.problem_id)


@login_required
def report_comment(request, comment_id: int):
    comment = get_object_or_404(Comment, id=comment_id)
    if request.method == "POST":
        try:
            severity = int(request.POST.get("severity", "1"))
        except (TypeError, ValueError):
            severity = 1
        Report.objects.create(
            reporter=request.user,
            content_type=ContentType.objects.get_for_model(Comment),
            object_id=comment.id,
            reason_code=request.POST.get("reason_code", "other"),
            details=request.POST.get("details", ""),
            severity=severity,
        )
    redirect_problem_id = comment.problem_id or (comment.solution.problem_id if comment.solution_id else None)
    if redirect_problem_id is None:
        return redirect("catalog:list")
    return redirect("catalog:detail", problem_id=redirect_problem_id)
