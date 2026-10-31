"""Contest papers preserve statement order and keep review clues closed."""

import re
from html import unescape
from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.urls import reverse

from inspinia.pages.asymptote_render import AsymptoteRenderResult
from inspinia.pages.models import ContestMetadata
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.models import ProblemSolution
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _statement(**overrides):
    return ContestProblemStatement.objects.create(
        **{
            "contest_name": "Fixture Cup",
            "contest_year": 2025,
            "problem_number": 1,
            "problem_code": "P1",
            "statement_latex": "Prove that $n=n$.",
            **overrides,
        },
    )


@pytest.fixture
def learner_client(client):
    client.force_login(UserFactory())
    return client


def test_contest_papers_requires_login(client):
    response = client.get(reverse("pages:contest_papers"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("account_login"))


def test_contest_papers_preserves_approval_gate(client):
    client.force_login(UserFactory(is_approved=False))

    response = client.get(reverse("pages:contest_papers"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("users:approval_pending")


def test_directory_links_to_contests_with_active_statement_year_counts(learner_client):
    _statement()
    _statement(contest_year=2024)
    _statement(contest_year=2026, is_active=False)
    _statement(contest_name="Hidden Cup", is_active=False)
    ContestMetadata.objects.create(contest="Fixture Cup", full_name="The Fixture Mathematics Olympiad")

    response = learner_client.get(reverse("pages:contest_papers"))

    assert response.status_code == HTTPStatus.OK
    rows = list(response.context["contest_page"])
    assert [(row["contest_name"], row["year_count"], row["problem_count"]) for row in rows] == [
        ("Fixture Cup", 2, 2),
    ]
    html = response.content.decode()
    assert "The Fixture Mathematics Olympiad" in html
    assert "Hidden Cup" not in html
    assert 'href="/dashboard/contest-papers/?contest=Fixture+Cup"' in html
    assert rows[0]["latest_url"] == reverse("pages:contest_papers") + "?contest=Fixture+Cup&year=2025"
    latest = learner_client.get(rows[0]["latest_url"])
    assert latest.status_code == HTTPStatus.OK
    assert latest.context["paper_title"] == "Fixture Cup 2025"
    assert '<span class="menu-text">Contest papers</span>' in html


@pytest.mark.parametrize("query", ["fixture", "Mathematics Olympiad"])
def test_directory_searches_names_and_metadata_full_names(learner_client, query):
    _statement()
    _statement(contest_name="Another Cup")
    ContestMetadata.objects.create(contest="Fixture Cup", full_name="The Fixture Mathematics Olympiad")

    response = learner_client.get(reverse("pages:contest_papers"), {"q": query})

    assert [row["contest_name"] for row in response.context["contest_page"]] == ["Fixture Cup"]


def test_directory_pagination_preserves_search(learner_client):
    for index in range(31):
        _statement(contest_name=f"Search Cup {index:02}")

    response = learner_client.get(reverse("pages:contest_papers"), {"q": "Search Cup", "page": 2})

    assert response.status_code == HTTPStatus.OK
    assert [row["contest_name"] for row in response.context["contest_page"]] == ["Search Cup 30"]
    assert "?q=Search+Cup&amp;page=1" in response.content.decode()


def test_contest_selection_shows_years_newest_first_without_premature_statements(learner_client):
    _statement()
    _statement(contest_year=2024)
    _statement(contest_year=2026, is_active=False)

    response = learner_client.get(reverse("pages:contest_papers"), {"contest": "Fixture Cup"})

    assert response.status_code == HTTPStatus.OK
    assert [row["contest_year"] for row in response.context["year_rows"]] == [2025, 2024]
    assert "paper_groups" not in response.context
    assert "Papers by year" in response.content.decode()
    assert "?contest=Fixture+Cup&amp;year=2025" in response.content.decode()


def test_year_archive_groups_decade_boundaries_and_links_latest_active_paper(learner_client):
    for year in [1994, 1999, 2000, 2009, 2010, 2024, 2025]:
        _statement(contest_name="APMO", contest_year=year)
    _statement(contest_name="APMO", contest_year=2025, problem_code="P2", problem_number=2)
    _statement(contest_name="APMO", contest_year=2026, is_active=False)
    ContestMetadata.objects.create(contest="APMO", full_name="Asian Pacific Mathematics Olympiad")

    response = learner_client.get(reverse("pages:contest_papers"), {"contest": "APMO"})

    groups = response.context["decade_groups"]
    assert [(group["decade"], [row["contest_year"] for row in group["years"]]) for group in groups] == [
        (2020, [2025, 2024]), (2010, [2010]), (2000, [2009, 2000]), (1990, [1999, 1994]),
    ]
    assert response.context["latest_paper"]["contest_year"] == 2025  # noqa: PLR2004
    assert response.context["latest_paper"]["problem_count"] == 2  # noqa: PLR2004
    assert response.context["first_year"] == 1994  # noqa: PLR2004
    assert response.context["last_year"] == 2025  # noqa: PLR2004
    html = response.content.decode()
    assert "Asian Pacific Mathematics Olympiad" in html
    assert html.count('paper-year-link--latest"') == 1
    latest_link = re.search(r'<a href="([^"]+)" class="[^"]*paper-open-latest">', html)
    assert latest_link is not None
    assert unescape(latest_link[1]) == response.context["latest_paper"]["url"]
    latest = learner_client.get(response.context["latest_paper"]["url"])
    assert latest.status_code == HTTPStatus.OK
    assert latest.context["paper_title"] == "APMO 2025"


def test_single_year_archive_works_without_contest_metadata(learner_client):
    _statement(contest_year=2000)

    response = learner_client.get(reverse("pages:contest_papers"), {"contest": "Fixture Cup"})

    assert response.status_code == HTTPStatus.OK
    assert response.context["contest_full_name"] == ""
    assert [group["decade"] for group in response.context["decade_groups"]] == [2000]
    assert response.context["first_year"] == response.context["last_year"] == 2000  # noqa: PLR2004
    assert "Open latest paper" in response.content.decode()


def test_paper_groups_rounds_naturally_and_restarts_numbering(learner_client):
    for day, number in [("Round 10", 1), ("Round 2", 10), ("Round 1", 2), ("Round 2", 2), ("Round 1", 1)]:
        _statement(
            day_label=day, problem_number=number, problem_code=f"P{number}", statement_latex=f"{day} item {number}",
        )
    _statement(day_label="Round 1", problem_number=3, problem_code="P3", is_active=False)
    _statement(contest_year=2024, statement_latex="Wrong year")
    _statement(contest_name="Other Cup", statement_latex="Wrong contest")

    response = learner_client.get(reverse("pages:contest_papers"), {"contest": "Fixture Cup", "year": 2025})

    assert response.status_code == HTTPStatus.OK
    groups = response.context["paper_groups"]
    assert [group["label"] for group in groups] == ["Round 1", "Round 2", "Round 10"]
    assert [[row["heading"] for row in group["problems"]] for group in groups] == [
        ["Problem 1", "Problem 2"],
        ["Problem 2", "Problem 10"],
        ["Problem 1"],
    ]
    html = response.content.decode()
    assert html.index("Round 1 item 1") < html.index("Round 1 item 2") < html.index("Round 2 item 2")
    assert html.index("Round 2 item 2") < html.index("Round 2 item 10") < html.index("Round 10 item 1")
    assert "Wrong year" not in html
    assert "Wrong contest" not in html


def test_paper_uses_problem_number_before_code_and_preserves_original_codes(learner_client):
    _statement(problem_number=2, problem_code="A1")
    _statement(problem_number=1, problem_code="Z1")

    response = learner_client.get(reverse("pages:contest_papers"), {"contest": "Fixture Cup", "year": 2025})

    assert [row["heading"] for row in response.context["paper_groups"][0]["problems"]] == ["Problem Z1", "Problem A1"]


def test_paper_is_uncapped_and_renders_unlinked_statements(learner_client):
    problem_count = 105
    ContestProblemStatement.objects.bulk_create(
        [
            ContestProblemStatement(
                contest_name="Large Cup",
                contest_year=2025,
                problem_number=number,
                problem_code=f"P{number}",
                statement_latex=f"Statement number {number}.",
            )
            for number in range(1, problem_count + 1)
        ],
    )

    response = learner_client.get(reverse("pages:contest_papers"), {"contest": "Large Cup", "year": 2025})

    assert response.status_code == HTTPStatus.OK
    assert response.context["paper_problem_count"] == problem_count
    html = response.content.decode()
    assert html.count('<article class="paper-problem"') == problem_count
    assert "Statement number 105." in html
    assert "Showing latest" not in html
    assert response.context["paper_groups"][0]["label"] == "Problems"


def test_unlabelled_statements_are_retained_after_labelled_sections(learner_client):
    _statement()
    _statement(day_label="Day 1")

    response = learner_client.get(reverse("pages:contest_papers"), {"contest": "Fixture Cup", "year": 2025})

    assert [group["label"] for group in response.context["paper_groups"]] == ["Day 1", "Other problems"]


def test_every_statement_has_a_writing_action_and_section_navigation(learner_client):
    statement = _statement()
    response = learner_client.get(reverse("pages:contest_papers"), {"contest": "Fixture Cup", "year": 2025})
    html = response.content.decode()

    assert reverse("solutions:statement_solution_start", args=[statement.statement_uuid]) in html
    assert 'class="paper-write-action"' in html
    assert 'name="csrfmiddlewaretoken"' in html
    assert "Write solution" in html
    assert 'aria-label="Paper sections"' in html
    assert 'href="#paper-section-1"' in html
    assert "no-store" in response["Cache-Control"]
    assert not ProblemSolveRecord.objects.exists()


def test_paper_offers_to_continue_only_the_current_users_solution(learner_client):
    user = learner_client.session["_auth_user_id"]
    problem = ProblemSolveRecord.objects.create(contest="Fixture Cup", year=2025, problem="P1", topic="NT", mohs=10)
    _statement(linked_problem=problem)
    ProblemSolution.objects.create(problem=problem, author=UserFactory(), title="Someone else's private solution")
    url = reverse("pages:contest_papers")
    params = {"contest": "Fixture Cup", "year": 2025}
    assert "Continue solution" not in learner_client.get(url, params).content.decode()
    ProblemSolution.objects.create(problem=problem, author_id=user)
    html = learner_client.get(url, params).content.decode()
    assert "Continue solution" in html
    assert "Someone else" not in html


def test_review_details_are_closed_and_contain_all_topic_difficulty_and_solution_clues(learner_client):
    problem = ProblemSolveRecord.objects.create(year=2025, contest="Fixture Cup", problem="P1", topic="GEO", mohs=5)
    _statement(linked_problem=problem, topic="NT", mohs=0, statement_latex="Read this statement immediately.")

    response = learner_client.get(reverse("pages:contest_papers"), {"contest": "Fixture Cup", "year": 2025})

    html = response.content.decode()
    reviews = re.findall(r'<details\b([^>]*class="paper-review[^>]*)>(.*?)</details>', html, re.S)
    assert len(reviews) == 1
    assert not re.search(r"\bopen\b", reviews[0][0])
    assert "Number Theory" in reviews[0][1]
    assert "Difficulty (MOHS): 0" in reviews[0][1]
    assert reverse("solutions:problem_solution_list", args=[problem.problem_uuid]) in reviews[0][1]
    without_reviews = re.sub(r'<details class="paper-review.*?</details>', "", html, flags=re.S)
    assert "Read this statement immediately." in without_reviews
    assert "Number Theory" not in without_reviews
    assert "Difficulty (MOHS)" not in without_reviews
    assert "View solutions" not in without_reviews
    assert "Geometry" not in html


def test_paper_uses_linked_metadata_fallback_but_omits_inactive_solution_links(learner_client):
    problem = ProblemSolveRecord.objects.create(
        year=2025,
        contest="Fixture Cup",
        problem="P1",
        topic="GEO",
        mohs=5,
        is_active=False,
    )
    _statement(linked_problem=problem)

    response = learner_client.get(reverse("pages:contest_papers"), {"contest": "Fixture Cup", "year": 2025})

    row = response.context["paper_groups"][0]["problems"][0]
    assert row["topic"] == "Geometry"
    assert row["mohs"] == problem.mohs
    assert row["solutions_url"] == ""


def test_paper_uses_shared_diagram_rendering_and_escapes_statement_html(learner_client):
    _statement(statement_latex='<script>alert("untrusted")</script> $n^2$ [asy]draw((0,0)--(1,1));[/asy]')
    diagram = AsymptoteRenderResult(svg_markup='<svg id="paper-fixture-diagram"></svg>', backend="local")
    with patch("inspinia.pages.asymptote_render.render_asymptote_svg", return_value=diagram) as render:
        response = learner_client.get(reverse("pages:contest_papers"), {"contest": "Fixture Cup", "year": 2025})

    render.assert_called_once_with("draw((0,0)--(1,1));")
    html = response.content.decode()
    assert "&lt;script&gt;" in html
    assert '<script>alert("untrusted")</script>' not in html
    assert "tex-mml-chtml.js" in html
    assert "data-mathjax-scope" in html
    assert '<svg id="paper-fixture-diagram"></svg>' in html


@pytest.mark.parametrize(
    "params",
    [
        {"contest": "Missing Cup"},
        {"contest": "Fixture Cup", "year": "2024"},
        {"contest": "Fixture Cup", "year": "invalid"},
        {"contest": "Fixture Cup", "year": "9" * 5000},
        {"year": "2025"},
    ],
)
def test_invalid_contest_year_returns_not_found(learner_client, params):
    _statement()

    response = learner_client.get(reverse("pages:contest_papers"), params)

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("query", ["", "no match"])
def test_empty_directory_is_explained(learner_client, query):
    response = learner_client.get(reverse("pages:contest_papers"), {"q": query})

    assert response.status_code == HTTPStatus.OK
    assert response.context["contest_page"].paginator.count == 0
    assert ("No contests match" if query else "No contest papers are available") in response.content.decode()
