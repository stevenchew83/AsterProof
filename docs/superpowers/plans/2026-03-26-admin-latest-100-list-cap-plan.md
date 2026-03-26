# Admin Latest-100 List Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce a strict server-side `latest 100` cap (ordered by `updated_at DESC`) for admin listing pages so heavy tables no longer load full datasets.

**Architecture:** Keep existing URLs and filter query params, but move filtering into queryset logic and apply a hard limit (`100`) after filters and ordering. Build DataTables payloads only from capped rows, then show a clear cap notice in each template so users understand that search/filter narrows scope while output remains bounded.

**Tech Stack:** Django 5, QuerySet filtering/ordering/slicing, Django templates, pytest (`inspinia/pages/tests.py`), Ruff.

---

## File map

| File | Role |
|------|------|
| `inspinia/pages/views.py` | Add shared limit constant and refactor the three target list views/helpers to apply filter -> order -> slice(100) before serialization |
| `inspinia/templates/pages/problem-statement-list.html` | Show cap notice and visible/limit metadata for statement table |
| `inspinia/templates/pages/completion-record-list.html` | Show cap notice and visible/limit metadata for completion table |
| `inspinia/templates/pages/user-solution-record-list.html` | Show cap notice and visible/limit metadata for user-solution table |
| `inspinia/pages/tests.py` | Add/adjust tests for hard cap, latest ordering, filter+cap interaction, and cap-notice rendering |

## Scope guardrails

- In scope: `pages:problem_statement_list`, `pages:completion_record_list`, `pages:user_solution_record_list`.
- Out of scope: replacing DataTables with server-side pagination APIs, broad unrelated refactors, permission model changes.
- Non-negotiable behavior: cap is strict even when filters match more than 100 rows.

---

### Task 1: Shared cap primitive and statement list queryset-first filtering

**Files:**
- Modify: `inspinia/pages/views.py`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Write failing test for statement hard cap + latest ordering**

Add a test (for example `test_problem_statement_list_caps_to_latest_100_by_updated_at`) that:
- creates 120 statement rows with controlled `updated_at`
- requests `pages:problem_statement_list`
- asserts `len(response.context["statement_datatable_rows"]) == 100`
- asserts first row is newest by `updated_at`

- [ ] **Step 2: Run only the new statement cap test to confirm failure**

Run: `uv run pytest inspinia/pages/tests.py::test_problem_statement_list_caps_to_latest_100_by_updated_at -q`  
Expected: FAIL (current implementation returns all matching rows).

- [ ] **Step 3: Add shared cap constant and queryset filter helper for statement list**

In `inspinia/pages/views.py`:
- add `ADMIN_TABLE_LATEST_LIMIT = 100` near other module constants
- replace Python-side `_filter_statement_table_rows(...)` usage in `problem_statement_list_view` with queryset filtering logic based on existing GET params
- apply ordering and cap in this exact sequence:
  1. filtered queryset
  2. `order_by("-updated_at", "-id")`
  3. slice `[:ADMIN_TABLE_LATEST_LIMIT]`
- keep total stats (`statement_total`, linked/unlinked totals) computed from full base queryset
- set explicit cap context keys for template wiring:
  - `statement_visible_total`
  - `statement_result_limit`
  - `statement_is_capped`

- [ ] **Step 4: Ensure statement row serialization only uses capped queryset**

Keep `_statement_table_rows(...)` row-shape output compatible, but pass only capped queryset input so no full-table serialization occurs.

- [ ] **Step 5: Add statement filter+cap and invalid-MOHS behavior tests**

Add tests that assert:
- filter criteria that match >100 rows still return exactly 100 rows
- restrictive filters can return <100 rows
- invalid `mohs_min`/`mohs_max` values do not crash and preserve non-fatal behavior

- [ ] **Step 6: Run the statement cap test to verify pass**

Run: `uv run pytest inspinia/pages/tests.py::test_problem_statement_list_caps_to_latest_100_by_updated_at -q`  
Expected: PASS.

- [ ] **Step 7: Run statement-list cap/filter regression tests**

