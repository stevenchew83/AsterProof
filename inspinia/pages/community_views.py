"""Authenticated community posts, mandatory preflight, and human moderation."""

import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from inspinia.users.roles import user_has_admin_role

from .community_forms import CONTENT_FIELDS
from .community_forms import CommunityProblemForm
from .community_forms import CommunityReviewForm
from .community_models import CommunityProblem
from .community_models import CommunityProblemReview
from .community_models import StatementReviewPolicy
from .statement_reviews import StatementReviewError
from .statement_reviews import enqueue_statement_review
from .statement_reviews import policy_ready
from .statement_similarity import check_statement_similarity
from .statement_similarity import digest

CHECK_SALT = "community-problem-check-v1"
CHECK_MAX_AGE = 15 * 60
DAILY_POST_LIMIT = 10


def _content_digest(form):
    return digest(json.dumps({field: form.cleaned_data[field] for field in CONTENT_FIELDS}, sort_keys=True))


def _check_token(request, form, problem, similarity):
    return signing.dumps(
        {
            "user": str(request.user.pk),
            "problem": str(problem.pk) if problem else "new",
            "version": problem.version if problem else 1,
            "digest": _content_digest(form),
            "signature": similarity["signature"],
        },
        salt=CHECK_SALT,
    )


def _valid_check(request, form, problem, similarity):
    try:
        previous = signing.loads(request.POST.get("similarity_token", ""), salt=CHECK_SALT, max_age=CHECK_MAX_AGE)
    except signing.BadSignature:
        return False
    return previous == {
        "user": str(request.user.pk),
        "problem": str(problem.pk) if problem else "new",
        "version": problem.version if problem else 1,
        "digest": _content_digest(form),
        "signature": similarity["signature"],
    }


@login_required
@never_cache
def community_problem_list(request):
    tab = "all" if request.GET.get("tab") == "all" else "reviewed"
    source = CommunityProblem.objects.select_related("author")
    counts = dict(source.values_list("status").annotate(total=Count("pk")))
    problems = source if tab == "all" else source.filter(status=CommunityProblem.Status.APPROVED)
    page = Paginator(problems, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "pages/community-problem-list.html",
        {
            "problems": page,
            "tab": tab,
            "all_count": sum(counts.values()),
            "reviewed_count": counts.get(CommunityProblem.Status.APPROVED, 0),
            "pagination_url": reverse("pages:community_problem_list") + f"?tab={tab}&page=",
            "is_admin": user_has_admin_role(request.user),
        },
    )


