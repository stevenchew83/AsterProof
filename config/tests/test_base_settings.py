import importlib
import sys


def _load_base_settings():
    sys.modules.pop("config.settings.base", None)
    return importlib.import_module("config.settings.base")


def test_base_settings_login_user_on_email_confirmation():
    base = _load_base_settings()

    assert base.ACCOUNT_EMAIL_VERIFICATION == "none"
    assert base.ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION is True
