# Problem Statement List — DataTable Header Alignment Design

## Goal

Fix the header/body column misalignment on the **Problem statements** page,
inside the **All problem statements** table, without changing the page's
server-side filter flow or widening scope to other DataTable screens.

## Context

- Template: `inspinia/templates/pages/problem-statement-list.html`
- View: `problem_statement_list_view` in `inspinia/pages/views.py`
- The page already initializes `new DataTable("#problem-statements-table", ...)`
  with `scrollX: true` and `autoWidth: false`.
- The populated table is also wrapped in a Bootstrap `.table-responsive`
  container.
- Other archive/admin pages also use DataTables, but this fix is scoped to the
  **All problem statements** page only.

## Root-cause hypothesis

The page is already using DataTables. The most likely cause of the visible
header/cell drift is the combination of:

- Bootstrap `.table-responsive` around the table, and
- DataTables horizontal scrolling (`scrollX: true`)

These create two competing width/scroll coordination layers for the same
rendered table, which can cause the header and body columns to size
independently.

## Scope

### In scope

- Keep the page as a DataTable.
- Fix alignment only for the populated **All problem statements** table.
- Adjust the template/initialization layer in
  `inspinia/templates/pages/problem-statement-list.html`.
- Add or update the smallest useful test coverage in `inspinia/pages/tests.py`
  to lock in the intended table shell / initialization for this page.

### Out of scope

- Refactoring all DataTables pages to a shared helper.
- Changing server-side filtering, row payload structure, or visible columns.
- Converting this page away from DataTables.
- Fixing similar issues on other list pages in the same pass.

## Core decision

Use a single horizontal-scroll owner on this page.

The recommended fix is:

- remove the redundant `.table-responsive` wrapper around the populated
  DataTable table on this page, and
- keep `scrollX: true` so DataTables continues handling wide-table scrolling.

If needed, add a narrow post-init width-adjustment hook (for example,
`columns.adjust()`) after initialization and/or on resize so the table settles
correctly after the browser computes card width.

## Design details

### Populated table state

For the branch where `statement_filtered_total > 0`:

- render `#problem-statements-table` without the outer Bootstrap
  `.table-responsive` wrapper
- preserve existing table classes (`table`, `table-striped`, `table-bordered`,
  `align-middle`, `w-100`)
- preserve current column definitions and renderers
- preserve DataTables options unless a width-settling hook is needed

### Empty-results state

For the branch where the page renders the static empty table/message:

- leave the current empty-results table shell unchanged unless implementation
  simplicity strongly favors keeping markup parallel
- no DataTable is initialized in this branch today; preserve that behavior

### DataTables init behavior

- keep `scrollX: true`
- keep current paging/order/page-length behavior
- keep `searching: false` because server search/filter UI remains authoritative
- only add a width-adjustment hook if inspection shows it is needed after
  removing the wrapper

## Testing notes

Update the smallest relevant assertions in `inspinia/pages/tests.py` so the
page contract reflects the intended shell for the populated table, including:

- the populated page still includes DataTables assets and initialization
- the populated DataTable branch no longer renders the redundant responsive
  wrapper around `#problem-statements-table` if that is the implemented fix
- the zero-results branch keeps its current non-DataTable behavior

A browser-level visual assertion is out of scope for automated tests here; the
main value is protecting the rendered structure that avoids the alignment bug.

## Risks and mitigations

- **Risk:** removing `.table-responsive` could reduce horizontal overflow
  resilience if DataTables scroll init fails.
  - **Mitigation:** keep `scrollX: true` and add a narrow `columns.adjust()`
    follow-up only if needed.
- **Risk:** changing the shell might unintentionally affect the empty-results
  branch.
  - **Mitigation:** keep the empty branch unchanged unless there is a strong
    implementation reason to align the markup.

## Approval

Product direction confirmed in session on 2026-03-27:

- this page is already a DataTable; do not convert it again
- scope the fix to the **All problem statements** page only
- prefer the smallest change that restores header/cell alignment
