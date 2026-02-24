from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.http import HttpResponseNotFound
from django.shortcuts import redirect
from django.shortcuts import render

from inspinia.backoffice.models import ProblemRequest
from inspinia.backoffice.models import ProblemSubmission
from inspinia.backoffice.services import get_effective_feature_flags
from inspinia.backoffice.services import validate_abuse_policy
from inspinia.core.permissions import require_posting_allowed
from .models import FeedbackItem


def feedback_board(request):
    if not get_effective_feature_flags().get("feedback_hub", True):
        return HttpResponseNotFound("Feedback hub is disabled.")
    items = FeedbackItem.objects.all()[:200]
    return render(request, "feedback/board.html", {"items": items})


@login_required
def my_feedback(request):
    if not get_effective_feature_flags().get("feedback_hub", True):
        return HttpResponseNotFound("Feedback hub is disabled.")
    items = FeedbackItem.objects.filter(author=request.user)
    return render(request, "feedback/my_feedback.html", {"items": items})


@login_required
def create_feedback(request):
    if not get_effective_feature_flags().get("feedback_hub", True):
        return HttpResponseNotFound("Feedback hub is disabled.")
    blocked = require_posting_allowed(request.user)
    if blocked:
        return blocked
    if request.method == "POST":
        description = request.POST.get("description", "")
        policy_error = validate_abuse_policy(request.user, description)
        if policy_error:
            return HttpResponseForbidden(policy_error)
        feedback_type = request.POST.get("feedback_type", "feature")
        FeedbackItem.objects.create(
            author=request.user,
            feedback_type=feedback_type,
            title=request.POST.get("title", ""),
            description=description,
        )
        if feedback_type == "problem_request":
            ProblemRequest.objects.create(
                requester=request.user,
                requested_contest=request.POST.get("title", ""),
                details=description,
                source_url=request.POST.get("source_url", ""),
                suggested_tags=request.POST.get("suggested_tags", ""),
                suggested_difficulty=int(request.POST.get("suggested_difficulty", "3") or 3),
            )
    return redirect("feedback:board")


@login_required
def create_problem_submission(request):
    if not get_effective_feature_flags().get("feedback_hub", True):
        return HttpResponseNotFound("Feedback hub is disabled.")
    blocked = require_posting_allowed(request.user)
    if blocked:
        return blocked
    if request.method == "POST":
        statement = request.POST.get("statement", "")
        policy_error = validate_abuse_policy(request.user, statement)
        if policy_error:
            return HttpResponseForbidden(policy_error)
        ProblemSubmission.objects.create(
            submitter=request.user,
            title=request.POST.get("title", ""),
            statement=statement,
            source_reference=request.POST.get("source_reference", ""),
            proposed_tags=request.POST.get("proposed_tags", ""),
            proposed_difficulty=int(request.POST.get("proposed_difficulty", "3") or 3),
        )
    return redirect("feedback:mine")
