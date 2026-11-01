"""An explicit community solve/report intent survives the actual sign-in form."""

import uuid
from http import HTTPStatus

import pytest
from allauth.account.models import EmailAddress
from django.urls import reverse

from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
LOCAL_PASSWORD = "Community-handoff-test-2026!"  # noqa: S105 - Synthetic test account only.


@pytest.mark.parametrize("name", ["proof_attempt", "proof_report"])
def test_community_next_survives_login(client, name):
    user = UserFactory(password=LOCAL_PASSWORD)
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
    target = reverse("pages:" + name, args=[uuid.uuid4()])
    page = client.get(reverse("account_login"), {"next": target})
    assert f'value="{target}"' in page.content.decode()
    response = client.post(reverse("account_login"), {
        "login": user.email, "password": LOCAL_PASSWORD, "next": target,
    })
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == target


@pytest.mark.parametrize("target", [
    "//evil.example/community/solve/", "https://evil.example/community/solve/",
    "/community/solve/not-a-uuid/", "/users/profile/", "/\\evil.example/",
])
def test_external_or_unrelated_next_retains_existing_login_destination(client, target):
    user = UserFactory(password=LOCAL_PASSWORD)
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
    response = client.post(reverse("account_login"), {
        "login": user.email, "password": LOCAL_PASSWORD, "next": target,
    })
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == user.get_login_redirect_url()
