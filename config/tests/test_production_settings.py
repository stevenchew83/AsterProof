import importlib
import sys


def _load_production_settings(monkeypatch, **extra_env):
    required_env = {
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/asterproof",
        "DJANGO_ADMIN_URL": "secure-admin/",
        "DJANGO_AWS_ACCESS_KEY_ID": "access-key",
        "DJANGO_AWS_SECRET_ACCESS_KEY": "secret-key",
        "DJANGO_AWS_STORAGE_BUCKET_NAME": "bucket-name",
        "DJANGO_SECRET_KEY": "secret-key",
        "MAILGUN_API_KEY": "mailgun-key",
        "MAILGUN_DOMAIN": "mg.example.com",
    }
    for key, value in {**required_env, **extra_env}.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop("config.settings.production", None)
    return importlib.import_module("config.settings.production")


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
