# Solution editor: paste images → LaTeX `\includegraphics` + live preview

## Goal

On the **solution editor** (`problem_solution_edit`, template `solutions/problem-solution-editor.html`), allow authors to **paste images from the clipboard** into a block body `textarea`. The result should be **LaTeX-first** stored text: insert a canonical `\includegraphics{...}` (with optional width) pointing at a **server-hosted** asset. The **live preview** should show the image (not only raw TeX), alongside existing **MathJax** rendering for math in `body_format=latex` blocks.

## Context

- Blocks use `ProblemSolutionBlock.body_source` (textarea) and `body_format` (e.g. `latex`). Preview today sets `textContent` from the textarea and runs **MathJax** on `[data-mathjax-scope]` only for LaTeX blocks.
- **MathJax does not** render `\includegraphics` like pdfLaTeX. Preview requires a **hybrid**: keep MathJax for math delimiters; resolve allowlisted `\includegraphics{url}` into safe `<img>` (preview and public list views).
- **Published list** (`problem-solution-list.html`) renders `body_source` inside a div with MathJax—**same limitation** as the editor. Parity: implement **one shared static JS module** (e.g. under `inspinia/static/...`) that: (1) finds LaTeX block bodies, (2) splits `\includegraphics[optional width]{path}` into text vs image segments, (3) builds DOM with `<img>` only for allowlisted paths, (4) calls `MathJax.typesetPromise` on **text-only** subtrees (or equivalent) so user HTML never enters MathJax input.
- **Load order**: include the shared script **after** MathJax config, **before** or with `defer` coordinated so `DOMContentLoaded` (or explicit init) runs `initSolutionLatexHybrid(root)` on `#solution-live-preview` and on each `.solution-block-body[data-mathjax-scope]` on the list page—**single entry point** to avoid editor vs list drift.
- **Media**: `MEDIA_URL` / `MEDIA_ROOT` in base; production may use S3 (`config/settings/production.py`). Uploaded files must use Django storage; **`img src`** in the browser must be whatever `FileField.url` resolves to in that environment (absolute S3 URL is fine). **Canonical stored form in `body_source`**: use a **stable path string** the app controls, e.g. `\includegraphics{solution_body_images/<uuid>.png}` **without** scheme/host, and resolve to full URL in JS via a template-injected `window.SOLUTION_MEDIA_PREFIX` or prefix + `new URL(path, MEDIA_URL)`—document the exact rule in implementation so dev/staging/prod stay consistent.
- **`problem_solution_edit_view`** may hold an **unsaved** `ProblemSolution` in memory until the first successful POST. Image uploads need a persisted PK for an FK.

## Decision (approved direction: LaTeX-first, hybrid preview)

1. **Storage model**  
   - New model, e.g. `SolutionBodyImage`: **`ImageField`** (Pillow verify) under `upload_to=solution_body_images/%Y/%m/` (or UUID filenames), **FK to `ProblemSolution`**, `uploaded_at`, optional `uploaded_by`.  
   - **Persistence before upload (required):** If `ProblemSolution` for `(problem, request.user)` has **no PK** yet, the upload endpoint **`get_or_create`s** and **saves** a minimal row (status `DRAFT`, empty title/summary acceptable per model constraints) **inside the same transaction** as file save, mirroring “user has opened the editor for this problem.” This avoids orphan `SolutionBodyImage` rows without a solution and matches editor access.  
   - **Ownership:** only the author of that `ProblemSolution` may upload; `problem_uuid` in the URL must match the linked `ProblemSolveRecord`; return **403** otherwise.

2. **Upload API**  
   - `POST` multipart, `@login_required`, CSRF.  
   - Validate: allowlist **image** types; **max size** (e.g. 3 MB); **`ImageField` / Pillow** open to verify magic matches extension.  
   - Return JSON: `{ "path": "<canonical path for body_source>", "url": "<browser src URL>" }` where `path` is the documented stored token and `url` is `file.url` for immediate preview if needed.

3. **Canonical LaTeX insertion**  
   - Insert at cursor: `\includegraphics[width=0.9\linewidth]{<canonical path>}` using **only** the server-returned path (opaque filename).  
   - **Bracket args (v1):** optional `[width=0.9\linewidth]` fixed template or allowlisted `width=` only.

4. **Paste UX**  
   - `paste` on `body_source`: if image in clipboard, **preventDefault**, `POST` upload, then insert LaTeX.  
   - Non-image: default paste. Errors: non-blocking message.

5. **Preview (editor) + list**  
   - Shared JS: parse `\includegraphics` with **strict grammar** (path segment = characters from upload naming only, or regex aligned with storage).  
   - **URL allowlist (JS + mirror in Python if server emits HTML later):**  
     - Reject `javascript:`, `data:`, backslashes, control chars, `//` (protocol-relative), and any path not under **`solution_body_images/`** after **normalization** (resolve `.` / `..`, no traversal).  
     - Prefer validating **prefix + UUID filename** from storage, not arbitrary subpaths.  
   - Build `<img src="...">` only after validation; map canonical path to URL using `MEDIA_URL` / injected base.  
   - **MathJax:** typeset only on text nodes or wrapped text elements, not on parent that contains unverified HTML.

6. **Published / list view**  
   - For `body_format == latex` (`ProblemSolutionBlock.BodyFormat.LATEX`), run the **same** hybrid initializer as the editor after DOM ready.

7. **Server-side HTML (future)**  
   - Never mark `body_source` safe in templates without the **same** allowlisted `img` rules; today templates use auto-escape—**keep** that until a dedicated sanitizer exists.

8. **Out of scope (v1)**  
   - PDF/LaTeX export. Drag-and-drop. Orphan file GC. Upload rate limits / per-solution quota (note for ops).  
   - Non-LaTeX blocks: disable paste-to-upload or no-op.

## Success criteria

- Paste → LaTeX line in textarea + image in live preview.  
- Cross-user upload denied.  
- Hand-typed malicious `\includegraphics{...}` does not load arbitrary URLs.  
- List page shows images for LaTeX blocks.  
- Tests: upload authz, validation, optional Python tests for path validator; manual QA note for clipboard if no browser tests.

## Risks / notes

- **S3 vs local:** document canonical **stored** path vs **resolved** `src`.  
- **CSP `img-src`:** allow media host.  
- **First paste creates draft:** editor UX may show “draft saved” implicitly—optional small message on first upload.
