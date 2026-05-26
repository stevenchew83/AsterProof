# Problem List Statement Preview Design

## Goal

Make the problem-list editor safer by showing whether each archive search result
has a linked active problem statement before the curator adds it to a list.

Curators may still add unlinked problems, but the UI must make that risk clear:
public list pages and PDFs will show a missing-statement notice for those rows
until a statement is linked.

## Confirmed Product Decision

Use an allow-with-warning flow:

- linked problems show a statement-ready status and can be previewed before add
- unlinked problems are still addable
- adding an unlinked problem requires an explicit confirmation
- the draft sequence continues to show a subtle no-statement status after add

## Context

The current editor lives in:

- view: `edit_view` and `problem_search_view` in
  `inspinia/problemsets/views.py`
- search/data helpers: `inspinia/problemsets/selectors.py`
- template: `inspinia/templates/problemsets/edit.html`
- tests: `inspinia/problemsets/tests.py`

`searchable_problem_payload(...)` already fetches the latest active
`ContestProblemStatement` per returned `ProblemSolveRecord` so it can resolve
author-specific User MOHS ratings. The same lookup can drive statement
availability without adding another query path.

Public/detail/PDF outputs already have a fallback when no linked statement is
available. This change is about warning during curation, not changing the public
fallback behavior.

## UX Design

Visual thesis: keep the existing dense Inspinia editor style, but make statement
availability impossible to miss with calm status badges and a focused preview
panel.

Content plan:

1. Add a statement status signal to each archive search row.
2. Add a `Preview` action for linked rows.
3. Show a warning state for unlinked rows.
4. Require confirmation before adding an unlinked row.
5. Keep the same draft-sequence editing workflow after a row is added.

Interaction plan:

- `Preview` opens a Bootstrap offcanvas panel using the existing editor shell.
- Linked rows render a short statement preview in that panel.
- Unlinked rows can still open the panel, but it shows the missing-statement
  explanation instead of problem text.
- Clicking `Add` on a linked row adds immediately, as today.
- Clicking `Add` on an unlinked row opens a Bootstrap confirmation modal. The
  modal explains that shared views and PDFs will not contain the problem
  statement until the archive row is linked.
- Confirming the modal adds the row to the draft sequence and preserves the
  existing unsaved-change behavior.

## Search Result Design

Each search row should include a compact statement status in the problem cell or
metadata cell:

- `Statement ready` for rows with an active linked statement
- `No statement` for rows without an active linked statement

The status must be visible before the user reaches the action buttons. It should
use Bootstrap/Inspinia badge styles and Tabler icons, not custom global styling.

The row actions become:

- `Preview`
- `Archive`
- `Add` / `Added`

`Preview` should be available for both states so the user can inspect why a row
is risky. The unlinked preview is an explanatory empty state rather than a
disabled control.

## Preview Panel Design

Use one page-local offcanvas near the search table. JavaScript fills it from the
selected row payload.

Panel content for linked rows:

- problem label
- contest/year/code and UUID
- topic, MOHS, User MOHS if present
- tag badges
- statement preview text

Panel content for unlinked rows:

- same problem identity metadata
- warning title: `No linked statement`
- concise body explaining that adding is allowed, but public lists and PDFs will
  show the missing-statement fallback until a statement is linked
- `Add anyway` button that opens or reuses the unlinked confirmation flow

The preview should use text-only statement content in this first version. Do not
render MathJax or the full statement-render partial inside the search picker,
because the picker payload is JSON and the goal is a quick safety check.

## Data Contract

Extend `_problem_picker_row(...)` to include statement-preview metadata:

- `has_statement`: boolean
- `statement_status_label`: display label for the badge
- `statement_preview`: short plain-text preview, empty for unlinked rows
- `statement_uuid`: string, empty for unlinked rows

`problem_list_picker_rows(...)` should pass the latest statement from existing
list rows so draft rows have the same status data.

`searchable_problem_payload(...)` should pass the latest statement already found
for each search result into `_problem_picker_row(...)`. This keeps the lookup
centralized and avoids new per-row queries.

The plain-text preview should be short and deterministic. If there is no
existing reusable helper, add a small private selector helper that strips
obvious LaTeX whitespace and truncates to a safe length for table/offcanvas
display.

## Confirmation Modal Design

The modal should be page-local in `edit.html` and populated from the row being
added.

Copy:

- title: `Add problem without a statement?`
- body: `This archive row has no linked problem statement. You can add it, but
  public lists and PDFs will show a missing-statement notice until the statement
  is linked.`
- primary action: `Add anyway`
- secondary action: `Cancel`

The modal only appears for rows where `has_statement` is false. It should not
block linked rows or already-added rows.

## Accessibility And States

- `Preview` and `Add` controls are real buttons/links with clear labels.
- The offcanvas title updates to the selected problem label.
- The confirmation modal returns focus naturally through Bootstrap behavior.
- The search status live region remains unchanged for result counts and errors.
- Existing `Added` disabled state remains unchanged after a row is added.
- Draft rows with no statement should show a small `No statement` badge near
  the problem label.

## Non-Goals

- Blocking unlinked problems.
- Changing public list, dashboard detail, or PDF fallback behavior.
- Adding statement-linking actions from the problem-list editor.
- Rendering full MathJax/Asymptote statement content in the search picker.
- Adding new global SCSS, a new JavaScript bundle, or a parallel UI framework.

## Testing Plan

Selector tests:

- search payload marks linked rows with `has_statement: true`, statement UUID,
  and a non-empty preview
- search payload marks unlinked rows with `has_statement: false` and empty
  statement preview fields
- existing draft rows include the statement status metadata
- User MOHS behavior remains scoped to the list author

Template/view tests:

- editor page includes the preview offcanvas and unlinked confirmation modal
- search table JavaScript contains the `Preview` action and unlinked
  confirmation path
- draft rows render a no-statement status for unlinked payload rows

Manual acceptance:

- search for a linked problem and open `Preview`; confirm the statement preview
  appears before adding
- add a linked problem and confirm no modal appears
- search for an unlinked problem and click `Add`; confirm the warning modal
  appears
- confirm `Add anyway`; verify the row is added, marked unsaved, and shows a no
  statement badge in the draft sequence
- save the list and verify existing public fallback behavior remains unchanged

## Implementation Boundary

Expected touched files:

- `inspinia/problemsets/selectors.py`
- `inspinia/templates/problemsets/edit.html`
- `inspinia/problemsets/tests.py`

No model changes, migrations, permissions changes, route changes, global assets,
or external integrations are needed.
