# AsterProof (Django + Inspinia)

Django 5 project using the **Inspinia** admin/dashboard seed (templates, static assets, `inspinia.pages`, `inspinia.users`, django-allauth, Crispy Forms).

## Python environment

- **Django** is declared in `requirements/base.txt` (pulled in by `requirements/local.txt`). The lockfile-style pins there resolve to **Django 5.1.x** (and friends: django-allauth, Crispy, etc.).
- **`.venv`** at the repo root is the intended local virtualenv; it is listed in `.gitignore`. Everyone creates their own copy on disk.

## Setup (pip)

```bash
cd /Users/stevenchew/Dev/AsterProof
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/local.txt
createdb asterproof
cp .env.sample .env
python manage.py migrate
python manage.py runserver
```

## Setup (uv)

You can use [uv](https://docs.astral.sh/uv/) instead of `pip`; it respects the same `requirements/*.txt` files:

```bash
cd /Users/stevenchew/Dev/AsterProof
uv venv              # creates .venv
source .venv/bin/activate
uv pip install -r requirements/local.txt
createdb asterproof
cp .env.sample .env
python manage.py migrate
python manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) for the starter shell; **`/dashboard/`** for problem analytics (bar charts + DataTable). With **`DEBUG=True`** (typical local dev), `/dashboard/` is open without signing in. With **`DEBUG=False`**, only users with the **`admin`** role or **superusers** may access it. Roles (**admin**, **moderator**, **trainer**, **normal**) are stored on each user; after `migrate`, superusers and members of the legacy **`Admin`** auth group are upgraded to **`admin`** role. Admins can manage roles at **`/users/manage-roles/`** (requires sign-in). `/admin/` is the Django admin site.

## Settings

- Local development: `DJANGO_SETTINGS_MODULE=config.settings.local` (default in `manage.py`).
- Local development now defaults to PostgreSQL via `DATABASE_URL`, using `postgresql:///asterproof` if you do not override it.
- Production uses `config.settings.production` and now expects `DATABASE_URL` to point at PostgreSQL, plus `DJANGO_SECRET_KEY`.
- A repo-local `.env` file is read automatically when present. Start from `.env.sample` and override `DATABASE_URL` if your local PostgreSQL user/password/host differ.
- Copy `.envs/.local/.django` from the seed docs only if you still want that layout; the repo no longer depends on `PYTHONPATH` hacks to import the app packages.

If your PostgreSQL instance is not using the default local socket/current-user setup, set `DATABASE_URL` explicitly, for example:

```bash
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/asterproof
```

## Frontend assets (optional)

The repo includes compiled CSS/JS under `inspinia/static/`. To rebuild from SCSS/JS sources:

```bash
npm install
npx gulp build    # or see package.json / gulpfile.js
```

## Layout

| Path | Purpose |
|------|---------|
| `config/` | Django project settings and URL config |
| `docs/inspinia-dashboard-style.md` | Conventions for keeping dashboard UI aligned with Inspinia |
| `inspinia/` | Theme app: `pages`, `users`, templates, static files |
| `requirements/` | `base.txt`, `production.txt`, `local.txt` |

Removed from the old repo: Excel dashboard generator, AWS SQL/tmp artifacts, and the nested `Seed/` folder (content promoted to this root).
