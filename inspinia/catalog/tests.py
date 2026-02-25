import pytest
from django.urls import reverse

from inspinia.catalog.latex_utils import lint_statement_source
from inspinia.catalog.latex_utils import to_plaintext
from inspinia.catalog.models import Contest
from inspinia.catalog.models import Problem

pytestmark = pytest.mark.django_db


def test_problem_browser_renders(client):
    contest = Contest.objects.create(
        name="IMO 2019",
        short_code="IMO2019",
        contest_type="imo",
        year=2019,
    )
    Problem.objects.create(
        contest=contest,
        problem_position=42,
        label="P1",
        title="Sample Problem",
        statement="Prove something.",
        editorial_difficulty=3,
    )
    response = client.get(reverse("catalog:list"))
    assert response.status_code == 200
    assert "42" in response.content.decode()


def test_latex_lint_blocks_dangerous_commands():
    issues = lint_statement_source(r"\input{evil.tex}", "latex")
    assert issues
    assert "Disallowed LaTeX command detected: \\input" in issues[0]


def test_latex_lint_allows_plain_statements():
    issues = lint_statement_source(r"\input{evil.tex}", "plain")
    assert issues == []


def test_plaintext_extraction_from_latex():
    source = r"Let $x^2+y^2=1$ and \frac{a}{b}."
    text = to_plaintext(source, "latex")
    assert "Let" in text
    assert "and" in text
