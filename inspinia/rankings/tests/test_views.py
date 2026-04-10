from http import HTTPStatus

import pytest
from django.conf import settings
from django.urls import reverse

from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_ranking_table_requires_login(client):
    response = client.get(reverse("rankings:ranking_table"))
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == f"{reverse(settings.LOGIN_URL)}?next={reverse('rankings:ranking_table')}"


def test_ranking_table_renders_for_authenticated_user(client):
    user = UserFactory()
    client.force_login(user)
    response = client.get(reverse("rankings:ranking_table"))
    assert response.status_code == HTTPStatus.OK
    assert "Ranking table" in response.content.decode()
