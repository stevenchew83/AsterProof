import re
from http import HTTPStatus

import pytest
from django.urls import reverse

from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("url_name", "heading"),
    [
        ("account_email", "Email Addresses"),
        ("mfa_index", "Two-Factor Authentication"),
        ("account_change_password", "Change Password"),
    ],
)
def test_account_settings_keep_dashboard_shell_and_one_page_heading(client, url_name, heading):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse(url_name))

    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert html.count('class="wrapper"') == 1
    assert html.count('class="content-page"') == 1
    assert 'class="sidenav-menu"' in html
    assert html.count('class="app-page-header-title"') == 1
    assert len(re.findall(r"<h1(?:\s|>)", html)) == 1
    assert re.search(rf"<h1[^>]*>\s*{re.escape(heading)}\s*</h1>", html)
    assert 'name="csrfmiddlewaretoken"' in html or url_name == "mfa_index"


def test_standard_dashboard_keeps_its_shell_and_heading(client):
    client.force_login(UserFactory())

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert html.count('class="wrapper"') == 1
    assert html.count('class="content-page"') == 1
    assert html.count('class="app-page-header-title"') == 1
    assert len(re.findall(r"<h1(?:\s|>)", html)) == 1


@pytest.mark.parametrize("url_name", ["account_login", "account_signup"])
def test_anonymous_entrance_keeps_its_branding_and_single_heading(client, url_name):
    response = client.get(reverse(url_name))

    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert "auth-brand" in html
    assert 'class="sidenav-menu"' not in html
    assert len(re.findall(r"<h1(?:\s|>)", html)) == 1
