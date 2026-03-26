# Admin listing performance: latest-100 hard cap

## Goal

Reduce slow page loads on heavy admin listing pages by enforcing a strict server-side result cap and avoiding full-table materialization.

The primary user requirement is:

- never load full `ProblemStatement` / solved-problem / user-solution tables at once
- always return at most the latest 100 rows
- let users narrow results using search/filter controls

## Locked decisions

1. Cap policy is strict: hard max 100 rows per response.
2. Search/filter does not bypass the cap.
3. "Latest" means `updated_at DESC`.
4. Scope includes all three pages:
   - `pages:problem_statement_list` (`/dashboard/problem-statements/`)
   - `pages:completion_record_list` (`/dashboard/completion-records/`)
   - `pages:user_solution_record_list` (`/dashboard/user-solutions/`)

## Current bottlenecks

- `problem_statement_list_view` builds large Python row lists and applies filtering in Python.
- `completion_record_list_view` and `user_solution_record_list_view` build full in-memory row payloads and serialize all filtered rows into DataTables JSON.
- Browser cost scales with payload size, and backend cost scales with full row construction.

## Design

### Shared policy

- Add a shared constant in `inspinia/pages/views.py`:
  - `ADMIN_TABLE_LATEST_LIMIT = 100`
- For each target page:
  1. Apply search/filter at queryset level.
  2. Order by `-updated_at`, then `-id` for deterministic ties.
  3. Slice queryset to `[:ADMIN_TABLE_LATEST_LIMIT]`.
  4. Serialize only the capped rows for template JSON/DataTables.

### Page-level changes

#### 1) Problem statement list

- Refactor `problem_statement_list_view` and helper path (`_statement_table_rows`) so filtering happens in DB, not post-serialization list filtering.
- Keep existing filter controls (`q`, `year`, `topic`, `confidence`, `mohs_min`, `mohs_max`) but map them into queryset predicates.
- Build table rows from the capped queryset only.
- Keep full-library headline counts (`statement_total`, linked/unlinked totals) unchanged, but add capped-result context fields for display:
  - `statement_visible_total`
  - `statement_result_limit`
  - `statement_is_capped` (or equivalent boolean)

#### 2) Completion record list

- Refactor `_admin_completion_listing_rows` to accept filters and return capped rows from queryset-driven selection.
- Apply existing filters (contest/user/date status/solution status/query tokens) in DB where practical.
- Order by `UserProblemCompletion.updated_at DESC`, `id DESC`.
- Serialize only capped rows; keep filter options generated from the same visible set (consistent with strict cap behavior).
- Add cap metadata for template notice:
  - `completion_record_visible_total`
  - `completion_record_result_limit`
  - `completion_record_is_capped`

#### 3) User solution record list

- Refactor `_admin_solution_listing_rows` similarly:
  - filter in queryset
  - order by `ProblemSolution.updated_at DESC`, `id DESC`
  - cap to 100 before row serialization
- Keep existing filter semantics (contest/user/status/search tokens) while enforcing capped output.
- Add cap metadata:
  - `user_solution_record_visible_total`
  - `user_solution_record_result_limit`
  - `user_solution_record_is_capped`

### Template updates

- Update these templates to display cap notice near table headings:
  - `inspinia/templates/pages/problem-statement-list.html`
  - `inspinia/templates/pages/completion-record-list.html`
  - `inspinia/templates/pages/user-solution-record-list.html`
- Standard copy pattern:
  - "Showing latest 100 results by updated time. Use search/filters to narrow further."
- Keep existing DataTables behavior (pagination/sort/search UI) operating only on server-provided capped data.

## Data flow

1. Request arrives with query-string filters.
2. View builds filtered queryset.
3. Queryset ordered by latest `updated_at`.
4. Queryset hard-limited to 100.
5. Capped rows serialized to JSON and rendered.
6. UI shows cap note so users know the table is intentionally bounded.

## Error handling and behavior guarantees

- Invalid numeric filter inputs remain non-fatal (current behavior style); invalid values are ignored.
- Empty-match behavior remains unchanged (no DataTable initialization where already expected).
- Access control remains unchanged (`_require_admin_tools_access`).
- No destructive data-path changes.

## Testing plan

Update `inspinia/pages/tests.py` with focused coverage:

1. Problem statement list cap:
   - Create >100 statements with distinct `updated_at`.
   - Assert only 100 rows rendered and newest row appears first.
2. Completion record list cap:
   - Create >100 completion rows.
   - Assert visible rows length is 100 and ordered by latest `updated_at`.
3. User solution record list cap:
   - Create >100 solutions.
   - Assert visible rows length is 100 and ordered by latest `updated_at`.
4. Filter + cap interaction:
   - With filters matching >100 rows, still capped at 100.
   - With restrictive filters, fewer rows allowed.
5. Template messaging:
   - Assert cap notice text is present on each page.

## Risks and mitigations

- Risk: queryset refactor changes filter semantics.
  - Mitigation: retain existing filter parameter names and add targeted tests for current query behavior.
- Risk: stats cards may be interpreted as global totals.
  - Mitigation: keep explicit cap notice and show visible row count near tables.

## Acceptance criteria

1. Each target admin list page returns at most 100 rows, always.
2. Rows are ordered by latest `updated_at DESC` (stable tie-break).
3. Search/filter still works, but capped output is enforced.
4. Table payload size and server-side row materialization are bounded to 100 entries per response.
5. Tests cover cap, ordering, and filter interactions for all three pages.
