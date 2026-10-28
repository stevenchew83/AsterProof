from http import HTTPStatus
from types import SimpleNamespace

import pytest
from django.core import mail
from django.urls import reverse

from inspinia.users.adapters import AccountAdapter
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

MAX_EMAIL_HTML_BYTES = 20_000


def render_email(template, **context):
    return AccountAdapter().render_mail(
        f"account/email/{template}",
        "recipient@example.com",
        {
            "current_site": SimpleNamespace(name="AsterProof", domain="testserver"),
            "user": User(email="recipient@example.com"),
            **context,
        },
        headers={"X-Test-Header": "preserved"},
    )


@pytest.mark.parametrize(
    ("template", "context", "expected"),
    [
        ("password_reset_key", {"password_reset_url": "https://testserver/reset/token/"}, "Reset password"),
        ("email_confirmation", {"activate_url": "https://testserver/confirm/token/"}, "Confirm email"),
        ("email_confirmation_signup", {"activate_url": "https://testserver/confirm/token/"}, "Confirm email"),
        ("email_confirmation", {"code": "ABC456"}, "ABC456"),
        ("login_code", {"code": "DEF789"}, "DEF789"),
        ("password_reset_code", {"code": "GHI34567"}, "GHI34567"),
        ("unknown_account", {"email": "unknown@example.com", "signup_url": "https://testserver/signup/"}, "sign up"),
        ("delivery_test", {}, "Gmail email delivery"),
    ],
)
def test_account_email_contains_branded_html_and_plain_text(template, context, expected):
    message = render_email(template, **context)
    html, content_type = message.alternatives[0]

    assert content_type == "text/html"
    assert len(message.alternatives) == 1
    assert message.subject.startswith("[AsterProof] ")
    assert message.from_email == "AsterProof <chinchiat83@gmail.com>"
    assert message.to == ["recipient@example.com"]
    assert message.extra_headers == {"X-Test-Header": "preserved"}
    assert message.body.strip()
    assert "AsterProof" in message.body
    assert expected in html
    assert "#192d3d" in html
    assert "#149e92" in html
    assert "<script" not in html
    assert "stylesheet" not in html
    assert len(html.encode()) < MAX_EMAIL_HTML_BYTES


def test_account_security_notification_keeps_details_and_escapes_html():
    message = render_email(
        "password_changed", ip="192.0.2.10", user_agent="<script>alert('test')</script>",
        timestamp="2026-10-28 14:00 UTC",
    )
    html = message.alternatives[0][0]

    assert "192.0.2.10" in message.body
    assert "192.0.2.10" in html
    assert "2026-10-28 14:00 UTC" in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


@pytest.mark.django_db
def test_password_reset_delivers_matching_links_in_html_and_plain_text(client):
    user = UserFactory(email="reset-html@example.com")

    response = client.post(reverse("account_reset_password"), {"email": user.email})

    assert response.status_code == HTTPStatus.FOUND
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    html = message.alternatives[0][0]
    reset_link = next(line for line in message.body.splitlines() if "/password/reset/key/" in line)
    assert f'href="{reset_link}"' in html
    assert "Your password will stay the same." in html


def test_email_logo_is_embedded_and_mime_structure_keeps_plain_text_and_html():
    message = render_email("email_confirmation", activate_url="https://testserver/confirm/key/")

    assert 'src="cid:asterproof-logo"' in message.alternatives[0][0]
    assert 'alt="AsterProof"' in message.alternatives[0][0]
    mime = message.message()
    assert mime.get_content_type() == "multipart/related"
    alternatives, logo = mime.get_payload()
    assert alternatives.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in alternatives.get_payload()] == ["text/plain", "text/html"]
    assert logo.get_content_type() == "image/png"
    assert logo["Content-ID"] == "<asterproof-logo>"
    assert logo.get_content_disposition() == "inline"
    assert logo.get_payload(decode=True).startswith(b"\x89PNG\r\n\x1a\n")
