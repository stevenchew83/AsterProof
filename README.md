# AsterProof (Django + Inspinia)

AsterProof is a Django 5 project built on the Inspinia dashboard shell. The current product centers on:

- workbook-imported contest problem analytics
- parsed topic-technique tags with uppercase normalization
- contest problem statement import and analytics
- per-user problem completion tracking
- role-aware profile, audit log, and session monitoring screens

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

## Setup (pip)

```bash
cd /Users/stevenchew/Dev/AsterProof
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/local.txt
createdb asterproof
cp .env.sample .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Setup (uv)

You can use [uv](https://docs.astral.sh/uv/) instead of `pip`; it respects the same `requirements/*.txt` files:

```bash
cd /Users/stevenchew/Dev/AsterProof
uv venv
source .venv/bin/activate
uv pip install -r requirements/local.txt
createdb asterproof
cp .env.sample .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## First run and access model

- Sign in through [http://127.0.0.1:8000/accounts/login/](http://127.0.0.1:8000/accounts/login/).
- `/` is the authenticated landing page and search entry point.
- Most product pages are login-protected.
- When `DEBUG=True`, archive dashboards and import tools are available to any authenticated user.
- When `DEBUG=False`, admin tools require either a superuser or a user whose `role` is `admin`.
- Roles live on `inspinia.users.models.User.role`.
- Django admin is mounted at `/admin/` by default, unless `DJANGO_ADMIN_URL` overrides it.

## Main routes

| Route | Purpose | Access |
|------|---------|--------|
| `/` | Landing page, archive search, and navigation hub | Login required |
| `/problems/` | Contest-first problem explorer | Login required |
| `/problems/contests/<slug>/` | Contest drill-down / checklist-style problem list | Login required |
| `/dashboard/` | Problem analytics dashboard | Login required; admin tools only when `DEBUG=False` |
| `/dashboard/contests/` | Contest analytics dashboard | Login required; admin tools only when `DEBUG=False` |
| `/dashboard/topic-tags/` | Topic-tag analytics dashboard | Login required; admin tools only when `DEBUG=False` |
| `/dashboard/problem-statements/` | Problem statement library list | Login required |
| `/dashboard/problem-statements/analytics/` | Problem statement analytics | Login required; admin tools only when `DEBUG=False` |
| `/import-problems/` | Excel workbook preview/import for archive rows | Login required; admin tools only when `DEBUG=False` |
| `/tools/latex-preview/` | Parse and preview statement text | Login required; save path requires admin tools when `DEBUG=False` |
| `/users/profile/` | User profile, completion stats, and completion import | Login required |
| `/users/manage-roles/` | Role management | Admin-only in practice |
| `/users/monitor/events/` | Audit event log | Admin-focused |
| `/users/monitor/sessions/` | Session monitor and revocation UI | Admin-focused |

## Settings

- Local development defaults to `config.settings.local` via `manage.py`.
- Local development uses `DATABASE_URL`, defaulting to `postgresql:///asterproof`.
- Test runs use `config.settings.test`.
- Production uses `config.settings.production` and expects at least:
  - `DATABASE_URL`
  - `DJANGO_SECRET_KEY`
- A repo-local `.env` file is loaded automatically when present. Start from `.env.sample`.

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

## Quality checks

Common validation commands:

```bash
uv run ruff check config inspinia
uv run pytest inspinia/pages/tests.py
uv run pytest inspinia/users/tests
uv run python manage.py check
```

Run `npm run build` after SCSS or shared asset changes under `inspinia/static/`.

## Agent docs

This repo now includes layered `AGENTS.md` files so coding agents can pick up path-specific constraints before they start editing:

- [AGENTS.md](AGENTS.md)
- [config/AGENTS.md](config/AGENTS.md)
- [inspinia/AGENTS.md](inspinia/AGENTS.md)
- [inspinia/pages/AGENTS.md](inspinia/pages/AGENTS.md)
- [inspinia/users/AGENTS.md](inspinia/users/AGENTS.md)
- [inspinia/templates/AGENTS.md](inspinia/templates/AGENTS.md)
- [inspinia/static/AGENTS.md](inspinia/static/AGENTS.md)

Start at the repo root file, then read the nearest more specific file for the path you are changing.

## Project layout

| Path | Purpose |
|------|---------|
| `config/` | Settings split, middleware, and root URL wiring |
| `docs/` | Shared implementation guidance such as Inspinia dashboard rules |
| `inspinia/pages/` | Archive models, imports, dashboards, statements, completions |
| `inspinia/users/` | Custom user model, roles, profiles, sessions, audit log |
| `inspinia/templates/` | Django templates for pages, users, allauth, and shared layout |
| `inspinia/static/` | SCSS, JS, images, plugins, and compiled frontend assets |
| `requirements/` | Base, local, and production Python dependency sets |

Removed from the old repo: the nested `Seed/` folder, old Excel dashboard generator artifacts, and unrelated AWS SQL/tmp clutter.
