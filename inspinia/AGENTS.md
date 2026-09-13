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

## UI rules

- Follow [`docs/inspinia-dashboard-style.md`](../docs/inspinia-dashboard-style.md) for dashboard and admin UI.
- Preserve the current layout shell and Bootstrap/Inspinia conventions.
- Use Tabler `ti ti-*` icons when adding new iconography to dashboard pages.
