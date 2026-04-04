# LaTeX preview: reusable PDF upload parsing into structured problem statements

## Goal

Enable `/tools/latex-preview/` to accept a PDF upload, extract text server-side, and run the existing statement parser pipeline so users can preview/save structured problem statements without manual copy-paste.

## Scope

- In scope:
  - Reusable PDF upload support on `/tools/latex-preview/`.
  - Server-side PDF text extraction and normalization.
  - Integration with existing `parse_contest_problem_statements(...)` preview/save flow.
  - Validation and user messaging for source selection and extraction failures.
  - Targeted tests for preview/save + validation/error paths.
- Out of scope:
  - OCR for scanned/image-only PDFs.
  - New parser heuristics for contest structure beyond current text parser behavior.
  - Non-PDF document formats (`.docx`, images, etc.).

## Confirmed product decisions

1. This is a reusable upload capability, not a one-off format hook.
2. Upload flow should auto-run parse in the same submit (no extra manual parse step).
3. If both text and PDF are provided, reject with validation error and ask for exactly one source.

## Current baseline

`latex_preview_view` currently accepts only pasted `source_text` through `ProblemStatementImportForm`, then runs:

1. `parse_contest_problem_statements(source_text)`
2. `build_problem_statement_preview_payload(...)`
3. optional `import_problem_statements(...)` for save action

This is already stable and covered by tests, so the design keeps that pipeline intact and adds a pre-parse PDF extraction stage.

## Approaches considered

1. Server-side extraction with `pypdf` (recommended)
   - Pros: keeps parser and validation in backend, minimal UI complexity, easy testability in Django.
   - Cons: relies on PDF text layer quality; some layout artifacts may remain.
2. Client-side extraction with PDF.js
   - Pros: no backend PDF dependency.
   - Cons: larger JS surface, weaker server-side guarantees, harder integration testing.
3. Multi-backend extraction service with fallback engines
   - Pros: potentially more robust for edge PDFs.
   - Cons: unnecessary complexity for this scope.

## Selected design

Use backend extraction via `pypdf` and feed extracted text into existing parser logic.

### 1. Form contract update

File: `inspinia/pages/forms.py`

- Extend `ProblemStatementImportForm` with optional `file` field:
  - accept only `.pdf` and `application/pdf`.
- Keep `source_text` optional at field level.
- Add `clean()` rule enforcing exactly one source:
  - valid: text only or PDF only
  - invalid: neither
  - invalid: both

### 2. Extraction helper

File: `inspinia/pages/statement_import.py`

Add helper:

- `extract_statement_text_from_pdf(uploaded_file) -> str`

Behavior:

1. Open uploaded file with `pypdf.PdfReader`.
2. Extract each page via `page.extract_text()`.
3. Join pages with stable separators/newlines.
4. Normalize line endings and strip null bytes.
5. Raise `ProblemStatementImportValidationError` when:
   - extraction fails (corrupt/encrypted/unreadable), or
   - extracted text is empty/near-empty.

### 3. View integration

File: `inspinia/pages/views.py` (`latex_preview_view`)

- Build form with `ProblemStatementImportForm(request.POST, request.FILES)` on POST.
- Determine parse source:
  - PDF path: call extraction helper, then parse extracted text.
  - text path: existing behavior unchanged.
- Keep parse/save actions unchanged after source resolution.
- UX consistency:
  - when parsing from PDF, populate `form.source_text` with extracted text so user can inspect and re-run quickly.
  - include info message indicating parsed source type (`PDF upload`) and extracted size.

### 4. Template update

File: `inspinia/templates/pages/latex-preview.html`

- Add PDF file input to the existing tool form.
- Keep textarea present for manual edits and non-PDF workflow.
- Keep existing action buttons and behavior.
- Show form errors for source exclusivity and file validation clearly near controls.

## Data flow

1. User uploads `.pdf` and clicks `Parse structure` or `Save to database`.
2. Form validates single source and file type.
3. Server extracts text from PDF.
4. Existing parser extracts contest/year/day/problem/statement blocks.
5. Existing preview payload and save-preview duplicate analysis run unchanged.
6. For save action, existing import upsert flow runs unchanged.

## Error handling

- Both sources provided: validation error (`use one source only`).
- Neither source provided: validation error.
- Non-PDF file: validation error.
- PDF extraction failure: parser-style error message with cause category.
- Empty extraction result: explicit error indicating PDF may be image-only or unsupported.

## Testing plan

Update `inspinia/pages/tests.py` with minimal focused tests:

1. `latex_preview` preview action parses valid uploaded PDF and does not write DB rows.
2. `latex_preview` save action with PDF upserts rows for admin.
3. Form rejects both `source_text` + `file` together.
4. Form rejects when neither source is provided.
5. Form rejects non-PDF upload.
6. Extraction failure path surfaces user-visible validation message.

Fixture plan:

- Add a small deterministic PDF fixture under `inspinia/pages/testdata/` containing one contest header and a few numbered problems.
- Keep fixture tiny to preserve test speed.

## Dependency change

- Add `pypdf` to `requirements/base.txt`.

## Risks and mitigations

1. PDF text ordering artifacts can degrade parse quality for some documents.
   - Mitigation: extracted text is surfaced back to textarea for manual cleanup before rerun/save.
2. Scanned PDFs without text layer will fail extraction.
   - Mitigation: explicit error explains limitation; OCR is intentionally out of scope for this iteration.
3. Regression risk in existing text path.
   - Mitigation: preserve existing parsing/saving path and add targeted regression tests.

## Acceptance criteria

1. `/tools/latex-preview/` accepts `.pdf` upload and parses in one submit.
2. Parsed PDF content appears as structured preview using existing backend parser.
3. Save action from PDF source persists rows through existing upsert logic.
4. Dual source input is rejected with clear validation.
5. Existing paste-text flow remains functional.
