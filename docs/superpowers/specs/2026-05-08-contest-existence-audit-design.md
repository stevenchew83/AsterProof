# Contest Existence Audit Design

## Goal

Add a read-only admin tool that accepts pasted contest scrape text, extracts
contest headers that begin with a year, and checks whether each parsed
contest-year exists in the app's current runtime database.

The page is intended for production audit use. When the app runs in production,
it checks production data. When the app runs locally, it checks local data. It
does not open a separate production database connection.

## Confirmed Product Decisions

- Check both `ContestProblemStatement` and `ProblemSolveRecord`.
- Use exact normalized `(year, contest)` matches to decide whether a row exists.
- Show suggestions for missing or partial rows, but do not count suggestions as
  found.
- Parse only lines that start with a 4-digit year after leading whitespace.
- Provide an audit screen and copyable/export-ready TSV.
- Keep the first version read-only: no import, rename, delete, or repair action.

## Route And Access

Add a new authenticated admin tool under the existing pages app:

- route: `/tools/contest-existence-audit/`
- view name: `pages:contest_existence_audit`
- template: `inspinia/templates/pages/contest-existence-audit.html`

The view uses `@login_required` and `_require_admin_tools_access(request)`,
matching existing operations/utilities such as the handle summary parser and
contest rename tools. This keeps production access limited to admins while
allowing local debug admin-tool access through the existing helper.

## UI Design

Visual thesis: a calm operations workspace with dense, scannable status and one
clear action path.

Content plan:

1. Page title: "Contest existence audit".
2. Input and summary row: multiline paste field on the left, parsed-count and
   status summary on the right after submission.
3. Results table: exact statement/analytics status, counts, and same-year
   suggestions.
4. TSV export: copyable text area or copy button for spreadsheet review.

Interaction thesis:

- Submit parses and checks all detected contest headers in one request.
- Clear empties the input and focuses the textarea.
- Copy TSV writes the generated audit output to the clipboard.

The template extends `layouts/vertical.html`, uses `container-fluid`, the shared
page title partial, Bootstrap/Inspinia card and table patterns, and Tabler icons.
No new global SCSS or JavaScript is needed; page-local JavaScript belongs in
`extra_javascript`.

## Parser Design

Create a small parser module in `inspinia/pages` so parsing can be unit-tested
without going through the view.

Parsing rules:

- Split input into lines and inspect each line independently.
- Strip leading whitespace.
- Accept only lines beginning with `YYYY` followed by whitespace and title text.
- Skip generic container headings such as `2026 Contests3`.
- Normalize parsed contest titles by trimming and collapsing whitespace.
- Remove a trailing duplicate year from titles such as `AIMEAIME 2026`.
- Apply a conservative duplicate-title cleanup for AoPS-style concatenations:
  - `AIMEAIME 2026` becomes `AIME`.
  - `All-Russian OlympiadAll-Russian Olympiad 2026` becomes
    `All-Russian Olympiad`.
- Deduplicate parsed `(year, contest)` rows while tracking first line number and
  occurrence count.

If no contest headers are detected, return a validation error explaining that
only year-prefixed contest header lines are parsed.

## Matching Design

The checker builds same-year inventories from:

- `ContestProblemStatement`: grouped by `contest_year`, `contest_name`
- `ProblemSolveRecord`: grouped by `year`, `contest`

For each parsed contest-year:

- Statement status is found when at least one statement row exists for the exact
  normalized `(contest_year, contest_name)`.
- Analytics status is found when at least one analytics row exists for the exact
  normalized `(year, contest)`.
- Overall status is one of:
  - `both_found`
  - `statements_only`
  - `analytics_only`
  - `missing`

Suggestions are same-year contest names from both tables ranked by simple string
similarity and capped at three names. Suggestions are display-only and exported
in TSV as a joined text field.

## Output Design

The page shows summary KPIs:

- parsed contests
- found in both tables
- partial matches
- missing from both tables

The results table includes:

- first parsed line number
- year
- parsed contest name
- occurrence count
- statement status and statement count
- analytics status and analytics count
- suggestions

The TSV export includes the same audit fields with a header row. It is safe to
paste into a spreadsheet and is deterministic for the same input and database
state.

## Error Handling

- Empty input: form-level validation error.
- No year-prefixed headers: parser validation error shown as a message or form
  error.
- Generic headings are skipped silently unless every detected year line is
  skipped, in which case the no-header error is shown.
- Suggestions never change status, so fuzzy matching cannot create a false
  "found" result.

## Non-Goals

- Importing contest statements or analytics rows.
- Renaming contest rows.
- Connecting from local/dev to a separate production database.
- Checking individual problems within a contest.
- Treating fuzzy matches as existing rows.

## Testing Plan

Parser tests:

- parses year-prefixed contest headers from pasted scrape text
- ignores usernames, `view topic`, day labels, dates, and problem statements
- skips generic headings such as `2026 Contests3`
- cleans duplicated titles such as `AIMEAIME 2026`
- deduplicates repeated contest-year headers while tracking occurrence count
- raises a validation error when no contest headers are detected

View tests:

- requires login
- enforces admin-tool access in production-style settings
- renders the page for an allowed admin user
- POST shows `both_found`, `statements_only`, `analytics_only`, and `missing`
  rows using seeded `ContestProblemStatement` and `ProblemSolveRecord` records
- missing rows include same-year suggestions
- TSV output contains the expected header and audit rows

Navigation smoke:

- add the utility link to the admin operations sidebar near the handle parser
- do not add the tool to the archive hub in v1, because that hub is currently
  focused on archive workflows rather than admin utilities

## Implementation Boundary

This is a focused pages-app change. Expected touched files:

- `inspinia/pages/forms.py`
- `inspinia/pages/urls.py`
- `inspinia/pages/views.py`
- new parser/helper module under `inspinia/pages/`
- new template under `inspinia/templates/pages/`
- `inspinia/templates/partials/sidenav.html`
- `inspinia/pages/tests.py`

No model changes, migrations, global asset build, or external service
configuration are needed.
