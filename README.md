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
python manage.py migrate
python manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) for the dashboard; `/admin/` for Django admin.

## Settings

- Local development: `DJANGO_SETTINGS_MODULE=config.settings.local` (default in `manage.py`).
- Copy `.envs/.local/.django` / `.postgres` from the seed docs if you use the provided env layout, or set `DJANGO_SECRET_KEY` in production.

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
| `inspinia/` | Theme app: `pages`, `users`, templates, static files |
| `requirements/` | `base.txt`, `production.txt`, `local.txt` |

Removed from the old repo: Excel dashboard generator, AWS SQL/tmp artifacts, and the nested `Seed/` folder (content promoted to this root).
