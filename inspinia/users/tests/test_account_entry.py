import re
from http import HTTPStatus
from urllib.parse import urlsplit

import pytest
from django.core import mail
from django.urls import reverse

from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
TEST_OLD_PASSWORD = "OriginalPassword!854"  # noqa: S105 - synthetic test credential
TEST_NEW_PASSWORD = "ReplacementPassword!963"  # noqa: S105 - synthetic test credential


def test_login_keeps_accessible_fields_and_recovery_links(client):
    response = client.get(reverse("account_login"))
    html = response.content.decode()

    assert response.status_code == HTTPStatus.OK
    assert 'autocomplete="email"' in html
    assert 'autocomplete="current-password"' in html
    assert 'name="csrfmiddlewaretoken"' in html
    assert 'for="id_login"' in html
    assert 'for="id_password"' in html
    assert 'id="id_password_helptext"' in html
    assert f'href="{reverse("account_reset_password")}"' in html
    assert f'href="{reverse("account_signup")}"' in html


def test_login_displays_errors_and_keeps_password_private(client):
    response = client.post(
        reverse("account_login"),
        {"login": "invalid-email", "password": "NeverRenderThisPassword!"},
    )
    html = response.content.decode()

    assert response.status_code == HTTPStatus.OK
    assert "Enter a valid email address." in html
    assert 'aria-invalid="true"' in html
    assert 'role="alert"' in html
    assert "NeverRenderThisPassword!" not in html


def test_login_displays_invalid_credential_errors(client):
    user = UserFactory(password=TEST_OLD_PASSWORD)

    response = client.post(
        reverse("account_login"), {"login": user.email, "password": TEST_NEW_PASSWORD},
    )

    assert response.status_code == HTTPStatus.OK
    errors = response.context["form"].non_field_errors()
    assert errors
    assert str(errors[0]) in response.content.decode()
    assert 'role="alert"' in response.content.decode()


def test_password_reset_generates_email_and_single_use_working_link(client):
    user = UserFactory(email="reset-check@example.com", password=TEST_OLD_PASSWORD)
    response = client.post(reverse("account_reset_password"), {"email": user.email})

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("account_reset_password_done")
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    reset_url = re.search(r"https?://[^\s]+/password/reset/key/[^\s]+", mail.outbox[0].body)
    assert reset_url is not None
    reset_path = urlsplit(reset_url.group()).path

    response = client.get(reset_path, follow=True)
    assert response.status_code == HTTPStatus.OK
    assert 'name="password1"' in response.content.decode()
    response = client.post(
        response.request["PATH_INFO"],
        {"password1": TEST_NEW_PASSWORD, "password2": TEST_NEW_PASSWORD},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    user.refresh_from_db()
    assert user.check_password(TEST_NEW_PASSWORD)
    assert not user.check_password(TEST_OLD_PASSWORD)
    response = client.get(reset_path, follow=True)
    assert 'name="password1"' not in response.content.decode()
