# Problem Statement List DataTable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the All problem statements HTML table and Django pagination with a client-side DataTables grid (full server-filtered row set in JSON), per-column footer filters, and no DataTables global search; keep the existing GET form Search field and copy-TSV behavior.

**Architecture:** `problem_statement_list_view` continues to build and filter `filtered_rows` in Python. Remove `Paginator` and `statement_list_query`; pass `_json_script_safe(filtered_rows)` as a new context key. The template outputs `json_script` plus an empty `<table id="problem-statements-table">`, loads DataTables assets only when `statement_total > 0` and `statement_filtered_total > 0`, and initializes `new DataTable(...)` with `searching: false`, footer inputs wired to `column().search`, and paging/sorting on the client. Copy-TSV and server filters stay server-side.

**Tech stack:** Django 5 templates, DataTables (Bootstrap 5 bundle already in `inspinia/static/plugins/datatables/`), jQuery (via vendor partial), existing helpers in `inspinia/pages/views.py` (`_statement_table_rows`, `_filter_statement_table_rows`, `_json_script_safe`).

---

## File map

| File | Responsibility |
|------|----------------|
| `inspinia/pages/views.py` | Drop `Paginator` and `_problem_statement_list_filter_querystring` / `statement_list_query` for this view; add `statement_datatable_rows`; remove `statement_page`. |
| `inspinia/templates/pages/problem-statement-list.html` | Conditional DataTables CSS/JS; empty `<tbody>` + `<tfoot>` filters; `json_script`; remove Django pagination `<nav>`; meta/toolbar copy; DataTable init + `createdRow` for `data-problem-uuid`. |
| `inspinia/pages/tests.py` | DataTables present only when `statement_total > 0` and filters match; no Django pagination markup; no global DT search control; zero-match skips DataTables. |

---

## Commit policy

- **Commit 1 (allowed red):** Complete **Task 1** (view + test expectation updates together in one commit). Pytest stays **red** until Task 2 finishes — do **not** land view-only without test updates.
- **Commit 2 (must be green):** Complete **Task 2** (template + JavaScript). Run `pytest -k problem_statement_list` and fix until **green**.

---

### Task 1: View + test expectations (same commit; expect red until Task 2)

**Files:**
- Modify: `inspinia/pages/views.py`
- Modify: `inspinia/pages/tests.py`

- [ ] **Step 1 (discovery):** `rg "data-problem-uuid|problem-statements-table" inspinia` — note any JS/tests that require `data-problem-uuid` on each row; Task 2 must use **`createdRow`** to set `tr.setAttribute("data-problem-uuid", row.problem_uuid)` (or equivalent) so DOM parity is preserved unless grep proves no consumers.

- [ ] **Step 2:** In `problem_statement_list_view`, remove `Paginator`, `statement_page`, the `list_query = _problem_statement_list_filter_querystring(...)` call, and **`statement_list_query`** from the context dict (that helper exists only for prev/next `page=` links today).

- [ ] **Step 3:** Add `statement_datatable_rows` to context: `_json_script_safe(filtered_rows)`. Keep validating JSON serializability as today (extend dumps check to this payload if you rely on that pattern).

- [ ] **Step 4:** `uv run ruff check inspinia/pages/views.py` — remove unused imports (`Paginator`, etc.).

- [ ] **Step 5:** In `test_problem_statement_list_shows_statement_rows_and_link_counts`: remove `assert "dataTables" not in response_html.lower()` and **`assert response.context["statement_page"].paginator.per_page == 25`**. Add: DataTables CSS/JS path substrings and `new DataTable("#problem-statements-table"` in HTML; `id="problem-statements-table-data"` (or your chosen `json_script` id); **`assert 'aria-label="Statement pages"' not in response_html`** (or equivalent) so Django pagination nav is gone; assert **`dataTables_filter` not in `response_html.lower()`** so the default global DataTables search UI is not injected (`searching: false`).

- [ ] **Step 6:** Add `test_problem_statement_list_skips_datatables_when_filters_match_nothing`: at least one statement in DB, `GET` with `?q=__unlikely_token_xyz__`, assert `statement_filtered_total == 0`, assert `dataTables` not in HTML, assert no `new DataTable("#problem-statements-table"`.

- [ ] **Step 7:** Run `uv run pytest inspinia/pages/tests.py -k problem_statement_list -v` — expect **FAILures** on tests that require DataTables markup (until Task 2).

