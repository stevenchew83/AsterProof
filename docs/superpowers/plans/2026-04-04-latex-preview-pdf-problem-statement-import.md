# LaTeX Preview PDF Problem Statement Import Implementation Plan

> **Status: Historical — implemented and superseded.** The initial single-PDF flow was implemented; the current importer also supports multiple PDFs and URL input. The original checklist, examples, and commands are retained as planning history, and unchecked steps do not represent pending work.

Use the current [import form](../../../inspinia/pages/forms.py), [preview handler](../../../inspinia/pages/views.py), [PDF extraction helper](../../../inspinia/pages/statement_import.py), and [regression tests](../../../inspinia/pages/tests.py) for current behavior. The single-file form and view examples below describe the earlier design.

**Goal:** Let `/tools/latex-preview/` accept a PDF upload, extract text server-side, and parse/save structured problem statements through the existing backend parser flow.

**Architecture:** Keep `parse_contest_problem_statements(...)` as the single parser and add one pre-parse source-resolution layer in `latex_preview_view`: either use pasted `source_text` or extract text from an uploaded PDF. Enforce mutual exclusivity in `ProblemStatementImportForm`, route extraction through a dedicated helper in `statement_import.py`, and keep preview/save payload generation unchanged after source resolution.

**Tech Stack:** Django forms/views/templates, pytest, `pypdf`

---

## File structure

- Modify: `requirements/base.txt`
  - Add pinned `pypdf` dependency used by server-side PDF extraction.
- Modify: `inspinia/pages/forms.py`
  - Extend `ProblemStatementImportForm` to support exactly one source (`source_text` or `file`).
- Modify: `inspinia/pages/statement_import.py`
  - Add `extract_statement_text_from_pdf(...)` helper and normalization/error behavior.
- Modify: `inspinia/pages/views.py`
  - Wire upload path into `latex_preview_view` while preserving existing parse/save workflow.
- Modify: `inspinia/templates/pages/latex-preview.html`
  - Add PDF upload UI and multipart form encoding.
- Modify: `inspinia/pages/tests.py`
  - Add focused tests for extraction helper, source validation, PDF preview/save flow, and upload UI rendering.

### Task 1: Add PDF extraction helper with unit tests

**Files:**
- Modify: `inspinia/pages/tests.py`
- Modify: `inspinia/pages/statement_import.py`

- [ ] **Step 1: Write the failing extraction-helper tests**

Add imports near existing statement import imports in `inspinia/pages/tests.py`:

```python
from inspinia.pages.statement_import import ProblemStatementImportValidationError
from inspinia.pages.statement_import import extract_statement_text_from_pdf
```

Add tests near other statement parser tests:

```python
def test_extract_statement_text_from_pdf_normalizes_and_joins_pages(monkeypatch):
    class _FakePage:
        def __init__(self, text: str | None) -> None:
            self._text = text

        def extract_text(self) -> str | None:
            return self._text

    class _FakeReader:
        def __init__(self, _stream) -> None:
            self.pages = [
                _FakePage("2026 Spain Mathematical Olympiad\r\nDay 1\x00"),
                _FakePage("1 First statement."),
                _FakePage(None),
                _FakePage("  \n2 Second statement.\n"),
            ]

    monkeypatch.setattr("inspinia.pages.statement_import.PdfReader", _FakeReader)

    upload = SimpleUploadedFile(
        "sample.pdf",
        b"%PDF-1.4\n%mock\n",
        content_type="application/pdf",
    )

    extracted = extract_statement_text_from_pdf(upload)

    assert extracted == (
        "2026 Spain Mathematical Olympiad\n"
        "Day 1\n\n"
        "1 First statement.\n\n"
        "2 Second statement."
    )


def test_extract_statement_text_from_pdf_raises_validation_error_when_reader_fails(monkeypatch):
    class _BrokenReader:
        def __init__(self, _stream) -> None:
            raise ValueError("broken pdf")

    monkeypatch.setattr("inspinia.pages.statement_import.PdfReader", _BrokenReader)

    upload = SimpleUploadedFile(
        "broken.pdf",
        b"%PDF-1.4\n%broken\n",
        content_type="application/pdf",
    )

    with pytest.raises(ProblemStatementImportValidationError, match="Could not read the uploaded PDF"):
        extract_statement_text_from_pdf(upload)


def test_extract_statement_text_from_pdf_raises_validation_error_when_no_text(monkeypatch):
    class _FakePage:
        def extract_text(self) -> str | None:
            return "   "

    class _ReaderNoText:
        def __init__(self, _stream) -> None:
            self.pages = [_FakePage()]

    monkeypatch.setattr("inspinia.pages.statement_import.PdfReader", _ReaderNoText)

    upload = SimpleUploadedFile(
        "empty.pdf",
        b"%PDF-1.4\n%empty\n",
        content_type="application/pdf",
    )

    with pytest.raises(ProblemStatementImportValidationError, match="No extractable text was found in the uploaded PDF"):
        extract_statement_text_from_pdf(upload)
```