def _save_problem(request, form, problem, similarity):
    with transaction.atomic():
        if problem:
            current = CommunityProblem.objects.select_for_update().get(pk=problem.pk)
            if current.version != form.cleaned_data["version"] or current.status not in {
                CommunityProblem.Status.PENDING,
                CommunityProblem.Status.CHANGES_REQUESTED,
            }:
                form.add_error(None, "This post changed or has been reviewed. Reload before editing.")
                return None
            for field in CONTENT_FIELDS:
                setattr(current, field, form.cleaned_data[field])
            current.version += 1
            current.status = CommunityProblem.Status.PENDING
            current.reviewed_by = current.reviewed_at = None
            current.review_notes = ""
        else:
            # Lock the author to serialize duplicate form submits and the daily limit.
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            now = timezone.now()
            if (
                CommunityProblem.objects.filter(author=request.user, created_at__date=now.date()).count()
                >= DAILY_POST_LIMIT
            ):
                form.add_error(None, "You can post up to ten problems per day.")
                return None
            previous = CommunityProblem.objects.filter(
                author=request.user,
                similarity_snapshot__content_digest=(_content_digest(form)),
            ).first()
            if previous:
                return previous
            current = form.save(commit=False)
            current.author = request.user
        current.similarity_snapshot = {**similarity, "content_digest": _content_digest(form)}
        current.save()
        return current


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def community_problem_create(request, problem_id=None):
    problem = get_object_or_404(CommunityProblem, pk=problem_id, author=request.user) if problem_id else None
    if problem and problem.status not in {CommunityProblem.Status.PENDING, CommunityProblem.Status.CHANGES_REQUESTED}:
        raise PermissionDenied
    form = CommunityProblemForm(request.POST or None, instance=problem)
    similarity, token = None, ""
    if request.method == "POST" and form.is_valid():
        # ModelForm validation mutates its instance; re-read the version used to
        # bind the check and never trust author/status fields from the browser.
        original = CommunityProblem.objects.get(pk=problem.pk) if problem else None
        similarity = check_statement_similarity(form.cleaned_data["statement_latex"])
        if similarity["available"]:
            action = request.POST.get("action")
            if action == "submit":
                if not _valid_check(request, form, original, similarity):
                    form.add_error(
                        None,
                        "Check for similar problems again after changing details or when the check expires.",
                    )
                elif similarity["matches"] and request.POST.get("matches_acknowledged") != "1":
                    form.add_error(None, "Review and acknowledge the possible matches before submitting.")
                else:
                    saved = _save_problem(request, form, original, similarity)
                    if saved:
                        messages.success(request, "Problem posted for admin review.")
                        return redirect("pages:community_problem_detail", problem_id=saved.pk)
            token = _check_token(request, form, original, similarity)
    return render(
        request,
        "pages/community-problem-form.html",
        {
            "form": form,
            "problem": problem,
            "similarity": similarity,
            "similarity_token": token,
        },
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def community_problem_detail(request, problem_id):
    problem = get_object_or_404(CommunityProblem.objects.select_related("author", "reviewed_by"), pk=problem_id)
    is_admin = user_has_admin_role(request.user)
    review_form = CommunityReviewForm(initial={"version": problem.version})
    if request.method == "POST":
        if not is_admin:
            raise PermissionDenied
        review_form = CommunityReviewForm(request.POST)
        if review_form.is_valid():
            with transaction.atomic():
                current = CommunityProblem.objects.select_for_update().get(pk=problem.pk)
                if (
                    current.version != review_form.cleaned_data["version"]
                    or current.status != CommunityProblem.Status.PENDING
                ):
                    review_form.add_error(None, "This post changed or was already reviewed. Reload before deciding.")
                else:
                    current.status = review_form.cleaned_data["decision"]
                    current.review_notes = review_form.cleaned_data["notes"]
                    current.reviewed_by, current.reviewed_at = request.user, timezone.now()
                    current.save(update_fields=["status", "review_notes", "reviewed_by", "reviewed_at", "updated_at"])
                    CommunityProblemReview.objects.create(
                        problem=current,
                        version=current.version,
                        reviewer=request.user,
                        decision=current.status,
                        notes=current.review_notes,
                        content_snapshot={field: getattr(current, field) for field in CONTENT_FIELDS},
                    )
                    messages.success(request, "Admin review saved. The post remains separate from the main library.")
                    return redirect("pages:community_problem_detail", problem_id=problem.pk)
    can_edit = problem.author_id == request.user.pk and problem.status in {
        CommunityProblem.Status.PENDING,
        CommunityProblem.Status.CHANGES_REQUESTED,
    }
    return render(
        request,
        "pages/community-problem-detail.html",
        {
            "problem": problem,
            "is_admin": is_admin,
            "can_edit": can_edit,
            "can_review": is_admin and problem.status == CommunityProblem.Status.PENDING,
            "show_private": is_admin or problem.author_id == request.user.pk,
            "review_form": review_form,
            "ai_review": problem.ai_reviews.filter(version=problem.version).first() if is_admin else None,
            "ai_ready": policy_ready(StatementReviewPolicy.objects.filter(pk=1).first()) if is_admin else False,
        },
    )


@login_required
@never_cache
@require_http_methods(["POST"])
def community_problem_ai_review(request, problem_id):
    if not user_has_admin_role(request.user):
        raise PermissionDenied
    get_object_or_404(CommunityProblem, pk=problem_id)
    try:
        version = int(request.POST.get("version", ""))
        enqueue_statement_review(
            request.user,
            problem_id,
            version,
            acknowledged=request.POST.get("acknowledged") == "1",
        )
    except (StatementReviewError, ValueError) as error:
        messages.error(request, str(error) if isinstance(error, StatementReviewError) else "Use a valid post version.")
    else:
        messages.success(request, "AI review queued. Refresh this page to see the worker result.")
    return redirect("pages:community_problem_detail", problem_id=problem_id)
