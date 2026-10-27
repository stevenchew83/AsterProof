"""Keep compact contest rows connected to their full problem details."""

import re
from http import HTTPStatus

import pytest
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.users.tests.factories import UserFactory


@pytest.mark.django_db
def test_contest_dashboard_listing_keeps_full_details_out_of_single_table_summary_rows(client):
    client.force_login(UserFactory())
    years = (2026, 2025)
    for year in years:
        problem = ProblemSolveRecord.objects.create(
            year=year,
            contest="Fixture Cup",
            problem="P1",
            contest_year_problem=f"Fixture Cup {year} P1",
            topic="NT",
            mohs=0,
        )
        for technique in ("DIVISIBILITY", "MULTIPLICATIVE ORDER", "CONGRUENCES"):
            ProblemTopicTechnique.objects.create(record=problem, technique=technique, domains=["NT"])
        ContestProblemStatement.objects.create(
            linked_problem=problem,
            contest_year=year,
            contest_name="Fixture Cup",
            problem_number=1,
            problem_code="P1",
            day_label="Round One · Test 1",
            statement_latex=f"Full statement for {year}: prove $n=n$.",
        )

    response = client.get(reverse("pages:contest_dashboard_listing"), {"contest": "Fixture Cup"})

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert len(re.findall(r"<table\b[^>]*\bproblem-table\b", page)) == 1
    rows = re.findall(r'<tr id="([^"]+)" class="js-problem-row"[^>]*>(.*?)</tr>', page, re.S)
    assert len(rows) == len(years)
    for (anchor, row), year in zip(rows, years, strict=True):
        visible_text = re.sub(r"<[^>]+>", " ", row)
        assert str(year) in visible_text
        assert "P1" in visible_text
        assert "Fixture Cup" not in visible_text
        assert "Full statement" not in visible_text
        assert 'class="problem-list-add-form"' not in row
        assert ">+2</span>" in row
        assert 'data-sort-value="0"' in row
        assert f'aria-controls="statement-drawer-{anchor}"' in row
        drawer = re.search(rf'<tr id="statement-drawer-{re.escape(anchor)}"[^>]*>(.*?)</tr>', page, re.S)
        assert drawer is not None
        assert f"Full statement for {year}" in drawer[1]
        assert "MULTIPLICATIVE ORDER" in drawer[1]
        assert "CONGRUENCES" in drawer[1]
        assert "Create list" in drawer[1]
        assert 'class="btn btn-light btn-sm js-statement-close"' in drawer[1]
    assert "js-problem-select" not in page
