# Problem Statement List — DataTable And Column Filters Design

## Goal

On the **Problem statements** page, in the **All problem statements** card,
replace the static HTML table and Django pagination with a **DataTables**
grid, add a **per-column filter row** under the headers, and **keep the
existing Search text box** (and the rest of the server-side filter form) as
the only global search UI.

## Context

- Template: `inspinia/templates/pages/problem-statement-list.html` defines
  `#problem-statements-table` and a GET form (`q`, `year`, `topic`,
  `confidence`, `mohs_min`, `mohs_max`).
- View: `problem_statement_list_view` in `inspinia/pages/views.py` builds
  `table_rows` via `_statement_table_rows`, filters with
  `_filter_statement_table_rows`, paginates with `Paginator(..., 25)`, and
  passes `statement_page` to the template. Copy-TSV uses the **full**
  `filtered_rows` list, not only the current page.
- Elsewhere, the app already ships DataTables (Bootstrap 5) and
  `partials/datatables-vendor-scripts.html`, e.g.
  `user-solution-record-list.html` (`json_script` + `new DataTable(...)`).

## Scope

### In scope

- Initialize DataTables on the All problem statements table when
  `statement_total > 0` and the filtered result is non-empty (or show the
  existing empty state when there are zero matching rows).
- Feed the grid from a **JSON payload** of the **current server-filtered**
  rows (`filtered_rows` after `_filter_statement_table_rows`), passed through
  the same JSON-safety path used today (`_json_script_safe`), exposed as a new
  template context key (name TBD in implementation, e.g.
  `statement_datatable_rows`).
- Set **`searching: false`** on DataTables so there is no second global search
  box; the existing `#statement-search-q` field remains unchanged.
- Add a **footer row** (or equivalent second row) with one text input per
  column; wire inputs to `column().search(...).draw()` with behavior appropriate
  per column (plain text vs numeric where needed). Debounce rapid typing where
  it avoids janky redraws.
- Use DataTables for **client-side** paging and sorting on that filtered set
  (defaults aligned with `user-solution-record-list`: e.g. `pageLength: 25`,
  `lengthMenu: [10, 25, 50, 100]`, `scrollX: true` if the wide layout needs
  it).
- **Remove** Django template pagination for this panel when the DataTable is
  active; drop `Paginator` usage from this view path for the list body (the
  view may stop passing `statement_page` or pass only metadata if still useful).
- Update on-page copy that currently implies “pagination shows 25 rows per
  page” purely on the server so it matches the new behavior (server narrows the
  set; grid sorts, pages, and column-filters in the browser).
- Preserve **Copy filtered rows** semantics: TSV continues to reflect **all**
  rows matching the current server filters (unchanged server-side generation).
- Adjust `inspinia/pages/tests.py` (and any assertions on pagination markup /
  row counts per page) to match the new behavior; add coverage that DataTables
  assets and initialization appear when the statement library has data.

### Out of scope

- Server-side / AJAX DataTables pipelines or new JSON API endpoints.
- Changing server-side filter semantics (`_filter_statement_table_rows`) or
  adding new server filter fields.
- Replacing or restyling the Inspinia shell, cards, or KPI tiles above the
  panel.
- Moving copy-TSV generation to the client.

## Core decisions

### Client-side DataTable on the full filtered row set

After each GET, the template embeds **all** `filtered_rows` as JSON and
DataTables renders rows in the browser. This matches the approved approach and
the existing `user-solution-record-list` pattern.

Reason:

- Column filters must apply to the **entire** server-filtered set, not only the
  previous 25-row server page.
- The view already computes the full filtered list for copy-TSV; reusing it
  avoids duplicating filter logic.

### No DataTables global search UI

`searching: false` keeps a single search field: the existing form input `q`.

### Column filter row

A **footer row** of inputs (one per visible column) drives per-column
`column().search` calls. Rendered cell HTML (badges, links) is not the search
target; use row fields and orthogonal `render` types (`display` vs `sort` /
`filter`) so filtering and sorting stay predictable.

### Paginator removal

Django `Paginator` for this list is removed once the grid owns paging, to avoid
two sources of truth.

## Data flow

1. User adjusts server filters (including Search) and submits GET (or Reset).
2. View builds `filtered_rows` as today; builds `statement_copy_tsv` from the
   same list.
3. Template outputs `json_script` for `filtered_rows` and an empty table
   scaffold; script initializes `DataTable` with `data` or columns definition
   mirroring current columns (Year, Contest, Topic, Problem code, Day, Solved,
   Topic tags, MOHS, Confidence, IMO slot, Updated, Solution).
4. User refines visible rows with footer filters and DataTables paging/sort
   without a round-trip.

## Testing notes

- Extend or replace tests that expect `page=` links or “Page X of Y” from
  Django pagination on this page.
- Assert presence of DataTables CSS/JS includes and a stable init hook (e.g.
  `new DataTable("#problem-statements-table"` or equivalent) when statements
  exist and filters yield rows.
- Keep existing tests for login, recheck-links, completion toggles, and row
  visibility unless behavior intentionally changes.

## Risks and mitigations

- **Very large filtered sets** increase HTML/JSON payload size. Mitigation for
  now: accept same practical limits as loading full `table_rows` in memory
  today; document that server-side AJAX DataTables is a future option if needed.
- **Footer inputs vs accessibility**: use `<th scope="row">` or associated
  labels as appropriate so filter inputs are identifiable.

## Approval

Product direction (column filter row, keep server Search box, DataTables
replace static table) was confirmed in session on 2026-03-24.
