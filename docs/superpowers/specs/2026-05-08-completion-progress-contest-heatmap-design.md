# Completion Progress Contest Heatmap Design

## Summary

Add a contest completion heatmap to the completion progress analytics page at `/dashboard/completion-progress/`, and by reuse to `/dashboard/my-progress/`, immediately before the "Filtered completion rows" table.

The heatmap uses the page's existing `contest` query parameter as its contest selector. This keeps the page shareable and prevents two independent contest filters from disagreeing.

## Goals

- Show year-by-problem completion coverage for one statement-backed contest.
- Reuse the existing contest heatmap visual language from `contest-advanced-analytics`.
- Scope completion state to the page's selected user:
  - admin progress page: the selected user
  - my progress page: the signed-in user
- Preserve the existing completion progress filters, charts, table, CSV export, and difficulty editing behavior.
- Add focused test coverage for payload, rendering, selector behavior, and user scoping.

## Non-Goals

- Do not add a second independent contest selector.
- Do not change completion storage or matching semantics.
- Do not redesign the completion progress dashboard.
- Do not broaden admin-only access.

## UI Design

The existing filter card remains the contest selector. Its `Contest` select continues to submit `contest=<name>` in the query string.

Add one full-width card after the chart rows and before the `Filtered completion rows` card:

- Header title: `Completion heatmap`
- Header copy: `Year-by-problem completion coverage for this contest. Green shows your completions on those rows; red means you have not completed any row in that cell yet.`
- Header badge: `<year_total> years · <problem_code_total> codes`
- Legend:
  - green: `Your completions`
  - red: `No completion from you yet`
  - orange: `Mixed coverage when a year/code has multiple rows`, shown only when needed
  - gray: `No statement row for that year/code`
- Body:
  - ApexCharts heatmap when a contest is selected and statement-backed problem codes exist
  - info alert when no contest is selected
  - info alert when the contest has no statement-backed problem codes

The heatmap should use the same scroll behavior, color states, compact labels, and click-through-to-problem behavior as `contest-advanced-analytics`.

## Data Design

Add a helper in `inspinia/pages/completion_progress.py` for the contest heatmap payload so the large view stays smaller and the behavior can be tested directly.

Inputs:

- `contest`: selected contest string from `CompletionProgressFilters.contest`
- `user`: the selected completion user

Processing:

1. If `contest` or `user` is missing, return an empty payload with a state message.
2. Load active `ContestProblemStatement` rows for the selected contest.
3. Build sorted problem-code columns using `_problem_sort_key`-compatible ordering.
4. Build descending year rows.
5. Mark a cell:
   - `empty` when no statement row exists for that year/code
   - `unsolved` when statement rows exist but none are completed by the selected user
   - `partial` when some, but not all, rows are completed
   - `solved` when all rows are completed
6. Treat direct statement completions and legacy linked-problem completions the same way the existing contest heatmap does.
7. Include `solution_url` for linked problem rows when available.

Output shape should match the existing `contest_completion_heatmap` contract enough for template and JavaScript reuse:

- `chart`
- `filled_cell_total`
- `has_partial_cells`
- `problem_code_total`
- `problem_codes`
- `rows`
- `year_total`
- `selected_contest`

## Template And JavaScript

Update `inspinia/templates/pages/completion-progress-analytics.html`:

- Add heatmap-specific CSS using the existing `contest-completion-*` class pattern with page-local names or shared-compatible names.
- Render the heatmap card before the table.
- Add `json_script` for the heatmap chart payload.
- Reuse the ApexCharts vendor include already present on the page.
- Add heatmap rendering JavaScript alongside the existing chart functions.
- Keep DataTables initialization unchanged.

The page currently includes ApexCharts for its existing charts, so no new dependency is needed.

## Edge Cases

- No selected user: keep the current no-completion-row alert behavior.
- No selected contest: show an info alert in the heatmap card telling the user to select a contest.
- Invalid contest value: no new 404; the existing filter behavior simply yields no matching completion rows, and the heatmap card shows no statement-backed data.
- Selected contest with statements but no completions: render all present statement cells as red unsolved.
- Selected contest with missing year/code pairs: render those cells gray empty.
- Multiple statement rows for one year/code: render partial state when completion coverage is mixed.

## Tests

Add or update tests in `inspinia/pages/tests.py`:

- The completion progress page includes `Completion heatmap` before `Filtered completion rows`.
- The heatmap uses the same selected `contest` query parameter as the table and charts.
- The heatmap payload marks solved, unsolved, empty, and partial cells correctly.
- Admin selected-user mode scopes heatmap completions to `selected_user`, not `request.user`.
- My-progress mode scopes heatmap completions to the signed-in user.
- The template includes the heatmap chart DOM id and JSON payload only when appropriate.

Run the focused test file or targeted tests, plus `uv run ruff check inspinia/pages`, before completion.
