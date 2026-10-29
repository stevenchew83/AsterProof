import re
import time
from http import HTTPStatus
from types import SimpleNamespace

import pytest
from allauth.account import app_settings
from allauth.account.internal.flows import code_verification
from allauth.core import ratelimit
from allauth.mfa.models import Authenticator
from django.core import mail
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from inspinia.users.adapters import AccountAdapter
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
TEST_CREDENTIAL = "SyntheticTestOnly!986"


@pytest.fixture(autouse=True)
def isolate_rate_limits():
    cache.clear()
    yield
    cache.clear()


def request_code(client, user):
    response = client.post(reverse("account_request_login_code"), {"email": user.email})
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("account_confirm_login_code")
    match = re.search(r"(?m)^[A-Z0-9]{6}$", mail.outbox[-1].body)
    assert match
    return match.group()


def test_login_offers_codes_and_keeps_password_fields(client):
    response = client.get(reverse("account_login"))
    html = response.content.decode()

    assert f'href="{reverse("account_request_login_code")}"' in html
    assert 'name="password"' in html
    assert 'autocomplete="current-password"' in html


def test_code_sign_in_uses_branded_mail_and_keeps_existing_password(client):
    user = UserFactory(password=TEST_CREDENTIAL)
    code = request_code(client, user)
    message = mail.outbox[-1]

    assert message.to == [user.email]
    assert "3 minutes" in message.body
    assert 'src="cid:asterproof-logo"' in message.alternatives[0][0]
    response = client.get(reverse("account_confirm_login_code"))
    assert 'autocomplete="one-time-code"' in response.content.decode()
    assert code not in response.content.decode()
    response = client.post(reverse("account_confirm_login_code"), {"code": code})

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("pages:user_activity_dashboard")
    assert client.session["_auth_user_id"] == str(user.pk)
    user.refresh_from_db()
    assert user.check_password(TEST_CREDENTIAL)


def test_password_sign_in_does_not_send_or_require_a_code(client):
    user = UserFactory(password=TEST_CREDENTIAL)

    response = client.post(reverse("account_login"), {"login": user.email, "password": TEST_CREDENTIAL})

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("pages:user_activity_dashboard")
    assert client.session["_auth_user_id"] == str(user.pk)
    assert not mail.outbox


def test_code_is_bound_to_the_requesting_session(client):
    user = UserFactory()
    code = request_code(client, user)
    other = Client()

    response = other.post(reverse("account_confirm_login_code"), {"code": code})

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("account_request_login_code")
    assert "_auth_user_id" not in other.session
    response = client.post(reverse("account_confirm_login_code"), {"code": code})
    assert response.url == reverse("pages:user_activity_dashboard")


def test_code_cannot_be_reused_after_logout(client):
    code = request_code(client, UserFactory())
    client.post(reverse("account_confirm_login_code"), {"code": code})
    client.post(reverse("account_logout"))

    response = client.post(reverse("account_confirm_login_code"), {"code": code})

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("account_request_login_code")
    assert "_auth_user_id" not in client.session


def test_expired_code_cannot_sign_in(client, settings, monkeypatch):
    code = request_code(client, UserFactory())
    expired_at = time.time() + settings.ACCOUNT_LOGIN_BY_CODE_TIMEOUT + 1
    monkeypatch.setattr(code_verification, "time", SimpleNamespace(time=lambda: expired_at))

    response = client.post(reverse("account_confirm_login_code"), {"code": code})

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("account_request_login_code")
    assert "_auth_user_id" not in client.session


def test_wrong_attempt_limit_invalidates_the_code(client, settings):
    code = request_code(client, UserFactory())
    for _ in range(settings.ACCOUNT_LOGIN_BY_CODE_MAX_ATTEMPTS - 1):
        response = client.post(reverse("account_confirm_login_code"), {"code": "WRONG!"})
        assert response.status_code == HTTPStatus.OK
        assert response.context["form"].errors
    response = client.post(reverse("account_confirm_login_code"), {"code": "WRONG!"})
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("account_request_login_code")

    response = client.post(reverse("account_confirm_login_code"), {"code": code})
    assert response.status_code == HTTPStatus.FOUND
    assert "_auth_user_id" not in client.session