- [ ] **Step 2: Run tests to verify they fail before implementation**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_extract_statement_text_from_pdf_normalizes_and_joins_pages \
  inspinia/pages/tests.py::test_extract_statement_text_from_pdf_raises_validation_error_when_reader_fails \
  inspinia/pages/tests.py::test_extract_statement_text_from_pdf_raises_validation_error_when_no_text \
  -q
```

Expected:

- Failures because `extract_statement_text_from_pdf` does not exist yet.

- [ ] **Step 3: Implement extraction helper in `statement_import.py`**

Add import near top-level imports:

```python
from pypdf import PdfReader
```

Add helper below `ProblemStatementImportValidationError`:

```python
def extract_statement_text_from_pdf(uploaded_file) -> str:
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        pass

    try:
        reader = PdfReader(uploaded_file)
    except Exception as exc:  # noqa: BLE001
        msg = "Could not read the uploaded PDF. Please upload a valid text-based PDF file."
        raise ProblemStatementImportValidationError(msg) from exc

    page_chunks: list[str] = []
    for page in reader.pages:
        try:
            raw_text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            msg = "Could not extract text from one or more PDF pages."
            raise ProblemStatementImportValidationError(msg) from exc

        normalized = raw_text.replace("\x00", "")
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.strip()
        if normalized:
            page_chunks.append(normalized)

    extracted_text = "\n\n".join(page_chunks).strip()
    if not extracted_text:
        msg = "No extractable text was found in the uploaded PDF. The file may be image-only."
        raise ProblemStatementImportValidationError(msg)

    return extracted_text
```

- [ ] **Step 4: Run the extraction-helper tests again**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_extract_statement_text_from_pdf_normalizes_and_joins_pages \
  inspinia/pages/tests.py::test_extract_statement_text_from_pdf_raises_validation_error_when_reader_fails \
  inspinia/pages/tests.py::test_extract_statement_text_from_pdf_raises_validation_error_when_no_text \
  -q
```

Expected:

- All three tests pass.

- [ ] **Step 5: Commit helper + helper tests**

Run:

```bash
git add inspinia/pages/statement_import.py inspinia/pages/tests.py
git commit -m "feat(pages): add pdf text extraction helper for statement parsing"
```

### Task 2: Enforce single-source input and wire PDF source in view

**Files:**
- Modify: `inspinia/pages/tests.py`
- Modify: `inspinia/pages/forms.py`
- Modify: `inspinia/pages/views.py`

- [ ] **Step 1: Write failing view/form behavior tests**

Add helper near existing upload helpers in `inspinia/pages/tests.py`:

```python
def _pdf_upload(name: str = "contest.pdf", payload: bytes = b"%PDF-1.4\n%upload\n") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, payload, content_type="application/pdf")
```

Add tests near existing `latex_preview` tests:

