"""The optional guide follows saved work without publishing or changing progress."""

from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.test_public_sharing import create_share
from inspinia.solutions.test_public_sharing import saved_editor_data
from inspinia.users.models import User
from inspinia.users.models import UserAccessSettings
from inspinia.users.tests.factories import UserFactory
from inspinia.users.tests.test_views import TEST_PASSWORD

pytestmark = pytest.mark.django_db
SAVED_STEPS = 2
SHARED_STEPS = 3


@pytest.fixture
def learner(client):
    user = UserFactory()
    client.force_login(user)
    return user


@pytest.fixture
def solution(learner):
    problem = ProblemSolveRecord.objects.create(contest="GUIDE", year=2026, problem="P1", topic="ALG", mohs=1)
    ContestProblemStatement.objects.create(
        linked_problem=problem, contest_name="GUIDE", contest_year=2026, problem_code="P1",
        problem_number=1, topic="ALG", statement_latex=r"Prove $x^2\geq 0$.",
    )
    return ProblemSolution.objects.create(author=learner, problem=problem, title="My first proof")


def guide(client):
    response = client.get(reverse("solutions:my_solution_list"))
    assert response.status_code == HTTPStatus.OK
    assert "no-store" in response["Cache-Control"]
    return response.context["solution_guide"]


def test_new_account_starts_with_optional_guide_and_no_fabricated_work(client, learner):
    assert learner.get_login_redirect_url() == reverse("solutions:my_solution_list")
    progress = guide(client)
    assert progress["visible"]
    assert progress["completed_steps"] == 0
    assert progress["start_url"] == reverse("solutions:problem_solution_create")
    html = client.get(reverse("solutions:my_solution_list")).content.decode()
    assert "Write my first solution" in html
    assert "Skip for now" in html
    assert "Optional" in html
    assert "All solutions</p>" not in html
    assert not ProblemSolution.objects.exists()
    assert not SolutionPublicShare.objects.exists()
    assert not UserProblemCompletion.objects.exists()


def test_existing_account_has_no_automatic_guide_and_can_opt_in(client, learner, solution):
    learner.solution_guide_status = User.SolutionGuideStatus.NOT_ENROLLED
    learner.save(update_fields=["solution_guide_status"])
    assert learner.get_login_redirect_url() == reverse("pages:user_activity_dashboard")
    assert not guide(client)["visible"]
    editor = client.get(reverse("solutions:problem_solution_edit", args=[solution.problem.problem_uuid]))
    assert not editor.context["show_solution_guide"]
    assert "Next: save your solution." not in editor.content.decode()
    client.post(reverse("solutions:solution_guide_preference"), {"action": "show"})
    assert guide(client)["visible"]


def test_empty_upload_placeholder_does_not_count_as_saved_proof(client, solution):
    progress = guide(client)
    assert progress["chosen"]
    assert not progress["saved"]
    assert not progress["shared"]
    assert progress["completed_steps"] == 1
    assert progress["editor_url"] == reverse("solutions:problem_solution_edit", args=[solution.problem.problem_uuid])


def test_save_then_share_advances_guide_without_publishing_or_marking_solved(client, solution):
    editor_url = reverse("solutions:problem_solution_edit", args=[solution.problem.problem_uuid])
    editor = client.get(editor_url)
    assert "Next: save your solution." in editor.content.decode()
    response = client.post(editor_url, {
        "action": "save", "solution-title": "My first proof", "solution-summary": "",
        "blocks-TOTAL_FORMS": "1", "blocks-INITIAL_FORMS": "0", "blocks-MIN_NUM_FORMS": "0",
        "blocks-MAX_NUM_FORMS": "1000", "blocks-0-ORDER": "1", "blocks-0-body_format": "plain_text",
        "blocks-0-body_source": "A square is nonnegative.",
    }, follow=True)
    assert response.status_code == HTTPStatus.OK
    assert "Your solution is saved." in response.content.decode()
    progress = guide(client)
    assert progress["completed_steps"] == SAVED_STEPS
    assert not progress["shared"]
    assert not SolutionPublicShare.objects.exists()

    share = create_share(client, solution)
    progress = guide(client)
    assert progress["completed_steps"] == SHARED_STEPS
    assert progress["shared"]
    assert "Your public link is ready." in client.get(editor_url).content.decode()
    assert Client().get(reverse("solutions:public_solution", args=[share.token])).status_code == HTTPStatus.OK
    solution.refresh_from_db()
    assert solution.status == ProblemSolution.Status.DRAFT
    assert solution.published_at is None
    assert solution.submitted_at is None
    assert not UserProblemCompletion.objects.exists()

    # Stopping sharing is reflected immediately; no stale completion flag survives.
    share.is_active = False
    share.save(update_fields=["is_active"])
    assert guide(client)["completed_steps"] == SAVED_STEPS


