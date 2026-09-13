import importlib
import sys


def _load_base_settings():
    sys.modules.pop("config.settings.base", None)
    return importlib.import_module("config.settings.base")


def test_base_settings_login_user_on_email_confirmation():
    base = _load_base_settings()

    assert base.ACCOUNT_EMAIL_VERIFICATION == "none"
    assert base.ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION is True


def test_base_settings_keep_existing_media_default(monkeypatch):
    monkeypatch.delenv("DJANGO_MEDIA_ROOT", raising=False)
    monkeypatch.setenv("DJANGO_READ_DOT_ENV_FILE", "False")

    base = _load_base_settings()

    assert str(base.APPS_DIR / "media") == base.MEDIA_ROOT


def test_base_settings_allow_media_root_override(monkeypatch, tmp_path):
    media_root = tmp_path / "persistent-media"
    monkeypatch.setenv("DJANGO_MEDIA_ROOT", str(media_root))
    monkeypatch.setenv("DJANGO_READ_DOT_ENV_FILE", "False")

    base = _load_base_settings()

    assert str(media_root) == base.MEDIA_ROOT
