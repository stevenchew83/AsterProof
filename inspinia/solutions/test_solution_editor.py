"""Canonical source context and validation for the solution workspace."""

from http import HTTPStatus

import pytest
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionBlockType
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def editor(client):
    user = UserFactory()
    client.force_login(user)
    problem = ProblemSolveRecord.objects.create(
        contest="WORKSPACE TEST", year=2026, problem="A1", topic="ALG", mohs=30,
    )
    url = reverse("solutions:problem_solution_edit", args=[problem.problem_uuid])
    return client, problem, url


def linked_statement(problem):
    return ContestProblemStatement.objects.create(
        linked_problem=problem, contest_name=problem.contest, contest_year=problem.year,
        problem_code="A1", problem_number=1, topic="A", statement_latex="Prove the inequality.",
    )


def test_editor_canonical_coverage_combines_roles_and_preserves_held_captions(editor):
    client, problem, url = editor
    row = linked_statement(problem)
    StatementTopicTechnique.objects.create(
        statement=row, technique="AM-GM", main_topic="ALG", domains=["ALG"],
        technique_tags=["AM-GM"], lemma_theorem_tags=["AM-GM"],
    )
    StatementTopicTechnique.objects.create(
        statement=row, technique="MATRIX METHOD", main_topic="ALG", domains=["ALG"],
        technique_tags=["MATRIX METHOD"],
    )
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    coverage = response.context["editor_coverage"]
    assert [c["id"] for c in coverage["concept_coverage"]] == ["am-gm"]
    assert coverage["concept_coverage"][0]["roles"] == ["lemma", "method", "technique"]
    assert coverage["concept_areas"] == ["Inequalities and optimization"]
    assert coverage["concept_review_labels"] == ["MATRIX METHOD (method, technique)"]
    html = response.content.decode()
    assert html.count('class="solution-concept"') == 1
    assert "?q=AM-GM" in html
    assert "MATRIX METHOD" in html
    assert not ProblemSolution.objects.exists()


def test_editor_uses_problem_tags_without_creating_a_statement_or_solution(editor):
    client, problem, url = editor
    ProblemTopicTechnique.objects.create(
        record=problem, technique="SUBSTITUTION", main_topic="ALG", domains=["ALG"],
        technique_tags=["SUBSTITUTION"],
    )
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert [c["id"] for c in response.context["editor_coverage"]["concept_coverage"]] == ["substitution"]
    assert "No linked statement is available" in response.content.decode()
    assert not ContestProblemStatement.objects.exists()
    assert not ProblemSolution.objects.exists()


def test_editor_suppressed_statement_tags_block_linked_problem_fallback(editor):
    client, problem, url = editor
    ProblemTopicTechnique.objects.create(record=problem, technique="AM-GM", domains=["ALG"])
    row = linked_statement(problem)
    StatementTopicTechnique.objects.create(
        statement=row, technique="CORRUPT SOURCE", main_topic="ALG", domains=["ALG"],
        normalization_status="invalid",
    )
    response = client.get(url)
    coverage = response.context["editor_coverage"]
    assert coverage["concept_coverage"] == []
    assert coverage["concept_source_tags"] == ["CORRUPT SOURCE"]
    assert "No confirmed concepts yet" in response.content.decode()


def test_editor_invalid_publish_retains_input_and_exposes_validation(editor):
    client, _problem, url = editor
    proof = SolutionBlockType.objects.get(slug="proof")
    response = client.post(url, {
        "action": "publish", "solution-title": "My unfinished argument", "solution-summary": "Keep this idea.",
        "blocks-TOTAL_FORMS": "1", "blocks-INITIAL_FORMS": "0", "blocks-MIN_NUM_FORMS": "0",
        "blocks-MAX_NUM_FORMS": "1000", "blocks-0-id": "", "blocks-0-ORDER": "1",
        "blocks-0-block_type": str(proof.pk), "blocks-0-title": "Still working", "blocks-0-body_format": "latex",
        "blocks-0-body_source": "",
    })
    assert response.status_code == HTTPStatus.OK
    assert response.context["formset"].errors
    html = response.content.decode()
    assert "My unfinished argument" in html
    assert "Keep this idea." in html
    assert "Still working" in html
    assert "This field is required." in html
    assert 'data-has-errors="true"' in html
    assert 'data-bound="true"' in html
    assert not ProblemSolution.objects.exists()
