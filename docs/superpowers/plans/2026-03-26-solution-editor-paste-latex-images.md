# Solution editor paste images (`\includegraphics`) — implementation plan

> **For agentic workers:** Use subagent-driven-development or executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Paste images in the solution block textarea; store LaTeX `\includegraphics{...}` with server-hosted files; hybrid MathJax + `<img>` in editor live preview and on `problem-solution-list.html`.

**Architecture:** New `SolutionBodyImage` model + authenticated POST upload; `get_or_create` persist `ProblemSolution` draft when needed; shared static JS splits LaTeX body, allowlists paths, typesets math only; templates pass `MEDIA_URL` / path prefix for URL resolution.

**Tech stack:** Django 5.x, Pillow, MathJax 3 (existing CDN), Inspinia templates.

---

### Task 1: Model and migration

**Files:**
- Add: `inspinia/solutions/models.py` (model)
- Add: migration in `inspinia/solutions/migrations/`

- [ ] Add `SolutionBodyImage` with `ImageField(upload_to=...)`, `ForeignKey(ProblemSolution, ...)`, `uploaded_at`, `uploaded_by` (FK User nullable).
- [ ] Run `makemigrations` / `migrate`; smoke `manage.py check`.

### Task 2: Upload view and URL

**Files:**
- Modify: `inspinia/solutions/views.py`
- Modify: `inspinia/solutions/urls.py`
- Add tests: `inspinia/solutions/tests.py`

- [ ] `POST` view: `@login_required`, resolve `problem_uuid` → `ProblemSolveRecord`, `get_or_create(ProblemSolution, problem=..., author=request.user, defaults={status: DRAFT})`, save if new.
- [ ] Validate file (size, `ImageField`, Pillow verify); save `SolutionBodyImage`; return JSON `{path, url}` with canonical path for `\includegraphics`.
- [ ] Forbid upload if user is not author (403).
- [ ] Tests: success path, wrong user 403, invalid file 400, oversized 400.

### Task 3: Path allowlist helper (Python)

**Files:**
- Add: small module e.g. `inspinia/solutions/body_image_paths.py` or in `views.py` if tiny

- [ ] `is_allowed_includegraphics_path(path: str) -> bool`: normalized, no `..`, prefix `solution_body_images/`, allowed charset.
- [ ] Unit tests for traversal, `//`, `javascript:` rejected.

### Task 4: Shared frontend — hybrid renderer

**Files:**
- Add: `inspinia/static/js/solution-latex-hybrid.js` (or path per project conventions; run `npm run build` if pipeline requires)
- Read: `inspinia/static/AGENTS.md`

- [ ] Parse `body_source` for `\includegraphics[optional]{path}`; only emit `<img>` for paths passing same rules as Python (document parity).
- [ ] `initSolutionLatexHybrid(container)`: replace content with fragment of text spans + imgs; `MathJax.typesetPromise` on text spans only.
- [ ] Accept config global: `window.ASTERPROOF_SOLUTION_MEDIA` = `{ baseUrl, pathPrefix }` from Django template.

### Task 5: Editor template

**Files:**
- Modify: `inspinia/templates/solutions/problem-solution-editor.html`

- [ ] Inject media config JSON from context (new context key from view).
- [ ] Include shared JS; on `paste` for `textarea[name$="-body_source"]`, upload to new URL, insert LaTeX at selection.
- [ ] Replace inline preview `renderPreview` body rendering with hybrid + debounced typeset (match existing behavior for non-latex blocks).

### Task 6: Editor view context

**Files:**
- Modify: `inspinia/solutions/views.py` (`problem_solution_edit_view`)

- [ ] Pass upload URL name, `MEDIA_URL`, and any CSRF-safe hints for JS `fetch`.

### Task 7: Solution list template

**Files:**
- Modify: `inspinia/templates/solutions/problem-solution-list.html`

- [ ] Same media config + shared JS.
- [ ] On load, run `initSolutionLatexHybrid` for each `.solution-block-body[data-mathjax-scope]` (or mark blocks explicitly).

### Task 8: Verification

- [ ] `uv run pytest inspinia/solutions/tests.py`
- [ ] `uv run ruff check inspinia/solutions`
- [ ] Manual: paste PNG in editor, preview + list page after publish.

---

## Dependencies

Task 4 blocks 5 and 7. Task 2 blocks 5. Task 1 blocks 2.
