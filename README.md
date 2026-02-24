# AsterProof

AsterProof is a Django-based web application that uses the Inspinia UI templates and a Node/Gulp asset pipeline for frontend static assets.

## Project structure

- `manage.py`: Django management entrypoint (`config.settings.local` by default).
- `config/`: Django project configuration (`urls.py`, `wsgi.py`, and environment-specific settings).
- `inspinia/`: Main Django app package (users/pages apps, templates, static files).
- `requirements/`: Python dependency sets for base, local, and production environments.
- `locale/`: Translation sources and locale artifacts.
- `gulpfile.js`, `package.json`: Frontend build pipeline and scripts.

## Prerequisites

- Python 3.12+
- Node.js + npm

## Local setup

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install Python dependencies:

   ```bash
   pip install -r requirements/local.txt
   ```

3. Install Node dependencies:

   ```bash
   npm install
   ```

4. Run database migrations:

   ```bash
   python manage.py migrate
   ```

5. Start Django development server:

   ```bash
   python manage.py runserver
   ```

## Frontend workflow

- Start development asset build/watch:

  ```bash
  npm run dev
  ```

- Build production assets:

  ```bash
  npm run build
  ```

- Build RTL assets:

  ```bash
  npm run rtl
  npm run rtl-build
  ```

## Tests and code quality

- Run test suite:

  ```bash
  pytest
  ```

- Lint Python code:

  ```bash
  ruff check .
  ```

- Optional static checks configured in this repo:

  ```bash
  mypy inspinia
  djlint inspinia/templates --check
  ```

## Part B migration rollout

Part B introduces migration history for previously unmigrated apps. For environments that already have legacy tables, use `--fake-initial` so Django records initial migrations without recreating tables:

```bash
python manage.py migrate users --fake-initial
python manage.py migrate catalog --fake-initial
python manage.py migrate progress --fake-initial
python manage.py migrate notes --fake-initial
python manage.py migrate community --fake-initial
python manage.py migrate organization --fake-initial
python manage.py migrate feedback --fake-initial
python manage.py migrate contests --fake-initial
python manage.py migrate backoffice --fake-initial
```

Or run the helper command:

```bash
python manage.py migrate_part_b
```

## Internationalization

Translation workflow details are documented in `locale/README.md`.
