# Solution Editor: Evan Template Parity for PDF Export

## Goal

Make the solution editor PDF export produce a genuine Evan Chen olympiad writeup instead of a plain LaTeX dump that merely loads `evan.sty`.

The exported PDF should follow the project rule for olympiad-style solutions:

- `\documentclass[11pt]{scrartcl}`
- `\usepackage[sexy,noasy]{evan}`
- KOMA headers from `evan.sty`
- problem statement in the purple `mdpurplebox`
- semantic theorem/proof environments such as `claim`, `remark`, and `proof`

## Why this design exists

The current exporter already compiles through vendored `evan.sty`, but the generated `.tex` is structurally too plain:

- it uses `\documentclass{scrartcl}` without `11pt`
- it loads `\usepackage[noasy]{evan}` instead of the long-document `[sexy]` option set
- it renders the problem as `\section*{Problem}` instead of the purple framed statement box
- it renders most blocks as `\paragraph{...}` labels instead of real theorem/proof environments

As a result, the output does not look like an Evan-style olympiad solution even though `evan.sty` is technically present.

This design updates the rendering semantics while preserving the current download endpoint, authorization model, compile flow, and error handling.

## Scope

In scope:

- change the generated LaTeX wrapper and block rendering
- preserve saved block order
- keep PDF compilation on the server through the existing `latexmk` pipeline
- keep image resolution through `\graphicspath`
- update focused unit tests for the generated `.tex`

Out of scope:

- changing editor storage or schema
- changing auth or URL structure
- unsaved "export current form state" behavior
- HTML preview parity beyond what already exists
- block nesting semantics based on `parent_block`

## Relationship to prior design

This design refines and partially supersedes [`2026-03-24-solution-pdf-evan-design.md`](./2026-03-24-solution-pdf-evan-design.md).

The earlier document correctly established the compile pipeline, saved-content source of truth, and error handling. The gap was in output semantics: "use `evan.sty`" was implemented too literally as "load the package" instead of "emit an Evan-style olympiad document."

## Recommended approach

Keep the existing exporter architecture and upgrade the LaTeX builder to emit semantic Evan-style constructs.

Why this approach:

- smallest change with the biggest visible improvement
- preserves the already working auth, compile, and response pipeline
- keeps risk localized to `inspinia/solutions/pdf_latex.py` and its tests
- avoids unnecessary template or intermediate-render-model complexity

## Document structure

The PDF builder should emit:

```latex
\documentclass[11pt]{scrartcl}
\usepackage[sexy,noasy]{evan}
...
\title{<problem label>}
\subtitle{<solution title>} % only when meaningful
\author{<author display name>}
\date{<local yyyy-mm-dd>}
\begin{document}
\maketitle
```

### Title and subtitle rules

- `\title` should be the canonical problem label, such as `USAMO 2026 P4`
- `\subtitle` should carry the solution title only when it is meaningful
- the placeholder title `Untitled solution` should not appear in the final PDF subtitle

This keeps the running headers aligned with the problem while still exposing a user-provided solution title when present.

## Problem statement rendering

If a linked problem statement exists, render it as:

```latex
\begin{mdframed}[style=mdpurplebox,frametitle={Problem Statement}]
...
\end{mdframed}
```

This replaces the current plain `\section*{Problem}` block.

## Block rendering semantics

The exporter should preserve block order exactly as saved, but change how each block type is rendered.

### Theorem-like blocks

- `claim` -> `claim`
- `remark` -> `remark`
- `observation` -> `fact`

For these block types:

- `title` is treated as raw LaTeX
- if `title` is present, it becomes the leading statement text inside the environment
- `body_source` follows after a blank line when both are present
- if only one of `title` or `body_source` exists, render only the non-empty content

Example shape:

```latex
\begin{claim}
1 is solitary.

This is trivial.
\end{claim}
```

### Proof blocks

- `proof` -> `proof`
- if the block title is present, use it as the optional proof heading:

```latex
\begin{proof}[Induction step]
...
\end{proof}
```

- `title` remains raw LaTeX here as well

### Structural blocks

- `section` -> `\section*{<title>}`
- `part` -> `\subsection*{<title>}`

If the title is empty, fall back to the block type label rather than emitting an empty heading.

`body_source` follows the heading as raw LaTeX.

### Narrative blocks

- `plain` -> raw body only, with no wrapper
- `idea` -> bold narrative lead-in plus raw body
- `computation` -> bold narrative lead-in plus raw body
- `conclusion` -> bold narrative lead-in plus raw body
- `case` -> bold narrative lead-in plus raw body
- `subcase` -> bold narrative lead-in plus raw body

These block types should not be forced into theorem boxes that would distort the intended flow. They should read as ordinary olympiad prose.

Representative shape:

```latex
\textbf{Case 1.}
...
```

## Content handling

- `title` and `body_source` are both treated as raw LaTeX
- the exporter should not auto-escape theorem titles
- malformed LaTeX in either field is allowed to fail compilation explicitly
- the exporter should never silently drop either field

This is consistent with the PDF export already being a LaTeX-first authoring path.

## Compilation and error behavior

Keep the existing compile behavior:

- compile in a private temp directory
- vendor `evan.sty` into the compile directory
- use the configured LaTeX binary and timeout
- keep shell escape disabled
- preserve controlled author-facing error pages with log tails

No behavior change is needed in the view layer beyond consuming the upgraded LaTeX source.

## Media behavior

Keep the existing `\graphicspath` behavior so pasted solution images continue to resolve in exported PDFs.

No new image-copying or media rewriting behavior is required for this change.

## Testing

Update unit tests around `build_solution_tex_source()` to assert the new semantics.

Add or update tests for:

- `\documentclass[11pt]{scrartcl}`
- `\usepackage[sexy,noasy]{evan}`
- problem statement wrapped in `mdpurplebox`
- `claim` blocks rendered with `\begin{claim}...\end{claim}`
- `proof` blocks rendered with optional proof headings
- `remark` and `observation` mapping to Evan-supported environments
- plain blocks still omitting wrappers
- block order preserved
- raw LaTeX titles inserted without escaping
- placeholder title suppression from subtitle output

The tests should stay at the generated-TeX level rather than introducing real PDF compilation in CI.

## Risks and mitigations

Risk: some existing saved solutions may have relied on the old paragraph-style export.

Mitigation:

- keep block order and raw content intact
- limit semantic upgrades to obvious block-type mappings
- keep narrative types out of theorem boxes unless they clearly belong there

Risk: raw LaTeX titles can cause compilation failures.

Mitigation:

- this is intentional and matches the requested "real Evan template" workflow
- current compile error pages already surface a useful log tail to the author

## Acceptance criteria

- Exported PDFs visibly match the Evan-style olympiad layout much more closely than the current output
- the document uses `11pt`, `[sexy,noasy]`, KOMA headers, and the purple problem statement frame
- claim- and proof-style blocks render as real theorem/proof environments instead of paragraph labels
- the exporter still uses the saved database content and current compile/error pipeline
- pasted solution images still resolve in the exported PDF