Run:
- `uv run pytest inspinia/pages/tests.py::test_problem_statement_list_caps_to_latest_100_by_updated_at -q`
- `uv run pytest inspinia/pages/tests.py::test_problem_statement_list_filter_applies_before_latest_100_cap -q`
- `uv run pytest inspinia/pages/tests.py::test_problem_statement_list_invalid_mohs_filters_are_non_fatal -q`
- `uv run pytest inspinia/pages/tests.py::test_problem_statement_list_shows_statement_rows_and_link_counts -q`
- `uv run pytest inspinia/pages/tests.py::test_problem_statement_list_skips_datatables_when_filters_match_nothing -q`  
Expected: PASS.

- [ ] **Step 8: Commit statement-list cap refactor**

```bash
git add inspinia/pages/views.py inspinia/pages/tests.py
git commit -m "perf(pages): cap problem statement list to latest 100 rows"
```

---

### Task 2: Completion records queryset filtering and strict cap

**Files:**
- Modify: `inspinia/pages/views.py`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Write failing completion cap and filter+cap tests**

Add test (for example `test_completion_record_list_caps_to_latest_100_by_updated_at`) that creates >100 completion rows and asserts:
- exactly 100 rows in `completion_record_rows`
- rows ordered by latest `updated_at` first

Add a second test (for example `test_completion_record_list_applies_filters_before_latest_100_cap`) that asserts:
- broad filters matching >100 rows still return 100
- restrictive filters can return fewer rows

- [ ] **Step 2: Run only the new completion tests and confirm failure**

Run:
- `uv run pytest inspinia/pages/tests.py::test_completion_record_list_caps_to_latest_100_by_updated_at -q`
- `uv run pytest inspinia/pages/tests.py::test_completion_record_list_applies_filters_before_latest_100_cap -q`  
Expected: FAIL.

- [ ] **Step 3: Refactor completion query path to filter/order/limit in DB**

In `inspinia/pages/views.py`:
- update `_admin_completion_listing_rows(...)` to accept filter inputs (contest/user/date status/solution status/search tokens)
- construct queryset predicates directly
- order by `-updated_at`, `-id`
- slice `[:ADMIN_TABLE_LATEST_LIMIT]` before row dict serialization

- [ ] **Step 4: Update `completion_record_list_view` to use refactored helper and cap metadata**

Set context fields:
- `completion_record_visible_total`
- `completion_record_result_limit`
- `completion_record_is_capped`

- [ ] **Step 5: Run completion cap/filter regression tests**

Run:
- `uv run pytest inspinia/pages/tests.py::test_completion_record_list_caps_to_latest_100_by_updated_at -q`
- `uv run pytest inspinia/pages/tests.py::test_completion_record_list_applies_filters_before_latest_100_cap -q`
- `uv run pytest inspinia/pages/tests.py::test_completion_record_list_applies_query_filters -q`  
Expected: PASS.

- [ ] **Step 6: Commit completion list refactor**

```bash
git add inspinia/pages/views.py inspinia/pages/tests.py
git commit -m "perf(pages): cap completion records to latest 100 rows"
```

---

### Task 3: User solution records queryset filtering and strict cap

**Files:**
- Modify: `inspinia/pages/views.py`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Write failing user-solution cap and filter+cap tests**

Add test (for example `test_user_solution_record_list_caps_to_latest_100_by_updated_at`) that creates >100 solutions and asserts:
- exactly 100 rows in `user_solution_record_rows`
- rows ordered by latest `updated_at` first

Add a second test (for example `test_user_solution_record_list_applies_filters_before_latest_100_cap`) that asserts:
- broad filters matching >100 rows still return 100
- restrictive filters can return fewer rows

- [ ] **Step 2: Run only the new user-solution tests and confirm failure**

Run:
- `uv run pytest inspinia/pages/tests.py::test_user_solution_record_list_caps_to_latest_100_by_updated_at -q`
- `uv run pytest inspinia/pages/tests.py::test_user_solution_record_list_applies_filters_before_latest_100_cap -q`  
Expected: FAIL.

- [ ] **Step 3: Refactor solution query path to filter/order/limit in DB**

In `inspinia/pages/views.py`:
- update `_admin_solution_listing_rows(...)` to accept filters (contest/user/status/query)
- apply queryset filtering
- order by `-updated_at`, `-id`
- cap with `[:ADMIN_TABLE_LATEST_LIMIT]` before serialization

