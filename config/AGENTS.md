# Config Agent Guide

This directory owns settings composition, middleware wiring, and root URL inclusion.

## What belongs here

- `urls.py`: top-level route inclusion only.
- `settings/base.py`: shared defaults that are safe in every environment.
- `settings/local.py`: local developer convenience.
- `settings/test.py`: deterministic, fast test behavior.
- `settings/production.py`: security, external services, and deployment-specific behavior.

## Settings split rules

- Put a setting in `base.py` only if it is truly shared.
- Keep local-only defaults, debug helpers, and developer ergonomics in `local.py`.
- Keep production services, caches, storage, and strict security in `production.py`.
- Keep test-only speedups and isolation in `test.py`.
- If you add a required environment variable, update `.env.sample` and any relevant setup docs in the same change.

## Existing project assumptions

- `base.py` defaults to SQLite; `local.py` and `production.py` override the database from `DATABASE_URL`.
- The test suite uses `config.settings.test`.
- `TrackActiveSessionMiddleware` is part of the standard stack. Changes to middleware order can affect login tracking and audit behavior.
- `inspinia.users.context_processors.*` feed template behavior across the whole app.
- Root URLs include `inspinia.users`, `allauth`, and `inspinia.pages`; app-specific routes should usually stay in the app `urls.py` modules.

## Change discipline

- When changing middleware, context processors, auth backends, or template settings, audit both `pages` and `users` flows.
- When changing `config/urls.py`, prefer adding or updating routes in the app namespace rather than growing root routing logic.
- Do not move production-only dependencies into `base.py` just to make imports convenient.
- Do not remove migration-safe guards around session/audit tracking unless you have checked startup, tests, and migrate flows.

## Validation

- `uv run python manage.py check`
- `uv run ruff check config`
- Relevant pytest coverage for the affected app after any auth, middleware, or routing change
