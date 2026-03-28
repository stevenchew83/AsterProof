# Problem Statement Delete Checkbox Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single UUID delete form with a searchable checkbox table that lets admins delete multiple statement rows in one action while preserving the current cascade semantics.

**Architecture:** Keep this as a page-local admin workflow. The Django form will validate a submitted list of selected statement UUIDs plus the destructive confirmation checkbox, the view will load/delete the targeted `ContestProblemStatement` rows inside one transaction, and the template will render a DataTable-backed checkbox inventory with a client-side selected-set that submits hidden inputs for the chosen UUIDs. The implementation should reuse existing page patterns such as `_statement_preview_text`, Bootstrap/Inspinia cards, and the local DataTables setup used on other admin pages.

**Tech Stack:** Django forms/views/templates, Bootstrap 5/Inspinia, DataTables, pytest, Django test client, Ruff

---

## File map

- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/forms.py`
  - Reshape `ProblemStatementDeleteByUuidForm` from a single UUID input into a bulk-selection form contract.
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`
  - Build delete-table row payloads, validate submitted UUID selections against the live database, delete selected rows in one transaction, and emit bulk success/error messages.
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/problem-statement-delete-by-uuid.html`
  - Replace the old UUID text input UI with the checkbox table, confirmation control, and page-local DataTables/selection JavaScript.
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`
  - Lock in the new render contract, validation, and bulk-delete cascade behavior.
- Reference only: `/Users/stevenchew/Dev/AsterProof/docs/superpowers/specs/2026-03-28-problem-statement-delete-checkbox-table-design.md`
  - Approved scope and UX contract.
- Reference only: `/Users/stevenchew/Dev/AsterProof/docs/inspinia-dashboard-style.md`
  - Dashboard/admin styling rules for cards, page title, badges, and table shell.

### Task 1: Lock In The Bulk-Delete Contract With Failing Tests

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`
- Reference: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`
- Reference: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/problem-statement-delete-by-uuid.html`

- [ ] **Step 1: Update the admin GET test to require the checkbox-table workflow**

Replace the current lightweight render assertion in `test_problem_statement_delete_by_uuid_page_renders_for_admin` with a table-oriented contract that proves the single UUID text input is gone and the page now exposes a selectable statement inventory.

Use a real statement row in the test setup and assert shapes like:

```python
statement = ContestProblemStatement.objects.create(
    contest_year=2025,
    contest_name="IMO",
    problem_number=1,
    problem_code="P1",
    day_label="Day 1",
    statement_latex="Short preview text for delete page.",
)

response = client.get(reverse("pages:problem_statement_delete_by_uuid"))
response_html = response.content.decode()

assert response.status_code == HTTPStatus.OK
assert "Delete statement by UUID" in response_html
assert 'id="statement-delete-table"' in response_html
assert 'name="statement_uuid"' in response_html
assert str(statement.statement_uuid) in response_html
assert "Short preview text for delete page." in response_html
assert "placeholder=\"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx\"" not in response_html
```

- [ ] **Step 2: Add a no-selection validation test**

Add a new test named `test_problem_statement_delete_by_uuid_requires_selection` that posts only the confirmation checkbox and verifies the server rejects the request without deleting anything.

Use assertions like:

```python
response = client.post(
    reverse("pages:problem_statement_delete_by_uuid"),
    {"confirm_delete": "on"},
)

assert response.status_code == HTTPStatus.OK
assert "Select at least one statement row to delete." in response.content.decode()
```

- [ ] **Step 3: Tighten the unknown-UUID test so it proves no partial delete happens**

Change `test_problem_statement_delete_by_uuid_unknown_uuid_shows_error` so it posts one real statement UUID plus one random UUID. The expected behavior is a validation error and zero deletions.

Example shape:

```python
statement = ContestProblemStatement.objects.create(
    contest_year=2025,
    contest_name="IMO",
    problem_number=1,
    problem_code="P1",
    day_label="Day 1",
    statement_latex="Keep me",
)

response = client.post(
    reverse("pages:problem_statement_delete_by_uuid"),
    {
        "statement_uuid": [str(statement.statement_uuid), str(uuid.uuid4())],
        "confirm_delete": "on",
    },
)

