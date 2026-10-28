"""Capture the Gmail app password without echoing it or putting it in history."""
# ruff: noqa: T201 - interactive setup command

import getpass
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
SENDER = "chinchiat83@gmail.com"


def main() -> int:
    if not sys.stdin.isatty():
        print("Run this script in an interactive terminal; password entry must be hidden.")
        return 1
    if ENV_FILE.is_symlink():
        print("Refusing to replace a symlink at .env.")
        return 1
    ignored = subprocess.run(  # noqa: S603 - fixed read-only Git command
        ["git", "check-ignore", "-q", ".env"],  # noqa: S607 - normal project Git executable
        cwd=PROJECT_ROOT,
        check=False,
    )
    if ignored.returncode != 0:
        print("Refusing to store the app password: .env is not ignored by Git.")
        return 1

    print(f"Configure AsterProof email from {SENDER}.")
    print("Paste the 16-character Google app password below. It will not be displayed.")
    try:
        password = "".join(getpass.getpass("Google app password: ").split())
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; no settings were changed.")
        return 1
    if not re.fullmatch(r"[A-Za-z0-9]{16}", password):
        print("Expected a 16-character app password. No settings were changed.")
        return 1

    values = {
        "DJANGO_EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "DJANGO_EMAIL_HOST": "smtp.gmail.com",
        "DJANGO_EMAIL_PORT": "587",
        "DJANGO_EMAIL_USE_TLS": "True",
        "DJANGO_EMAIL_USE_SSL": "False",
        "DJANGO_EMAIL_HOST_USER": SENDER,
        "DJANGO_EMAIL_HOST_PASSWORD": password,
        "DJANGO_DEFAULT_FROM_EMAIL": f'"AsterProof <{SENDER}>"',
        "DJANGO_SERVER_EMAIL": f'"AsterProof <{SENDER}>"',
        "DJANGO_EMAIL_SUBJECT_PREFIX": '"[AsterProof] "',
    }
    previous = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    retained = [
        line for line in previous.splitlines()
        if not any(re.match(rf"^(?:export\s+)?{key}\s*=", line) for key in values)
    ]
    content = "\n".join([*retained, *(f"{key}={value}" for key, value in values.items()), ""])
    descriptor, temporary = tempfile.mkstemp(prefix=".env.gmail-", dir=PROJECT_ROOT)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
        Path(temporary).replace(ENV_FILE)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print("Saved Gmail settings to the ignored .env file (permissions: 0600).")
    print("No emails sent. Production configuration was not changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
