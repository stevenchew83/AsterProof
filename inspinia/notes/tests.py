import pytest
from django.urls import reverse

from inspinia.catalog.models import Contest
from inspinia.catalog.models import Problem
from inspinia.notes.models import PrivateNote
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_note_autosave(client):
    user = UserFactory()
    client.force_login(user)
    contest = Contest.objects.create(name="IMO 2020", short_code="IMO2020", contest_type="imo", year=2020)
    problem = Problem.objects.create(contest=contest, label="P2", statement="Text", editorial_difficulty=2)
    response = client.post(reverse("notes:autosave", kwargs={"problem_id": problem.id}), {"content": "My note"})
    assert response.status_code == 200
    assert PrivateNote.objects.get(user=user, problem=problem).content == "My note"
