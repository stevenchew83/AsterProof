# Solution PDF: Separate Claim And Proof Rendering

## Goal

Adjust the Evan-style solution PDF export so claim statements and proof text do not share the same green claim box, and tighten the spacing between top-level blocks.

This follow-up design keeps the current Evan-template upgrade in place while refining two presentation details:

- claim statement stays in the green `claim` box
- proof text renders as a normal unboxed `proof` environment
- top-level block spacing is reduced to one line

## Why this change exists

The current renderer maps a `claim` block with both `title` and `body_source` into a single green `claim` environment. Visually, that makes the proof content appear inside the claim styling, which does not match the intended olympiad layout.

The user expectation is:

- claim statement highlighted in the green Evan theorem box
- proof content below it in normal proof styling, not inside the colored frame
- less vertical whitespace between consecutive blocks

## Relationship to prior designs

This design refines:

- [`2026-03-26-solution-pdf-evan-template-parity-design.md`](./2026-03-26-solution-pdf-evan-template-parity-design.md)
- [`2026-03-24-solution-pdf-evan-design.md`](./2026-03-24-solution-pdf-evan-design.md)

Those documents established the Evan-style wrapper and semantic block mapping. This note narrows the rendering rules for `claim`, `proof`, and block spacing.

## Approved rendering behavior

### Claim blocks

For `claim` blocks:

- if `title` and `body_source` are both present:
  - render `title` alone inside `\begin{claim}...\end{claim}`
  - render `body_source` immediately after as a normal unboxed `\begin{proof}...\end{proof}`
- if only `title` is present:
  - render only the green `claim` environment
- if only `body_source` is present:
  - render only a green `claim` environment containing that text
  - rationale: without a separate statement field, there is no trustworthy way to split statement from proof
- if both are empty:
  - render nothing

Representative output for a populated claim block:

```latex
\begin{claim}
1 is solitary.
\end{claim}
\begin{proof}
This is trivial.
\end{proof}
```

### Proof blocks

For standalone `proof` blocks:

- always render as a normal unboxed `proof` environment
- if `title` is present, use it as the optional proof heading
- if `body_source` is empty and `title` is also empty, render nothing

Representative output:

```latex
\begin{proof}[Induction step]
Assume the result for $n$.
\end{proof}
```

### Other block types

No rendering changes are required for:

- `remark`
- `observation`
- `section`
- `part`
- `case`
- `subcase`
- `idea`
- `computation`
- `conclusion`
- `plain`

## Spacing behavior

The current top-level block spacing is too loose for the desired solution style.

Change:

- reduce the top-level inter-block vertical spacing constant from `\addvspace{2\baselineskip}` to `\addvspace{\baselineskip}`

Keep:

- the existing `\par` plus `\addvspace{...}` structure between top-level rendered blocks

Important consequence:

- a split `claim` + `proof` emitted from one saved `claim` block should behave as one visual unit
- the one-line spacing applies between top-level blocks, not between the claim box and its immediately-following proof

## Testing updates

Update generated-TeX tests in `inspinia/solutions/tests.py` to assert:

- a `claim` block with both title and body renders as a green `claim` followed by a normal `proof`
- a standalone `proof` block still renders as a normal `proof`
- the old combined claim-body rendering no longer appears
- top-level spacing uses `\addvspace{\baselineskip}`

All previously added wrapper/problem-box/semantic block tests should remain in place unless their assumptions directly conflict with this change.

## Risks and mitigations

Risk:

- some existing solutions may have relied on claim body text appearing inside the green claim box

Mitigation:

- the new behavior better matches standard olympiad typesetting and the user’s explicit expectation
- the split occurs only when a `claim` block actually has both statement-like and proof-like fields available

Risk:

- spacing reduction could make some long solutions feel denser

Mitigation:

- the new value is still explicit `\addvspace{\baselineskip}`, not zero spacing

## Acceptance criteria

- claim statements remain in the green Evan `claim` box
- proof text is not rendered inside that green box
- standalone `proof` blocks remain unboxed
- the spacing between top-level blocks is one line rather than two
