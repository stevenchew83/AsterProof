"""Administrator reports for saved AI help and account credit usage."""

from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from inspinia.pages.ai_credits import ACCOUNT_CREDIT_LIMIT
from inspinia.pages.ai_credits import REVIEW_PENDING
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.study_help_models import HINT_ACTIONS
from inspinia.pages.study_help_models import INFLIGHT_PREDICATE
from inspinia.pages.study_help_models import StudyHelpRequest
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_review_models import SelfSolutionReviewUsage
from inspinia.solutions.admin_reviews import require_admin

PAGE_SIZE = 50
MAX_SEARCH_CHARS = 160


def _search(request):
    return request.GET.get("q", "").strip()[:MAX_SEARCH_CHARS]


def _selected_user(request):
    value = request.GET.get("user", "")
    if not value:
        return None
    user_id = int(value) if value.isascii() and value.isdecimal() and len(value) <= 18 else None  # noqa: PLR2004
    return get_object_or_404(get_user_model().objects.only("name", "email"), pk=user_id)


def _pagination_query(query, user):
    return urlencode({"q": query, "user": user.pk if user else ""})


def _history(request, rows, *, is_hint):
    user = _selected_user(request)
    query = _search(request)
    owner = "owner" if is_hint else "solver"
    if user:
        rows = rows.filter(**{owner: user})
    if query:
        rows = rows.filter(
            Q(problem_label__icontains=query)
            | Q(**{f"{owner}__name__icontains": query})
            | Q(**{f"{owner}__email__icontains": query}),
        )
    return render(request, "pages/ai-history.html", {
        "page_title": "Hint history" if is_hint else "Review history",
        "page_obj": Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page")),
        "pagination_query": _pagination_query(query, user),
        "is_hint": is_hint,
        "search": query,
        "selected_user": user,
    })


@login_required
@never_cache
@require_GET
def ai_hint_history(request):
    require_admin(request.user)
    label = ContestProblemStatement.objects.filter(statement_uuid=OuterRef("statement_uuid"))
    rows = StudyHelpRequest.objects.filter(action__in=HINT_ACTIONS, state=StudyHelpRequest.State.READY).annotate(
        problem_label=Subquery(label.values("contest_year_problem")[:1]),
    ).select_related("owner").only(
        "owner__name", "owner__email", "statement_uuid", "problem_uuid", "action", "body", "model", "finished_at",
    ).order_by("-finished_at", "-pk")
    return _history(request, rows, is_hint=True)


@login_required
@never_cache
@require_GET
def ai_review_history(request):
    require_admin(request.user)
    rows = AdminSolutionReview.objects.filter(status=AdminSolutionReview.Status.COMPLETED).select_related(
        "solver", "requested_by", "self_request",
    ).only(
        "problem_label", "solver__name", "solver__email", "requested_by__name", "requested_by__email",
        "self_request__id", "created_at", "published_at", "score", "feedback", "model",
    ).order_by("-created_at", "-pk")
    return _history(request, rows, is_hint=False)


def _attempt_counts(rows, owner, *, charged, pending):
    return {row[owner]: row for row in rows.values(owner).annotate(
        attempts=Count("pk"), charged=Count("pk", filter=charged), pending=Count("pk", filter=pending),
    )}


@login_required
@never_cache
@require_GET
def ai_user_usage(request):
    require_admin(request.user)
    user = _selected_user(request)
    query = _search(request)
    users = get_user_model().objects.only("name", "email").order_by("email", "pk")
    if user:
        users = users.filter(pk=user.pk)
    elif query:
        users = users.filter(Q(name__icontains=query) | Q(email__icontains=query))
    page = Paginator(users, PAGE_SIZE).get_page(request.GET.get("page"))
    user_ids = [account.pk for account in page]
    hints = _attempt_counts(
        StudyHelpRequest.objects.filter(owner_id__in=user_ids, action__in=HINT_ACTIONS),
        "owner_id", charged=Q(state=StudyHelpRequest.State.READY), pending=INFLIGHT_PREDICATE,
    )
    reviews = _attempt_counts(
        SelfSolutionReviewUsage.objects.filter(user_id__in=user_ids),
        "user_id", charged=Q(succeeded=True), pending=Q(review__status__in=REVIEW_PENDING),
    )
    admin_reviews = dict(AdminSolutionReview.objects.filter(
        solver_id__in=user_ids, status=AdminSolutionReview.Status.COMPLETED, self_request__isnull=True,
    ).values("solver_id").annotate(count=Count("pk")).values_list("solver_id", "count"))
    rows = []
    for account in page:
        hint = hints.get(account.pk, {})
        review = reviews.get(account.pk, {})
        spent = hint.get("charged", 0) + review.get("charged", 0)
        pending = hint.get("pending", 0) + review.get("pending", 0)
        rows.append({
            "account": account,
            "hint_count": hint.get("charged", 0),
            "review_count": review.get("charged", 0),
            "admin_review_count": admin_reviews.get(account.pk, 0),
            "remaining": max(0, ACCOUNT_CREDIT_LIMIT - spent),
            "pending": pending,
            "uncharged": hint.get("attempts", 0) + review.get("attempts", 0) - spent - pending,
        })
    return render(request, "pages/ai-user-usage.html", {
        "rows": rows,
        "page_obj": page,
        "pagination_query": _pagination_query(query, user),
        "search": query,
        "selected_user": user,
        "credit_limit": ACCOUNT_CREDIT_LIMIT,
    })
