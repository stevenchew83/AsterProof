import pytest
from django.urls import reverse

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
        label="P1",
        title="Sample Problem",
        statement="Prove something.",
        editorial_difficulty=3,
    )
    response = client.get(reverse("catalog:list"))
    assert response.status_code == 200
