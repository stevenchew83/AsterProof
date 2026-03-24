# Pages App Guide

This app owns the contest/problem archive and its surrounding tooling.

## Core models and ownership

- `ProblemSolveRecord`: one analytics-sheet problem row keyed canonically by `problem_uuid`. Do not assume `(year, contest, problem)` is globally unique.
- `ProblemTopicTechnique`: parsed technique tags for a problem. Techniques and domain labels are stored in uppercase.
- `ContestProblemStatement`: imported statement text keyed by contest/year/problem code, optionally linked to a `ProblemSolveRecord`. Holds workbook analytics fields (`topic`, `mohs`, etc.) as the long-term canonical copy; `linked_problem` fills gaps until backfilled.
- `StatementTopicTechnique`: parsed technique tags for a statement row (mirror of `ProblemTopicTechnique` on the archive record).
- `UserProblemCompletion`: per-user completion state for a problem.

## Import invariants

- Workbook import expects columns `YEAR`, `TOPIC`, `MOHS`, `CONTEST`, `PROBLEM`, `CONTEST PROBLEM`, and `Topic tags`.
- Preview and write paths should share the same parsing/preparation logic. Do not let preview behavior drift from import behavior.
- `ProblemSolveRecord.topic_tags` is raw workbook text. Parsed/searchable tags belong in `ProblemTopicTechnique`.
- `replace_tags=False` means merge domains for the same technique instead of creating duplicates.
- Topic techniques and domains must remain uppercase across parser, model saves, migrations, previews, and import code paths.

## Statement and UUID invariants

- `ProblemSolveRecord.problem_uuid` and `ContestProblemStatement.problem_uuid` should stay aligned when rows refer to the same problem.
- `ContestProblemStatement.problem_code` is normalized to uppercase in `save()`. Preserve that behavior.
- If you change statement linking logic, update the analytics workbook import, statement import, and statement list/analytics views together.
- Asymptote-aware statement rendering flows through `asymptote_render.py` and the render-preview endpoint. Keep parser and renderer concerns separate.

## View and route discipline

- `views.py` is already broad. Prefer extracting or reusing helpers instead of adding more inline logic.
- Landing search, contest directory pages, dashboards, and statement pages share contest slug and problem anchor helpers. If routes or labels change, update link generation everywhere.
- Keep admin gating intentional. Check both `@login_required` and `_require_admin_tools_access` before changing access behavior.
- If a template or JS widget depends on a payload key, update the view, template, and tests together.

## Current UX shape

- `problem_list_view` is a contest-directory explorer, not a flat raw-problem table.
- Contest drill-down for users is `contest_dashboard_listing_view` (`/dashboard/contests/listing/`). Legacy `/problems/contests/<slug>/` redirects there when logged in.
- The landing page search routes into contest and problem explorer pages, not only dashboards.
- Topic-tag analytics and problem-statement analytics are separate pages with their own payloads.

## Tests and fixtures

- Most app coverage currently lives in `inspinia/pages/tests.py`.
- Use `inspinia/pages/testdata/` when adding statement-parser coverage instead of inventing large inline samples.
- For import changes, cover create, merge, replace, preview, and normalization behavior.
- For statement changes, cover parser output, duplicate detection, and link syncing.

## Recommended checks

- `uv run pytest inspinia/pages/tests.py`
- `uv run ruff check inspinia/pages`