assert response.status_code == HTTPStatus.OK
assert "One or more selected statement rows no longer exist." in response.content.decode()
assert ContestProblemStatement.objects.filter(pk=statement.pk).exists()
```

- [ ] **Step 4: Replace the single-row delete test with a multi-row cascade test**

Update `test_problem_statement_delete_by_uuid_removes_statement_and_cascades` so it deletes at least two statement rows in one POST and proves both rows plus their dependent technique/completion rows are removed.

Use the same page URL and assertions like:

```python
response = client.post(
    reverse("pages:problem_statement_delete_by_uuid"),
    {
        "statement_uuid": [
            str(first_statement.statement_uuid),
            str(second_statement.statement_uuid),
        ],
        "confirm_delete": "on",
    },
    follow=True,
)

assert response.status_code == HTTPStatus.OK
assert not ContestProblemStatement.objects.filter(pk__in=[first_pk, second_pk]).exists()
assert not StatementTopicTechnique.objects.filter(statement_id__in=[first_pk, second_pk]).exists()
assert not UserProblemCompletion.objects.filter(statement_id__in=[first_pk, second_pk]).exists()
assert "Deleted 2 statement row(s)" in response.content.decode()
```

- [ ] **Step 5: Run the focused delete-page tests and verify they fail before implementation**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_problem_statement_delete_by_uuid_page_renders_for_admin \
  inspinia/pages/tests.py::test_problem_statement_delete_by_uuid_requires_selection \
  inspinia/pages/tests.py::test_problem_statement_delete_by_uuid_unknown_uuid_shows_error \
  inspinia/pages/tests.py::test_problem_statement_delete_by_uuid_removes_statement_and_cascades -q
```

Expected: FAIL because the page still renders the old UUID input workflow and the POST handler still expects one UUID.

### Task 2: Implement The Bulk-Selection Form And Delete Backend

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/forms.py`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`
- Test: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`

- [ ] **Step 1: Replace the old form contract with a UUID-list cleaner**

Edit `ProblemStatementDeleteByUuidForm` so `statement_uuid` becomes a multi-value field and `clean_statement_uuid()` parses, trims, validates, and deduplicates the submitted UUID list.

Target shape:

```python
class ProblemStatementDeleteByUuidForm(forms.Form):
    statement_uuid = forms.Field(
        required=False,
        widget=forms.MultipleHiddenInput,
    )
    confirm_delete = forms.BooleanField(
        label="I understand this permanently deletes the statement row, its technique tags, "
        "and any user completions tied to this statement.",
        required=True,
    )

    def clean_statement_uuid(self) -> list[str]:
        raw_values = self.data.getlist("statement_uuid")
        normalized_values: list[str] = []
        seen_values: set[str] = set()

        for raw_value in raw_values:
            normalized_value = str(raw_value or "").strip()
            if not normalized_value:
                continue
            try:
                uuid.UUID(normalized_value)
            except ValueError as exc:
                raise forms.ValidationError(
                    "One or more selected statement UUID values are invalid.",
                ) from exc
            if normalized_value in seen_values:
                continue
            seen_values.add(normalized_value)
            normalized_values.append(normalized_value)

        if not normalized_values:
            raise forms.ValidationError("Select at least one statement row to delete.")
        return normalized_values
```

Remember to add `import uuid` near the top of the form module.

- [ ] **Step 2: Add small view helpers for row payloads and success preview text**

In `inspinia/pages/views.py`, add a small row-shaping helper near the existing statement helpers so the template stays dumb and the preview text is generated in Python.

Use `_statement_preview_text()` directly:

```python
def _problem_statement_delete_row(statement: ContestProblemStatement) -> dict[str, str]:
    return {
        "contest_name": statement.contest_name,
        "contest_year": str(statement.contest_year),
        "day_label": statement.day_label or "—",
        "problem_code": statement.problem_code,
        "statement_uuid": str(statement.statement_uuid),
        "contest_year_problem": statement.contest_year_problem,
        "statement_preview": _statement_preview_text(statement.statement_latex, max_length=120),
    }


def _preview_statement_delete_labels(labels: list[str]) -> str:
    preview_limit = 3
    preview = ", ".join(labels[:preview_limit])
    if len(labels) > preview_limit:
        return f"{preview}, and {len(labels) - preview_limit} more"
    return preview
