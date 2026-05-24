# Problem List Statement Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add statement availability, preview, and unlinked-add confirmation to the problem-list editor archive picker.

**Architecture:** Reuse the existing `ContestProblemStatement` lookup in `inspinia/problemsets/selectors.py` and extend the JSON row payload consumed by `edit.html`. Keep UI behavior page-local inside the existing Bootstrap/Inspinia editor template with one offcanvas preview and one confirmation modal.

**Tech Stack:** Django selectors/views/tests, Django templates, Bootstrap 5 offcanvas/modal, page-local vanilla JavaScript, pytest.

---

## File Structure

- `inspinia/problemsets/selectors.py`: add statement metadata to picker rows and provide a private text-preview helper.
- `inspinia/templates/problemsets/edit.html`: render statement status badges, preview offcanvas, unlinked confirmation modal, and page-local JavaScript behavior.
- `inspinia/problemsets/tests.py`: cover selector payload fields, draft-row payload fields, and static editor hooks.

No model, migration, URL, permission, or global asset changes are part of this plan.

---

### Task 1: Extend Picker Payload With Statement Metadata

**Files:**
- Modify: `inspinia/problemsets/tests.py`
- Modify: `inspinia/problemsets/selectors.py`

- [ ] **Step 1: Write failing search-payload assertions**

In `inspinia/problemsets/tests.py`, update `test_problem_list_problem_search_requires_author_and_returns_active_problem_rows` by adding these assertions after the existing `topic_tags` assertion:

```python
    assert payload["results"][0]["has_statement"] is True
    assert payload["results"][0]["statement_status_label"] == "Statement ready"
    assert payload["results"][0]["statement_uuid"] == str(searchable_statement.statement_uuid)
    assert payload["results"][0]["statement_preview"] == "Prove that $a+b \\ge c$."
```

Then add these assertions after `existing_response = client.get(...)`:

```python
    existing_payload = existing_response.json()
    assert existing_payload["results"][0]["is_in_list"] is True
    assert existing_payload["results"][0]["has_statement"] is False
    assert existing_payload["results"][0]["statement_status_label"] == "No statement"
    assert existing_payload["results"][0]["statement_uuid"] == ""
    assert existing_payload["results"][0]["statement_preview"] == ""
```

Replace the existing single-line assertion:

```python
    assert existing_response.json()["results"][0]["is_in_list"] is True
```

with the `existing_payload` block above.

- [ ] **Step 2: Write failing draft-payload assertions**

In `test_problem_list_edit_page_exposes_picker_payload_and_save_urls`, create an unlinked problem list item after the existing item:

```python
    unlinked_problem = _problem(problem="P2", contest="USAMO", year=2025)
    ProblemListItem.objects.create(
        problem_list=problem_list,
        problem=unlinked_problem,
        position=2,
    )
```

Add these assertions after the existing context assertions for `user_mohs`, `hint`, and `comment`:

```python
    draft_rows = response.context["problem_list_draft_rows"]
    assert draft_rows[0]["has_statement"] is True
    assert draft_rows[0]["statement_status_label"] == "Statement ready"
    assert draft_rows[0]["statement_uuid"] == str(statement.statement_uuid)
    assert draft_rows[0]["statement_preview"] == "Prove that $a+b \\ge c$."
    assert draft_rows[1]["has_statement"] is False
    assert draft_rows[1]["statement_status_label"] == "No statement"
    assert draft_rows[1]["statement_uuid"] == ""
    assert draft_rows[1]["statement_preview"] == ""
```

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```bash
uv run pytest inspinia/problemsets/tests.py::test_problem_list_problem_search_requires_author_and_returns_active_problem_rows inspinia/problemsets/tests.py::test_problem_list_edit_page_exposes_picker_payload_and_save_urls -q
```

Expected: FAIL with missing `has_statement` or related statement metadata keys.

- [ ] **Step 4: Add selector implementation**

In `inspinia/problemsets/selectors.py`, change `problem_list_picker_rows` so it passes each row's statement into `_problem_picker_row`:

```python
        picker_row = _problem_picker_row(
            row["problem"],
            is_in_list=True,
            statement=row["statement"],
            topic_tags=row["topic_tags"],
            user_mohs=row["user_mohs"],
        )
```

In `searchable_problem_payload`, change the rows comprehension into a loop so each row receives its latest statement:

```python
    rows = []
    for problem in problems:
        statement = latest_statement_by_problem_id.get(problem.id)
        rows.append(
            _problem_picker_row(
                problem,
                is_in_list=problem.problem_uuid in existing_problem_uuids,
                statement=statement,
                user_mohs=user_mohs_by_problem_id.get(problem.id),
            ),
        )
```

Change `_problem_picker_row` signature to accept the statement:

```python
def _problem_picker_row(
    problem: ProblemSolveRecord,
    *,
    is_in_list: bool,
    statement: ContestProblemStatement | None = None,
    topic_tags: list[str] | None = None,
    user_mohs: int | None = None,
) -> dict:
```

Inside `_problem_picker_row`, add statement fields before returning:

```python
    label = problem_label(problem)
    has_statement = statement is not None
```

Then add these keys to the returned dictionary:

```python
        "has_statement": has_statement,
        "statement_preview": _statement_preview_text(statement),
        "statement_status_label": "Statement ready" if has_statement else "No statement",
        "statement_uuid": str(statement.statement_uuid) if statement is not None else "",
```

Add this private helper near `_problem_topic_tags`:

```python
def _statement_preview_text(statement: ContestProblemStatement | None, *, limit: int = 220) -> str:
    if statement is None:
        return ""
    preview = re.sub(r"\s+", " ", statement.statement_latex or "").strip()
    if len(preview) <= limit:
        return preview
    return f"{preview[: limit - 3].rstrip()}..."
```

- [ ] **Step 5: Run focused tests and verify pass**

Run:

```bash
uv run pytest inspinia/problemsets/tests.py::test_problem_list_problem_search_requires_author_and_returns_active_problem_rows inspinia/problemsets/tests.py::test_problem_list_edit_page_exposes_picker_payload_and_save_urls -q
```

Expected: PASS.

- [ ] **Step 6: Commit selector payload change**

Run:

```bash
git add inspinia/problemsets/selectors.py inspinia/problemsets/tests.py
git commit -m "feat: expose problem list statement status"
```

Expected: commit succeeds with only selector and test changes staged.

---

### Task 2: Add Preview And Unlinked Confirmation UI

**Files:**
- Modify: `inspinia/problemsets/tests.py`
- Modify: `inspinia/templates/problemsets/edit.html`

- [ ] **Step 1: Write failing template hook assertions**

In `test_problem_list_edit_page_exposes_picker_payload_and_save_urls`, add these assertions near the other editor HTML hook assertions:

```python
    assert "problem-list-statement-preview" in response_html
    assert "problem-list-unlinked-confirm-modal" in response_html
    assert "data-preview-problem" in response_html
    assert "data-confirm-unlinked-add" in response_html
    assert "Add problem without a statement?" in response_html
    assert "statementStatusBadge" in response_html
    assert "openStatementPreview" in response_html
```

- [ ] **Step 2: Run focused template test and verify failure**

Run:

```bash
uv run pytest inspinia/problemsets/tests.py::test_problem_list_edit_page_exposes_picker_payload_and_save_urls -q
```

Expected: FAIL because the offcanvas, modal, and JavaScript hooks are not present yet.

- [ ] **Step 3: Add page-local styles**

In `inspinia/templates/problemsets/edit.html`, add these styles inside the existing `{% block extra_css %}` `<style>` block after `.problem-list-picker-status`:

```css
  .problem-list-statement-preview-text {
    max-height: 18rem;
    overflow: auto;
    white-space: pre-wrap;
  }

  .problem-list-preview-meta-grid {
    display: grid;
    gap: .75rem;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  @media (max-width: 575.98px) {
    .problem-list-preview-meta-grid {
      grid-template-columns: 1fr;
    }
  }
```

- [ ] **Step 4: Add preview offcanvas and confirmation modal markup**

In `inspinia/templates/problemsets/edit.html`, add this markup after the load-more button container and before the closing `</div>` of the search card body:

```html
          <div class="offcanvas offcanvas-end" tabindex="-1" id="problem-list-statement-preview" aria-labelledby="problem-list-statement-preview-title">
            <div class="offcanvas-header border-bottom">
              <div>
                <p class="text-muted fs-xs text-uppercase fw-semibold mb-1">Problem preview</p>
                <h5 class="offcanvas-title" id="problem-list-statement-preview-title">Problem preview</h5>
              </div>
              <button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="Close"></button>
            </div>
            <div class="offcanvas-body">
              <div id="problem-list-statement-preview-body" class="d-grid gap-3"></div>
              <div class="d-flex flex-wrap gap-2 mt-3">
                <button type="button" id="problem-list-preview-add-button" class="btn btn-primary btn-sm">
                  <i class="ti ti-plus me-1"></i>Add to list
                </button>
                <button type="button" class="btn btn-outline-secondary btn-sm" data-bs-dismiss="offcanvas">Close</button>
              </div>
            </div>
          </div>

          <div class="modal fade" id="problem-list-unlinked-confirm-modal" tabindex="-1" aria-labelledby="problem-list-unlinked-confirm-title" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
              <div class="modal-content">
                <div class="modal-header">
                  <h5 class="modal-title" id="problem-list-unlinked-confirm-title">Add problem without a statement?</h5>
                  <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                  <p class="mb-2">This archive row has no linked problem statement.</p>
                  <p class="text-muted mb-0">You can add it, but public lists and PDFs will show a missing-statement notice until the statement is linked.</p>
                </div>
                <div class="modal-footer">
                  <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
                  <button type="button" class="btn btn-warning" data-confirm-unlinked-add>
                    <i class="ti ti-alert-triangle me-1"></i>Add anyway
                  </button>
                </div>
              </div>
            </div>
          </div>
```

- [ ] **Step 5: Add JavaScript element references**

In the script block of `edit.html`, after `var loadMoreButton = document.getElementById("problem-list-load-more");`, add:

```javascript
  var statementPreview = document.getElementById("problem-list-statement-preview");
  var statementPreviewTitle = document.getElementById("problem-list-statement-preview-title");
  var statementPreviewBody = document.getElementById("problem-list-statement-preview-body");
  var previewAddButton = document.getElementById("problem-list-preview-add-button");
  var unlinkedConfirmModal = document.getElementById("problem-list-unlinked-confirm-modal");
  var confirmUnlinkedAddButton = document.querySelector("[data-confirm-unlinked-add]");
```

After `var latestResults = [];`, add:

```javascript
  var previewRow = null;
  var pendingUnlinkedRow = null;
```

- [ ] **Step 6: Add status, preview, and add helper functions**

In the script block, add these functions after `userMohsCell(row)`:

```javascript
  function statementStatusBadge(row) {
    if (row.has_statement) {
      return "<span class=\"badge bg-success-subtle text-success\"><i class=\"ti ti-file-check me-1\"></i>" + escapeHtml(row.statement_status_label || "Statement ready") + "</span>";
    }
    return "<span class=\"badge bg-warning-subtle text-warning\"><i class=\"ti ti-file-alert me-1\"></i>" + escapeHtml(row.statement_status_label || "No statement") + "</span>";
  }

  function findLatestRow(problemUuid) {
    return latestResults.find(function (resultRow) {
      return resultRow.problem_uuid === problemUuid;
    });
  }

  function addProblemRow(row) {
    if (!row || draftContains(row.problem_uuid)) return;
    draftRows.push(Object.assign({}, row, {
      comment: row.comment || "",
      custom_title: row.custom_title || "",
      hint: row.hint || "",
      _justAdded: true
    }));
    renderDraftRows();
    renderSearchResults(latestResults);
  }

  function showUnlinkedConfirm(row) {
    pendingUnlinkedRow = row;
    if (window.bootstrap && unlinkedConfirmModal) {
      window.bootstrap.Modal.getOrCreateInstance(unlinkedConfirmModal).show();
      return;
    }
    if (window.confirm("This archive row has no linked problem statement. Add it anyway?")) {
      addProblemRow(row);
      pendingUnlinkedRow = null;
    }
  }

  function requestAddProblem(row) {
    if (!row || draftContains(row.problem_uuid)) return;
    if (!row.has_statement) {
      showUnlinkedConfirm(row);
      return;
    }
    addProblemRow(row);
  }

  function previewMetaItem(label, value) {
    return [
      "<div>",
      "<p class=\"text-muted fs-xs text-uppercase fw-semibold mb-1\">" + escapeHtml(label) + "</p>",
      "<div class=\"fw-semibold\">" + escapeHtml(value || "-") + "</div>",
      "</div>"
    ].join("");
  }

  function renderStatementPreviewBody(row) {
    var tags = tagBadges(row);
    var statementBlock = row.has_statement
      ? [
          "<div>",
          "<p class=\"text-muted fs-xs text-uppercase fw-semibold mb-1\">Statement preview</p>",
          "<div class=\"border rounded p-3 bg-body-tertiary problem-list-statement-preview-text\">" + escapeHtml(row.statement_preview || "No preview text is available.") + "</div>",
          "</div>"
        ].join("")
      : [
          "<div class=\"alert alert-warning mb-0\" role=\"alert\">",
          "<div class=\"fw-semibold mb-1\">No linked statement</div>",
          "<div>You can add this problem, but public lists and PDFs will show a missing-statement notice until the statement is linked.</div>",
          "</div>"
        ].join("");
    return [
      "<div>",
      "<div class=\"d-flex flex-wrap align-items-center gap-2 mb-2\">",
      statementStatusBadge(row),
      row.user_mohs === null || row.user_mohs === undefined || row.user_mohs === "" ? "" : "<span class=\"badge bg-primary-subtle text-primary\">User MOHS " + escapeHtml(row.user_mohs) + "</span>",
      "</div>",
      "<div class=\"problem-list-preview-meta-grid\">",
      previewMetaItem("Contest", row.contest),
      previewMetaItem("Year", row.year),
      previewMetaItem("Problem", row.problem_code),
      previewMetaItem("MOHS", row.mohs),
      "</div>",
      "<p class=\"text-muted fs-xs mt-3 mb-0 font-monospace\">" + escapeHtml(row.problem_uuid) + "</p>",
      "</div>",
      "<div>",
      "<p class=\"text-muted fs-xs text-uppercase fw-semibold mb-1\">Tags</p>",
      tags,
      "</div>",
      statementBlock
    ].join("");
  }

  function openStatementPreview(row) {
    if (!row || !statementPreview || !statementPreviewBody || !statementPreviewTitle) return;
    previewRow = row;
    statementPreviewTitle.textContent = row.problem_label || "Problem preview";
    statementPreviewBody.innerHTML = renderStatementPreviewBody(row);
    if (previewAddButton) {
      var isAdded = draftContains(row.problem_uuid);
      previewAddButton.disabled = isAdded;
      previewAddButton.innerHTML = isAdded
        ? "<i class=\"ti ti-check me-1\"></i>Added"
        : row.has_statement
          ? "<i class=\"ti ti-plus me-1\"></i>Add to list"
          : "<i class=\"ti ti-alert-triangle me-1\"></i>Add anyway";
      previewAddButton.classList.toggle("btn-warning", !row.has_statement && !isAdded);
      previewAddButton.classList.toggle("btn-primary", row.has_statement || isAdded);
    }
    if (window.bootstrap) {
      window.bootstrap.Offcanvas.getOrCreateInstance(statementPreview).show();
    }
  }
```

- [ ] **Step 7: Render status badges and preview action**

In `renderDraftRows()`, add the statement badge below the UUID line in the problem/title cell:

```javascript
        "<div class=\"text-muted fs-xs\">" + escapeHtml(row.problem_uuid) + "</div>",
        "<div class=\"mt-1\">" + statementStatusBadge(row) + "</div>",
```

In `renderSearchResults(rows)`, add the statement badge below the UUID line:

```javascript
        "<div class=\"text-muted fs-xs\">" + escapeHtml(row.contest) + " " + escapeHtml(row.year) + " · " + escapeHtml(row.problem_uuid) + "</div>",
        "<div class=\"mt-1\">" + statementStatusBadge(row) + "</div>",
```

In the search result actions, add the preview button before the archive link:

```javascript
        "<button type=\"button\" class=\"btn btn-outline-secondary btn-sm\" data-preview-problem><i class=\"ti ti-eye me-1\"></i>Preview</button>",
```

- [ ] **Step 8: Route add clicks through confirmation flow**

Replace the existing `[data-add-problem]` click handler body with:

```javascript
      var rowNode = button.closest("[data-result-uuid]");
      if (!rowNode) return;
      var problemUuid = rowNode.getAttribute("data-result-uuid");
      var row = findLatestRow(problemUuid);
      requestAddProblem(row);
```

Then add this preview click branch at the start of the same `searchResultsBody` click listener, before the add button branch:

```javascript
      var previewButton = event.target.closest("[data-preview-problem]");
      if (previewButton) {
        var previewRowNode = previewButton.closest("[data-result-uuid]");
        if (!previewRowNode) return;
        openStatementPreview(findLatestRow(previewRowNode.getAttribute("data-result-uuid")));
        return;
      }
```

The full listener should still ignore clicks that are neither preview nor add.

- [ ] **Step 9: Wire preview Add and modal Confirm buttons**

After the `searchResultsBody` click listener, add:

```javascript
  if (previewAddButton) {
    previewAddButton.addEventListener("click", function () {
      requestAddProblem(previewRow);
    });
  }

  if (confirmUnlinkedAddButton) {
    confirmUnlinkedAddButton.addEventListener("click", function () {
      if (!pendingUnlinkedRow) return;
      addProblemRow(pendingUnlinkedRow);
      pendingUnlinkedRow = null;
      if (window.bootstrap && unlinkedConfirmModal) {
        window.bootstrap.Modal.getOrCreateInstance(unlinkedConfirmModal).hide();
      }
      if (previewRow && previewAddButton) {
        previewAddButton.disabled = true;
        previewAddButton.innerHTML = "<i class=\"ti ti-check me-1\"></i>Added";
        previewAddButton.classList.remove("btn-warning");
        previewAddButton.classList.add("btn-primary");
      }
    });
  }
```

- [ ] **Step 10: Run focused template test and verify pass**

Run:

```bash
uv run pytest inspinia/problemsets/tests.py::test_problem_list_edit_page_exposes_picker_payload_and_save_urls -q
```

Expected: PASS.

- [ ] **Step 11: Commit editor UI change**

Run:

```bash
git add inspinia/templates/problemsets/edit.html inspinia/problemsets/tests.py
git commit -m "feat: preview problem statements before list add"
```

Expected: commit succeeds with only template and test changes staged.

---

### Task 3: Verify Behavior And Visual Fit

**Files:**
- Inspect: `inspinia/problemsets/selectors.py`
- Inspect: `inspinia/templates/problemsets/edit.html`
- Inspect: `inspinia/problemsets/tests.py`

- [ ] **Step 1: Run problemsets test module**

Run:

```bash
uv run pytest inspinia/problemsets/tests.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Django system check**

Run:

```bash
uv run python manage.py check
```

Expected: `System check identified no issues`.

- [ ] **Step 3: Start the local server if no server is already available**

Run:

```bash
uv run python manage.py runserver 127.0.0.1:8000
```

Expected: server starts and prints the local development URL. If port 8000 is in use, use `127.0.0.1:8001`.

- [ ] **Step 4: Visually verify editor state**

Open the editor route from the original request against the local server:

```text
http://127.0.0.1:8000/problem-lists/ac0cf5e3-f3f5-403a-be0f-cb7fcd1687b7/edit/
```

If that list UUID is not present in the local database, run this command to print the newest local editor URL:

```bash
uv run python manage.py shell -c "from inspinia.problemsets.models import ProblemList; row = ProblemList.objects.order_by('-updated_at').first(); print(f'/problem-lists/{row.list_uuid}/edit/' if row else 'NO_LOCAL_PROBLEM_LIST')"
```

Expected: prints a `/problem-lists/.../edit/` path. If it prints `NO_LOCAL_PROBLEM_LIST`, create a list through `/problem-lists/create/` while signed in, then open its edit page.

Use a test account/list available in the local database. Search for a linked problem and an unlinked problem. Verify:

- search rows show `Statement ready` or `No statement` before the action buttons
- `Preview` opens an offcanvas with problem metadata and either statement preview text or the no-statement warning
- linked `Add` adds immediately
- unlinked `Add` opens the confirmation modal
- `Add anyway` adds the row and the draft row shows `No statement`
- the UI still matches the existing Bootstrap/Inspinia editor style

- [ ] **Step 5: Stop the local server**

Stop the `runserver` process with `Ctrl-C`.

Expected: no lingering server process from this verification step.

- [ ] **Step 6: Final git status check**

Run:

```bash
git status --short
```

Expected: clean working tree after the Task 1 and Task 2 commits. If visual verification required a small fix, commit it with:

```bash
git add inspinia/problemsets/selectors.py inspinia/templates/problemsets/edit.html inspinia/problemsets/tests.py
git commit -m "fix: polish statement preview picker"
```
