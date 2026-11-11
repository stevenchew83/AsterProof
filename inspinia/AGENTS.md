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

- Follow [the INSPINIA 5.2.0 Bootstrap reference](../docs/inspinia-dashboard-style.md) for browser layouts, theme tokens, components, and icons.
