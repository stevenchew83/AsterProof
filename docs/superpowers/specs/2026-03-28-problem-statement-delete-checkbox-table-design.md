# Problem Statement Delete Page — Checkbox Table Design

## Goal

Replace the current single-UUID delete form on the **Delete statement by UUID**
admin page with a searchable checkbox table so an admin can select one or more
statement rows and permanently delete them in one action.

## Context

- Template:
  `inspinia/templates/pages/problem-statement-delete-by-uuid.html`
- View:
  `problem_statement_delete_by_uuid_view` in `inspinia/pages/views.py`
- Form:
  `ProblemStatementDeleteByUuidForm` in `inspinia/pages/forms.py`
- Existing behavior deletes exactly one `ContestProblemStatement` by immutable
  `statement_uuid`, with cascade cleanup for statement techniques and
  statement-linked user completions.
- Nearby admin pages already use Bootstrap/Inspinia cards plus DataTables for
  searchable admin inventory views.

## Scope

### In scope

- Replace the single UUID text input workflow on this page.
- Render a table of statement rows with one checkbox per row.
- Allow deleting multiple selected statement rows in one POST.
- Keep existing admin-only access and permanent-delete semantics.
- Add the smallest useful test coverage in `inspinia/pages/tests.py`.

### Out of scope

- Adding soft delete or undo behavior.
- Moving this delete workflow into the statement editor or statement list page.
- Adding per-row modal confirmations.
- Changing cascade behavior for statement techniques or user completions.
- Adding new shared DataTable helpers for unrelated pages.

## Core decision

Use a DataTable-backed checkbox inventory on the existing delete page and make
that the only delete workflow on this screen.

This keeps the page aligned with current admin tooling:

- search/sort/paging are available immediately for large statement inventories
- the page remains a focused destructive-action tool
- the change stays local to one view, one template, and one form contract

## UX design

### Page structure

Keep the current page shell and title, but replace the body content with one
main delete card containing:

- short destructive-action guidance text
- a compact toolbar with:
  - selected-count summary
  - confirmation checkbox
  - destructive submit button
- a searchable DataTable below the toolbar

### Table columns

Render the following columns:

- selection checkbox
- contest
- year
- day label
- problem code
- statement UUID
- statement preview

The preview should be short and text-only, using an existing statement preview
helper if available instead of duplicating formatting logic.

### Selection behavior

- each row has a checkbox named `statement_uuid`
- a header checkbox selects or clears the currently visible page rows
- a small selected-count label updates in the browser as boxes are toggled
- the delete button remains enabled; server-side validation is still the source
  of truth if nothing is selected

### Confirmation behavior

Keep one explicit confirmation checkbox, reusing the current destructive text
or a close variant of it. The admin must still acknowledge permanent deletion
before the POST is accepted.

## Server-side behavior

### GET

The view should load statement rows for display, ideally with the same related
data already used elsewhere for labels and previews (`linked_problem` if
needed).

The rendered context should include a serialized row payload suitable for the
DataTable and any initial selection metadata the page needs.

### POST

The view should accept a list of submitted `statement_uuid` values plus the
confirmation checkbox.

Validation rules:

- at least one `statement_uuid` must be selected
- confirmation checkbox is required
- duplicate submitted UUID values should be deduplicated server-side
- if any submitted UUID no longer exists, show a clear validation error and do
  not partially delete

### Delete transaction

On a valid submission:

- fetch all targeted `ContestProblemStatement` rows by `statement_uuid`
- delete them inside one transaction
- rely on the existing cascade behavior for:
  - `StatementTopicTechnique`
  - `UserProblemCompletion.statement`

### Success messaging

Replace the single-row success message with a bulk summary, for example:

- deleted row count
- short preview of up to a few deleted labels

The message should stay concise and not dump all UUIDs when many rows are
deleted.

## Form design

The current `ProblemStatementDeleteByUuidForm` should be reshaped from a single
`UUIDField` into a bulk-selection form contract:

- `statement_uuid`: multi-value input from the selected checkboxes
- `confirm_delete`: required boolean

The form should own validation for:

- missing selection
- missing confirmation
- UUID parsing / normalization

This keeps the view thin and makes the POST contract explicit.

## Testing notes

Update `inspinia/pages/tests.py` with the smallest relevant coverage for:

- admin GET renders the delete page and includes the table workflow
- POST with no selected rows shows a validation error
- POST with unknown UUID in the submitted selection shows a validation error
- POST with multiple selected UUIDs deletes all requested rows and cascades
  related technique/completion rows
- non-admin and anonymous access behavior remains unchanged

## Risks and mitigations

- **Risk:** large statement text makes the delete table noisy.
  - **Mitigation:** keep preview short and single-purpose.
- **Risk:** bulk deletion increases the blast radius of mistakes.
  - **Mitigation:** keep the explicit confirmation checkbox and clear destructive
    wording.
- **Risk:** client-side selection across paginated DataTable views can be
  confusing.
  - **Mitigation:** scope header select-all to the visible page rows and keep
    the selected-count indicator visible.

## Manual acceptance

- open the delete page as an admin and confirm the UUID text input is gone
- search for a known statement row and select it from the table
- select multiple rows and verify the count updates
- submit without confirmation and verify the server rejects it
- submit with confirmation and verify selected rows are removed
- confirm related statement technique rows and statement-linked user
  completions are also removed

## Approval

Product direction confirmed in session on 2026-03-28:

- replace the single UUID form entirely
- use a checkbox table as the delete workflow on this page
- keep the change local to this delete screen