```

- [ ] **Step 3: Rewrite the delete view to support bulk lookup, validation, and transaction delete**

Refactor `problem_statement_delete_by_uuid_view` so it always loads table rows for rendering and, on POST, validates the submitted UUID list against the live database before deleting.

Target structure:

```python
@login_required
def problem_statement_delete_by_uuid_view(request):
    _require_admin_tools_access(request)

    statement_queryset = ContestProblemStatement.objects.select_related("linked_problem").order_by(
        "-contest_year",
        "contest_name",
        "day_label",
        "problem_number",
        "problem_code",
    )

    if request.method == "POST":
        form = ProblemStatementDeleteByUuidForm(request.POST)
        if form.is_valid():
            selected_statement_uuids = form.cleaned_data["statement_uuid"]
            selected_statements = list(
                statement_queryset.filter(statement_uuid__in=selected_statement_uuids),
            )
            found_uuid_values = {str(statement.statement_uuid) for statement in selected_statements}
            missing_uuid_values = [
                value for value in selected_statement_uuids if value not in found_uuid_values
            ]
            if missing_uuid_values:
                form.add_error("statement_uuid", "One or more selected statement rows no longer exist.")
            else:
                deleted_labels = [statement.contest_year_problem for statement in selected_statements]
                with transaction.atomic():
                    ContestProblemStatement.objects.filter(
                        pk__in=[statement.pk for statement in selected_statements],
                    ).delete()
                messages.success(
                    request,
                    f"Deleted {len(selected_statements)} statement row(s): "
                    f"{_preview_statement_delete_labels(deleted_labels)}.",
                )
                return redirect("pages:problem_statement_delete_by_uuid")
    else:
        form = ProblemStatementDeleteByUuidForm()

    statement_delete_rows = [
        _problem_statement_delete_row(statement)
        for statement in statement_queryset
    ]
    return render(
        request,
        "pages/problem-statement-delete-by-uuid.html",
        {
            "form": form,
            "statement_delete_rows": statement_delete_rows,
            "statement_delete_total": len(statement_delete_rows),
        },
    )
```

- [ ] **Step 4: Run the backend-oriented tests and make sure the validation/delete behavior passes**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_problem_statement_delete_by_uuid_requires_selection \
  inspinia/pages/tests.py::test_problem_statement_delete_by_uuid_unknown_uuid_shows_error \
  inspinia/pages/tests.py::test_problem_statement_delete_by_uuid_removes_statement_and_cascades -q
```

Expected: PASS once the form and view accept bulk UUID submission and reject bad selections without partial delete.

### Task 3: Replace The Template With The DataTable Checkbox UI

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/problem-statement-delete-by-uuid.html`
- Test: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`
- Reference: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/contest-rename.html`

- [ ] **Step 1: Replace the old UUID input card with a form-wrapped table card**

Keep the existing page title and message area, but replace the body with one main form containing:

- destructive guidance text
- selected-count badge
- confirmation checkbox
- delete button
- filter input
- responsive table shell with checkbox column

Target markup shape:

```html
<form method="post" id="statement-delete-form" novalidate>
  {% csrf_token %}
  {{ statement_delete_rows|json_script:"statement-delete-table-data" }}
  <div class="card">
    <div class="card-header border-bottom d-flex flex-wrap align-items-center gap-2">
      <div class="flex-grow-1">
        <h4 class="header-title mb-0">Delete statement rows</h4>
        <p class="text-muted fs-xs mb-0">
          Select one or more imported statement rows, confirm permanent deletion, then submit.
        </p>
      </div>
      <span id="statement-delete-selected-count" class="badge text-bg-light">0 selected</span>
    </div>
    <div class="card-body">
      <div class="mb-3">
        <label class="form-label" for="statement-delete-filter">Filter table</label>
        <input id="statement-delete-filter" type="search" class="form-control" autocomplete="off">
      </div>
      <div id="statement-delete-hidden-fields"></div>
      <div class="table-responsive">
        <table id="statement-delete-table" class="table align-middle w-100 mb-0"></table>
      </div>
      <div class="mt-3 form-check">
        {{ form.confirm_delete }}
        <label class="form-check-label" for="{{ form.confirm_delete.id_for_label }}">{{ form.confirm_delete.label }}</label>
      </div>
      <button type="submit" class="btn btn-danger mt-3">Delete selected statement rows</button>
    </div>
  </div>