- [ ] **Step 4: Update `user_solution_record_list_view` context with cap metadata**

Set:
- `user_solution_record_visible_total`
- `user_solution_record_result_limit`
- `user_solution_record_is_capped`

- [ ] **Step 5: Run user-solution cap/filter regression tests**

Run:
- `uv run pytest inspinia/pages/tests.py::test_user_solution_record_list_caps_to_latest_100_by_updated_at -q`
- `uv run pytest inspinia/pages/tests.py::test_user_solution_record_list_applies_filters_before_latest_100_cap -q`
- `uv run pytest inspinia/pages/tests.py::test_user_solution_record_list_applies_query_filters -q`  
Expected: PASS.

- [ ] **Step 6: Commit user-solution list refactor**

```bash
git add inspinia/pages/views.py inspinia/pages/tests.py
git commit -m "perf(pages): cap user solution records to latest 100 rows"
```

---

### Task 4: Template cap notice and UI consistency

**Files:**
- Modify: `inspinia/templates/pages/problem-statement-list.html`
- Modify: `inspinia/templates/pages/completion-record-list.html`
- Modify: `inspinia/templates/pages/user-solution-record-list.html`
- Test: `inspinia/pages/tests.py`

- [ ] **Step 1: Add consistent cap notice block in all three templates**

Render a single consistent message style using explicit per-page keys:
- problem statements: `statement_visible_total`, `statement_result_limit`, `statement_is_capped`
- completion records: `completion_record_visible_total`, `completion_record_result_limit`, `completion_record_is_capped`
- user solutions: `user_solution_record_visible_total`, `user_solution_record_result_limit`, `user_solution_record_is_capped`

Message pattern:
- "Showing latest {{ <visible_total_key> }} of {{ <result_limit_key> }} max results by updated time. Use search/filters to narrow further."

- [ ] **Step 2: Write/adjust tests asserting cap notice presence**

In existing page-render tests, assert the cap note text is present for each page.

- [ ] **Step 3: Run focused template/view tests**

Run:
- `uv run pytest inspinia/pages/tests.py::test_problem_statement_list_shows_statement_rows_and_link_counts -q`
- `uv run pytest inspinia/pages/tests.py::test_completion_record_list_renders_admin_inventory -q`
- `uv run pytest inspinia/pages/tests.py::test_user_solution_record_list_renders_admin_inventory -q`  
Expected: PASS.

- [ ] **Step 4: Commit template messaging updates**

```bash
git add inspinia/templates/pages/problem-statement-list.html \
        inspinia/templates/pages/completion-record-list.html \
        inspinia/templates/pages/user-solution-record-list.html \
        inspinia/pages/tests.py
git commit -m "ui(pages): show latest-100 cap notice on admin list tables"
```

---

### Task 5: End-to-end validation and cleanup

**Files:**
- Verify only (no new files expected)

- [ ] **Step 1: Run targeted pages test slice**

Run:
`uv run pytest inspinia/pages/tests.py -k "problem_statement_list or completion_record_list or user_solution_record_list" -q`  
Expected: PASS.

- [ ] **Step 2: Run app lint**

Run: `uv run ruff check inspinia/pages`  
Expected: `All checks passed!`

- [ ] **Step 3: Run Django checks**

Run: `UV_CACHE_DIR=/tmp/uv-cache DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py check`  
Expected: `System check identified no issues`.

- [ ] **Step 4: Manual smoke in browser**

Validate each page:
- loads quickly with large test data
- table never exceeds 100 rows
- newest `updated_at` row appears first at initial load
- filters/search work and still cap at 100

- [ ] **Step 5: Final commit if needed**

```bash
git add -A
git commit -m "perf(pages): enforce latest-100 cap for admin inventory tables"
```

---

## Done criteria

- All three target pages enforce strict `100` hard cap.
- Cap is applied after request filters, then ordered by latest `updated_at DESC`.
- No full-table JSON payloads are emitted for these pages.
- Cap notice is visible and consistent on all three templates.
- Focused tests and lint/check commands pass.