def test_repeated_email_request_is_throttled_but_password_fallback_works(client):
    user = UserFactory(password=TEST_CREDENTIAL)
    request_code(client, user)

    response = Client().post(reverse("account_request_login_code"), {"email": user.email.upper()})

    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors
    assert len(mail.outbox) == 1
    client.post(reverse("account_logout"), {"next": reverse("account_login")})
    assert "account_login" not in client.session
    response = client.post(reverse("account_login"), {"login": user.email, "password": TEST_CREDENTIAL})
    assert response.url == reverse("pages:user_activity_dashboard")
    assert len(mail.outbox) == 1


def test_requesting_a_new_code_invalidates_the_previous_code(client, monkeypatch):
    codes = iter(["ABC123", "DEF456"])
    monkeypatch.setattr(AccountAdapter, "generate_login_code", lambda self: next(codes))
    user = UserFactory()
    old_code = request_code(client, user)
    response = client.post(reverse("account_logout"), {"next": reverse("account_request_login_code")})
    assert response.url == reverse("account_request_login_code")
    later = time.time() + 61
    monkeypatch.setattr(ratelimit, "time", SimpleNamespace(time=lambda: later))
    new_code = request_code(client, user)

    response = client.post(reverse("account_confirm_login_code"), {"code": old_code})

    assert response.status_code == HTTPStatus.OK
    assert "_auth_user_id" not in client.session
    response = client.post(reverse("account_confirm_login_code"), {"code": new_code})
    assert response.url == reverse("pages:user_activity_dashboard")


@pytest.mark.parametrize("existing_inactive_user", [False, True])
def test_unknown_or_inactive_account_cannot_sign_in(client, existing_inactive_user):
    email = "unavailable@example.com"
    if existing_inactive_user:
        UserFactory(email=email, is_active=False)

    response = client.post(reverse("account_request_login_code"), {"email": email})

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("account_confirm_login_code")
    response = client.post(reverse("account_confirm_login_code"), {"code": "ABC123"})
    assert response.status_code == HTTPStatus.OK
    assert "_auth_user_id" not in client.session


def test_code_sign_in_keeps_the_approval_gate(client):
    user = UserFactory(is_approved=False)
    code = request_code(client, user)

    response = client.post(reverse("account_confirm_login_code"), {"code": code}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.request["PATH_INFO"] == reverse("users:approval_pending")
    user.refresh_from_db()
    assert user.is_approved is False


def test_code_sign_in_still_requires_existing_admin_mfa(client):
    user = UserFactory(role=User.Role.ADMIN)
    Authenticator.objects.create(user=user, type=Authenticator.Type.TOTP, data={"secret": "TESTONLY"})
    code = request_code(client, user)

    response = client.post(reverse("account_confirm_login_code"), {"code": code})

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("mfa_authenticate")
    assert "_auth_user_id" not in client.session


def test_code_requests_retain_csrf_protection():
    client = Client(enforce_csrf_checks=True)

    response = client.post(reverse("account_request_login_code"), {"email": "test@example.com"})

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert not mail.outbox


def test_ip_rate_limit_prevents_more_email_sends(client):
    limit = 20
    for number in range(limit):
        response = Client().post(reverse("account_request_login_code"), {"email": f"unknown{number}@example.com"})
        assert response.status_code == HTTPStatus.FOUND
    before = len(mail.outbox)

    response = client.post(reverse("account_request_login_code"), {"email": "another@example.com"})

    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors
    assert len(mail.outbox) == before


def test_code_settings_preserve_other_account_protections(settings):
    assert settings.ACCOUNT_LOGIN_BY_CODE_ENABLED is True
    assert settings.ACCOUNT_LOGIN_BY_CODE_REQUIRED is False
    assert "password1*" in settings.ACCOUNT_SIGNUP_FIELDS
    assert app_settings.RATE_LIMITS["request_login_code"] == "20/m/ip,1/m/key"
    assert app_settings.RATE_LIMITS["reset_password"] == "20/m/ip,5/m/key"  # noqa: S105 - rate-limit expression
