"""Canonical source context and validation for the solution workspace."""

from http import HTTPStatus
from io import BytesIO
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def editor(client):
    user = UserFactory()
    client.force_login(user)
    problem = ProblemSolveRecord.objects.create(
        contest="WORKSPACE TEST",
        year=2026,
        problem="A1",
        topic="ALG",
        mohs=30,
    )
    url = reverse("solutions:problem_solution_edit", args=[problem.problem_uuid])
    return client, problem, url


def linked_statement(problem):
    return ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_name=problem.contest,
        contest_year=problem.year,
        problem_code="A1",
        problem_number=1,
        topic="A",
        statement_latex="Prove the inequality.",
    )


def test_editor_canonical_coverage_combines_roles_and_preserves_held_captions(editor):
    client, problem, url = editor
    row = linked_statement(problem)
    StatementTopicTechnique.objects.create(
        statement=row,
        technique="AM-GM",
        main_topic="ALG",
        domains=["ALG"],
        technique_tags=["AM-GM"],
        lemma_theorem_tags=["AM-GM"],
    )
    StatementTopicTechnique.objects.create(
        statement=row,
        technique="MATRIX METHOD",
        main_topic="ALG",
        domains=["ALG"],
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
        record=problem,
        technique="SUBSTITUTION",
        main_topic="ALG",
        domains=["ALG"],
        technique_tags=["SUBSTITUTION"],
    )
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert [c["id"] for c in response.context["editor_coverage"]["concept_coverage"]] == ["substitution"]
    assert "Statement missing." in response.content.decode()
    assert not ContestProblemStatement.objects.exists()
    assert not ProblemSolution.objects.exists()


def test_editor_suppressed_statement_tags_block_linked_problem_fallback(editor):
    client, problem, url = editor
    ProblemTopicTechnique.objects.create(record=problem, technique="AM-GM", domains=["ALG"])
    row = linked_statement(problem)
    StatementTopicTechnique.objects.create(
        statement=row,
        technique="CORRUPT SOURCE",
        main_topic="ALG",
        domains=["ALG"],
        normalization_status="invalid",
    )
    response = client.get(url)
    coverage = response.context["editor_coverage"]
    assert coverage["concept_coverage"] == []
    assert coverage["concept_source_tags"] == ["CORRUPT SOURCE"]
    assert "No confirmed concepts yet" in response.content.decode()


def solution_payload(client, url, *, source="Opening\n\nStart here.\n\nFirst argument\n\n$a=b$", action="save_draft"):
    response = client.get(url, {"edit": "1"})
    form = response.context.get("form") or response.context["inline_draft_form"]
    return {
        "action": action,
        "solution-title": "My proof",
        "solution-summary": "Two steps.",
        "solution-body_source": source,
        "solution-base_version": form["base_version"].value(),
        "solution-editor_context": form["editor_context"].value(),
        "solution-pdf_options_present": "1",
        "solution-pdf_show_date": "on",
    }


def test_editor_invalid_publish_retains_input_and_exposes_validation(editor):
    client, _problem, url = editor
    payload = solution_payload(client, url, source="", action="publish")
    payload.update({"solution-title": "My unfinished argument", "solution-summary": "Keep this idea."})
    response = client.post(url, payload)
    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors
    html = response.content.decode()
    assert "My unfinished argument" in html
    assert "Keep this idea." in html
    assert 'data-bound="true"' in html
    assert not ProblemSolution.objects.exists()


def test_problem_page_uses_the_full_editor_workspace(editor):
    client, problem, _url = editor
    response = client.get(reverse("solutions:problem_solution_list", args=[problem.problem_uuid]))
    html = response.content.decode()
    templates = {template.name for template in response.templates}
    assert "solutions/partials/solution-editor-toolbar.html" in templates
    assert "solutions/partials/solution-editor-workspace.html" in templates
    assert "solutions/partials/solution-block-form.html" not in templates
    assert html.count('id="solution-editor-form"') == 1
    assert html.count("js/solution-document-editor.bundle.js") == 1
    assert response.context["solution_body_image_upload_url"] == reverse(
        "solutions:solution_body_image_upload",
        args=[problem.problem_uuid],
    )
    assert 'data-editor-view="preview"' in html
    assert 'id="solution-add-block"' not in html
    assert 'name="solution-body_source"' in html
    assert 'name="solution-pdf_options_present"' in html
    assert not ProblemSolution.objects.exists()


