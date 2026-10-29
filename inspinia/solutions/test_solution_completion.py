"""Saving a proof and recording a solve use separate explicit requests."""

from datetime import UTC
from datetime import date
from datetime import datetime
from http import HTTPStatus

import pytest
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.completion_record_fields import is_completion_status_solved
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace(client):
    user = UserFactory()
    client.force_login(user)
    problem = ProblemSolveRecord.objects.create(
        contest="SOLUTION COMPLETION TEST", year=2026, problem="P1", topic="ALG", mohs=5,
    )
    return client, user, problem, reverse("solutions:problem_solution_edit", args=[problem.problem_uuid])


def statement_for(problem, *, text="Prove the inequality."):
    return ContestProblemStatement.objects.create(
        linked_problem=problem, contest_name=problem.contest, contest_year=problem.year,
        problem_code="P1", problem_number=1, topic="ALG", statement_latex=text,
    )


def proof_data(*, action="save", solution=None, body="This completes the proof."):
    block = solution.blocks.get() if solution else None
    return {
        "action": action, "solution-title": "My proof", "solution-summary": "A useful identity.",
        "blocks-TOTAL_FORMS": "1", "blocks-INITIAL_FORMS": "1" if block else "0",
        "blocks-MIN_NUM_FORMS": "0", "blocks-MAX_NUM_FORMS": "1000",
        "blocks-0-id": str(block.pk) if block else "", "blocks-0-ORDER": "1",
        "blocks-0-block_type": str(SolutionBlockType.objects.get(slug="proof").pk),
        "blocks-0-title": "Proof", "blocks-0-body_format": "latex", "blocks-0-body_source": body,
    }


def save_then_mark_solved(client, problem, url, data, *, follow=False):
    saved = client.post(url, data)
    if saved.status_code != HTTPStatus.FOUND:
        return saved
    # Saving alone must never change completion; the second POST is explicit.
    params = {"action": "mark_solved", "problem_uuid": str(problem.problem_uuid)}
    statement = ContestProblemStatement.objects.filter(linked_problem=problem).first()
    if statement:
        params["statement_uuid"] = str(statement.statement_uuid)
    if data.get("completion_timezone"):
        params["completion_timezone"] = data["completion_timezone"]
    completion = client.post(reverse("pages:completion_board_toggle"), params)
    assert completion.status_code == HTTPStatus.OK
    return client.get(url) if follow else saved


@pytest.mark.parametrize("has_statement", [True, False])
def test_save_and_solve_saves_proof_and_own_progress_without_publishing(workspace, has_statement):
    client, user, problem, url = workspace
    statement = statement_for(problem) if has_statement else None
    other_user = UserFactory()
    other = UserProblemCompletion.objects.create(
        user=other_user, statement=statement, problem=None if statement else problem,
        status=UserProblemCompletion.Status.ATTEMPTED,
    )
    data = {**proof_data(), "user_id": str(other_user.pk)}

    response = save_then_mark_solved(client, problem, url, data, follow=True)

    assert response.status_code == HTTPStatus.OK
    solution = ProblemSolution.objects.get(author=user, problem=problem)
    assert solution.blocks.get().body_source == data["blocks-0-body_source"]
    assert solution.status == ProblemSolution.Status.DRAFT
    assert solution.published_at is None
    completion = UserProblemCompletion.objects.get(user=user)
    assert completion.statement == statement
    assert completion.problem == (None if statement else problem)
    assert completion.status == UserProblemCompletion.Status.SOLVED
    assert completion.completion_date == timezone.localdate()
    assert "Saved changes." in response.content.decode()
    assert response.context["completion_state"]["is_solved"] is True
    assert reverse("pages:my_completion_progress_analytics") in response.content.decode()
    progress = client.get(reverse("pages:my_completion_progress_analytics"))
    assert progress.context["completion_progress_stats"]["solved_total"] == 1
    other.refresh_from_db()
    assert other.status == UserProblemCompletion.Status.ATTEMPTED
    assert other.completion_date is None

    save_then_mark_solved(client, problem, url, proof_data(solution=solution))
    assert UserProblemCompletion.objects.filter(user=user).count() == 1
    assert solution.blocks.count() == 1


@pytest.mark.parametrize("action", ["save", "save_draft", "publish"])
def test_normal_solution_actions_do_not_record_a_solve(workspace, action):
    client, user, problem, url = workspace
    statement_for(problem)

    response = client.post(url, proof_data(action=action))

    assert response.status_code == HTTPStatus.FOUND
    assert ProblemSolution.objects.filter(author=user, problem=problem).exists()
    assert not UserProblemCompletion.objects.exists()