</form>
```

Keep the old UUID text input completely removed.

- [ ] **Step 2: Initialize the DataTable with a client-side selected set**

In `{% block extra_javascript %}`, include `partials/datatables-vendor-scripts.html` when rows exist and build a page-local script that:

- parses the JSON row data
- keeps `selectedStatementUuids = new Set()`
- renders the checkbox column from that set
- supports a header select-all checkbox for the current page rows
- updates the selected-count badge
- writes one hidden `statement_uuid` input per selected UUID before submit

Target JavaScript structure:

```javascript
(function () {
  var dataEl = document.getElementById("statement-delete-table-data");
  var tableEl = document.getElementById("statement-delete-table");
  var filterEl = document.getElementById("statement-delete-filter");
  var hiddenFields = document.getElementById("statement-delete-hidden-fields");
  var selectedCount = document.getElementById("statement-delete-selected-count");
  var formEl = document.getElementById("statement-delete-form");
  if (!dataEl || !tableEl || !filterEl || !hiddenFields || !selectedCount || !formEl) return;
  if (typeof DataTable === "undefined") return;

  var rows = JSON.parse(dataEl.textContent);
  var selectedStatementUuids = new Set();

  function updateSelectedCount() {
    selectedCount.textContent = selectedStatementUuids.size + " selected";
  }

  function writeHiddenFields() {
    hiddenFields.innerHTML = "";
    Array.from(selectedStatementUuids).forEach(function (statementUuid) {
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = "statement_uuid";
      input.value = statementUuid;
      hiddenFields.appendChild(input);
    });
  }

  var table = new DataTable("#statement-delete-table", {
    data: rows,
    pageLength: 25,
    lengthMenu: [10, 25, 50, 100],
    scrollX: true,
    autoWidth: false,
    columns: [
      {
        data: "statement_uuid",
        orderable: false,
        searchable: false,
        render: function (value, type, row) {
          if (type !== "display") return value;
          var checked = selectedStatementUuids.has(value) ? " checked" : "";
          return '<input type="checkbox" class="form-check-input js-statement-delete-select" value="' + value + '"' + checked + ' aria-label="Select ' + row.contest_year_problem + '">';
        }
      },
      { data: "contest_name", title: "Contest" },
      { data: "contest_year", title: "Year" },
      { data: "day_label", title: "Day" },
      { data: "problem_code", title: "Problem" },
      { data: "statement_uuid", title: "Statement UUID" },
      { data: "statement_preview", title: "Preview" }
    ]
  });

  filterEl.addEventListener("input", function () {
    table.search(filterEl.value || "").draw();
  });

  tableEl.addEventListener("change", function (event) {
    if (!event.target.matches(".js-statement-delete-select")) return;
    if (event.target.checked) selectedStatementUuids.add(event.target.value);
    else selectedStatementUuids.delete(event.target.value);
    updateSelectedCount();
  });

  formEl.addEventListener("submit", function () {
    writeHiddenFields();
  });

  updateSelectedCount();
})();
```

When you finish the implementation, enhance the first column header so it renders a master checkbox for the visible page rows and keeps its checked/indeterminate state in sync on every draw.

- [ ] **Step 3: Re-run the admin GET render test and make sure it passes**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_problem_statement_delete_by_uuid_page_renders_for_admin -q
```

Expected: PASS, with the response containing the checkbox-table UI and no legacy UUID placeholder input.

### Task 4: Run Broader Verification And Finish Cleanly

**Files:**
- Verify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/forms.py`
- Verify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`
- Verify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/problem-statement-delete-by-uuid.html`
- Verify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`

- [ ] **Step 1: Run the full delete-page test slice**

Run:

```bash
uv run pytest inspinia/pages/tests.py -k "problem_statement_delete_by_uuid" -q
```

Expected: PASS.

- [ ] **Step 2: Run Django checks**

Run:

```bash
uv run python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Run Ruff on the touched Python modules**

Run:

```bash
uv run ruff check inspinia/pages/forms.py inspinia/pages/views.py
```

Expected: PASS.

- [ ] **Step 4: Manually verify the page behavior in a browser**

Run:

```bash
uv run python manage.py runserver
```

Then open `/tools/problem-statements/delete-by-uuid/` and confirm:

- the UUID text input is gone
- searching narrows the visible rows
- selecting rows updates the selected-count badge
- the current page header checkbox selects and clears the visible page rows
- submitting without the confirmation checkbox shows the server-side error
- submitting a real multi-row selection deletes the selected rows
- dependent statement technique rows and statement-linked completions also disappear

- [ ] **Step 5: Review the final diff for scope discipline**

Run:

```bash
git diff --stat -- inspinia/pages/forms.py inspinia/pages/views.py inspinia/templates/pages/problem-statement-delete-by-uuid.html inspinia/pages/tests.py
git diff -- inspinia/pages/forms.py inspinia/pages/views.py inspinia/templates/pages/problem-statement-delete-by-uuid.html inspinia/pages/tests.py
```

Expected: only the form, view, template, and delete-page tests changed.

- [ ] **Step 6: Commit once verification is complete**

```bash
git add inspinia/pages/forms.py inspinia/pages/views.py inspinia/templates/pages/problem-statement-delete-by-uuid.html inspinia/pages/tests.py
git commit -m "feat: add bulk delete table for statement rows"
```
