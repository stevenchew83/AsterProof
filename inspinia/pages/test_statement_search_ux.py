"""The library has one full-library search with optional, persistent filters."""

from http import HTTPStatus

import pytest
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("filters", [{}, {"year": "2026"}, {"topic": "Geometry"}])
def test_statement_library_search_keeps_active_filters_visible(client, filters):
    client.force_login(UserFactory())
    ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="Search UX Olympiad",
        problem_number=1,
        problem_code="P1",
        topic="GEO",
        statement_latex="A geometry problem.",
    )

    response = client.get(reverse("pages:problem_statement_list"), filters)

    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert response.context["statement_filtered_total"] == 1
    assert html.count('name="q"') == 1
    assert 'role="search" aria-label="Statement library"' in html
    assert "searching: false" in html
    assert "Within loaded rows" not in html
    if filters:
        assert 'id="statement-advanced-filters" class="collapse show' in html
        assert 'aria-expanded="true"' in html
        assert response.context["statement_has_active_filters"] is True
    else:
        assert 'id="statement-advanced-filters" class="collapse mt-2"' in html
        assert response.context["statement_has_active_filters"] is False