def test_saving_a_draft_after_a_solve_preserves_progress(workspace):
    client, user, problem, url = workspace
    save_then_mark_solved(client, problem, url, proof_data())
    solution = ProblemSolution.objects.get(author=user, problem=problem)
    completion = UserProblemCompletion.objects.get(user=user)

    client.post(url, proof_data(action="save_draft", solution=solution, body="A revised proof."))

    solution.refresh_from_db()
    completion.refresh_from_db()
    assert solution.status == ProblemSolution.Status.DRAFT
    assert solution.blocks.get().body_source == "A revised proof."
    assert completion.status == UserProblemCompletion.Status.SOLVED
    assert completion.completion_date == timezone.localdate()


@pytest.mark.parametrize("status", UserProblemCompletion.Status.values)
@pytest.mark.parametrize("existing_date", [None, date(2026, 1, 2)])
def test_save_and_solve_preserves_existing_dates_status_advances_and_study_details(workspace, status, existing_date):
    client, user, problem, url = workspace
    statement = statement_for(problem)
    details = {
        "time_spent_minutes": 45, "first_idea_found": True, "proof_completed": False,
        "main_obstacle": "proof_rigor", "key_technique": "Sum of squares", "post_mortem": "Check equality.",
        "reattempt_date": date(2027, 1, 1), "confidence": "medium",
    }
    completion = UserProblemCompletion.objects.create(
        user=user, statement=statement, status=status, completion_date=existing_date, **details,
    )

    response = save_then_mark_solved(client, problem, url, proof_data())

    assert response.status_code == HTTPStatus.FOUND
    completion.refresh_from_db()
    already_solved = is_completion_status_solved(status)
    assert completion.status == (status if already_solved else UserProblemCompletion.Status.SOLVED)
    assert completion.completion_date == (existing_date if already_solved else existing_date or timezone.localdate())
    for key, value in details.items():
        assert getattr(completion, key) == value


def test_save_and_solve_preserves_legacy_completion_details(workspace):
    client, user, problem, url = workspace
    statement = statement_for(problem)
    legacy = UserProblemCompletion.objects.create(
        user=user, problem=problem, status=UserProblemCompletion.Status.CHECKED,
        completion_date=date(2026, 1, 2), key_technique="An invariant", post_mortem="Try a second proof.",
    )

    save_then_mark_solved(client, problem, url, proof_data())

    completion = UserProblemCompletion.objects.get(user=user, statement=statement)
    assert completion.status == legacy.status
    assert completion.completion_date == legacy.completion_date
    assert completion.key_technique == legacy.key_technique
    assert completion.post_mortem == legacy.post_mortem


def test_save_and_solve_follows_duplicate_completion_rules_without_rewriting_prior_solves(workspace):
    client, user, problem, url = workspace
    statement = statement_for(problem)
    duplicate = ContestProblemStatement.objects.create(
        contest_name="DUPLICATE TEST", contest_year=2025, problem_code="P2", problem_number=2,
        statement_latex=statement.statement_latex,
    )
    prior = UserProblemCompletion.objects.create(
        user=user, statement=duplicate, status=UserProblemCompletion.Status.WRITTEN,
        completion_date=date(2025, 5, 6), key_technique="My earlier approach",
    )

    save_then_mark_solved(client, problem, url, proof_data())

    completion = UserProblemCompletion.objects.get(user=user, statement=statement)
    assert completion.status == UserProblemCompletion.Status.SOLVED
    prior.refresh_from_db()
    assert prior.status == UserProblemCompletion.Status.WRITTEN
    assert prior.completion_date == date(2025, 5, 6)
    assert prior.key_technique == "My earlier approach"


def test_save_and_solve_records_a_completion_for_an_empty_linked_statement(workspace):
    client, user, problem, url = workspace
    statement = statement_for(problem, text="")

    save_then_mark_solved(client, problem, url, proof_data())

    completion = UserProblemCompletion.objects.get(user=user, statement=statement)
    assert completion.status == UserProblemCompletion.Status.SOLVED


def test_save_and_solve_uses_the_browser_local_date(workspace, monkeypatch):
    client, user, problem, url = workspace
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 10, 29, 17, tzinfo=UTC))

    save_then_mark_solved(client, problem, url, {**proof_data(), "completion_timezone": "America/New_York"})

    assert UserProblemCompletion.objects.get(user=user).completion_date == date(2026, 10, 29)


def test_save_and_solve_invalid_proof_changes_neither_solution_nor_progress(workspace):
    client, _user, problem, url = workspace
    statement_for(problem)

    response = client.post(url, proof_data(body=""))

    assert response.status_code == HTTPStatus.OK
    assert response.context["formset"].errors
    assert not ProblemSolution.objects.exists()
    assert not UserProblemCompletion.objects.exists()