- [ ] **Step 8:** Commit: `refactor: prepare problem statement list for DataTables` (view + tests together).

---

### Task 2: Template + JavaScript (one commit; suite green)

**Files:**
- Modify: `inspinia/templates/pages/problem-statement-list.html`

- [ ] **Step 1:** Add `{% load static %}` if not already present (keep existing `i18n` / `statement_list` loads).

- [ ] **Step 2:** In `extra_css`, link `dataTables.bootstrap5.min.css` only when **`statement_total > 0` and `statement_filtered_total > 0`**.

- [ ] **Step 3:** Replace meta line that used `statement_page.start_index` / `end_index` with copy based on `statement_filtered_total` and `statement_total` (server vs grid behavior per spec).

- [ ] **Step 4:** Update toolbar blurb: remove “pagination shows 25 rows per page” as server-only; describe default 25 rows **in the grid**.

- [ ] **Step 5:** Emit `{{ statement_datatable_rows|json_script:"problem-statements-table-data" }}` only when **`statement_total > 0` and `statement_filtered_total > 0`** (same compound condition as CSS).

- [ ] **Step 6:** Replace server-rendered `<tbody>` loop with empty `<tbody></tbody>`. Add `<tfoot><tr>`: each cell is `<th scope="col">` wrapping `<input type="search" …>` with unique **`aria-label`** (and optional `title`) per column — matches spec a11y note.

- [ ] **Step 7:** Delete the `{% if statement_page.has_other_pages %}` pagination block.

- [ ] **Step 8:** Branch `statement_total > 0` and `statement_filtered_total == 0`: keep empty-state row/message; **no** DataTables CSS/JS/`json_script`/init.

- [ ] **Step 9:** In `extra_javascript`, `{% include 'partials/datatables-vendor-scripts.html' %}` only when **`statement_total > 0` and `statement_filtered_total > 0`**, before the inline init. Keep the copy-button script working (same `statement_total > 0` gate as today; copy still uses hidden textarea).

- [ ] **Step 10:** Inline IIFE: `JSON.parse` from `#problem-statements-table-data`, `escapeHtml`, `new DataTable("#problem-statements-table", { searching: false, data: rows, columns: [...], order: [...], pageLength: 25, lengthMenu: [10, 25, 50, 100], scrollX: true, createdRow: function (row, data) { row.setAttribute("data-problem-uuid", data.problem_uuid || ""); } })` (adjust if UUID field name differs).

- [ ] **Step 11:** Column definitions: mirror existing columns (Year, Contest, Topic, Problem code, Day, Solved, Topic tags, MOHS, Confidence, IMO slot, Updated, Solution). Use `render` with orthogonal types for **sort** (`updated_at_sort`, `user_completion_sort`, numeric MOHS) and plain strings for **filter**. Topic tags: links from `linked_problem_topic_tag_links` in display. IMO slot: prefer Python-side display string (e.g. reuse `_format_imo_slot_label` or align with `imo_slot_labels`) added to row dict if needed.

- [ ] **Step 12:** `initComplete`: debounced footer `input` handlers → `api.column(i).search(value).draw()`; empty string clears search.

- [ ] **Step 13:** `uv run pytest inspinia/pages/tests.py -k problem_statement_list -v` — **PASS**.

- [ ] **Step 14:** Grep other tests under `problem_statement_list` for assumptions about **server-rendered** row HTML or **`statement_page`**; adjust if any break.

- [ ] **Step 15:** Commit: `feat: DataTables and column filters on problem statement list`

---

### Task 3: Final verification

- [ ] **Step 1:** `uv run python manage.py check`

- [ ] **Step 2:** `uv run ruff check inspinia`

- [ ] **Step 3:** Optional manual smoke: server Search + Apply narrows embedded JSON; footer filters narrow visible rows only; Copy filtered rows = full server-filtered set; `data-problem-uuid` present on rows.

---

## Spec reference

`docs/superpowers/specs/2026-03-24-problem-statement-list-datatable-design.md`

## Pattern reference

- `inspinia/templates/pages/user-solution-record-list.html` — `json_script`, `new DataTable`, `escapeHtml`, columns
- `inspinia/templates/partials/datatables-vendor-scripts.html` — script order / `window.DataTable` shim
