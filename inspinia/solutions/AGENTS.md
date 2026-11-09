# Solutions App Guide

This app owns user-authored archive problem solutions and their saved revisions.
See the [continuous editor guide](../../docs/solutions/continuous-solution-editor.md),
[document schema contract](../../docs/deployment/solution-document-editor.md),
and [multiple-solutions contract](../../docs/deployment/multiple-solutions-release.md).

## Ownership and routing

- Each `ProblemSolution` belongs to one author and one `pages.ProblemSolveRecord`.
  Preserve the shared problem UUID. The linked statement provides context for
  rendering and review.
- A problem-only authoring route selects the author's original slot
  (`additional_draft_key` is null). Additional solutions have their own IDs.
  Carry the selected solution ID through edit, upload, export, and share flows
  for an additional solution. Check ownership and problem identity on lookup.
  Repeated creation with the same additional draft key must resolve to the same draft.
- Reuse the existing access checks for editing, member publication, and public
  sharing. A private save must not change a published snapshot.

## Saved source and legacy content

- The editor saves one continuous LaTeX document. `current_revision` points to
  an immutable `SolutionRevision` belonging to that solution. Save a new revision
  through the existing signed editor context and optimistic version check.
- When `current_revision` is null, read the legacy blocks in `position` order.
  The first explicit document save preserves those blocks. Keep parent and child
  blocks inside their solution, preserve free-form titles, and respect
  `body_format` when converting legacy content.
- `SolutionSourceArtifact` records import provenance. Keep it separate from the
  rendered proof source. Store moderation and review history separately from
  the authored content.

## PDF export

- **Download PDF** (`problem_solution_pdf`) compiles the **saved** solution with vendored `latex/evan.sty` and KOMA `scrartcl` via `latexmk` (see `SOLUTION_PDF_LATEX_*` in settings). The host needs TeX Live with KOMA-Script and the packages `evan.sty` pulls in.

## Recommended checks

- `uv run pytest inspinia/solutions/tests.py`
- `uv run ruff check inspinia/solutions`
