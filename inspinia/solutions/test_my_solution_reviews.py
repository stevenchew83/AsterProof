import uuid
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions import forum
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_review_models import SelfSolutionReviewUsage
from inspinia.solutions.admin_reviews import problem_label
from inspinia.solutions.evaluation_models import AssistancePolicy
from inspinia.solutions.models import ProblemSolution
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
Status = AdminSolutionReview.Status
FEEDBACK = "Private feedback for the exact saved proof."


@pytest.fixture
def solution():
    problem = ProblemSolveRecord.objects.create(contest="IMO", year=2026, problem="P1")
    ContestProblemStatement.objects.create(
        linked_problem=problem, contest_name="IMO", contest_year=2026, problem_code="P1",
        problem_number=1, statement_latex="Prove that a square is nonnegative.",
    )
    solution = ProblemSolution.objects.create(
        problem=problem, author=UserFactory(), status=ProblemSolution.Status.PUBLISHED,
    )
    solution.blocks.create(position=1, body_source="A square is nonnegative.")
    return solution


def _review(solution, status, *, score=None, shared=False, owner_request=False):
    target = forum._target(solution, {"target_key": forum.current_target_data(solution)["key"]})  # noqa: SLF001
    review = AdminSolutionReview.objects.create(
        target=target, solver=solution.author, problem_label=problem_label(solution), status=status,
        batch_id=uuid.uuid4(), key_version=uuid.uuid4(), model="gpt-6.1-sol", output_limit=1000,
        score=score, feedback=FEEDBACK, published_at=timezone.now() if shared else None,
    )
    if owner_request:
        SelfSolutionReviewUsage.objects.create(
            user=solution.author, review=review, problem_uuid=solution.problem.problem_uuid, batch_id=review.batch_id,
        )
    return review


def _inventory(client, solution):
    client.force_login(solution.author)
    response = client.get(reverse("solutions:my_solution_list"))
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


@pytest.mark.parametrize("role", [User.Role.NORMAL, User.Role.ADMIN])
def test_my_solutions_links_to_the_saved_entry_and_keeps_admin_drafts_private(client, solution, role):
    solution.author.role = role
    solution.author.save(update_fields=["role"])
    solution.status = ProblemSolution.Status.DRAFT
    solution.save(update_fields=["status", "updated_at"])
    other = ProblemSolution.objects.create(
        problem=solution.problem, author=UserFactory(), status=ProblemSolution.Status.PUBLISHED,
    )
    _review(solution, Status.COMPLETED, score=7)
    exact_url = reverse("solutions:solution_detail", args=[solution.pk])

    html = _inventory(client, solution)
    assert '<th scope="col">AI review</th>' in html
    assert f'href="{exact_url}"' in html
    assert "View solution</a>" in html
    assert reverse("solutions:solution_detail", args=[other.pk]) not in html
    assert "Not reviewed" in html
    assert "Draft ready" not in html
    assert "7/7" not in html
    assert FEEDBACK not in html

    detail = client.get(exact_url)
    assert detail.status_code == HTTPStatus.OK
    assert detail.context["solution"].pk == solution.pk


def test_my_solutions_shows_shared_zero_score_and_marks_changed_statement_as_earlier(client, solution, settings):
    settings.SELF_SOLUTION_REVIEW_ENABLED = False
    review = _review(solution, Status.COMPLETED, score=0, shared=True)
    _review(solution, Status.COMPLETED, score=7)
    review_url = reverse("solutions:solution_detail", args=[solution.pk]) + "#ai-review"

    html = _inventory(client, solution)
    assert f'href="{review_url}"' in html
    assert "0/7</span> · Reviewed" in html
    assert "7/7" not in html
    assert FEEDBACK not in html

    ContestProblemStatement.objects.filter(pk=review.target.statement_id_value).update(
        statement_latex="Find all equality cases.",
    )
    html = _inventory(client, solution)
    assert "Earlier version</a>" in html
    assert "0/7" not in html


@pytest.mark.parametrize(
    ("status", "label"),
    [
        (Status.QUEUED, "Queued"),
        (Status.RUNNING, "Reviewing"),
        (Status.COMPLETED, "Awaiting publication"),
        (Status.FAILED, "Failed"),
        (Status.UNKNOWN, "Outcome unknown"),
    ],
)
def test_my_solutions_shows_own_request_status_without_unshared_score(client, solution, settings, status, label):
    settings.SELF_SOLUTION_REVIEW_ENABLED = True
    score = 7 if status == Status.COMPLETED else None
    _review(solution, status, score=score, owner_request=True)
    _review(solution, Status.COMPLETED, score=7)

    html = _inventory(client, solution)
    assert f">{label}</a>" in html
    assert "7/7" not in html
    assert FEEDBACK not in html


def test_my_solutions_hides_shared_author_review_during_restricted_assessment(client, solution, settings):
    settings.SELF_SOLUTION_REVIEW_ENABLED = True
    _review(solution, Status.COMPLETED, score=7, shared=True, owner_request=True)
    assert "7/7</span> · Reviewed" in _inventory(client, solution)

    now = timezone.now()
    AssistancePolicy.objects.create(
        actor_id_scope=solution.author_id, problem_uuid=solution.problem.problem_uuid,
        mode="restricted_assessment", starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(minutes=10),
    )

    html = _inventory(client, solution)
    assert "Not reviewed" in html
    assert "7/7" not in html
    assert "Earlier version" not in html
