import pytest
from django.urls import reverse

from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_private_profile_restricted(client):
    owner = UserFactory(profile_visibility="private")
    stranger = UserFactory()
    client.force_login(stranger)
    response = client.get(reverse("profiles:detail", kwargs={"user_id": owner.id}))
    assert response.status_code == 403
