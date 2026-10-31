"""Canonical source context and validation for the solution workspace."""

from http import HTTPStatus
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
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


def test_problem_page_uses_the_full_editor_workspace(editor):
    client, problem, _url = editor
    response = client.get(reverse("solutions:problem_solution_list", args=[problem.problem_uuid]))
    html = response.content.decode()
    templates = {template.name for template in response.templates}
    assert "solutions/partials/solution-editor-toolbar.html" in templates
    assert "solutions/partials/solution-editor-workspace.html" in templates
    assert "solutions/partials/solution-block-form.html" in templates
    assert html.count('id="solution-editor-form"') == 1
    assert html.count("js/solution-editor.js") == 1
    assert html.count("js/solution-latex-hybrid.js") == 1
    assert response.context["solution_body_image_upload_url"] == reverse(
        "solutions:solution_body_image_upload", args=[problem.problem_uuid],
    )
    assert 'data-editor-view="preview"' in html
    assert 'id="solution-add-block"' in html
    assert 'data-insert-math="display"' in html
    assert 'name="solution-pdf_options_present"' in html
    assert not ProblemSolution.objects.exists()


def test_problem_page_edits_only_the_current_users_solution(editor):
    client, problem, url = editor
    client.post(url, solution_payload())
    own = ProblemSolution.objects.get(problem=problem)
    other = ProblemSolution.objects.create(problem=problem, author=UserFactory(), title="Other private draft")
    page_url = reverse("solutions:problem_solution_list", args=[problem.problem_uuid])
    response = client.get(page_url, {"edit": "1", "solution": str(other.pk)})
    assert response.status_code == HTTPStatus.OK
    assert response.context["inline_draft_form"].instance.pk == own.pk
    assert response.context["show_inline_draft_editor"]
    html = response.content.decode()
    assert "First argument" in html
    assert "Other private draft" not in html
    assert "PDF · saved version" in html
    assert "data-share-url=" in html


def solution_payload():
    return {
        "action": "save_draft", "solution-title": "My proof", "solution-summary": "Two steps.",
        "solution-pdf_options_present": "1", "solution-pdf_show_date": "on",
        "blocks-TOTAL_FORMS": "2", "blocks-INITIAL_FORMS": "0", "blocks-MIN_NUM_FORMS": "0",
        "blocks-MAX_NUM_FORMS": "1000", "blocks-0-id": "", "blocks-0-ORDER": "2",
        "blocks-0-block_type": "", "blocks-0-title": "First argument", "blocks-0-body_format": "latex",
        "blocks-0-body_source": "$a=b$", "blocks-1-id": "", "blocks-1-ORDER": "1",
        "blocks-1-block_type": "", "blocks-1-title": "Opening", "blocks-1-body_format": "plain_text",
        "blocks-1-body_source": "Start here.",
    }


@pytest.mark.parametrize("route", ["problem_solution_list", "problem_solution_edit"])
def test_shared_editor_saves_multiple_blocks_after_clipboard_upload(editor, route):
    client, problem, _url = editor
    image = BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, format="PNG")
    uploaded = client.post(reverse("solutions:solution_body_image_upload", args=[problem.problem_uuid]), {
        "image": SimpleUploadedFile("clipboard.png", image.getvalue(), content_type="image/png"),
    })
    assert uploaded.status_code == HTTPStatus.OK
    draft = ProblemSolution.objects.get(problem=problem)
    payload = solution_payload()
    payload["blocks-0-body_source"] += "\\includegraphics{" + uploaded.json()["path"] + "}"
    response = client.post(reverse(f"solutions:{route}", args=[problem.problem_uuid]), payload)
    assert response.status_code == HTTPStatus.FOUND
    draft.refresh_from_db()
    assert ProblemSolution.objects.filter(problem=problem).count() == 1
    assert draft.status == ProblemSolution.Status.DRAFT
    assert draft.pdf_show_date
    assert not draft.pdf_show_author
    assert not draft.pdf_show_footer
    blocks = list(draft.blocks.order_by("position"))
    assert [block.title for block in blocks] == ["Opening", "First argument"]
    assert uploaded.json()["path"] in blocks[1].body_source
    assert not problem.user_completions.exists()


def test_problem_page_validation_keeps_every_block_and_its_controls(editor):
    client, problem, _url = editor
    payload = solution_payload()
    payload["blocks-1-body_source"] = ""
    response = client.post(reverse("solutions:problem_solution_list", args=[problem.problem_uuid]), payload)
    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert 'name="blocks-1-body_source"' in html
    assert "First argument" in html
    assert "Opening" in html
    assert "This field is required." in html
    assert 'data-bound="true"' in html
    assert response.context["show_inline_draft_editor"]
    assert not ProblemSolutionBlock.objects.exists()


def test_problem_page_can_update_reorder_remove_and_publish_existing_blocks(editor):
    client, problem, _url = editor
    url = reverse("solutions:problem_solution_list", args=[problem.problem_uuid])
    assert client.post(url, solution_payload()).status_code == HTTPStatus.FOUND
    solution = ProblemSolution.objects.get(problem=problem)
    opening, argument = solution.blocks.order_by("position")
    payload = solution_payload()
    payload.update({
        "action": "publish", "blocks-INITIAL_FORMS": "2", "blocks-TOTAL_FORMS": "3",
        "blocks-0-id": str(argument.pk), "blocks-0-DELETE": "on",
        "blocks-1-id": str(opening.pk), "blocks-1-ORDER": "2", "blocks-1-body_source": "Updated opening.",
        "blocks-2-id": "", "blocks-2-ORDER": "1", "blocks-2-block_type": "",
        "blocks-2-title": "New first block", "blocks-2-body_format": "latex", "blocks-2-body_source": "$x=y$",
    })
    assert client.post(url, payload).status_code == HTTPStatus.FOUND
    solution.refresh_from_db()
    assert solution.status == ProblemSolution.Status.PUBLISHED
    assert list(solution.blocks.order_by("position").values_list("title", "body_source")) == [
        ("New first block", "$x=y$"), ("Opening", "Updated opening."),
    ]
    assert not ProblemSolutionBlock.objects.filter(pk=argument.pk).exists()
    assert not problem.user_completions.exists()
