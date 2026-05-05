from http import HTTPStatus

import pytest
from django.urls import reverse

from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_unapproved_user_is_redirected_from_app_feature(client):
    user = UserFactory(is_approved=False)
    client.force_login(user)

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("users:approval_pending")


def test_unapproved_user_can_view_approval_pending_page(client):
    user = UserFactory(is_approved=False)
    client.force_login(user)

    response = client.get(reverse("users:approval_pending"))

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode("utf-8")
    assert "Approval pending" in content
    assert "Your account is waiting for admin approval." in content


def test_unapproved_user_can_open_logout_page(client):
    user = UserFactory(is_approved=False)
    client.force_login(user)

    response = client.get(reverse("account_logout"))

    assert response.status_code == HTTPStatus.OK


def test_approved_user_can_open_app_feature(client):
    user = UserFactory(is_approved=True)
    client.force_login(user)

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.OK


def test_admin_role_can_open_app_feature_without_stored_approval(client):
    admin_user = UserFactory(role=User.Role.ADMIN, is_approved=False)
    client.force_login(admin_user)

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.OK


def test_approved_user_is_redirected_away_from_pending_page(client):
    user = UserFactory(is_approved=True)
    client.force_login(user)

    response = client.get(reverse("users:approval_pending"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("pages:user_activity_dashboard")
