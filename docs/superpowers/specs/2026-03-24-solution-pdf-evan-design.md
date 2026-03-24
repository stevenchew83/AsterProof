# Solution editor: export PDF with `evan.sty`

## Goal

From the **solution editor** flow, allow an authorized user to **download a PDF** whose content is the **saved** solution blocks, typeset with **Evan Chen’s `evan.sty`** (vendored in-repo) so the output matches that LaTeX ecosystem (fonts, theorem styles when enabled, KOMA headers, etc.), not a MathJax/HTML snapshot.

## Locked decisions

1. **Compilation location:** **On application servers** (or equivalent host in the deployment unit that runs Django): full **TeX Live** (or equivalent) available; compile in a **private temp directory**; return `application/pdf` or a structured error with log tail.
2. **Source of truth (v1):** **Saved solution in the database** (ordered blocks). Unsaved textarea-only export is **out of scope for v1**; a later iteration may POST current form state.
3. **Non–`latex` blocks:** **All blocks** contribute `body_source` to the generated `.tex` **as LaTeX**, **regardless of `body_format`.**  
   - *Implication:* `body_format` is ignored for PDF export; invalid or non-LaTeX text may **fail compilation** or render poorly. Authors are expected to keep bodies LaTeX-safe if they use PDF export.

## Context

- Editor today: `problem-solution-editor.html`, MathJax preview; no server-side LaTeX.
- `evan.sty` depends on many packages (KOMA/scrlayer, `amsmath`, optional `mdframed`/`thmtools`, optional Asymptote, etc.). **Option strategy:** default to **`noasy`** on the server unless Asymptote is explicitly installed and supported; prefer **KOMA `scrartcl`** so running headers use `\theauthor` / `\thetitle` (the non-KOMA `fancyhdr` path in `evan.sty` hardcodes “Evan Chen” in `\lhead`).
- **License:** `evan.sty` is under the **Boost Software License**; **source** distributions that include the file must retain its copyright and license notice. PDF output attribution is optional but acceptable.

## Architecture

- **New view** (namespaced URL under `inspinia.solutions`), **`@login_required`**, same authorization as **editing** that solution (author and/or admin—mirror `problem_solution_edit` rules).
- **GET** (preferred for “open in new tab / download”): `solution_id` or problem UUID + solution id; load `ProblemSolution` and ordered `ProblemSolutionBlock` queryset.
- **Build:** render a **wrapper `.tex` Jinja2/Django template** (or string builder) that:
  - sets `\documentclass{scrartcl}` (or agreed KOMA class);
  - `\usepackage[noasy, …]{evan}` with documented optional flags;
  - sets `\title`, `\author`, `\date` from solution + problem label;
  - `\begin{document}`, optional `\maketitle`;
  - for each block: emit heading from **block type** + optional **title**, then **raw `body_source`** (no HTML escaping beyond what TeX requires—use careful escaping or delimited verbatim only if we later add a safe mode; v1 assumes trusted authors).
- **Assets:** copy or symlink referenced media (e.g. `\includegraphics{solution_body_images/...}`) into the temp tree or set `\graphicspath` toward `MEDIA_ROOT` paths the process can read.
- **Run:** `latexmk -pdf -interaction=nonstopmode` (or `pdflatex` twice) with:
  - **timeout** (wall clock);
  - **no shell escape** (`-shell-escape` off);
  - capture **stdout/stderr** and `.log` tail on failure.
- **Response:** `FileResponse` with `Content-Disposition: attachment`; filename slug from problem + solution title.

## `evan.sty` placement

- Store under e.g. `inspinia/solutions/latex/evan.sty` (or `inspinia/static/latex/`) and set **`TEXINPUTS`** or copy into the temp dir before compile so the wrapper can `\usepackage{evan}`.
- Do not strip license/copyright header from the vendored file.

## UI

- **Solution editor:** button **“Download PDF”** (or icon) linking to the new GET URL; optional short note: “Uses last saved content.”

## Errors

- If compilation fails: show a **dedicated error page** or JSON for XHR with **user-safe message** + **last N lines of log** for authors; log server-side with solution id (no full body in logs by default).

## Testing

- **Unit tests:** mock subprocess; assert generated `.tex` contains expected **document class**, `\usepackage` line, **title/author**, and **block order** and headings.
- **Integration (optional):** run real `latexmk` in CI only if image provides TeX Live.

## Deployment

- Document **required TeX packages** for the chosen `[evan]` options (minimum set to be validated on a staging box once options are frozen).
- Ensure `MEDIA_ROOT` is readable by the worker that compiles (same as image upload serving).

## Future work

- **Unsaved** PDF: POST block JSON from the browser; handle uploads without persisted FK carefully (may remain out of scope).
- **Stricter `body_format`:** optionally only include `latex` blocks or wrap others in `\begin{verbatim}` if authors hit too many compile failures.

## Acceptance criteria

- Authorized user can download a PDF for a saved solution with multiple blocks; PDF uses **KOMA + `evan.sty`** styling (headers show solution author/title, not hardcoded third-party name).
- `\includegraphics` referencing app-managed media paths resolves when files exist.
- Compilation failures return a controlled error with log tail; no shell escape.
