# Users App Guide

This app owns user identity, roles, profile pages, session tracking, and audit history.

## Core model invariants

- `User` authenticates by email. `username`, `first_name`, and `last_name` are intentionally disabled.
- `User.role` is the primary product authorization field. Reuse `user_has_admin_role()` instead of scattering raw role-string checks.
- `UserSession` tracks active and ended sessions for authenticated users.
- `AuditEvent` is the append-only log for auth, role, session, and import actions.

## Change rules

- If you add profile fields, update the relevant forms, templates, admin, tests, and migration together.
- If you change role behavior, audit both the role-management UI and every page-level permission check that depends on admin access.
- If you change session tracking, preserve the migration-safe guards in `monitoring.py`; the code is written to tolerate missing tables during bootstrap and migrate flows.
- If you add or rename `AuditEvent.EventType` values, update event creation sites, event-log filters, badge logic, and tests together.
- Profile analytics pull from `inspinia.pages.models.UserProblemCompletion`; cross-app changes need coordinated tests.

## UI rules

- Profile and monitoring screens should continue to feel like part of the shared dashboard shell.
- Reuse existing user-facing patterns for badges, stat cards, and tables instead of inventing a separate admin style.
- Account and allauth flows should remain compatible with the custom email-first user model.

## Recommended checks

- `uv run pytest inspinia/users/tests`
- `uv run ruff check inspinia/users`

## Extra caution

- Changing the custom user model is high-impact. Prefer additive changes over structural rewrites.
- Session revocation and logout behavior touch middleware, session storage, monitoring helpers, audit events, and UI; treat them as one workflow.