def test_guide_uses_owners_saved_solution_even_with_newer_empty_draft(client, solution):
    ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source="A saved proof.")
    newer = ProblemSolveRecord.objects.create(contest="GUIDE", year=2026, problem="P2", topic="ALG", mohs=1)
    ProblemSolution.objects.create(author=solution.author, problem=newer)
    foreign = ProblemSolution.objects.create(author=UserFactory(), problem=solution.problem)
    ProblemSolutionBlock.objects.create(solution=foreign, position=1, body_source="Someone else's proof.")
    create_share(client_with_user(foreign.author), foreign)
    progress = guide(client)
    assert progress["completed_steps"] == SAVED_STEPS
    assert progress["share_url"] == reverse("solutions:problem_solution_share", args=[solution.problem.problem_uuid])


def client_with_user(user):
    client = Client()
    client.force_login(user)
    return client


def test_skip_and_reopen_persist_across_sessions_and_only_update_current_user(client, learner):
    other = UserFactory()
    preference = reverse("solutions:solution_guide_preference")
    response = client.post(preference, {"action": "dismiss", "user_id": other.pk})
    assert response.url == reverse("solutions:my_solution_list") + "#solution-guide"
    second_session = client_with_user(learner)
    assert not guide(second_session)["visible"]
    learner.refresh_from_db()
    assert learner.get_login_redirect_url() == reverse("solutions:my_solution_list")
    other.refresh_from_db()
    assert other.solution_guide_status == User.SolutionGuideStatus.ACTIVE
    second_session.post(preference, {"action": "show"})
    assert guide(client)["visible"]


def test_guide_preference_requires_login_approval_csrf_and_known_post_action(client, learner):
    url = reverse("solutions:solution_guide_preference")
    assert Client().post(url, {"action": "dismiss"}).status_code == HTTPStatus.FOUND
    assert client.get(url).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert client.post(url, {"action": "publish"}).status_code == HTTPStatus.BAD_REQUEST
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(learner)
    assert csrf_client.post(url, {"action": "dismiss"}).status_code == HTTPStatus.FORBIDDEN
    learner.is_approved = False
    learner.save(update_fields=["is_approved"])
    assert client.post(url, {"action": "dismiss"}).url == reverse("users:approval_pending")
    learner.refresh_from_db()
    assert learner.solution_guide_status == User.SolutionGuideStatus.ACTIVE


def test_invalid_editor_submission_does_not_advance_saved_step(client, solution):
    response = client.post(
        reverse("solutions:problem_solution_edit", args=[solution.problem.problem_uuid]),
        saved_editor_data(solution),
    )
    assert response.context["formset"].non_form_errors()
    assert guide(client)["completed_steps"] == 1


def test_whitespace_proof_is_rejected_without_advancing_saved_step(client, solution):
    response = client.post(reverse("solutions:problem_solution_edit", args=[solution.problem.problem_uuid]), {
        "action": "save", "solution-title": "Unfinished", "blocks-TOTAL_FORMS": "1",
        "blocks-INITIAL_FORMS": "0", "blocks-MIN_NUM_FORMS": "0", "blocks-MAX_NUM_FORMS": "1000",
        "blocks-0-ORDER": "1", "blocks-0-body_format": "plain_text", "blocks-0-body_source": " \n\t ",
    })
    assert response.context["formset"].errors
    assert not solution.blocks.exists()
    assert guide(client)["completed_steps"] == 1


def test_new_signup_lands_on_solutions_after_existing_approval_gate(client, settings):
    settings.ACCOUNT_EMAIL_VERIFICATION = "none"
    access = UserAccessSettings.get_solo()
    access.auto_approve_new_users = True
    access.save()
    response = client.post(reverse("account_signup"), {
        "email": "new-guide@example.test", "password1": TEST_PASSWORD, "password2": TEST_PASSWORD,
    }, follow=True)
    assert response.status_code == HTTPStatus.OK
    assert response.request["PATH_INFO"] == reverse("solutions:my_solution_list")
    assert response.context["solution_guide"]["visible"]
