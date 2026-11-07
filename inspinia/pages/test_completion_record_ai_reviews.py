import uuid
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.views import ADMIN_TABLE_LATEST_LIMIT
from inspinia.solutions import forum
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_reviews import problem_label
from inspinia.solutions.document_source import source_digest
from inspinia.solutions.models import ProblemSolution
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def inventory(client):
    client.force_login(UserFactory(role="admin"))
    return reverse("pages:completion_record_list")


@pytest.fixture
def author():
    return UserFactory()


def _proof(author, number):
    code = f"P{number}"
    problem = ProblemSolveRecord.objects.create(contest="IMO", year=2026, problem=code)
    statement = ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_name="IMO",
        contest_year=2026,
        problem_code=code,
        problem_number=number,
        statement_latex="Prove that a square is nonnegative.",
    )
    completion = UserProblemCompletion.objects.create(user=author, statement=statement)
    solution = ProblemSolution.objects.create(problem=problem, author=author, status=ProblemSolution.Status.SUBMITTED)
    solution.blocks.create(position=1, body_source="A square is nonnegative.")
    return solution, completion


def _review(solution, score):
    target = forum._target(solution, {"target_key": forum.current_target_data(solution)["key"]})  # noqa: SLF001
    return AdminSolutionReview.objects.create(
        target=target,
        solver=solution.author,
        problem_label=problem_label(solution),
        batch_id=uuid.uuid4(),
        key_version=uuid.uuid4(),
        model="gpt-6.1-sol",
        output_limit=1000,
        status=AdminSolutionReview.Status.COMPLETED,
        score=score,
        feedback="Private draft feedback.",
    )


def _review_cells(response):
    return {row["completion_id"]: row.get("ai_review") for row in response.context["completion_record_rows"]}


def test_review_column_uses_own_solution_and_published_score(client, inventory, author):
    solution, completion = _proof(author, 1)
    other = UserFactory()
    no_solution = UserProblemCompletion.objects.create(user=other, problem=solution.problem)
    draft = _review(solution, 0)

    response = client.get(inventory)
    cells = _review_cells(response)
    assert cells[completion.pk]["label"] == "Draft ready"
    assert cells[completion.pk]["score"] == 0
    assert cells[completion.pk]["url"] == reverse("solutions:solution_detail", args=[solution.pk]) + "#ai-review"
    assert cells[no_solution.pk] is None
    assert b"Private draft feedback." not in response.content

    _review(solution, 7)
    cells = _review_cells(client.get(inventory, {"ai_review": "draft_ready"}))
    assert cells[completion.pk]["label"] == "2 drafts ready"
    assert cells[completion.pk]["score"] is None

    draft.published_at = timezone.now()
    draft.save(update_fields=["published_at"])
    cells = _review_cells(client.get(inventory))
    assert cells[completion.pk]["label"] == "Published"
    assert cells[completion.pk]["score"] == 0
    assert _review_cells(client.get(inventory, {"ai_review": "draft_ready"})) == {}

    revised_source = "The sum is nonnegative because each summand is a square."
    solution.current_revision = solution.revisions.create(
        sequence=1, body_source=revised_source, source_digest=source_digest(revised_source),
    )
    solution.edit_version += 1
    solution.save()
    revised_review = _review(solution, 4)
    cells = _review_cells(client.get(inventory, {"ai_review": "draft_ready"}))
    assert cells[completion.pk]["label"] == "Draft ready"
    assert cells[completion.pk]["score"] == revised_review.score


def test_draft_filter_finds_older_match_and_excludes_changed_targets(client, inventory, author):
    ready, ready_completion = _proof(author, 1)
    changed_statement, stale_completion = _proof(author, 2)
    changed_proof, edited_completion = _proof(author, 3)
    for solution in (ready, changed_statement, changed_proof):
        _review(solution, 6)
    # Both edits change the target key even when the solution timestamp is untouched.
    stale_completion.statement.statement_latex = "Find all equality cases."
    stale_completion.statement.save(update_fields=["statement_latex"])
    changed_proof.blocks.update(body_source="An updated proof.")
    cells = _review_cells(client.get(inventory))
    for completion in (stale_completion, edited_completion):
        assert cells[completion.pk]["label"] == "Earlier version"
        assert cells[completion.pk]["score"] is None

    newer = ProblemSolveRecord.objects.bulk_create(
        [
            ProblemSolveRecord(contest="IMO", year=2026, problem=f"Q{number}")
            for number in range(ADMIN_TABLE_LATEST_LIMIT)
        ],
    )
    UserProblemCompletion.objects.bulk_create(
        [UserProblemCompletion(user=author, problem=problem) for problem in newer],
    )
    UserProblemCompletion.objects.filter(pk=ready_completion.pk).update(updated_at=timezone.now() - timedelta(days=1))
    assert ready_completion.pk not in _review_cells(client.get(inventory))

    response = client.get(inventory, {"ai_review": "draft_ready", "user": author.email})
    assert list(_review_cells(response)) == [ready_completion.pk]
    assert response.context["completion_record_is_capped"] is False
    assert response.context["completion_record_advanced_filters_open"] is True
    chips = {chip["key"]: chip for chip in response.context["completion_record_active_filters"]}
    assert chips["ai_review"]["value"] == "Draft ready"
    assert "ai_review=" not in chips["ai_review"]["remove_url"]
    assert b'<option value="draft_ready" selected>' in response.content


def test_review_data_and_filter_require_admin_even_in_debug(client, author, settings):
    solution, completion = _proof(author, 1)
    _review(solution, 6)
    client.force_login(UserFactory(role="trainer"))
    url = reverse("pages:completion_record_list")
    assert client.get(url, {"ai_review": "draft_ready"}).status_code == HTTPStatus.FORBIDDEN

    settings.DEBUG = True
    response = client.get(url, {"ai_review": "draft_ready"})
    assert response.status_code == HTTPStatus.OK
    assert _review_cells(response) == {completion.pk: None}
    assert b'name="ai_review"' not in response.content
