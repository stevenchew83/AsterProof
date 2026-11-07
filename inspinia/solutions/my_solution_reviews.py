"""Review summaries visible to the author in My solutions."""

from collections import defaultdict

from django.conf import settings
from django.db.models import Case
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import When

from inspinia.pages.models import ContestProblemStatement
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_reviews import LIVE_STATES
from inspinia.solutions.admin_reviews import REVIEWABLE_STATES
from inspinia.solutions.admin_reviews import approved_user
from inspinia.solutions.admin_reviews import problem_label
from inspinia.solutions.admin_reviews import self_review_restricted
from inspinia.solutions.forum import current_target_data
from inspinia.solutions.models import ProblemSolution

Status = AdminSolutionReview.Status
REQUEST_LABELS = {
    Status.QUEUED: "Queued",
    Status.RUNNING: "Reviewing",
    Status.COMPLETED: "Awaiting publication",
    Status.FAILED: "Failed",
    Status.UNKNOWN: "Outcome unknown",
}


def _visible_reviews(user, solution, reviews):
    has_self_request = any(row["self_request__pk"] is not None for row in reviews)
    restricted = has_self_request and self_review_restricted(
        user, solution.problem.problem_uuid, solution.active_statement_id,
    )
    if restricted:
        return [row for row in reviews if row["self_request__pk"] is None]
    if not settings.SELF_SOLUTION_REVIEW_ENABLED or solution.status not in REVIEWABLE_STATES:
        return [row for row in reviews if row["status"] not in LIVE_STATES]
    return reviews


def _current_reviews(solution, reviews):
    label = problem_label(solution)
    candidates = [
        row for row in reviews
        if row["problem_label"] == label
        and row["target__solution_version"] == solution.edit_version
        and row["target__solution_updated_at"] == solution.updated_at
    ]
    if not candidates:
        return []
    # Reuse the exact version check from the entry, including statement and legacy proof edits.
    key = current_target_data(solution)["key"]
    return [row for row in candidates if row["target__key"] == key]


def _summary(solution, reviews):
    current = _current_reviews(solution, reviews)
    shared = next((row for row in current if row["published_at"] is not None), None)
    if shared is not None:
        return {"label": "Reviewed", "score": shared["shared_score"]}
    if current:
        return {"label": REQUEST_LABELS[current[0]["status"]], "score": None}
    if any(row["published_at"] is not None for row in reviews):
        return {"label": "Earlier version", "score": None}
    return None


def author_review_summaries(user, solution_ids):
    if not solution_ids or not approved_user(user):
        return {}

    reviews = (
        AdminSolutionReview.objects.filter(
            solver_id=user.pk, target__solution__author_id=user.pk, target__solution_id__in=solution_ids,
        )
        .filter(
            Q(self_request__user_id=user.pk)
            | Q(self_request__isnull=True, published_at__isnull=False),
        )
        .annotate(shared_score=Case(When(published_at__isnull=False, then="score")))
        .values(
            "target__solution_id", "target__solution_version", "target__solution_updated_at", "target__key",
            "problem_label", "status", "published_at", "shared_score", "self_request__pk",
        )
    )
    by_solution = defaultdict(list)
    for review in reviews:
        by_solution[review["target__solution_id"]].append(review)
    if not by_solution:
        return {}

    active_statement = ContestProblemStatement.objects.filter(
        linked_problem_id=OuterRef("problem_id"), is_active=True,
    ).order_by("-updated_at", "-pk")
    solutions = (
        ProblemSolution.objects.filter(pk__in=by_solution, author_id=user.pk)
        .select_related("problem")
        .annotate(active_statement_id=Subquery(active_statement.values("pk")[:1]))
    )
    summaries = {}
    for solution in solutions:
        visible = _visible_reviews(user, solution, by_solution[solution.pk])
        summary = _summary(solution, visible)
        if summary is not None:
            summaries[solution.pk] = summary
    return summaries
