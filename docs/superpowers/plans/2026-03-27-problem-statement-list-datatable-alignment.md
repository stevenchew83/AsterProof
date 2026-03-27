# Problem Statement List DataTable Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the All problem statements table so DataTables header cells and body cells stay aligned, while preserving the existing server-side filter flow and page behavior.

**Architecture:** This is a page-local integration fix, not a DataTables conversion. The plan removes the redundant Bootstrap responsive wrapper from the populated DataTable branch in the statement-list template, keeps DataTables `scrollX` as the single horizontal-scroll owner, and locks that structure in with focused page tests. A manual browser check remains required because the reported defect is visual.

**Tech Stack:** Django templates, Django test client, DataTables (Bootstrap 5 integration), pytest, Ruff

---

## File map

- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/problem-statement-list.html`
  - Owns the populated and empty table shells for the All problem statements page and the page-local DataTable initialization.
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`
  - Owns response-level regression coverage for the problem statement list page.
- Reference only: `/Users/stevenchew/Dev/AsterProof/docs/superpowers/specs/2026-03-27-problem-statement-list-datatable-alignment-design.md`
  - Approved scope and acceptance criteria.

### Task 1: Lock In The Table-Shell Contract With Failing Tests

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`
- Reference: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/problem-statement-list.html`

- [ ] **Step 1: Update the populated-page test to require the non-responsive DataTable shell**

Edit `test_problem_statement_list_shows_statement_rows_and_link_counts` so it keeps the existing DataTables assertions and also requires the populated branch to render the statement table shell without Bootstrap’s `.table-responsive` wrapper.

Example assertion shape:

```python
assert 'id="problem-statements-table"' in response_html
assert 'class="statement-table-shell"' in response_html
assert 'statement-table-shell table-responsive' not in response_html
assert 'new DataTable("#problem-statements-table"' in response_html
```

- [ ] **Step 2: Update the zero-results test to require the current static responsive shell**

Edit `test_problem_statement_list_skips_datatables_when_filters_match_nothing` so it keeps the current “no DataTables assets/init” assertions and also proves the empty-results branch still renders the static responsive wrapper.

Example assertion shape:

```python
assert response.context["statement_filtered_total"] == 0
assert 'new DataTable("#problem-statements-table"' not in response_html
assert 'statement-table-shell table-responsive' in response_html
```

- [ ] **Step 3: Run the focused tests to verify they fail before implementation**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_problem_statement_list_shows_statement_rows_and_link_counts \
  inspinia/pages/tests.py::test_problem_statement_list_skips_datatables_when_filters_match_nothing -q
```

Expected: FAIL because the populated template still uses `.table-responsive` today.

### Task 2: Remove The Conflicting Wrapper In The Populated DataTable Branch

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/problem-statement-list.html`
- Test: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`

- [ ] **Step 1: Change only the populated branch wrapper around `#problem-statements-table`**

In the `statement_filtered_total > 0` branch, keep the shell div but remove the Bootstrap `.table-responsive` class so DataTables `scrollX` is the only horizontal-scroll owner.

Target shape:

```html
<div class="statement-table-shell">
  <table id="problem-statements-table" class="table table-striped table-bordered align-middle w-100">
    ...
  </table>
</div>
```

Keep the zero-results branch unchanged:

```html
<div class="statement-table-shell table-responsive">
  <table class="table table-striped table-bordered align-middle w-100">
    ...
  </table>
</div>
```

- [ ] **Step 2: Keep the existing DataTable configuration intact unless the visual issue clearly persists**

Preserve the current page behavior:

```javascript
new DataTable("#problem-statements-table", {
  data: rows,
  searching: false,
  order: [[10, "desc"]],
  pageLength: 25,
  lengthMenu: [10, 25, 50, 100],
  scrollX: true,
  autoWidth: false,
  columns: [...]
});
```

Do not add shared helpers or refactor other list pages. Only if wrapper removal alone is insufficient during verification, add the narrowest page-local width-settling follow-up such as:

```javascript
var table = new DataTable("#problem-statements-table", { ... });
window.requestAnimationFrame(function () {
  table.columns.adjust();
});
```

- [ ] **Step 3: Re-run the focused tests and make sure they pass**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_problem_statement_list_shows_statement_rows_and_link_counts \
  inspinia/pages/tests.py::test_problem_statement_list_skips_datatables_when_filters_match_nothing -q
```

Expected: PASS.

### Task 3: Run Broader Verification And Manual Visual Acceptance

**Files:**
- Verify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/problem-statement-list.html`
- Verify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`

- [ ] **Step 1: Run the statement-list page test slice**

Run:

```bash
uv run pytest inspinia/pages/tests.py -k "problem_statement_list" -q
```

Expected: PASS.

- [ ] **Step 2: Run Ruff for the touched app files**

Run:

```bash
uv run ruff check inspinia/pages
```

Expected: PASS.

- [ ] **Step 3: Manually verify the visual fix in a browser**

Use a local dev session and open the All problem statements page:

```bash
uv run python manage.py runserver
```

Then check `/dashboard/problem-statements/` with seeded statement rows.

Manual acceptance checklist:

- At desktop width, header columns align with body cells.
- At a narrower width that requires horizontal scrolling, header columns still align while scrolling.
- After the table has loaded, resize the viewport and confirm alignment still holds.
- Sorting, paging, and page-length controls still work.
- The existing server filter form still drives which rows are loaded.
- The zero-results case still shows the static empty table without DataTables initialization.

- [ ] **Step 4: Review the final diff for scope discipline**

Run:

```bash
git diff --stat -- inspinia/templates/pages/problem-statement-list.html inspinia/pages/tests.py
git diff -- inspinia/templates/pages/problem-statement-list.html inspinia/pages/tests.py
```

Expected: only the page template and its tests changed, with no unrelated page or DataTables refactors.

- [ ] **Step 5: Commit only after tests, lint, and manual visual acceptance all pass**

```bash
git add inspinia/templates/pages/problem-statement-list.html inspinia/pages/tests.py
git commit -m "fix: align problem statement datatable columns"
```
