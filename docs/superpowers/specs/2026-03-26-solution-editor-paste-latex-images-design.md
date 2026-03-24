# Solution editor: paste images → LaTeX `\includegraphics` + live preview

## Goal

On the **solution editor** (`problem_solution_edit`, template `solutions/problem-solution-editor.html`), allow authors to **paste images from the clipboard** into a block body `textarea`. The result should be **LaTeX-first** stored text: insert a canonical `\includegraphics{...}` (with optional width) pointing at a **server-hosted** asset. The **live preview** should show the image (not only raw TeX), alongside existing **MathJax** rendering for math in `body_format=latex` blocks.

## Context

- Blocks use `ProblemSolutionBlock.body_source` (textarea) and `body_format` (e.g. `latex`). Preview today sets `textContent` from the textarea and runs **MathJax** on `[data-mathjax-scope]` only for LaTeX blocks.
- **MathJax does not** render `\includegraphics` like pdfLaTeX. Preview requires a **hybrid**: keep MathJax for math delimiters; resolve allowlisted `\includegraphics{url}` into safe `<img>` (preview and public list views).
- **Published list** (`problem-solution-list.html`) renders `body_source` as text inside a div with MathJax—**same limitation** as the editor. Parity: any preview/list pipeline for graphics should be **shared or duplicated carefully** (prefer one small JS module or documented pattern).
- **Media**: `MEDIA_URL` / `MEDIA_ROOT` in base; production may use S3 (`config/settings/production.py`). Uploaded files must use Django storage and return a **browser-loadable URL** consistent with deployment.

## Decision (approved direction: LaTeX-first, hybrid preview)

1. **Storage model**  
   - New model, e.g. `SolutionBodyImage` (name TBD): `FileField` (or `ImageField`), `upload_to` under a dedicated prefix (e.g. `solution_body_images/`), **FK to `ProblemSolution`** (and thus author via solution), optional `uploaded_at`, `uploaded_by` (redundant but useful for audits).  
   - **Ownership**: only the **solution author** may upload; endpoint resolves `problem_uuid` + ensures `ProblemSolution` for `(problem, request.user)` exists or is created lazily—**prefer requiring an existing draft/solution row** to avoid orphan files (product choice: create draft on first upload vs require “start draft” first—spec recommends **require authenticated editor access to that problem’s solution** same as `problem_solution_edit_view`).

2. **Upload API**  
   - `POST` multipart, `@login_required`, CSRF (fetch cookie/header).  
   - Validate: **image MIME** (allowlist: png, jpeg, gif, webp as policy allows), **max size** (e.g. 2–5 MB), optional max dimensions.  
   - Return JSON: `{ "url": "<absolute or site-relative URL>" }` using `request.build_absolute_uri` or stable **`MEDIA_URL`-relative path** documented as the only form allowed inside `\includegraphics{...}`.

3. **Canonical LaTeX insertion**  
   - On successful upload, insert at cursor, e.g.  
     `\includegraphics[width=0.9\linewidth]{/media/solution_body_images/...}`  
     using the **exact** URL shape the app documents (site-relative path preferred so dev/staging/prod differ only by `MEDIA_URL`).  
   - **Optional bracket args**: support `[width=...]` only; no arbitrary user-controlled URLs in stored TeX beyond the inserted token.

4. **Paste UX**  
   - `paste` listener on each block’s `body_source` textarea: if `clipboardData.files` / items contain image, **preventDefault**, upload, then insert.  
   - If not an image, default paste behavior.  
   - Show inline error (toast or small alert) on failure; do not block typing.

5. **Preview (editor)**  
   - For LaTeX blocks: build preview DOM by **splitting** `body_source` into segments: text runs (MathJax) vs `\includegraphics[...]{url}` (render `<img src="..." alt="">` with **URL allowlist**: must start with `MEDIA_URL` prefix or relative `/media/` prefix—reject `javascript:`, other hosts).  
   - Run `MathJax.typesetPromise` on text segments only, or on containers that exclude raw `<img>`—avoid passing unsanitized HTML to MathJax.  
   - **Security**: never set `innerHTML` from user text except for **replaced** img tags with **validated** URLs only.

6. **Published / list view**  
   - Apply the **same** graphics + MathJax hybrid for `body_format == latex'` blocks so published solutions show diagrams, not raw `\includegraphics` text.  
   - Extract shared logic to a static JS file included by both templates if practical.

7. **Out of scope (v1)**  
   - Server-side PDF/LaTeX export pipeline changes (may need URL→file mapping later).  
   - Drag-and-drop file onto textarea (can be fast follow).  
   - Deleting unused images / garbage collection.  
   - Non-LaTeX `body_format` blocks (paste could be disabled or same insertion if format is latex-only feature).

## Success criteria

- Author on solution editor can paste a screenshot; after upload, **LaTeX line appears** in the textarea and **preview shows the image**.  
- Another user cannot upload to someone else’s solution (403).  
- Malicious `\includegraphics{javascript:...}` in pasted or hand-typed body does not execute; preview/list strip or ignore non-allowlisted URLs.  
- Tests: view permission, upload validation (type/size), optional URL allowlist unit tests in Python for a shared validator used when rendering server-side (if any); client-heavy behavior covered by minimal integration or documented manual QA if E2E not present.

## Risks / notes

- **Orphan files** when users delete `\includegraphics` lines—acceptable for v1.  
- **CDN/S3**: `build_absolute_uri` vs relative paths—pick one canonical stored form and document.  
- **CSP**: if strict img-src, allow own media host.
