# Inspinia App Guide

This file covers shared expectations for code under `inspinia/`.

## Architecture

- `pages/` owns archive data, imports, analytics, statement tooling, and completion tracking.
- `users/` owns authentication-adjacent product logic: profiles, roles, sessions, and audit history.
- `templates/` and `static/` provide the project UI shell and assets used by both apps.

## Shared coding rules

- Use named, namespaced URLs with `reverse()` or `{% url %}`. Avoid hard-coded path strings.
- Keep permissions explicit. Reuse existing helpers such as `user_has_admin_role` and `_require_admin_tools_access` instead of open-coded role checks.
- Prefer model or import-layer normalization over template-only cleanup.
- Search for existing helpers before adding another formatter, slug builder, filter helper, or dashboard payload function.
- If you change behavior, update the nearest tests in the same app rather than relying only on end-to-end manual checks.

## UI rules

- Follow [`docs/inspinia-dashboard-style.md`](../docs/inspinia-dashboard-style.md) for dashboard and admin UI.
- Preserve the current layout shell and Bootstrap/Inspinia conventions.
- Use Tabler `ti ti-*` icons when adding new iconography to dashboard pages.

## Validation

- `uv run ruff check inspinia`
- `uv run pytest inspinia/pages/tests.py` for archive/import/dashboard changes
- `uv run pytest inspinia/users/tests` for auth/profile/session changes
