# Solution PDF (evan.sty) Implementation Plan

> **For agentic workers:** Use task-by-task execution with tests after each cluster.

**Goal:** Server-side PDF export for saved solutions using vendored `evan.sty` and KOMA `scrartcl`.

**Architecture:** Build `.tex` in Python (avoid templating user bodies), compile with `latexmk -pdf` in a temp dir, return `FileResponse`. Same auth as solution edit (author-only).

**Tech stack:** Django, TeX Live (`latexmk`, `pdflatex`, KOMA-Script), vendored `inspinia/solutions/latex/evan.sty`.

---

### Tasks

1. Add `SOLUTION_PDF_*` settings in `config/settings/base.py`.
2. Add `inspinia/solutions/pdf_latex.py` (escape helpers, `build_solution_tex_source`, compile + errors).
3. Add `problem_solution_pdf_view` + URL; wire imports.
4. Templates `solution_pdf_error.html`, `solution_pdf_unavailable.html`.
5. Editor: Download PDF button when `form.instance.pk`.
6. Tests: tex shape, login, 404, mocked success, mocked compile error, tool missing.
