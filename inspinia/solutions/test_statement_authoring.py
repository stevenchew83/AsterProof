"""Every active statement can open a private solution under its existing UUID."""

from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions.models import ProblemSolution
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace(client):
    user = UserFactory()
    client.force_login(user)
    statement = ContestProblemStatement.objects.create(
        contest_name="Standalone Cup", contest_year=2025, problem_number=1, problem_code="P1",
        day_label="Day 1", statement_latex="Prove $n=n$.",
    )
    return client, user, statement


def start_url(statement):
    return reverse("solutions:statement_solution_start", args=[statement.statement_uuid])


def test_start_uses_existing_statement_identity_and_preserves_unknown_metadata(workspace):
    client, _user, statement = workspace
    identity = statement.problem_uuid
    response = client.post(start_url(statement))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("solutions:problem_solution_edit", args=[identity])
    statement.refresh_from_db()
    problem = ProblemSolveRecord.objects.get()
    assert statement.problem_uuid == identity == problem.problem_uuid
    assert statement.linked_problem_id == problem.pk
    assert problem.mohs is None
    assert problem.topic == ""
    assert ContestProblemStatement.objects.count() == 1
    assert not ProblemSolution.objects.exists()
    editor = client.get(response.url)
    assert editor.status_code == HTTPStatus.OK
    assert editor.context["problem_data"]["statement_entry"].pk == statement.pk
    assert editor.context["problem_data"]["problem_mohs"] is None
    assert "Prove" in editor.content.decode()


def test_repeat_start_reuses_link_and_existing_private_solution(workspace):
    client, user, statement = workspace
    client.post(start_url(statement))
    statement.refresh_from_db()
    solution = ProblemSolution.objects.create(problem=statement.linked_problem, author=user, title="My existing draft")

    response = client.post(start_url(statement), follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].instance.pk == solution.pk
    assert ProblemSolveRecord.objects.count() == 1
    assert ProblemSolution.objects.count() == 1
    assert ContestProblemStatement.objects.count() == 1


def test_start_reuses_uuid_match_without_guessing_from_contest_code(workspace):
    client, _user, statement = workspace
    unrelated = ProblemSolveRecord.objects.create(
        contest=statement.contest_name, year=2025, problem="P1", topic="GEO", mohs=30,
    )
    matching = ProblemSolveRecord.objects.create(
        problem_uuid=statement.problem_uuid, contest=statement.contest_name, year=2025,
        problem="P1", topic="NT", mohs=12,
    )
    client.post(start_url(statement))

    statement.refresh_from_db()
    assert statement.linked_problem_id == matching.pk
    assert statement.linked_problem_id != unrelated.pk
    matching.refresh_from_db()
    assert matching.topic == "NT"
    assert ProblemSolveRecord.objects.count() == len([matching, unrelated])


def test_same_problem_code_in_different_rounds_keeps_distinct_identities(workspace):
    client, _user, first = workspace
    second = ContestProblemStatement.objects.create(
        contest_name=first.contest_name, contest_year=2025, problem_number=1, problem_code="P1",
        day_label="Day 2", statement_latex="A different problem.",
    )
    client.post(start_url(first))
    client.post(start_url(second))
    first.refresh_from_db()
    second.refresh_from_db()

    assert first.problem_uuid != second.problem_uuid
    assert first.linked_problem_id != second.linked_problem_id
    assert first.linked_problem.problem_uuid == first.problem_uuid
    assert second.linked_problem.problem_uuid == second.problem_uuid


def test_statement_metadata_is_copied_without_truncation_or_invented_difficulty(workspace):
    client, _user, statement = workspace
    statement.contest_name = "A" * 128
    statement.topic = "NT"
    statement.mohs = 0
    statement.save()
    client.post(start_url(statement))
    statement.refresh_from_db()
    problem = statement.linked_problem

    assert problem.contest == statement.contest_name
    assert problem.contest_year_problem == statement.contest_year_problem
    assert problem.topic == "NT"
    assert problem.mohs == 0


def test_reading_papers_and_getting_start_route_do_not_create_problem_or_solution(workspace):
    client, _user, statement = workspace
    paper = client.get(reverse("pages:contest_papers"), {"contest": statement.contest_name, "year": 2025})
    assert paper.status_code == HTTPStatus.OK
    assert client.get(start_url(statement)).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert not ProblemSolveRecord.objects.exists()
    assert not ProblemSolution.objects.exists()


def test_start_enforces_csrf(workspace):
    _client, user, statement = workspace
    guarded = Client(enforce_csrf_checks=True)
    guarded.force_login(user)

    assert guarded.post(start_url(statement)).status_code == HTTPStatus.FORBIDDEN
    assert not ProblemSolveRecord.objects.exists()


@pytest.mark.parametrize("approved", [True, False])
def test_start_preserves_authentication_and_approval_gate(workspace, approved):
    _client, _user, statement = workspace
    guarded = Client()
    if not approved:
        guarded.force_login(UserFactory(is_approved=False))

    response = guarded.post(start_url(statement))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("account_login") if approved else reverse("users:approval_pending"))
    assert not ProblemSolveRecord.objects.exists()


def test_inactive_statement_cannot_start_solution(workspace):
    client, _user, statement = workspace
    statement.is_active = False
    statement.save()

    assert client.post(start_url(statement)).status_code == HTTPStatus.NOT_FOUND
    assert not ProblemSolveRecord.objects.exists()


def test_standalone_statement_can_save_private_solution_and_use_progress_pages(workspace):
    client, user, statement = workspace
    editor_url = client.post(start_url(statement)).url
    saved = client.post(editor_url, {
        "action": "save_draft", "solution-title": "My standalone proof", "solution-summary": "",
        "blocks-TOTAL_FORMS": "1", "blocks-INITIAL_FORMS": "0", "blocks-0-ORDER": "1",
        "blocks-0-block_type": "", "blocks-0-title": "", "blocks-0-body_format": "latex",
        "blocks-0-body_source": "$n=n$",
    })

    assert saved.status_code == HTTPStatus.FOUND
    solution = ProblemSolution.objects.get(author=user)
    assert solution.problem.problem_uuid == statement.problem_uuid
    assert solution.status == ProblemSolution.Status.DRAFT
    assert solution.blocks.get().body_source == "$n=n$"
    assert not hasattr(solution, "public_share")
    UserProblemCompletion.objects.create(user=user, problem=solution.problem, statement=statement, status="written")
    for route in ("pages:user_activity_dashboard", "pages:my_completion_progress_analytics"):
        response = client.get(reverse(route))
        assert response.status_code == HTTPStatus.OK
    assert client.get(reverse("pages:completion_record_list")).status_code == HTTPStatus.FORBIDDEN
