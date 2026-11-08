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
from inspinia.solutions.test_solution_editor import solution_payload
from inspinia.solutions.test_writer_handoff import source_data
from inspinia.solutions.writer_drafts import WRITER_DRAFT_SESSION_KEY
from inspinia.solutions.writer_drafts import writer_handoff_url
from inspinia.users.models import User
from inspinia.users.models import UserAccessSettings
from inspinia.users.tests.factories import UserFactory
from inspinia.users.tests.test_views import TEST_PASSWORD

pytestmark = pytest.mark.django_db
SAVED_STEPS = 2


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
    starter = ProblemSolveRecord.objects.create(contest="IMO", year=1959, problem="P1", topic="NT", mohs=10)
    ContestProblemStatement.objects.create(
        linked_problem=starter, contest_name="IMO", contest_year=1959, problem_code="P1",
        problem_number=1, statement_latex="Prove that the fraction is irreducible.",
    )
    easier = ProblemSolveRecord.objects.create(contest="GUIDE", year=2026, problem="P1", topic="ALG", mohs=5)
    fallback = ContestProblemStatement.objects.create(
        linked_problem=easier, contest_name="GUIDE", contest_year=2026, problem_code="P1",
        problem_number=1, statement_latex="Prove that a square is nonnegative.",
    )
    assert learner.get_login_redirect_url() == reverse("solutions:my_solution_list")
    progress = guide(client)
    assert progress["visible"]
    assert progress["completed_steps"] == 0
    assert progress["start_url"] == reverse("solutions:problem_solution_create")
    assert progress["starter_url"] == reverse("solutions:problem_solution_edit", args=[starter.problem_uuid])
    html = client.get(reverse("solutions:my_solution_list")).content.decode()
    assert f'href="{progress["starter_url"]}" class="btn btn-primary">Try a starter problem' in html
    assert "I already have a proof" in html
    assert "See a worked example" in html
    assert "0 of 2 complete" in html
    assert "Skip for now" in html
    assert "Share a public link" not in html
    assert 'id="create-solution-cta"' not in html
    assert 'id="my-solutions-list-heading"' not in html

    starter.is_active = False
    starter.save(update_fields=["is_active"])
    assert guide(client)["starter_url"] == reverse("solutions:problem_solution_edit", args=[easier.problem_uuid])
    fallback.is_active = False
    fallback.save(update_fields=["is_active"])
    assert not guide(client)["starter_url"]
    assert "I already have a proof" in client.get(reverse("solutions:my_solution_list")).content.decode()
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


def test_save_completes_getting_started_and_sharing_remains_optional(client, solution):
    editor_url = reverse("solutions:problem_solution_edit", args=[solution.problem.problem_uuid])
    editor = client.get(editor_url)
    assert "Save private draft" in editor.content.decode()
    response = client.post(editor_url, {
        "action": "save", "solution-title": "My first proof", "solution-summary": "",
        "solution-base_version": editor.context["form"]["base_version"].value(),
        "solution-editor_context": editor.context["form"]["editor_context"].value(),
        "solution-body_source": "A square is nonnegative.",
    }, follow=True)
    assert response.status_code == HTTPStatus.OK
    assert "Your solution is saved." in response.content.decode()
    progress = guide(client)
    assert progress["completed_steps"] == SAVED_STEPS
    assert not progress["shared"]
    assert not SolutionPublicShare.objects.exists()

    share = create_share(client, solution)
    progress = guide(client)
    assert progress["completed_steps"] == SAVED_STEPS
    assert progress["shared"]
    assert "Your public link is ready." in client.get(editor_url).content.decode()
    assert Client().get(reverse("solutions:public_solution", args=[share.token])).status_code == HTTPStatus.OK
    solution.refresh_from_db()
    assert solution.status == ProblemSolution.Status.DRAFT
    assert solution.published_at is None
    assert solution.submitted_at is None
    assert not UserProblemCompletion.objects.exists()

    # Stopping optional sharing does not undo getting started.
    share.is_active = False
    share.save(update_fields=["is_active"])
    progress = guide(client)
    assert progress["completed_steps"] == SAVED_STEPS
    assert not progress["shared"]


