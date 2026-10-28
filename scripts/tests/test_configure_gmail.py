from types import SimpleNamespace

import pytest

from scripts import configure_gmail

TEST_APP_CREDENTIAL = "abcd efgh ijkl mnop"
PRIVATE_FILE_MODE = 0o600


@pytest.fixture
def gmail_setup(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(configure_gmail, "ENV_FILE", env_file)
    monkeypatch.setattr(configure_gmail, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(configure_gmail.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(configure_gmail.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    monkeypatch.setattr(configure_gmail.getpass, "getpass", lambda prompt: TEST_APP_CREDENTIAL)
    return env_file


def test_hidden_setup_preserves_other_settings_and_writes_private_file(gmail_setup, capsys):
    gmail_setup.write_text("# Existing settings\nDATABASE_URL=sqlite:///local.sqlite3\nDJANGO_EMAIL_PORT=25\n")

    assert configure_gmail.main() == 0

    saved = gmail_setup.read_text()
    assert "# Existing settings\nDATABASE_URL=sqlite:///local.sqlite3\n" in saved
    assert "DJANGO_EMAIL_HOST_PASSWORD=abcdefghijklmnop\n" in saved
    assert saved.count("DJANGO_EMAIL_PORT=") == 1
    assert "DJANGO_EMAIL_PORT=587\n" in saved
    assert gmail_setup.stat().st_mode & 0o777 == PRIVATE_FILE_MODE
    output = capsys.readouterr().out
    assert TEST_APP_CREDENTIAL not in output
    assert "abcdefghijklmnop" not in output


def test_hidden_setup_rejects_invalid_input_without_changing_settings(gmail_setup, monkeypatch):
    gmail_setup.write_text("EXISTING=unchanged\n")
    monkeypatch.setattr(configure_gmail.getpass, "getpass", lambda prompt: "invalid")

    assert configure_gmail.main() == 1
    assert gmail_setup.read_text() == "EXISTING=unchanged\n"


def test_hidden_setup_refuses_noninteractive_input(gmail_setup, monkeypatch):
    monkeypatch.setattr(configure_gmail.sys, "stdin", SimpleNamespace(isatty=lambda: False))

    assert configure_gmail.main() == 1
    assert not gmail_setup.exists()


def test_hidden_setup_refuses_a_file_that_git_does_not_ignore(gmail_setup, monkeypatch):
    monkeypatch.setattr(configure_gmail.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))

    assert configure_gmail.main() == 1
    assert not gmail_setup.exists()
