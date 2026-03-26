# AsterProof Agent Guide

Start here before touching the repo. Then open the nearest more specific `AGENTS.md` for the path you are editing:

- `config/AGENTS.md`
- `inspinia/AGENTS.md`
- `inspinia/pages/AGENTS.md`
- `inspinia/users/AGENTS.md`
- `inspinia/templates/AGENTS.md`
- `inspinia/static/AGENTS.md`

If a task changes dashboard or admin UI, also read [`docs/inspinia-dashboard-style.md`](docs/inspinia-dashboard-style.md).

When generating **LaTeX or PDF** for olympiad-style written solutions, follow **`.cursor/rules/evan-chen-latex-pdf.mdc`** (`scrartcl`, `\usepackage[sexy]{evan}`, purple problem `mdframed`, claim/proof, KOMA headers).

## Project map

- `config/`: settings split, root URL wiring, environment behavior.
- `inspinia/pages/`: contest/problem archive, workbook imports, problem statements, analytics, and problem completion data.
- `inspinia/users/`: custom user model, roles, profiles, session tracking, and audit events.
- `inspinia/templates/`: Django templates for dashboard, account, and profile UI.
- `inspinia/static/`: SCSS, JS, images, vendored plugins, and compiled frontend assets.

## High-value invariants

- `ProblemSolveRecord.problem_uuid` is the shared identifier that connects analytics rows, statement rows, and user completion rows.
- `ProblemSolveRecord.topic_tags` keeps raw workbook text; parsed searchable tags live in `ProblemTopicTechnique`.
- Topic techniques and their domain labels are normalized to uppercase. Preserve that invariant in new import or edit paths.
- Most tool-style pages are guarded by `@login_required`, and admin-only actions typically route through `_require_admin_tools_access`. Do not widen access casually.
- The project uses the bundled Inspinia/Bootstrap 5 shell. Do not introduce a parallel UI framework.

## Default workflow

- Inspect the nearest models, views, templates, and tests before editing.
- Prefer focused changes that match the surrounding pattern.
- When behavior changes, update the smallest relevant test coverage in the same app.
- Before finishing, run the cheapest checks that meaningfully cover the touched area.

## Common validation commands

- `uv run ruff check config inspinia`
- `uv run pytest inspinia/pages/tests.py`
- `uv run pytest inspinia/users/tests`
- `uv run python manage.py check`
- `npm run build` after changes under `inspinia/static/scss/` or shared frontend asset sources

## Known sharp edges

- `inspinia/pages/views.py` is large and mixes landing page, explorers, dashboards, imports, and statement tooling. Search for existing helpers and view names before adding new ones.
- UI templates and Python views are tightly coupled by context keys and DOM hooks. When one changes, check the other immediately.
- Settings are intentionally split by environment. If a change is not safe for tests and production, it probably does not belong in `config/settings/base.py`.