@pytest.mark.parametrize("existing_solution", [True, False])
def test_completion_failure_preserves_saved_proof(workspace, monkeypatch, existing_solution):
    from inspinia.pages import views

    client, user, problem, url = workspace
    statement = statement_for(problem)
    solution = None
    if existing_solution:
        solution = ProblemSolution.objects.create(problem=problem, author=user, title="Earlier draft")
        ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source="Earlier argument")
        completion = UserProblemCompletion.objects.create(
            user=user, statement=statement, status=UserProblemCompletion.Status.ATTEMPTED,
            key_technique="An earlier idea",
        )
    mark_solved = views.mark_problem_solved

    def fail_after_completion(**kwargs):
        mark_solved(**kwargs)
        msg = "Simulated completion failure"
        raise DatabaseError(msg)

    monkeypatch.setattr(views, "mark_problem_solved", fail_after_completion)
    with pytest.raises(DatabaseError, match="Simulated completion failure"):
        save_then_mark_solved(client, problem, url, proof_data(solution=solution))

    if existing_solution:
        solution.refresh_from_db()
        assert solution.title == "My proof"
        assert solution.blocks.get().body_source == "This completes the proof."
        completion.refresh_from_db()
        assert completion.status == UserProblemCompletion.Status.ATTEMPTED
        assert completion.completion_date is None
        assert completion.key_technique == "An earlier idea"
    else:
        saved = ProblemSolution.objects.get(author=user, problem=problem)
        assert saved.blocks.get().body_source == "This completes the proof."
        assert not UserProblemCompletion.objects.filter(user=user, statement=statement).exists()


def test_editor_does_not_label_an_attempt_as_solved(workspace):
    client, user, problem, url = workspace
    UserProblemCompletion.objects.create(user=user, problem=problem, status=UserProblemCompletion.Status.ATTEMPTED)

    response = client.get(url)

    assert response.context["completion_state"]["is_solved"] is False
    html = response.content.decode()
    assert 'value="save_and_solve"' not in html
    assert 'type="button" id="solution-mark-solved"' in html
    assert 'value="save_draft"' in html
    assert 'id="solution-save"' in html


@pytest.mark.parametrize("saved", [True, False])
def test_marking_solved_never_saves_browser_proof_fields(workspace, saved):
    client, user, problem, url = workspace
    statement = statement_for(problem)
    solution = None
    if saved:
        client.post(url, proof_data())
        solution = ProblemSolution.objects.get(author=user, problem=problem)
        previous_updated_at = solution.updated_at
    payload = {
        **proof_data(solution=solution, body="Unsaved browser edit"),
        "action": "mark_solved", "problem_uuid": str(problem.problem_uuid),
        "statement_uuid": str(statement.statement_uuid),
    }

    response = client.post(reverse("pages:completion_board_toggle"), payload)

    assert response.status_code == HTTPStatus.OK
    assert response.json()["is_solved"] is True
    assert UserProblemCompletion.objects.filter(user=user).count() == 1
    if saved:
        solution.refresh_from_db()
        assert solution.blocks.get().body_source == "This completes the proof."
        assert solution.updated_at == previous_updated_at
    else:
        assert not ProblemSolution.objects.exists()


def test_legacy_combined_save_action_no_longer_records_a_solve(workspace):
    client, user, problem, url = workspace
    response = client.post(url, proof_data(action="save_and_solve"))
    assert response.status_code == HTTPStatus.FOUND
    assert ProblemSolution.objects.filter(author=user, problem=problem).exists()
    assert not UserProblemCompletion.objects.filter(user=user).exists()


def test_completion_action_requires_an_approved_authenticated_user(workspace):
    client, user, problem, _url = workspace
    endpoint = reverse("pages:completion_board_toggle")
    payload = {"action": "mark_solved", "problem_uuid": str(problem.problem_uuid)}
    client.logout()
    response = client.post(endpoint, payload)
    assert response.status_code == HTTPStatus.FOUND
    assert reverse("account_login") in response.url
    client.force_login(user)
    user.is_approved = False
    user.save(update_fields=["is_approved"])
    response = client.post(endpoint, payload)
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("users:approval_pending")
    assert not UserProblemCompletion.objects.filter(user=user).exists()


@pytest.mark.parametrize("status", [ProblemSolution.Status.DRAFT, ProblemSolution.Status.PUBLISHED])
def test_saved_solution_links_describe_drafts_and_published_work(workspace, status):
    client, user, problem, _url = workspace
    ProblemSolution.objects.create(problem=problem, author=user, title="My saved proof", status=status)

    response = client.get(reverse("solutions:problem_solution_list", args=[problem.problem_uuid]))

    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert "Edit my solution" in html
    assert "Open my solution" in html
    assert "Edit my draft" not in html
    assert "Open my draft" not in html
    assert ProblemSolution.Status(status).label in html
