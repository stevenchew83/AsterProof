# AsterProof transactional email

Account emails use `AsterProof <chinchiat83@gmail.com>` over Gmail SMTP with
STARTTLS on `smtp.gmail.com:587`. The Gmail app password is a secret. Never
commit it, pass it as a command-line argument, print it, or paste it into chat.

## Local setup

Run `python scripts/configure_gmail.py` in an interactive terminal. Paste the
16-character app password at the hidden prompt; spaces between groups are
accepted. The script preserves unrelated settings and atomically updates the
Git-ignored `.env` with mode `0600`. It does not send mail or change production.

Local settings keep the console email backend unless `DJANGO_EMAIL_BACKEND`
explicitly selects SMTP. The setup script selects SMTP in the local `.env`.
Test settings always use Django's in-memory backend. Set
`DJANGO_READ_DOT_ENV_FILE=False` for isolated tests.

## Production setup

Production defaults to SMTP and requires `DJANGO_EMAIL_HOST_PASSWORD` at startup.
Before deploying the change, install the Gmail settings in the existing protected
environment file identified by `deployment/production-target.json`; a workstation
`.env` is not included in release artifacts. Use the approved configuration and
deployment procedures, verify the target, and keep the credential out of logs.
This guide does not authorize a deployment or a service restart.

Non-secret settings are documented in `.env.sample`. During the transition,
explicitly selecting `DJANGO_EMAIL_BACKEND=anymail.backends.mailgun.EmailBackend`
retains the previous provider and its existing `MAILGUN_*` configuration.

Use one clearly labeled test message to the administrator for sending validation.
SMTP acceptance confirms that Gmail accepted the message; check the destination
inbox separately before claiming delivery. Do not test against other users or
change account passwords as a sending test.

## Templates

Account email templates live in `inspinia/templates/account/email/`. A shared
520-pixel shell matches the website's ink, teal, warm paper, and serif headings.
Styles are inline and layout tables are presentational. The existing light logo
is exported to a double-resolution PNG and embedded as an inline MIME image with
Content-ID `asterproof-logo`. It needs no remote image download; alt text still
identifies AsterProof if a client hides images. Every message retains its
plain-text alternative.

Password-reset links, confirmation links, verification codes, and login codes
have dedicated layouts. Other account/security messages receive the same HTML
shell through `AccountAdapter.render_mail`, retaining their original instructions,
security details, recipients, and headers. This does not enable code-based login
or change the site's email-verification policy.

References: [Google app passwords](https://support.google.com/accounts/answer/185833),
[Django 5.1 email](https://docs.djangoproject.com/en/5.1/topics/email/),
[allauth email templates](https://docs.allauth.org/en/latest/common/email.html).