```python
def test_latex_preview_parse_action_accepts_pdf_upload_and_uses_extracted_text(client, monkeypatch):
    user = UserFactory()
    client.force_login(user)

    monkeypatch.setattr(
        "inspinia.pages.views.extract_statement_text_from_pdf",
        lambda _uploaded: LATEX_STATEMENT_SAMPLE,
    )

    response = client.post(
        reverse("pages:latex_preview"),
        {"action": "preview", "source_text": ""},
        files={"file": _pdf_upload()},
    )

    assert response.status_code == HTTPStatus.OK
    assert ContestProblemStatement.objects.count() == 0
    assert response.context["parsed_statement_payload"]["contest_name"] == SPAIN_OLYMPIAD_NAME
    assert response.context["parsed_statement_payload"]["problem_count"] == EXPECTED_STATEMENT_PROBLEM_TOTAL
    assert response.context["form"]["source_text"].value().startswith("2026 Spain Mathematical Olympiad")


def test_latex_preview_save_action_accepts_pdf_upload_for_admin(client, monkeypatch):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    monkeypatch.setattr(
        "inspinia.pages.views.extract_statement_text_from_pdf",
        lambda _uploaded: LATEX_STATEMENT_SAMPLE,
    )

    response = client.post(
        reverse("pages:latex_preview"),
        {"action": "save", "source_text": ""},
        files={"file": _pdf_upload()},
    )

    assert response.status_code == HTTPStatus.OK
    assert ContestProblemStatement.objects.count() == EXPECTED_STATEMENT_PROBLEM_TOTAL
    assert response.context["statement_import_result"]["created_count"] == EXPECTED_STATEMENT_PROBLEM_TOTAL


def test_latex_preview_rejects_source_text_and_pdf_together(client):
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("pages:latex_preview"),
        {"action": "preview", "source_text": LATEX_STATEMENT_SAMPLE},
        files={"file": _pdf_upload()},
    )

    assert response.status_code == HTTPStatus.OK
    html = response.content.decode("utf-8")
    assert "Use either pasted contest text or a PDF upload, not both." in html


def test_latex_preview_rejects_when_no_source_is_provided(client):
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("pages:latex_preview"),
        {"action": "preview", "source_text": ""},
    )

    assert response.status_code == HTTPStatus.OK
    assert "Paste contest text or upload a PDF." in response.content.decode("utf-8")


def test_latex_preview_rejects_non_pdf_upload(client):
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("pages:latex_preview"),
        {"action": "preview", "source_text": ""},
        files={
            "file": SimpleUploadedFile(
                "contest.txt",
                b"not pdf",
                content_type="text/plain",
            ),
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert "Please upload a .pdf file." in response.content.decode("utf-8")


def test_latex_preview_pdf_extraction_error_is_displayed(client, monkeypatch):
    user = UserFactory()
    client.force_login(user)

    def _raise(_uploaded):
        msg = "Could not read the uploaded PDF. Please upload a valid text-based PDF file."
        raise ProblemStatementImportValidationError(msg)

    monkeypatch.setattr("inspinia.pages.views.extract_statement_text_from_pdf", _raise)

    response = client.post(
        reverse("pages:latex_preview"),
        {"action": "preview", "source_text": ""},
        files={"file": _pdf_upload()},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["parsed_statement_payload"] is None
    assert "Could not read the uploaded PDF. Please upload a valid text-based PDF file." in response.content.decode(
        "utf-8"
    )
```

- [ ] **Step 2: Run the new view/form tests to verify failure**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_latex_preview_parse_action_accepts_pdf_upload_and_uses_extracted_text \
  inspinia/pages/tests.py::test_latex_preview_save_action_accepts_pdf_upload_for_admin \
  inspinia/pages/tests.py::test_latex_preview_rejects_source_text_and_pdf_together \
  inspinia/pages/tests.py::test_latex_preview_rejects_when_no_source_is_provided \
  inspinia/pages/tests.py::test_latex_preview_rejects_non_pdf_upload \
  inspinia/pages/tests.py::test_latex_preview_pdf_extraction_error_is_displayed \
  -q
