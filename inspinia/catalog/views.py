from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render

from inspinia.backoffice.models import Report
from inspinia.catalog.models import Problem
from inspinia.community.models import Comment
from inspinia.core.permissions import is_moderator
from inspinia.core.permissions import require_learning_state_allowed
from inspinia.progress.models import ProblemProgress


def problem_list_view(request):
    qs = Problem.objects.select_related("contest").prefetch_related("tags").all()
    if not is_moderator(request.user):
        qs = qs.exclude(status=Problem.ProblemStatus.HIDDEN)
    if topic := request.GET.get("topic"):
        qs = qs.filter(tags__slug=topic)
    status = request.GET.get("status")
    if status and request.user.is_authenticated:
        qs = qs.filter(progress_records__user=request.user, progress_records__status=status)
    problems = qs.annotate(solution_count=Count("publicsolution", filter=Q(publicsolution__is_hidden=False), distinct=True))[:300]
    return render(request, "catalog/problem_list.html", {"problems": problems})


def problem_detail_view(request, problem_id: int):
    problem = get_object_or_404(
        Problem.objects.select_related("contest").prefetch_related("tags", "references"),
        id=problem_id,
    )
    if problem.status == Problem.ProblemStatus.HIDDEN and not is_moderator(request.user):
        return render(request, "404.html", status=404)
    comments = Comment.objects.filter(problem_id=problem_id, solution__isnull=True, parent__isnull=True).select_related("author")
    if not is_moderator(request.user):
        if request.user.is_authenticated:
            comments = comments.filter(Q(is_hidden=False) | Q(author=request.user))
        else:
            comments = comments.filter(is_hidden=False)
    return render(request, "catalog/problem_detail.html", {"problem": problem, "comments": comments})


@login_required
def problem_quick_status_partial(request, problem_id: int):
    blocked = require_learning_state_allowed(request.user)
    if blocked:
        return blocked
    progress, _ = ProblemProgress.objects.get_or_create(
        user=request.user,
        problem_id=problem_id,
    )
    next_status = request.POST.get("status", progress.status)
    progress.status = next_status
    progress.save(update_fields=["status", "updated_at"])
    return render(request, "catalog/partials/problem_status_badge.html", {"progress": progress})


@login_required
def report_problem(request, problem_id: int):
    problem = get_object_or_404(Problem, id=problem_id)
    if request.method == "POST":
        try:
            severity = int(request.POST.get("severity", "1"))
        except (TypeError, ValueError):
            severity = 1
        Report.objects.create(
            reporter=request.user,
            content_type=ContentType.objects.get_for_model(Problem),
            object_id=problem.id,
            reason_code=request.POST.get("reason_code", "other"),
            details=request.POST.get("details", ""),
            severity=severity,
        )
    return redirect("catalog:detail", problem_id=problem_id)
