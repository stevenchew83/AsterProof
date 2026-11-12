"""Authenticated readers and HTML actions for member-published proofs."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count
from django.db.models import Exists
from django.db.models import OuterRef
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from inspinia.inline_actions import inline_action_fragment
from inspinia.inline_actions import inline_action_response
from inspinia.inline_actions import wants_inline_action
from inspinia.training.markdown import render_markdown
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.roles import user_has_admin_role
from inspinia.users.roles import user_has_trainer_or_admin_role

from . import admin_review_views
from . import forum
from .forum_access import visible_solutions
from .forum_forms import AssessmentForm
from .forum_forms import CommentForm
from .forum_forms import VerificationForm
from .forum_models import SolutionComment
from .forum_models import SolutionCommentEvent
from .forum_models import SolutionForumReport
from .forum_models import SolutionForumTarget
from .forum_models import SolutionUpvote
from .image_access import internal_image_base_url
from .models import ProblemSolution
from .views import _problem_context
from .views import _solution_card_rows

PAGE_SIZE = 20
MAX_POST_BYTES = 80_000


def _private(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Referrer-Policy"] = "same-origin"
    return response


def _solution(request, solution_pk):
    return get_object_or_404(
        visible_solutions(request.user).select_related("author", "problem", "current_revision"),
        pk=solution_pk,
    )


def _page(queryset, request, name="page"):
    return Paginator(queryset, PAGE_SIZE).get_page(request.GET.get(name))


def _with_edit_marker(queryset):
    return queryset.annotate(was_edited=Exists(SolutionCommentEvent.objects.filter(
        comment_id=OuterRef("pk"), action="edit_comment",
    )))


def _comment_row(comment, user):
    visible = comment.state == "visible"
    return {
        "comment": comment,
        "body": render_markdown(comment.body) if visible else "",
        "can_edit": visible and comment.author_id == user.pk,
        "can_moderate": user_has_admin_role(user) and comment.state != "removed",
        "can_reply": visible and comment.parent_id is None,
        "can_report": visible,
    }


def _vote_context(solution, user):
    votes = SolutionUpvote.objects.filter(solution=solution)
    return {
        "vote_count": votes.count(),
        "has_upvoted": votes.filter(user=user).exists(),
    }


def _detail_context(request, solution, *, posted_action="", posted_data=None, error=""):
    state = forum.summary(solution)
    target = forum.current_target_data(solution)
    own = next((row for row in state["assessments"] if row.reviewer_id == request.user.pk), None)
    decision = state.get("decision")
    published = solution.status == ProblemSolution.Status.PUBLISHED
    author = solution.author_id == request.user.pk
    admin = user_has_admin_role(request.user)
    can_assess = published and not author and user_has_trainer_or_admin_role(request.user)
    comments = _page(
        _with_edit_marker(SolutionComment.objects.filter(solution=solution, parent__isnull=True))
        .select_related("author").annotate(reply_count=Count("replies")).order_by("created_at", "pk"),
        request,
        "comments_page",
    )
    assessment_initial = {
        "target_key": target["key"],
        "assessment_head": str(own.pk) if own else "",
        "verdict": own.verdict if own else "correct",
        "feedback": own.feedback if own else "",
        "gaps": own.gaps if own else "",
        "next_steps": own.next_steps if own else "",
    }
    verification_initial = {
        "target_key": target["key"],
        "decision_head": str(decision.pk) if decision else "",
        "assessment_basis": ",".join(str(row.pk) for row in sorted(state["assessments"], key=lambda row: row.pk)),
        "verdict": "correct",
    }
    assessments = [{
        "assessment": row,
        "feedback": render_markdown(row.feedback),
        "gaps": render_markdown(row.gaps),
        "next_steps": render_markdown(row.next_steps),
    } for row in state["assessments"]]
    form_data = posted_data if posted_action == "assess" else None
    verification_data = posted_data if posted_action in {"verify", "adjudicate", "revoke"} else None
    comment_data = posted_data if posted_action in {"comment", "edit_comment"} else None
    text_fields = {
        "body": "Your unsaved comment", "reason": "Your unsaved explanation", "resolution": "Your unsaved resolution",
        "feedback": "Your unsaved feedback", "gaps": "Your unsaved gaps or errors",
        "next_steps": "Your unsaved next steps",
    }
    retry_fields = [{
        "name": name, "value": value, "label": text_fields.get(name),
    } for name, value in (posted_data or {}).items() if name in {
        *text_fields, "target_key", "assessment_head", "decision_head", "assessment_basis", "verdict", "active",
        "parent_id", "comment_id", "version", "report_id",
    }]
    return {
        "solution": solution,
        "solution_row": _solution_card_rows([solution])[0],
        "problem_data": _problem_context(solution.problem),
        "forum_summary": state,
        "ai_reviews": admin_review_views.review_context(request, solution, target),
        "current_target": target,
        "is_author": author,
        "is_forum_admin": admin,
        "is_member_published": published,
        "can_assess": can_assess,
        "can_verify": published and admin and not author,
        "can_vote": published and not author,
        "can_discuss": published,
        **_vote_context(solution, request.user),
        "assessment_rows": assessments,
        "decision_reason": render_markdown(decision.reason) if decision else "",
        "assessment_form": AssessmentForm(form_data, initial=assessment_initial, auto_id="assessment_%s"),
        "verification_form": VerificationForm(
            verification_data, initial=verification_initial, auto_id="verification_%s",
        ),
        "comment_form": CommentForm(comment_data, auto_id="comment_%s"),
        "comment_page": comments,
        "comment_rows": [_comment_row(comment, request.user) for comment in comments],
        "posted_action": posted_action,
        "posted_data": posted_data or {},
        "forum_error": error,
        "retry_fields": retry_fields,
        "solution_media_base_url": internal_image_base_url(solution.pk),
    }


@login_required
@require_GET
@never_cache
def solution_detail(request, solution_pk):
    solution = _solution(request, solution_pk)
    return _private(render(request, "solutions/forum-detail.html", _detail_context(request, solution)))


@login_required
@require_POST
@never_cache
def forum_action(request, solution_pk, action):
    solution = _solution(request, solution_pk)
    inline_vote = action == "upvote" and wants_inline_action(request)
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        length = MAX_POST_BYTES + 1
    if length < 0 or length > MAX_POST_BYTES:
        response = (
            inline_action_response("This request is too large.", status=413)
            if inline_vote else render(request, "solutions/forum-detail.html", _detail_context(
                request, solution, error="This request is too large. Shorten the text before submitting.",
            ), status=413)
        )
        return _private(response)
    try:
        forum.write(request.user, solution.pk, action, request.POST)
    except forum.ForumError as error:
        # The write service reloads authority under lock. Never rerender a denied
        # object using the principal cached by authentication middleware.
        if error.status in {403, 404}:
            return _private(HttpResponse(status=error.status))
        request.user.refresh_from_db()
        if not request.user.is_active or not user_can_access_app_features(request.user):
            return _private(HttpResponse(status=403))
        solution = _solution(request, solution.pk)
        response = (
            inline_action_response(str(error), status=error.status)
            if inline_vote else render(request, "solutions/forum-detail.html", _detail_context(
                request, solution, posted_action=action, posted_data=request.POST, error=str(error),
            ), status=error.status)
        )
        return _private(response)
    if inline_vote:
        return _private(inline_action_fragment(
            request,
            "Your vote has been updated.",
            template="solutions/partials/forum-vote.html",
            context={"solution": solution, **_vote_context(solution, request.user)},
        ))
    messages.success(request, {
        "upvote": "Your vote has been updated.",
        "request_review": "Review requested for this version.",
        "assess": "Your assessment has been saved.",
        "verify": "This version has been verified correct.",
        "adjudicate": "The admin decision has been saved.",
        "revoke": "Verification has been revoked.",
        "comment": "Your comment has been posted.",
        "edit_comment": "Your comment has been updated.",
        "remove_comment": "Your comment has been removed.",
        "hide_comment": "The comment has been hidden.",
        "restore_comment": "The comment has been restored.",
        "report": "Your report has been sent to the admins.",
        "resolve_report": "The report has been resolved.",
    }.get(action, "Saved."))
    response = redirect("solutions:solution_detail", solution.pk)
    return _private(response)


@login_required
@require_GET
@never_cache
def forum_comment_replies(request, solution_pk, comment_pk):
    solution = _solution(request, solution_pk)
    parent = get_object_or_404(SolutionComment, pk=comment_pk, solution=solution, parent__isnull=True)
    parent = _with_edit_marker(SolutionComment.objects.filter(pk=parent.pk)).select_related("author").get()
    replies = _page(_with_edit_marker(parent.replies).select_related("author").order_by("created_at", "pk"), request)
    return _private(render(request, "solutions/forum-replies.html", {
        "solution": solution,
        "parent_row": _comment_row(parent, request.user),
        "comment_rows": [_comment_row(reply, request.user) for reply in replies],
        "comment_page": replies,
        "is_forum_admin": user_has_admin_role(request.user),
        "can_discuss": solution.status == ProblemSolution.Status.PUBLISHED,
    }))


@login_required
@require_GET
@never_cache
def forum_history(request, solution_pk):
    solution = _solution(request, solution_pk)
    if not user_has_admin_role(request.user):
        raise PermissionDenied
    targets = _page(SolutionForumTarget.objects.filter(solution=solution).order_by("-created_at", "-pk"), request)
    selected = None
    target_id = request.GET.get("target")
    if target_id:
        try:
            selected = get_object_or_404(SolutionForumTarget, solution=solution, pk=target_id)
        except (ValidationError, ValueError, TypeError) as error:
            raise Http404 from error
    assessments = selected.assessments.select_related("reviewer").order_by("-created_at", "-pk") if selected else []
    decisions = selected.decisions.select_related("admin").order_by("-created_at", "-pk") if selected else []
    events = _page(
        solution.forum_comments.values(
            "events__id", "events__action", "events__body", "events__reason", "events__created_at",
            "events__actor__name", "events__version", "pk",
        )
        .filter(events__isnull=False).order_by("-events__created_at", "-events__id"), request, "events_page",
    )
    return _private(render(request, "solutions/forum-history.html", {
        "solution": solution, "target_page": targets, "selected_target": selected,
        "assessment_page": _page(assessments, request, "assessments_page"),
        "decision_page": _page(decisions, request, "decisions_page"), "event_page": events,
        "solution_media_base_url": internal_image_base_url(solution.pk),
    }))


def _queue(request, *, admin=False):
    if not user_has_trainer_or_admin_role(request.user) or (admin and not user_has_admin_role(request.user)):
        raise PermissionDenied
    choices = [
        ("pending_verification", "Pending verification"),
        ("disputed", "Unresolved disagreement"),
        ("reports", "Comment reports"),
    ] if admin else [
        ("requested", "Review requested"),
        ("unassessed", "Not assessed"),
        ("assessed", "Assessed"),
        ("disputed", "Trainer disagreement"),
    ]
    state = request.GET.get("state", choices[0][0])
    if state not in dict(choices):
        raise Http404
    report_page = None
    report_status = request.GET.get("report_status", "open")
    page = None
    rows = []
    if state == "reports":
        if report_status not in {"open", "resolved"}:
            raise Http404
        report_page = _page(SolutionForumReport.objects.filter(status=report_status).select_related(
            "comment", "comment__solution", "comment__solution__problem", "reporter", "resolved_by",
        ).order_by("created_at", "pk"), request)
    else:
        page = _page(forum.queue_solutions(state, admin=admin).exclude(author=request.user), request)
        rows = [{"solution": solution, "summary": forum.summary(solution)} for solution in page]
    return _private(render(request, "solutions/forum-queue.html", {
        "is_admin_queue": admin, "queue_choices": choices, "queue_state": state,
        "queue_page": page, "queue_rows": rows, "report_page": report_page,
        "report_status": report_status,
    }))


@login_required
@require_GET
@never_cache
def forum_review_queue(request):
    return _queue(request)


@login_required
@require_GET
@never_cache
def forum_admin_queue(request):
    return _queue(request, admin=True)
