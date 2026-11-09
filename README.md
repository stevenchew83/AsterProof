# AsterProof (Django + Inspinia)

AsterProof is a Django application for olympiad mathematics. The public website
offers a Solution Writer, a library of published learning resources, and shared
community proofs. The signed-in workspace brings together the contest archive,
mathematical catalogue, progress tracking, training, and solution authoring.
Operator tools cover rankings, moderation, AI review, and operations.

Start with the [documentation index](docs/README.md) for subsystem guides, release
contracts, and historical records. The routes below describe this repository's
implementation. Features with rollout controls can vary by environment.

## Stack

- Django 5.1.x
- `django-allauth` for auth flows
- `crispy-forms` + `crispy-bootstrap5`
- Inspinia / Bootstrap 5 templates and SCSS under `inspinia/`
- PostgreSQL in local and production settings via `DATABASE_URL`
- SQLite fallback in shared base settings and test settings

## Python environment

- Django and Python dependencies are declared in `requirements/*.txt`.
- `pyproject.toml` defines pytest, coverage, mypy, djLint, and Ruff settings.
- `.venv/` at the repo root is the intended local virtualenv and is gitignored.

For Gmail SMTP setup, the hidden app-password prompt, and account email styling,
see [transactional email](docs/email.md).

For the public pages, draft-first learning library, and newsletter consent flow,
see [public website and library](docs/public-website.md).

## Setup (pip)

