"""The account allowance shared by student hints and self-requested proof reviews."""

from dataclasses import dataclass

from django.db.models import Count
from django.db.models import Q

from inspinia.pages.study_help_models import HINT_ACTIONS
from inspinia.pages.study_help_models import INFLIGHT_PREDICATE
from inspinia.pages.study_help_models import StudyHelpRequest
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_review_models import SelfSolutionReviewUsage

ACCOUNT_CREDIT_LIMIT = 50
REVIEW_PENDING = (AdminSolutionReview.Status.QUEUED, AdminSolutionReview.Status.RUNNING)


@dataclass(frozen=True)
class AccountCredits:
    hints: int
    reviews: int
    reviews_here: int
    hint_pending: bool
    review_pending: bool

    @property
    def remaining(self):
        return max(0, ACCOUNT_CREDIT_LIMIT - self.hints - self.reviews)


def account_credits(user, problem_uuid=None):
    hints = StudyHelpRequest.objects.filter(owner=user, action__in=HINT_ACTIONS).aggregate(
        completed=Count("pk", filter=Q(state=StudyHelpRequest.State.READY)),
        pending=Count("pk", filter=INFLIGHT_PREDICATE),
    )
    reviews = SelfSolutionReviewUsage.objects.filter(user=user).aggregate(
        completed=Count("pk", filter=Q(succeeded=True)),
        completed_here=Count("pk", filter=Q(succeeded=True, problem_uuid=problem_uuid)),
        pending=Count("pk", filter=Q(review__status__in=REVIEW_PENDING)),
    )
    return AccountCredits(
        hints=hints["completed"],
        reviews=reviews["completed"],
        reviews_here=reviews["completed_here"],
        hint_pending=bool(hints["pending"]),
        review_pending=bool(reviews["pending"]),
    )
