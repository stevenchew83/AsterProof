import importlib
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured

GMAIL_SUBMISSION_PORT = 587
SMTP_TEST_CREDENTIAL = "synthetic-smtp-credential"


def _load_production_settings(monkeypatch, **extra_env):
    required_env = {
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/asterproof",
        "DJANGO_ADMIN_URL": "secure-admin/",
        "DJANGO_SECRET_KEY": "secret-key",
        "DJANGO_EMAIL_HOST_PASSWORD": SMTP_TEST_CREDENTIAL,
    }
    for key, value in {**required_env, **extra_env}.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop("config.settings.production", None)
    return importlib.import_module("config.settings.production")


def _load_staticfiles_settings():
    sys.modules.pop("config.settings.staticfiles", None)
    return importlib.import_module("config.settings.staticfiles")


def test_production_settings_keep_secure_cookies_enabled_by_default(monkeypatch):
    production = _load_production_settings(monkeypatch)

    assert production.SESSION_COOKIE_SECURE is True
    assert production.CSRF_COOKIE_SECURE is True
    assert production.SESSION_COOKIE_NAME == "__Secure-sessionid"
    assert production.CSRF_COOKIE_NAME == "__Secure-csrftoken"


def test_production_settings_allow_cookie_security_overrides(monkeypatch):
    production = _load_production_settings(
        monkeypatch,
        DJANGO_CSRF_COOKIE_SECURE="False",
        DJANGO_SESSION_COOKIE_SECURE="False",
    )

    assert production.SESSION_COOKIE_SECURE is False
    assert production.CSRF_COOKIE_SECURE is False
    assert production.SESSION_COOKIE_NAME == "sessionid"
    assert production.CSRF_COOKIE_NAME == "csrftoken"


def test_production_settings_staticfiles_and_media_on_filesystem(monkeypatch):
    production = _load_production_settings(monkeypatch)

    assert production.STORAGES["staticfiles"]["BACKEND"] == (
        "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )
    assert production.STORAGES["default"]["BACKEND"] == (
        "django.core.files.storage.FileSystemStorage"
    )
    assert production.MEDIA_URL == "/media/"


def test_production_settings_use_persistent_media_override(monkeypatch, tmp_path):
    media_root = tmp_path / "shared" / "media"

    production = _load_production_settings(
        monkeypatch,
        DJANGO_MEDIA_ROOT=str(media_root),
        DJANGO_READ_DOT_ENV_FILE="False",
    )

    assert str(media_root) == production.MEDIA_ROOT


def test_staticfiles_settings_use_compressed_manifest_storage():
    staticfiles = _load_staticfiles_settings()

    assert staticfiles.STORAGES["staticfiles"]["BACKEND"] == (
        "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )


def test_production_settings_middleware_timing_then_security_then_whitenoise(monkeypatch):
    production = _load_production_settings(monkeypatch)
    mw = production.MIDDLEWARE

    assert mw[0] == "config.middleware.RequestTimingMiddleware"
    assert mw[1] == "django.middleware.security.SecurityMiddleware"
    assert mw[2] == "whitenoise.middleware.WhiteNoiseMiddleware"


def test_production_request_timing_defaults_on_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("DJANGO_REQUEST_TIMING_LOG", raising=False)
    assert _load_production_settings(monkeypatch).REQUEST_TIMING_LOG is True
    assert _load_production_settings(monkeypatch, DJANGO_REQUEST_TIMING_LOG="False").REQUEST_TIMING_LOG is False


def test_production_startup_preparation_defaults_on_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("DJANGO_PREPARE_FIRST_REQUEST", raising=False)
    assert _load_production_settings(monkeypatch).PREPARE_FIRST_REQUEST is True
    assert _load_production_settings(monkeypatch, DJANGO_PREPARE_FIRST_REQUEST="False").PREPARE_FIRST_REQUEST is False


def test_production_email_defaults_to_authenticated_gmail_without_mailgun(monkeypatch):
    production = _load_production_settings(monkeypatch)

    assert production.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
    assert production.EMAIL_HOST == "smtp.gmail.com"
    assert production.EMAIL_PORT == GMAIL_SUBMISSION_PORT
    assert production.EMAIL_USE_TLS is True
    assert production.EMAIL_USE_SSL is False
    assert production.EMAIL_HOST_USER == "chinchiat83@gmail.com"
    assert production.EMAIL_HOST_PASSWORD == SMTP_TEST_CREDENTIAL
    assert production.DEFAULT_FROM_EMAIL == "AsterProof <chinchiat83@gmail.com>"
    assert production.ACCOUNT_EMAIL_SUBJECT_PREFIX == "[AsterProof] "
    assert production.ADMINS == [("AsterProof admin", "chinchiat83@gmail.com")]
    assert "anymail" not in production.INSTALLED_APPS


def test_production_smtp_requires_the_app_password(monkeypatch):
    _load_production_settings(monkeypatch)
    monkeypatch.delenv("DJANGO_EMAIL_HOST_PASSWORD")
    sys.modules.pop("config.settings.production", None)

    with pytest.raises(ImproperlyConfigured, match="DJANGO_EMAIL_HOST_PASSWORD"):
        importlib.import_module("config.settings.production")


def test_production_keeps_mailgun_when_explicitly_selected(monkeypatch):
    production = _load_production_settings(
        monkeypatch, DJANGO_EMAIL_BACKEND="anymail.backends.mailgun.EmailBackend",
        MAILGUN_API_KEY="mailgun-key", MAILGUN_DOMAIN="mg.example.com",
    )

    assert production.EMAIL_BACKEND == "anymail.backends.mailgun.EmailBackend"
    assert production.ANYMAIL["MAILGUN_SENDER_DOMAIN"] == "mg.example.com"
    assert "anymail" in production.INSTALLED_APPS