@pytest.mark.parametrize("editor_route", ["problem_solution_edit", "problem_solution_list"])
@pytest.mark.parametrize("save_action", ["save_draft", "autosave"])
def test_first_proof_must_be_saved_privately_and_can_resume_on_another_session(
    client, solution, editor_route, save_action,
):
    url = reverse(f"solutions:{editor_route}", args=[solution.problem.problem_uuid])
    editor = client.get(url, {"edit": "1"})
    html = editor.content.decode()
    assert "Save private draft" in html
    assert 'class="btn btn-outline-primary btn-sm d-none" data-publish-after-save="desktop"' in html
    assert 'class="d-sm-none d-none" data-publish-after-save="mobile"' in html
    assert 'id="solution-share-trigger"' not in html
    if editor_route == "problem_solution_edit":
        assert 'id="solution-first-draft-message"' in html
        assert "Start with an idea." in html

    data = solution_payload(client, url, source="My first idea.", action="publish")
    refused = client.post(url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert refused.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "Save a private draft" in refused.json()["error"]
    solution.refresh_from_db()
    assert solution.current_revision_id is None

    saved = client.post(url, {**data, "action": save_action}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert saved.status_code == HTTPStatus.OK
    solution.refresh_from_db()
    assert solution.status == ProblemSolution.Status.DRAFT
    assert solution.published_at is solution.submitted_at is None
    assert not SolutionPublicShare.objects.exists()
    assert not UserProblemCompletion.objects.exists()
    detail_url = reverse("solutions:solution_detail", args=[solution.pk])
    assert client_with_user(UserFactory()).get(detail_url).status_code == HTTPStatus.NOT_FOUND

    returning = client_with_user(solution.author)
    assert "Continue your draft" in returning.get(reverse("solutions:my_solution_list")).content.decode()
    resumed = returning.get(guide(returning)["editor_url"]).content.decode()
    assert "My first idea." in resumed
    assert "Publish solution" in resumed
    assert 'id="solution-share-trigger"' in resumed


def test_saved_guide_names_the_solution_and_prioritizes_resuming(client, solution):
    ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source="A saved proof.")
    response = client.get(reverse("solutions:my_solution_list"))
    panel = response.content.decode().split('id="solution-guide"', 1)[1].split("</section>", 1)[0]
    progress = response.context["solution_guide"]
    assert "Getting started · Complete" in panel
    assert "Pick up where you left off" in panel
    assert "My first proof" in panel
    assert progress["solution_title"] == solution.title
    assert progress["problem_label"] == "GUIDE 2026 P1"
    assert "Problem selected" in panel
    assert "Solution saved" in panel
    assert "Optional" in panel
    assert "Review and share" in panel
    assert "Continue your draft" in panel
    assert f'href="{progress["share_url"]}"' in panel
    assert f'href="{progress["editor_url"]}"' in panel
    assert "Save a private draft" not in panel


def test_shared_guide_shows_link_management_without_extra_required_progress(client, solution):
    ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source="A saved proof.")
    create_share(client, solution)
    response = client.get(reverse("solutions:my_solution_list"))
    panel = response.content.decode().split('id="solution-guide"', 1)[1].split("</section>", 1)[0]
    assert "Getting started · Complete" in panel
    assert "Your public link is ready" in panel
    assert "Public link active" in panel
    assert "Copy or open public link" in panel
    assert "Continue editing" in panel
    assert "Optional" not in panel


def test_pending_writer_guide_focuses_on_the_handoff_instead_of_an_existing_solution(client, solution):
    ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source="A saved proof.")
    staged = client.post(reverse("website:solution_preview"), source_data())
    assert staged.status_code == HTTPStatus.FOUND
    assert ProblemSolution.objects.count() == 1
    token = client.session[WRITER_DRAFT_SESSION_KEY]["token"]
    response = client.get(reverse("solutions:my_solution_list"))
    panel = response.content.decode().split('id="solution-guide"', 1)[1].split("</section>", 1)[0]
    assert "Draft ready to continue" in panel
    assert "Continue your writing" in panel
    assert f'href="{writer_handoff_url()}"' in panel
    assert "My first proof" not in panel
    assert "Review and share" not in panel
    assert client.session[WRITER_DRAFT_SESSION_KEY]["token"] == token


@pytest.mark.parametrize("title", ["  ", "<script>Example title</script>"])
def test_guide_solution_label_has_safe_title_and_problem_fallback(client, solution, title):
    solution.title = title
    solution.save(update_fields=["title"])
    response = client.get(reverse("solutions:my_solution_list"))
    panel = response.content.decode().split('id="solution-guide"', 1)[1].split("</section>", 1)[0]
    if title.strip():
        assert "&lt;script&gt;Example title&lt;/script&gt;" in panel
        assert title not in panel
    else:
        assert response.context["solution_guide"]["solution_title"] == "GUIDE 2026 P1"
        assert panel.count("GUIDE 2026 P1") == 1


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


def test_guide_prioritizes_private_draft_over_newer_shared_work(client, solution):
    ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source="My private draft.")
    other_problem = ProblemSolveRecord.objects.create(contest="GUIDE", year=2026, problem="P2", topic="ALG")
    shared = ProblemSolution.objects.create(author=solution.author, problem=other_problem)
    ProblemSolutionBlock.objects.create(solution=shared, position=1, body_source="A different proof.")
    create_share(client, shared)
    progress = guide(client)
    assert progress["private_draft"]
    assert not progress["shared"]
    assert progress["editor_url"] == reverse("solutions:problem_solution_edit", args=[solution.problem.problem_uuid])


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
        saved_editor_data(solution, body=""),
    )
    assert response.context["form"].errors
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