def test_problem_page_edits_only_the_current_users_solution(editor):
    client, problem, url = editor
    assert client.post(url, solution_payload(client, url)).status_code == HTTPStatus.FOUND
    own = ProblemSolution.objects.get(problem=problem)
    other = ProblemSolution.objects.create(problem=problem, author=UserFactory(), title="Other private draft")
    page_url = reverse("solutions:problem_solution_list", args=[problem.problem_uuid])
    assert client.get(page_url, {"edit": "1", "solution": str(other.pk)}).status_code == HTTPStatus.NOT_FOUND
    response = client.get(page_url, {"edit": "1"})
    assert response.context["inline_draft_form"].instance.pk == own.pk
    assert response.context["show_inline_draft_editor"]
    html = response.content.decode()
    assert "First argument" in html
    assert "Other private draft" not in html
    assert "PDF · saved version" in html
    assert "data-share-url=" in html


@pytest.mark.parametrize("route", ["problem_solution_list", "problem_solution_edit"])
def test_autosave_creates_and_updates_only_private_drafts(editor, route):
    client, problem, _url = editor
    url = reverse(f"solutions:{route}", args=[problem.problem_uuid])
    autosave_url = reverse("solutions:problem_solution_autosave", args=[problem.problem_uuid])
    assert f'data-draft-autosave="{autosave_url}"' in client.get(url).content.decode()
    payload = solution_payload(client, url, action="publish")
    first = client.post(autosave_url, payload)
    assert first.status_code == HTTPStatus.OK
    draft = ProblemSolution.objects.get(problem=problem)
    assert draft.status == ProblemSolution.Status.DRAFT
    assert draft.published_at is draft.submitted_at is None
    assert not problem.user_completions.exists()

    payload["solution-base_version"] = first.json()["edit_version"]
    payload["solution-editor_context"] = first.json()["editor_context"]
    duplicate = client.post(autosave_url, payload)
    assert duplicate.status_code == HTTPStatus.OK
    assert duplicate.json()["edit_version"] == first.json()["edit_version"]
    assert draft.revisions.count() == 1

    payload["solution-body_source"] = "An updated proof."
    updated = client.post(autosave_url, payload)
    assert updated.status_code == HTTPStatus.OK
    assert client.post(autosave_url, payload).status_code == HTTPStatus.CONFLICT
    draft.refresh_from_db()
    assert draft.current_revision.body_source == "An updated proof."
    assert draft.status == ProblemSolution.Status.DRAFT

    payload["solution-base_version"] = updated.json()["edit_version"]
    payload["solution-editor_context"] = updated.json()["editor_context"]
    published = client.post(url, {**payload, "action": "publish"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert published.status_code == HTTPStatus.OK
    assert "data-draft-autosave" not in client.get(url, {"edit": "1"}).content.decode()
    refused = client.post(autosave_url, {
        **payload,
        "solution-base_version": published.json()["edit_version"],
        "solution-editor_context": published.json()["editor_context"],
        "solution-body_source": "This background edit must stay private.",
    })
    assert refused.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    draft.refresh_from_db()
    assert draft.status == ProblemSolution.Status.PUBLISHED
    assert draft.current_revision.body_source == "An updated proof."
    assert draft.revisions.count() == updated.json()["edit_version"]


def test_autosave_invalid_body_returns_json_without_creating_a_draft(editor):
    client, problem, url = editor
    autosave_url = reverse("solutions:problem_solution_autosave", args=[problem.problem_uuid])
    response = client.post(autosave_url, solution_payload(client, url, source=" "))
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["error"] == "Write your solution before saving."
    assert not ProblemSolution.objects.exists()


def test_autosave_requires_post_csrf_and_matching_author(editor):
    client, problem, url = editor
    autosave_url = reverse("solutions:problem_solution_autosave", args=[problem.problem_uuid])
    payload = solution_payload(client, url)
    assert client.get(autosave_url).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert Client().post(autosave_url, payload).status_code == HTTPStatus.FOUND

    other = UserFactory()
    protected_client = Client(enforce_csrf_checks=True)
    protected_client.force_login(other)
    assert protected_client.post(autosave_url, payload).status_code == HTTPStatus.FORBIDDEN
    client.force_login(other)
    assert client.post(autosave_url, payload).status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not ProblemSolution.objects.exists()


@pytest.mark.parametrize("route", ["problem_solution_list", "problem_solution_edit"])
def test_shared_editor_saves_continuous_document_after_clipboard_upload(editor, route):
    client, problem, _url = editor
    url = reverse(f"solutions:{route}", args=[problem.problem_uuid])
    payload = solution_payload(client, url)
    image = BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, format="PNG")
    uploaded = client.post(
        reverse("solutions:solution_body_image_upload", args=[problem.problem_uuid]),
        {
            "image": SimpleUploadedFile("clipboard.png", image.getvalue(), content_type="image/png"),
        },
    )
    assert uploaded.status_code == HTTPStatus.OK
    payload["solution-body_source"] += "\\includegraphics{" + uploaded.json()["path"] + "}"
    response = client.post(url, payload)
    assert response.status_code == HTTPStatus.FOUND
    draft = ProblemSolution.objects.get(problem=problem)
    assert draft.status == ProblemSolution.Status.DRAFT
    assert draft.pdf_show_date
    assert not draft.pdf_show_author
    assert not draft.pdf_show_footer
    assert uploaded.json()["path"] in draft.current_revision.body_source
    assert "Opening" in draft.current_revision.body_source
    assert not draft.blocks.exists()
    assert not problem.user_completions.exists()


def test_old_block_request_recovers_whole_document_without_saving(editor):
    client, problem, url = editor
    response = client.post(
        url,
        {
            "action": "save",
            "solution-title": "Preserved title",
            "blocks-TOTAL_FORMS": "1",
            "blocks-INITIAL_FORMS": "0",
            "blocks-0-body_source": "Original argument",
            "blocks-0-title": "Opening",
            "blocks-0-body_format": "latex",
            "blocks-0-ORDER": "1",
        },
    )
    assert response.status_code == HTTPStatus.OK
    assert "Original argument" in response.content.decode()
    assert "Opening" in response.content.decode()
    assert "Review the recovered document" in response.content.decode()
    assert not ProblemSolution.objects.filter(problem=problem).exists()


def test_document_edit_preserves_frozen_legacy_blocks_and_publishes(editor):
    client, problem, url = editor
    user = get_user_model().objects.get(pk=client.session["_auth_user_id"])
    solution = ProblemSolution.objects.create(problem=problem, author=user)
    block = ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source="Legacy source")
    assert "Legacy source" in client.get(url).content.decode()
    payload = solution_payload(client, url, source="New first paragraph.\n\nUpdated argument.", action="publish")
    assert client.post(url, payload).status_code == HTTPStatus.FOUND
    solution.refresh_from_db()
    block.refresh_from_db()
    assert solution.status == "published"
    assert solution.current_revision.body_source == payload["solution-body_source"]
    assert block.body_source == "Legacy source"
    assert not problem.user_completions.exists()


