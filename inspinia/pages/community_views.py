"""Authenticated community posts, mandatory preflight, and human moderation."""

import json
from copy import copy

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Case
from django.db.models import Count
from django.db.models import F
from django.db.models import Q
from django.db.models import Value
from django.db.models import When
from django.http import Http404
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
from .proof_library import active_publications
from .proof_library import ensure_statement_revision
from .proof_library import public_url
from .proof_models import CommunityAttempt
from .proof_models import CommunitySolution
from .statement_similarity import check_statement_similarity
from .statement_similarity import digest

CHECK_SALT = "community-problem-check-v1"
CHECK_MAX_AGE = 15 * 60
DAILY_POST_LIMIT = 10


def _content_digest(form):
    return digest(json.dumps(
        {field: form.cleaned_data[field] for field in CONTENT_FIELDS}, sort_keys=True, cls=DjangoJSONEncoder,
    ))


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
    is_admin = user_has_admin_role(request.user)
    direct_access = Q(author=request.user) | Q(legacy_member_visible=True)
    visible_public = active_publications().filter(visibility="public").values("problem_id")
    source = CommunityProblem.objects.select_related("author", "publication__statement_revision")
    if not is_admin:
        source = source.filter(direct_access | Q(pk__in=visible_public))
    source = source.annotate(audience_status=Case(
        When(direct_access if not is_admin else Q(pk__isnull=False), then=F("status")),
        default=Value(CommunityProblem.Status.APPROVED),
    ))
    counts = dict(source.values_list("audience_status").annotate(total=Count("pk")))
    problems = source if tab == "all" else source.filter(audience_status=CommunityProblem.Status.APPROVED)
    page = Paginator(problems, 20).get_page(request.GET.get("page"))
    safe_rows = []
    for source_row in page.object_list:
        row = source_row
        if not is_admin and row.author_id != request.user.pk and not row.legacy_member_visible:
            row = copy(row)
            publication = row.publication
            for name, value in publication.statement_revision.snapshot.items():
                if hasattr(row, name):
                    setattr(row, name, value)
            row.status = CommunityProblem.Status.APPROVED
            row.author = copy(row.author)
            row.author.name = publication.public_credit or "Community contributor"
            row.author.email = ""
        safe_rows.append(row)
    page.object_list = safe_rows
    return render(
        request,
        "pages/community-problem-list.html",
        {
            "problems": page,
            "tab": tab,
            "all_count": sum(counts.values()),
            "reviewed_count": counts.get(CommunityProblem.Status.APPROVED, 0),
            "pagination_url": reverse("pages:community_problem_list") + f"?tab={tab}&page=",
            "is_admin": is_admin,
        },
    )


def _save_problem(request, form, problem, similarity):
    with transaction.atomic():
        if problem:
            current = CommunityProblem.objects.select_for_update().get(pk=problem.pk)
            legacy_locked = current.legacy_member_visible and current.status not in {
                CommunityProblem.Status.PENDING, CommunityProblem.Status.CHANGES_REQUESTED,
            }
            if current.version != form.cleaned_data["version"] or legacy_locked:
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
            get_user_model().objects.select_for_update(no_key=True).get(pk=request.user.pk)
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
        ensure_statement_revision(current)
        return current


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def community_problem_create(request, problem_id=None):
    problem = get_object_or_404(CommunityProblem, pk=problem_id, author=request.user) if problem_id else None
    if problem and problem.legacy_member_visible and problem.status not in {
        CommunityProblem.Status.PENDING, CommunityProblem.Status.CHANGES_REQUESTED,
    }:
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
    is_owner = problem.author_id == request.user.pk
    if not (is_admin or is_owner or problem.legacy_member_visible):
        publication = active_publications().filter(problem=problem, visibility="public").first()
        if not publication:
            raise Http404
        return redirect(public_url(publication))
    review_form = CommunityReviewForm(initial={"version": problem.version})
    if request.method == "POST":
        if not is_admin:
            raise PermissionDenied
        if not problem.legacy_member_visible:
            return redirect("pages:proof_moderation", problem_id=problem.pk)
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
                        content_snapshot=json.loads(json.dumps(
                            {field: getattr(current, field) for field in CONTENT_FIELDS}, cls=DjangoJSONEncoder,
                        )),
                    )
                    messages.success(request, "Admin review saved. The post remains separate from the main library.")
                    return redirect("pages:community_problem_detail", problem_id=problem.pk)
    can_edit = is_owner and (not problem.legacy_member_visible or problem.status in {
        CommunityProblem.Status.PENDING, CommunityProblem.Status.CHANGES_REQUESTED,
    })
    return render(
        request,
        "pages/community-problem-detail.html",
        {
            "problem": problem,
            "is_admin": is_admin,
            "can_edit": can_edit,
            "can_review": (
                is_admin and problem.legacy_member_visible and problem.status == CommunityProblem.Status.PENDING
            ),
            "show_private": is_admin or problem.author_id == request.user.pk,
            "show_review_notes": is_admin or is_owner or problem.legacy_member_visible,
            "review_form": review_form,
            "ai_review": problem.ai_reviews.filter(version=problem.version).first() if is_admin else None,
            "ai_ready": False,
            "own_attempts": CommunityAttempt.objects.filter(problem=problem, owner=request.user),
            "own_solutions": CommunitySolution.objects.filter(
                problem=problem, author=request.user,
            ).select_related("current_revision"),
        },
    )


@login_required
@never_cache
@require_http_methods(["POST"])
def community_problem_ai_review(request, problem_id):
    msg = "AI review is disabled for the Community Proof Library."
    raise PermissionDenied(msg)
