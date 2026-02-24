from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render

from inspinia.backoffice.services import apply_rating_run
from inspinia.backoffice.services import get_effective_feature_flags
from inspinia.backoffice.services import validate_abuse_policy
from inspinia.core.permissions import admin_required
from inspinia.core.permissions import require_posting_allowed
from .models import ContestEvent
from .models import ContestRegistration
from .models import ContestVisibility
from .models import ScoreEntry
from .models import Submission
def contest_list(request):
    flags = get_effective_feature_flags()
    if not flags.get("contests", True):
        return HttpResponseNotFound("Contests are disabled.")
    contests = ContestEvent.objects.order_by("start_time")
    if not request.user.is_staff:
        contests = contests.filter(visibility_state=ContestVisibility.PUBLIC)
    return render(request, "contests/list.html", {"contests": contests})


def contest_detail(request, contest_id: int):
    flags = get_effective_feature_flags()
    if not flags.get("contests", True):
        return HttpResponseNotFound("Contests are disabled.")
    contest = get_object_or_404(ContestEvent, id=contest_id)
    if contest.visibility_state != ContestVisibility.PUBLIC and not request.user.is_staff:
        return HttpResponseForbidden("Contest not visible.")
    return render(request, "contests/detail.html", {"contest": contest})


@login_required
def register_contest(request, contest_id: int):
    flags = get_effective_feature_flags()
    if not flags.get("contests", True):
        return HttpResponseNotFound("Contests are disabled.")
    ContestRegistration.objects.get_or_create(user=request.user, contest_id=contest_id)
    return redirect("contests:detail", contest_id=contest_id)


@login_required
def submit_solution(request, contest_id: int, problem_id: int):
    flags = get_effective_feature_flags()
    if not flags.get("contests", True):
        return HttpResponseNotFound("Contests are disabled.")
    blocked = require_posting_allowed(request.user)
    if blocked:
        return blocked
    if request.method == "POST":
        content = request.POST.get("content", "")
        policy_error = validate_abuse_policy(request.user, content)
        if policy_error:
            return HttpResponseForbidden(policy_error)
        Submission.objects.create(
            user=request.user,
            contest_id=contest_id,
            problem_id=problem_id,
            content=content,
            pdf=request.FILES.get("pdf"),
        )
    return redirect("contests:detail", contest_id=contest_id)


def scoreboard(request, contest_id: int):
    flags = get_effective_feature_flags()
    if not flags.get("contests", True):
        return HttpResponseNotFound("Contests are disabled.")
    rows = ScoreEntry.objects.filter(contest_id=contest_id).select_related("user").order_by("rank")
    return render(request, "contests/scoreboard.html", {"rows": rows, "contest_id": contest_id})


@admin_required
def run_rating_update(request, contest_id: int):
    flags = get_effective_feature_flags()
    if not flags.get("ratings", True):
        return HttpResponseNotFound("Ratings are disabled.")
    contest = get_object_or_404(ContestEvent, id=contest_id)
    apply_rating_run(contest=contest, triggered_by=request.user)
    return redirect("contests:scoreboard", contest_id=contest_id)