def test_stale_ajax_save_preserves_both_versions(editor):
    client, problem, url = editor
    first = solution_payload(client, url, source="First version")
    stale = dict(first, **{"solution-body_source": "Other tab"})
    saved = client.post(url, first, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert saved.status_code == HTTPStatus.OK
    assert saved.json()["revision_id"]
    response = client.post(url, stale, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert response.status_code == HTTPStatus.CONFLICT
    assert ProblemSolution.objects.get(problem=problem).current_revision.body_source == "First version"


def test_editor_context_cannot_follow_an_account_switch(editor):
    client, problem, url = editor
    payload = solution_payload(client, url, source="Private proof")
    client.force_login(UserFactory())
    response = client.post(url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not ProblemSolution.objects.filter(problem=problem).exists()


def test_document_write_gate_preserves_submitted_source(editor, settings):
    client, problem, url = editor
    payload = solution_payload(client, url, source="Keep this unsaved proof")
    settings.SOLUTION_DOCUMENT_WRITES_ENABLED = False
    response = client.post(url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert not ProblemSolution.objects.filter(problem=problem).exists()


def test_revision_cannot_be_deleted_without_its_solution(editor):
    from django.core.exceptions import ValidationError

    client, problem, url = editor
    client.post(url, solution_payload(client, url))
    solution = ProblemSolution.objects.get(problem=problem)
    revision = solution.current_revision
    with pytest.raises(ValidationError):
        revision.delete()
    with pytest.raises(ValidationError):
        type(revision).objects.filter(pk=revision.pk).delete()
    solution.delete()
    assert not type(revision).objects.filter(pk=revision.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_first_document_saves_have_one_winner(editor):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections
    from django.db import connection

    from inspinia.solutions.revisions import StaleSolutionVersion
    from inspinia.solutions.revisions import save_document

    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency requires PostgreSQL.")
    client, problem, url = editor
    user = get_user_model().objects.get(pk=client.session["_auth_user_id"])
    payload = solution_payload(client, url)
    barrier = Barrier(2)

    def submit(source):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
            barrier.wait(timeout=10)
            try:
                save_document(
                    solution=ProblemSolution(problem=problem, author=user), user=user, source=source,
                    title="Concurrent proof", summary="", pdf_options={
                        "pdf_show_author": True, "pdf_show_date": True, "pdf_show_footer": True,
                    }, base_version=0, context=payload["solution-editor_context"],
                )
            except StaleSolutionVersion:
                return "conflict"
            return "saved"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(submit, ["First tab proof", "Second tab proof"]))
    assert sorted(results) == ["conflict", "saved"]
    solution = ProblemSolution.objects.get(problem=problem, author=user)
    assert solution.revisions.count() == 1
    assert solution.edit_version == 1
    assert solution.current_revision.body_source in {"First tab proof", "Second tab proof"}


def test_autosave_keeps_two_drafts_of_the_same_problem_separate(editor):
    client, problem, first_editor = editor
    first_autosave = reverse("solutions:problem_solution_autosave", args=[problem.problem_uuid])
    first_response = client.post(first_autosave, solution_payload(client, first_editor, source="First proof."))
    assert first_response.status_code == HTTPStatus.OK
    first = ProblemSolution.objects.get(problem=problem)
    alternate = ProblemSolution.objects.create(
        problem=problem, author=first.author, additional_draft_key=uuid4(),
    )
    args = [problem.problem_uuid, alternate.pk]
    alternate_editor = reverse("solutions:problem_solution_edit", args=args)
    alternate_autosave = reverse("solutions:problem_solution_autosave", args=args)
    assert f'data-draft-autosave="{alternate_autosave}"' in client.get(alternate_editor).content.decode()

    payload = solution_payload(client, alternate_editor, source="Independent second proof.")
    assert client.post(first_autosave, payload).status_code == HTTPStatus.CONFLICT
    assert client.post(alternate_autosave, payload).status_code == HTTPStatus.OK
    first.refresh_from_db()
    alternate.refresh_from_db()
    assert first.current_revision.body_source == "First proof."
    assert alternate.current_revision.body_source == "Independent second proof."
    assert alternate.status == ProblemSolution.Status.DRAFT
