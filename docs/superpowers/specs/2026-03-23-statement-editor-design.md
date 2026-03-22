# Statement Editor Design

## Goal

Add a dedicated admin-only side-menu page that lets staff edit existing
`ContestProblemStatement` rows safely through a modal-based editor.

## Why

The repo already has several statement-related tools, but they cover different
parts of the workflow:

- `Problem statements` is a searchable library page
- `Statement links` manages `ContestProblemStatement.linked_problem`
- `Statement metadata` edits linked problem metadata such as topic, MOHS,
  confidence, IMO slot guess, and topic tags

What is still missing is a direct UI for correcting the raw
`ContestProblemStatement` data itself, such as:

- wrong contest name
- wrong year
- wrong day label
- wrong problem code / problem number
- bad statement text
- statement rows that should be inactive

The new page should fill exactly that gap without turning the existing pages
into mixed-purpose tools.

## Scope

### In scope

- a new admin-only side-menu page for editing existing statement rows
- DataTable listing of existing `ContestProblemStatement` rows
- filters for contest, year, link status, and active status
- a per-row modal editor
- one-row-at-a-time save flow
- validation for required fields and uniqueness conflicts

### Out of scope

- creating new statement rows
- deleting statement rows
- bulk raw-statement editing
- editing linked problem metadata on this page
- changing statement links on this page

## Core decisions

### Separate page, not a retrofit

The raw statement editor should be a new page instead of being folded into
`problem-statement-list.html` or `problem-statement-metadata.html`.

Reason:

- `Problem statements` should remain a browse-first library
- `Statement metadata` should stay focused on problem metadata backfill
- raw statement editing has a different risk profile and deserves its own save
  flow and validation rules

### Modal editing

Editing will happen in a modal, not inline inside the table.

Reason:

- `statement_latex` can be long and multiline
- the modal can show both editable fields and read-only identifiers together
- modal validation messages are easier to keep understandable
- accidental edits are less likely than in-cell editing

### Edit existing rows only

Version 1 should only allow editing existing rows.

Reason:

- `ContestProblemStatement` has a uniqueness constraint on
  `(contest_year, contest_name, day_label, problem_code)`
- create/delete introduces more chances to damage imports and link integrity
- existing rows cover the immediate correction use case already

### Link editing stays elsewhere

The page should show the current link state, but should not edit
`linked_problem`.

Reason:

- the repo already has a dedicated `Statement links` tool
- mixing raw row editing and link editing would make failures harder to reason
  about

## Data model coverage

The editor will work against `ContestProblemStatement` and expose:

### Editable fields

- `contest_year`
- `contest_name`
- `day_label`
- `problem_number`
- `problem_code`
- `statement_latex`
- `is_active`

### Read-only fields

- `statement_uuid`
- `problem_uuid`
- current linked problem summary
- `created_at`
- `updated_at`

`contest_year_problem` remains derived in `save()` and should not be edited
directly.

## UX design

### Page placement

Add a new admin-only side-menu item:

- label: `Statement editor`

It should live near:

- `Problem statements`
- `Statement links`
- `Statement metadata`
- `Statement duplicates`

### Page layout

Use the existing Inspinia dashboard shell:

- `layouts/vertical.html`
- `container-fluid`
- `partials/page-title.html`
- KPI cards for quick counts
- one main card for the DataTable

Suggested summary cards:

- total statement rows
- active rows
- inactive rows
- unlinked rows

### Table behavior

The table should be DataTables-based and optimized for finding rows quickly.

Recommended columns:

- `#`
- `Contest-year`
- `Contest`
- `Day`
- `Code`
- `Problem #`
- `Active`
- `Link status`
- `Updated`
- `Edit`

Recommended filters:

- search
- contest select
- year select
- active/inactive select
- linked/unlinked select
- reset button

### Modal behavior

Each row gets an `Edit` action that opens a Bootstrap modal.

The modal should contain:

- a compact read-only identity section
- editable form controls for the raw statement fields
- a large textarea for `statement_latex`
- save and cancel buttons

The modal should also show:

- linked problem label if present
- a small note that linking is edited on the `Statement links` page

## Save workflow

### Request model

Use a dedicated POST action or small update endpoint for one row at a time.

Recommended behavior:

- submit one statement row id per save
- validate on the server
- save the model normally so `problem_code` normalization and
  `contest_year_problem` regeneration still happen through `save()`

### Validation rules

Required:

- `contest_year`
- `contest_name`
- `problem_number`
- `problem_code`
- `statement_latex`

Allow blank:

- `day_label`

Also validate:

- `contest_year` must be an integer
- `problem_number` must be a positive integer
- uniqueness conflict on
  `(contest_year, contest_name, day_label, problem_code)` must be caught and
  surfaced clearly

### Response behavior

After a successful save:

- show a success message
- return the updated row data
- refresh the DataTable row without a full-page reload if practical

If the implementation cost of in-place row refresh is not worth it for version
1, a normal redirect back to the editor page is acceptable.

## Access control

This page must be:

- `@login_required`
- protected by `_require_admin_tools_access`

Non-admin users should not be able to open or submit edits.

## Testing strategy

Add focused tests in `inspinia/pages/tests.py`.

### Required cases

1. Access control
   - login required
   - non-admin blocked

2. Page render
   - side-menu link visible for admins
   - page renders the DataTable payload

3. Successful save
   - admin edits an existing row
   - changed fields persist
   - `contest_year_problem` updates correctly
   - `problem_code` normalization still applies

4. Validation failure
   - missing required field rejects save

5. Uniqueness failure
   - trying to duplicate `(contest_year, contest_name, day_label, problem_code)`
     returns a clear error

6. Safety boundary
   - link fields remain unchanged through this page

## Risks

### Large statement text edits

`statement_latex` can be long and easy to overwrite accidentally. The modal
copy should make clear that this page edits the stored source text directly.

### Constraint collisions

Changing year, contest, day label, or problem code can collide with another row.
The uniqueness error needs to be clear and row-specific.

### Overlapping tools

Admins may confuse:

- raw statement editing
- metadata editing
- statement linking

The new page should explicitly say what it edits and what it does not.

## Acceptance criteria

The work is complete when:

- admins have a side-menu page called `Statement editor`
- the page lists existing `ContestProblemStatement` rows in a searchable,
  filterable DataTable
- each row can be edited through a modal
- edits save only existing rows
- uniqueness and required-field validation are enforced
- `Statement links` remains the place for link changes
- `Statement metadata` remains the place for metadata changes
