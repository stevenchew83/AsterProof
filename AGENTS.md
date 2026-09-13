# AsterProof Agent Guide

## Scoped guidance

For the paths being changed, use the applicable nested `AGENTS.md` files under `config/` and `inspinia/` (including `pages/`, `users/`, `solutions/`, `templates/`, and `static/`).

- Dashboard/admin UI: use [the dashboard style contract](docs/inspinia-dashboard-style.md). Keep the bundled Inspinia/Bootstrap 5 shell; do not introduce a parallel UI framework.
- Full compilable olympiad LaTeX/PDF solutions: follow [the Evan Chen layout rule](.cursor/rules/evan-chen-latex-pdf.mdc).
- Historical plans under `docs/plans/` and `docs/superpowers/` provide task context, not standing workflow authorization. Their commit, worktree, and deployment steps require explicit user authorization; skill references do not mandate invocation.

## Cross-app invariants

- `ProblemSolveRecord.problem_uuid` connects analytics, statement, solution, and user completion rows; preserve that shared identity.
- Tool pages generally use `@login_required`; admin actions use `_require_admin_tools_access`. Preserve access boundaries.
- Templates and views share context keys and DOM hooks. Coordinate changes with their consumers.

## Completion and checks

### Read-only command authorization

Read-only commands within the requested task are pre-approved, including production diagnostics. Do not ask for approval before each read-only command; this supersedes the earlier per-command approval requirement for production reads. For production, use the `asterproof-prod` alias, show the exact command and its purpose before execution, and report the exit status and relevant findings afterward. Keep queries bounded and do not expose secrets or unrelated personal data.

This authorization does not cover production writes, deployments, restarts, privilege escalation, credential or permission changes, or copying production files/databases locally. Those retain their existing action-specific approval requirements.

For an implementation request, complete the authorized local edits, relevant checks, and fixes for failures caused by the change without pausing after each reversible step. Finish when the requested behavior is verified and the final diff is reviewed, or report a concrete blocker. Leave unrelated failures outside scope. Existing production and external-action approval boundaries still apply.

Select checks for the touched area; the commands below are not a requirement to run every suite:

- Python: `uv run ruff check` with the changed files; app-specific pytest commands are in nested guides. Add regression coverage for behavior changes. Broaden coverage for shared auth, routing, middleware, or import/linking changes.
- Settings/routing: `uv run python manage.py check` using the intended local/test environment.
- SCSS/shared asset sources: `npm run build`.
- Instruction/documentation-only changes: check references and `git diff --check`; application tests are unnecessary unless executable examples or generated artifacts are affected.

Pytest selects `config.settings.test` through `pyproject.toml`; this is not a guarantee that arbitrary commands or environment overrides are isolated from external services.
