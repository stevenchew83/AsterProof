"""Document metadata choices persist for solutions and apply to public exports."""

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from itertools import product

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.forms import ProblemSolutionForm
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType
from inspinia.solutions.pdf_latex import build_solution_tex_source
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(("author", "date", "footer"), list(product((False, True), repeat=3)))
def test_pdf_metadata_and_footer_are_independently_optional(author, date, footer, tmp_path):
    user = UserFactory(name="Visible author")
    solution = ProblemSolution(
        author=user, updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        pdf_show_author=author, pdf_show_date=date, pdf_show_footer=footer,
    )
    tex = build_solution_tex_source(solution=solution, blocks=[], media_root=tmp_path, problem_label="Proof")
    assert (r"\author{Visible author}" in tex) is author
    assert (r"\date{2026-01-02}" in tex) is date
    assert (r"\ifoot*{}\cfoot*{}\ofoot*{}" in tex) is not footer
    if not author:
        assert r"\author{}" in tex
        assert "Visible author" not in tex
    if not date:
        assert r"\date{}" in tex
        assert "2026-01-02" not in tex
    if not author and not date:
        assert r"\ihead{}" in tex
    elif author != date:
        header = next(line for line in tex.splitlines() if line.startswith(r"\ihead{"))
        assert (r"\theauthor" in header) is author
        assert (r"\thedate" in header) is date
        assert "---" not in header


def _workspace(client):
    user = UserFactory(name="Proof author", is_approved=True)
    client.force_login(user)
    problem = ProblemSolveRecord.objects.create(contest="OPTIONS TEST", year=2026, problem="P1", topic="ALG", mohs=5)
    return user, problem, reverse("solutions:problem_solution_edit", args=[problem.problem_uuid])


def _proof_data():
    return {
        "solution-title": "Proof with options", "solution-summary": "", "solution-pdf_options_present": "1",
        "solution-pdf_show_date": "on", "action": "save",
        "blocks-TOTAL_FORMS": "1", "blocks-INITIAL_FORMS": "0", "blocks-MIN_NUM_FORMS": "0",
        "blocks-MAX_NUM_FORMS": "1000", "blocks-0-ORDER": "1", "blocks-0-title": "",
        "blocks-0-body_format": "latex", "blocks-0-body_source": "This proves the claim.",
        "blocks-0-block_type": str(SolutionBlockType.objects.get(slug="proof").pk),
    }


def test_editor_options_persist_and_control_saved_pdf(client, monkeypatch):
    user, problem, url = _workspace(client)
    response = client.post(url, _proof_data(), follow=True)
    assert response.status_code == HTTPStatus.OK
    solution = ProblemSolution.objects.get(author=user, problem=problem)
    assert (solution.pdf_show_author, solution.pdf_show_date, solution.pdf_show_footer) == (False, True, False)
    assert response.context["form"]["pdf_show_author"].value() is False
    assert response.context["form"]["pdf_show_date"].value() is True
    assert response.context["form"]["pdf_show_footer"].value() is False
    assert response.context["pdf_author_name"] == "Proof author"
    sources = []
    monkeypatch.setattr(
        "inspinia.solutions.pdf_latex.compile_solution_tex_to_pdf",
        lambda source, **kwargs: sources.append(source) or b"%PDF-1.4\n",
    )
    pdf = client.get(reverse("solutions:problem_solution_pdf", args=[problem.problem_uuid]))
    assert pdf.status_code == HTTPStatus.OK
    assert b"".join(pdf.streaming_content).startswith(b"%PDF")
    assert r"\author{}" in sources[0]
    assert "Proof author" not in sources[0]
    assert r"\cfoot*{}" in sources[0]
    assert rf"\date{{{timezone.localdate().isoformat()}}}" in sources[0]


def test_legacy_forms_preserve_saved_display_options(client):
    user, problem, _ = _workspace(client)
    solution = ProblemSolution.objects.create(
        author=user, problem=problem, pdf_show_author=False, pdf_show_date=False, pdf_show_footer=False,
    )
    form = ProblemSolutionForm(
        {"solution-title": "Revised", "solution-summary": ""}, instance=solution, prefix="solution",
    )
    assert form.is_valid()
    form.save()
    solution.refresh_from_db()
    assert (solution.pdf_show_author, solution.pdf_show_date, solution.pdf_show_footer) == (False, False, False)


@pytest.mark.parametrize("enabled", [False, True])
def test_public_options_and_literal_author_apply_without_saving(client, monkeypatch, enabled):
    cache.clear()
    data = {
        "title": "Public proof", "problem_statement": "", "pdf_options_present": "1",
        "author_name": r"Alice & Bob \input{private}",
        "blocks-TOTAL_FORMS": "1", "blocks-INITIAL_FORMS": "0", "blocks-MIN_NUM_FORMS": "0",
        "blocks-MAX_NUM_FORMS": "32", "blocks-0-ORDER": "1", "blocks-0-title": "",
        "blocks-0-body_format": "latex", "blocks-0-body_source": "A proof.",
    }
    if enabled:
        data.update(pdf_show_author="on", pdf_show_date="on", pdf_show_footer="on")
    sources = []
    monkeypatch.setattr(
        "inspinia.website.solution_preview.compile_solution_tex_to_pdf",
        lambda source, **kwargs: sources.append(source) or b"%PDF-1.4\n",
    )
    response = client.post(reverse("website:solution_preview"), data)
    assert response.status_code == HTTPStatus.OK
    response.close()
    assert (r"\author{Alice \& Bob \textbackslash{}input\{private\}}" in sources[0]) is enabled
    assert (rf"\date{{{timezone.localdate().isoformat()}}}" in sources[0]) is enabled
    assert (r"\cfoot*{}" in sources[0]) is not enabled
    assert not ProblemSolution.objects.exists()
    assert not ProblemSolutionBlock.objects.exists()
    cache.clear()


def test_public_invalid_export_preserves_option_values(client):
    response = client.post(reverse("website:solution_preview"), {
        "title": "Keep choices", "author_name": "Alice", "pdf_options_present": "1",
        "pdf_show_author": "on", "blocks-TOTAL_FORMS": "0", "blocks-INITIAL_FORMS": "0",
    })
    assert response.status_code == HTTPStatus.BAD_REQUEST
    form = response.context["form"]
    assert form["pdf_show_author"].value() is True
    assert form["pdf_show_date"].value() is False
    assert form["pdf_show_footer"].value() is False
    assert form["author_name"].value() == "Alice"
