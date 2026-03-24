# Solutions App Guide

This app owns user-authored problem solutions and their block structure.

## Core models and ownership

- `ProblemSolution`: one user-owned solution for one `ProblemSolveRecord`.
- `SolutionBlockType`: seeded structural vocabulary such as `claim`, `proof`, and `case`.
- `ProblemSolutionBlock`: ordered blocks inside a solution.
- `SolutionSourceArtifact`: optional raw PDF/text/URL provenance for imported material.

## Invariants

- V1 enforces at most one solution per `(problem, author)`.
- Block order is explicit through `position`; do not infer it from timestamps.
- Block `title` is free-form display text. Do not promote transition words like `Therefore` or `Hence` into schema-only meaning.
- `body_format` controls rendering expectations. Do not assume all stored content is valid LaTeX.
- Source artifacts are provenance, not the canonical rendered solution body.

## Schema discipline

- Anchor solutions to `pages.ProblemSolveRecord`, not directly to statement rows.
- If you add nesting behavior, keep parent/child relationships inside the same solution.
- If you add moderation or history, prefer new revision/review tables over mutating the authored blocks into audit records.

## PDF export

- **Download PDF** (`problem_solution_pdf`) compiles the **saved** solution with vendored `latex/evan.sty` and KOMA `scrartcl` via `latexmk` (see `SOLUTION_PDF_LATEX_*` in settings). The host needs TeX Live with KOMA-Script and the packages `evan.sty` pulls in.

## Recommended checks

- `uv run pytest inspinia/solutions/tests.py`
- `uv run ruff check inspinia/solutions`