Run these setup commands from the repository root.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/local.txt
createdb asterproof
cp .env.sample .env
python manage.py migrate
python manage.py seed_training_hub
python manage.py createsuperuser
python manage.py runserver
```

## Setup (uv)

You can use [uv](https://docs.astral.sh/uv/) instead of `pip`; it respects the same `requirements/*.txt` files:

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements/local.txt
createdb asterproof
cp .env.sample .env
python manage.py migrate
python manage.py seed_training_hub
python manage.py createsuperuser
python manage.py runserver
```

`seed_training_hub` is idempotent and creates development-only sample accounts:

| Role | Email | Password |
|------|-------|----------|
| Admin | `training-admin@example.com` | `training-admin` |
| Trainer | `training-trainer@example.com` | `training-trainer` |
| Student | `training-student@example.com` | `training-student` |

## First run and access model

- Sign in through [http://127.0.0.1:8000/accounts/login/](http://127.0.0.1:8000/accounts/login/).
- The public homepage is `/`. Sign in to open the dashboard, archive workspace,
  or your saved solutions.
- Archive tools that use the standard admin-tools gate can be available to signed-in
  users in `DEBUG`. In production that gate requires the app Admin role or
  superuser status. Individual tools can impose additional checks.
- Roles live on `inspinia.users.models.User.role`.
- Django admin is mounted at `/admin/` by default, unless `DJANGO_ADMIN_URL` overrides it.

## Training workspaces

The legacy Training Hub uses `/dashboard/` for points, levels, submissions, and
trainer feedback. Its roadmap remains available at `/training/legacy/`.
`PointLedger` records material completions and reviewed submission awards.
`seed_training_hub` supplies the local demo and default level thresholds.

[Training 2.0](docs/README.md#mathematics-training-20) adds a workspace for
catalogue-based learning, versioned notes, and curated pathways. When the module
is enabled, `/training/` leads to `/learning/`. Contribution intake and publication
have separate controls.

## Main routes

| Route | Purpose | Access |
|---|---|---|
| `/` | Homepage and Solution Writer | Public |
| `/library/` | Published learning resources | Public |
| `/community/proofs/` | Directory of public community proofs | Public |
| `/dashboard/` | Signed-in dashboard with legacy training progress | Sign-in required |
| `/archive/` | Contest archive tools and analytics | Sign-in required |
| `/dashboard/topic-tags/` | Mathematics catalogue | Sign-in required |
| `/training/` | Training entry point | Sign-in required |
| `/learning/` | Training 2.0 workspace | Sign-in, approval, and module enablement |
| `/solutions/` | Your saved solutions | Sign-in required |
| `/rankings/` | Olympiad rankings | Moderator or admin |
| `/dashboard/user-solutions/` | User Solution Records inventory | Admin tools |

## Settings

- Local development defaults to `config.settings.local` via `manage.py`.
- Local development uses `DATABASE_URL`, defaulting to `postgresql:///asterproof`.
- Test runs use `config.settings.test`.
- Production uses `config.settings.production` and expects at least:
  - `DATABASE_URL`
  - `DJANGO_SECRET_KEY`
- A repo-local `.env` file is loaded automatically when present. Start from `.env.sample`.
- Shared progress at `/dashboard/progress/alex/` and `/dashboard/progress/ben/`
  is restricted to the configured Alex/Ben accounts, while both accounts are active
  and approved for app access. Set both `DJANGO_PROGRESS_ALEX_EMAIL` and
  `DJANGO_PROGRESS_BEN_EMAIL` to enable sharing. Display names
  do not grant access. Shared pages show completions, technique coverage, and the
  published training roadmap; they do not grant editing or administrator access.

If your PostgreSQL instance is not using the default local socket/current-user setup, set `DATABASE_URL` explicitly, for example:

```bash
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/asterproof
```

## Frontend assets

Compiled CSS and JS already live under `inspinia/static/`. Rebuild only when you change SCSS or shared frontend asset sources:

```bash
npm install
npm run build
```

If you change dashboard-facing UI, follow [`docs/inspinia-dashboard-style.md`](docs/inspinia-dashboard-style.md).

## Production dependencies

`requirements/production.txt` (including `requirements/base.txt`) is the reviewed production dependency authority.
`requirements/production.lock` is its fully transitive Python 3.12 Linux lock and includes hashes for every resolved
distribution. Dependencies also declared in `pyproject.toml` must use the same exact version.

After intentionally editing a production requirement, regenerate without upgrading unrelated packages and validate it:

```bash
python scripts/deployment/check_production_lock.py --write
python scripts/deployment/check_production_lock.py --verify-resolution
```

For an explicitly reviewed dependency upgrade, use
`python scripts/deployment/check_production_lock.py --write --upgrade` and review the complete lock diff. CI builds a
hash-verified Linux wheelhouse from this lock, rejects non-wheel wheelhouse output, then proves a fresh environment can
install from that wheelhouse with network access disabled.

## Production static files (AWS)

All dashboard JS/CSS and vendored `plugins/` under `inspinia/static/` must be **built and collected** into `STATIC_ROOT` (`staticfiles/` at the repo root) before or during deploy. **User uploads** use the configured `MEDIA_ROOT`; production must set `DJANGO_MEDIA_ROOT` to the confirmed persistent shared-media directory outside versioned releases. Configure the reverse proxy to serve `/media/` from that persistent directory (Django does not serve media when `DEBUG=False`).

**Build + collect (recommended):**

```bash
ASTERPROOF_PYTHON="$PWD/.venv/bin/python" ./scripts/build_and_collectstatic.sh
```

The script deliberately requires `ASTERPROOF_PYTHON`; point it at a production-lock-installed release or CI environment.
Or manually: `npm ci && npm run build`, then
`DJANGO_SETTINGS_MODULE=config.settings.staticfiles .venv/bin/python manage.py collectstatic --noinput`.

**Deploy artifact:** The running app (or reverse proxy) must serve `/static/` from that collected tree — for example WhiteNoise (enabled in production settings) and/or nginx/ALB `alias` to `STATIC_ROOT`. Avoid mixing another origin for the same `/static/...` paths. The production and staticfiles settings use WhiteNoise compressed manifest storage, so collected assets include hashed names plus gzip variants by default, and brotli variants when brotli support is installed.

**Verify after deploy:** On production, open DevTools → Network and confirm `vendors.min.js`, `app.js`, and `app.min.css` return **200** from your **app hostname** with correct content types and `Content-Encoding: gzip` or `br` when requested. Compare with localhost on the same page.

## Quality checks

Common validation commands:

```bash
uv run ruff check config scripts
uv run pytest inspinia/pages/tests.py
uv run pytest inspinia/users/tests
uv run python manage.py check
```

Run `npm run build` after SCSS or shared asset changes under `inspinia/static/`.

## Scheduled maintenance

The technique progress dashboard uses precomputed catalog facts. Production should run the stale-only rebuild command on
a scheduler such as cron or a systemd timer:

```bash
python manage.py recompute_technique_progress_catalog --if-stale
```

Admin dashboard buttons only mark the catalog as needing rebuild; this scheduled command performs the expensive refresh.

## Production deployment

GitHub Actions and the protected `production` environment are the sole normal production authority. A local “merge and
deploy” request means merging through a pull request and dispatching the exact current `main` SHA through the
[`Production deploy`](.github/workflows/production-deploy.yml) workflow; it never authorizes a workstation SSH deploy.

- [Normal production release](docs/deployment/production-release.md)
- [Operator login and AsterProof AWS SSO](docs/deployment/production-release.md#operator-login)
- [One-time target bootstrap](docs/deployment/production-bootstrap.md)
- [GitHub governance](docs/deployment/github-administration.md)
- [Rollback and operation recovery](docs/deployment/rollback-and-recovery.md)
- [Production monitoring](docs/deployment/production-monitoring.md)
- [Credential and host-key rotation](docs/deployment/credential-rotation.md)
- [Host replacement](docs/deployment/host-replacement.md)
- [Disaster recovery and break glass](docs/deployment/disaster-recovery.md)

All target paths and service identities must come from the confirmed target contract. Historical production paths are
not authority. Production bootstrap, activation, host mutation, and break-glass recovery remain separately authorized
operational actions.

## Agent docs

This repo now includes layered `AGENTS.md` files so coding agents can pick up path-specific constraints before they start editing:

- [AGENTS.md](AGENTS.md)
- [config/AGENTS.md](config/AGENTS.md)
- [inspinia/AGENTS.md](inspinia/AGENTS.md)
- [inspinia/pages/AGENTS.md](inspinia/pages/AGENTS.md)
- [inspinia/users/AGENTS.md](inspinia/users/AGENTS.md)
- [inspinia/solutions/AGENTS.md](inspinia/solutions/AGENTS.md)
- [inspinia/templates/AGENTS.md](inspinia/templates/AGENTS.md)
- [inspinia/static/AGENTS.md](inspinia/static/AGENTS.md)

Start at the repo root file, then read the nearest more specific file for the path you are changing.

## Project layout

| Path | Purpose |
|------|---------|
| `config/` | Settings split, middleware, and root URL wiring |
| [`docs/`](docs/README.md) | Subsystem guides, operational contracts, and historical records |
| `inspinia/pages/` | Archive models, imports, dashboards, statements, completions |
| `inspinia/users/` | Custom user model, roles, profiles, sessions, audit log |
| `inspinia/templates/` | Django templates for pages, users, allauth, and shared layout |
| `inspinia/static/` | SCSS, JS, images, plugins, and compiled frontend assets |
| `requirements/` | Base, local, and production Python dependency sets |

Removed from the old repo: the nested `Seed/` folder, old Excel dashboard generator artifacts, and unrelated AWS SQL/tmp clutter.