```

Expected:

- Failures because `ProblemStatementImportForm` has no `file` field and `latex_preview_view` does not resolve PDF source.

- [ ] **Step 3: Implement form and view changes**

Update `ProblemStatementImportForm` in `inspinia/pages/forms.py`:

```python
class ProblemStatementImportForm(forms.Form):
    file = forms.FileField(
        required=False,
        label="Contest PDF",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".pdf,application/pdf",
            },
        ),
    )
    source_text = forms.CharField(
        required=False,
        label="Contest text",
        strip=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control font-monospace",
                "form": "latex-preview-form",
                "id": "latex-preview-input",
                "rows": 24,
                "spellcheck": "false",
            },
        ),
    )

    def clean_file(self):
        uploaded = self.cleaned_data.get("file")
        if uploaded is None:
            return None
        name = getattr(uploaded, "name", "") or ""
        if not name.lower().endswith(".pdf"):
            msg = "Please upload a .pdf file."
            raise forms.ValidationError(msg)
        return uploaded

    def clean_source_text(self):
        return (self.cleaned_data.get("source_text") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        uploaded = cleaned_data.get("file")
        source_text = cleaned_data.get("source_text") or ""
        if uploaded and source_text:
            msg = "Use either pasted contest text or a PDF upload, not both."
            raise forms.ValidationError(msg)
        if uploaded is None and not source_text:
            msg = "Paste contest text or upload a PDF."
            raise forms.ValidationError(msg)
        return cleaned_data
```

Update imports in `inspinia/pages/views.py`:

```python
from inspinia.pages.statement_import import extract_statement_text_from_pdf
```

Update POST path in `latex_preview_view`:

```python
if request.method == "POST":
    form = ProblemStatementImportForm(request.POST, request.FILES)
    if form.is_valid():
        action = request.POST.get("action") or "preview"
        source_text = form.cleaned_data["source_text"]
        source_label = "pasted text"
        uploaded_pdf = form.cleaned_data.get("file")
        if uploaded_pdf is not None:
            source_text = extract_statement_text_from_pdf(uploaded_pdf)
            source_label = "PDF upload"

        try:
            parsed_import = parse_contest_problem_statements(source_text)
        except ProblemStatementImportValidationError as exc:
            messages.error(request, str(exc))
        else:
            if uploaded_pdf is not None:
                form = ProblemStatementImportForm(initial={"source_text": source_text})

            parsed_statement_payload = build_problem_statement_preview_payload(parsed_import)
            for problem in parsed_statement_payload["problems"]:
                problem.update(_statement_render_payload(problem["statement_latex"]))
            statement_save_preview = build_problem_statement_save_preview(parsed_import)
            if action == "save":
                _require_admin_tools_access(request)
                save_result = import_problem_statements(parsed_import)
                statement_import_result = {
                    "created_count": save_result.created_count,
                    "linked_problem_count": save_result.linked_problem_count,
                    "updated_count": save_result.updated_count,
                }
                messages.success(
                    request,
                    (
                        f"Saved {parsed_statement_payload['problem_count']} problem statement(s) from {source_label}: "
                        f"{save_result.created_count} created, {save_result.updated_count} updated, "
                        f"{save_result.linked_problem_count} linked to existing problem rows."
                    ),
                )
            else:
                day_total = len(parsed_statement_payload["day_rows"])
                messages.info(
                    request,
                    (
                        f"Parsed {parsed_statement_payload['problem_count']} problem(s) from "
                        f"{parsed_statement_payload['contest_name']} {parsed_statement_payload['contest_year']} "
                        f"across {day_total} day section(s) using {source_label}."
                    ),
                )
                if statement_save_preview["existing_count"] > 0:
                    messages.warning(
                        request,
                        (
                            "Duplicate check: "
                            f"{statement_save_preview['existing_count']} existing row(s) found. "
                            f"Saving will create {statement_save_preview['create_count']} row(s), "
                            f"update {statement_save_preview['update_count']} row(s), and "
                            f"refresh {statement_save_preview['unchanged_count']} identical row(s) "
                            "without inserting duplicate contest/problem keys."
                        ),
                    )
```

- [ ] **Step 4: Re-run the new view/form tests**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_latex_preview_parse_action_accepts_pdf_upload_and_uses_extracted_text \
  inspinia/pages/tests.py::test_latex_preview_save_action_accepts_pdf_upload_for_admin \
  inspinia/pages/tests.py::test_latex_preview_rejects_source_text_and_pdf_together \
  inspinia/pages/tests.py::test_latex_preview_rejects_when_no_source_is_provided \
  inspinia/pages/tests.py::test_latex_preview_rejects_non_pdf_upload \
  inspinia/pages/tests.py::test_latex_preview_pdf_extraction_error_is_displayed \
  -q
```

Expected:

- All six tests pass.

- [ ] **Step 5: Commit form/view integration slice**

Run:

```bash
git add inspinia/pages/forms.py inspinia/pages/views.py inspinia/pages/tests.py
git commit -m "feat(pages): accept pdf source in latex preview parser flow"
```

### Task 3: Add upload control to UI and lock template behavior with a test

**Files:**
- Modify: `inspinia/pages/tests.py`
- Modify: `inspinia/templates/pages/latex-preview.html`

- [ ] **Step 1: Add failing UI test for upload controls**

Add test near other `latex_preview` page tests:

```python
def test_latex_preview_page_renders_pdf_upload_control(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:latex_preview"))

    assert response.status_code == HTTPStatus.OK
    html = response.content.decode("utf-8")
    assert 'enctype="multipart/form-data"' in html
    assert 'name="file"' in html
    assert 'accept=".pdf,application/pdf"' in html
    assert "Upload contest PDF" in html
```

- [ ] **Step 2: Run UI test to verify failure**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_latex_preview_page_renders_pdf_upload_control -q
```

Expected:

- Fails because form is not multipart and no PDF control exists yet.

- [ ] **Step 3: Implement template updates**

Update `<form>` in `inspinia/templates/pages/latex-preview.html`:

```html
<form id="latex-preview-form" method="post" enctype="multipart/form-data" class="card">
```

Add upload control block inside the existing form body (under the action button row):

```html
<div class="row g-2 mt-1">
  <div class="col-lg-6 col-xl-5">
    <label class="form-label mb-1" for="{{ form.file.id_for_label }}">Upload contest PDF</label>
    {{ form.file }}
    <div class="form-text">Upload one text-based PDF to parse immediately.</div>
    {% for error in form.file.errors %}
    <div class="invalid-feedback d-block">{{ error }}</div>
    {% endfor %}
  </div>
</div>
```

- [ ] **Step 4: Re-run UI test**

Run:

```bash
uv run pytest inspinia/pages/tests.py::test_latex_preview_page_renders_pdf_upload_control -q
```

Expected:

- Test passes.

- [ ] **Step 5: Commit template slice**

Run:

```bash
git add inspinia/templates/pages/latex-preview.html inspinia/pages/tests.py
git commit -m "feat(pages): add latex preview pdf upload control"
```

### Task 4: Add dependency and run end-to-end verification

**Files:**
- Modify: `requirements/base.txt`

- [ ] **Step 1: Add pinned dependency**

In `requirements/base.txt`, append this line in the shared dependencies section:

```txt
pypdf==5.4.0  # https://github.com/py-pdf/pypdf
```

- [ ] **Step 2: Run focused regression suite and lint checks**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_extract_statement_text_from_pdf_normalizes_and_joins_pages \
  inspinia/pages/tests.py::test_extract_statement_text_from_pdf_raises_validation_error_when_reader_fails \
  inspinia/pages/tests.py::test_extract_statement_text_from_pdf_raises_validation_error_when_no_text \
  inspinia/pages/tests.py::test_latex_preview_parse_action_accepts_pdf_upload_and_uses_extracted_text \
  inspinia/pages/tests.py::test_latex_preview_save_action_accepts_pdf_upload_for_admin \
  inspinia/pages/tests.py::test_latex_preview_rejects_source_text_and_pdf_together \
  inspinia/pages/tests.py::test_latex_preview_rejects_when_no_source_is_provided \
  inspinia/pages/tests.py::test_latex_preview_rejects_non_pdf_upload \
  inspinia/pages/tests.py::test_latex_preview_pdf_extraction_error_is_displayed \
  inspinia/pages/tests.py::test_latex_preview_page_renders_pdf_upload_control \
  -q
```

Then run:

```bash
uv run ruff check inspinia/pages
```

Expected:

- pytest: all listed tests pass.
- ruff: no new violations.

- [ ] **Step 3: Commit dependency + final green state**

Run:

```bash
git add requirements/base.txt
git commit -m "chore: add pypdf for latex preview pdf parsing"
```

## Self-review

### 1. Spec coverage check

- Reusable upload capability: covered by Task 2 + Task 3 (`file` field, multipart template).
- Auto-parse on upload: covered by Task 2 (`latex_preview_view` resolves source and parses in same request).
- Reject both text and file: covered by Task 2 (form `clean()` + test).
- Extraction helper and errors: covered by Task 1.
- Existing preview/save path unchanged after parse: covered by Task 2 (reuses existing payload/save calls).
- User-facing validation/error messaging: covered by Task 2 + Task 3 tests.
- Dependency addition: covered by Task 4.

No spec gaps remain.

### 2. Placeholder scan

- No `TBD`, `TODO`, or “similar to above” shortcuts.
- Every code-changing step contains concrete code blocks.
- Every test step has explicit command and expected outcome.

### 3. Type/signature consistency

- `extract_statement_text_from_pdf(uploaded_file) -> str` is used consistently in tests and view code.
- Validation message strings are identical between planned code and assertions.
- `ProblemStatementImportForm` fields referenced in template/tests are consistent (`file`, `source_text`).
