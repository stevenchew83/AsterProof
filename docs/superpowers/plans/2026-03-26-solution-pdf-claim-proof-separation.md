# Solution PDF Claim Proof Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update solution PDF export so claim statements stay in the green claim box, proof text renders separately and unboxed, and top-level block spacing is reduced to one line.

**Architecture:** Keep the existing Evan-template PDF pipeline intact and change only the LaTeX renderer in `inspinia/solutions/pdf_latex.py`. Drive the behavior change with focused generated-TeX tests in `inspinia/solutions/tests.py`, especially around split claim rendering and the spacing constant.

**Tech Stack:** Django, pytest, Ruff, TeX Live/`latexmk`, vendored `inspinia/solutions/latex/evan.sty`.

---

## File Map

- Modify: `inspinia/solutions/pdf_latex.py`
  - Narrow the `claim` rendering path so a populated claim block can emit a `claim` plus a following unboxed `proof`.
  - Reduce the top-level block spacing constant from two lines to one.
- Modify: `inspinia/solutions/tests.py`
  - Replace the current combined claim/proof expectation with a split rendering expectation.
  - Add an explicit spacing assertion for `\addvspace{\baselineskip}`.
- Reference only: `docs/superpowers/specs/2026-03-26-solution-pdf-claim-proof-separation-design.md`
  - Match the approved follow-up behavior exactly.

## Constraints And Guardrails

- Do not change views, URLs, templates, auth checks, or compile error handling.
- Keep the existing Evan wrapper, problem statement frame, and non-claim block mappings unchanged unless a test proves otherwise.
- Standalone `proof` blocks must remain unboxed.
- `claim` blocks with only body text should still render as a plain `claim` environment because there is no trustworthy statement/proof split.
- The split `claim` + `proof` emitted from one saved block should behave as one visual unit; the reduced spacing applies between top-level blocks, not inside that pair.

### Task 1: Lock In Split Claim Rendering With Failing Tests

**Files:**
- Modify: `inspinia/solutions/tests.py`
- Reference: `docs/superpowers/specs/2026-03-26-solution-pdf-claim-proof-separation-design.md`

- [ ] **Step 1: Replace the current claim/proof expectation with split-rendering tests**

Update or replace the existing builder coverage around claim/proof behavior so it asserts:

```python
def test_build_solution_tex_splits_claim_title_from_claim_body():
    tex = build_solution_tex_source(...)
    assert r"\begin{claim}" in tex
    assert "1 is solitary." in tex
    assert r"\end{claim}" in tex
    assert r"\begin{proof}" in tex
    assert "This is trivial." in tex
    assert tex.index(r"\end{claim}") < tex.index(r"\begin{proof}")


def test_build_solution_tex_claim_body_only_stays_in_claim_box():
    tex = build_solution_tex_source(...)
    assert r"\begin{claim}" in tex
    assert "This is the only content." in tex
    assert tex.count(r"\begin{proof}") == 0


def test_build_solution_tex_uses_single_line_spacing_between_blocks():
    tex = build_solution_tex_source(...)
    assert r"\addvspace{\baselineskip}" in tex
    assert r"\addvspace{2\baselineskip}" not in tex
```

- [ ] **Step 2: Run only the new split-claim and spacing tests to verify RED**

Run:

```bash
uv run pytest \
  inspinia/solutions/tests.py::test_build_solution_tex_splits_claim_title_from_claim_body \
  inspinia/solutions/tests.py::test_build_solution_tex_claim_body_only_stays_in_claim_box \
  inspinia/solutions/tests.py::test_build_solution_tex_uses_single_line_spacing_between_blocks \
  -v
```

Expected:
- FAIL because the current renderer still puts claim title and body in one green `claim`
- FAIL because `_SOLUTION_PDF_BLOCK_VSPACE` still uses `2\baselineskip`

- [ ] **Step 3: Keep the existing standalone proof test coverage in place**

Make sure there is still an assertion like:

```python
assert r"\begin{proof}[Induction step]" in tex
assert r"\end{proof}" in tex
```

This prevents the claim change from accidentally boxing standalone proofs.

- [ ] **Step 4: Commit the failing-test setup only if you are working in a reviewable TDD branch that expects explicit red commits**

```bash
git add inspinia/solutions/tests.py
git commit -m "test: cover split claim and single-line spacing"
```

If your workflow does not keep red commits, skip this commit and move directly to Task 2.

### Task 2: Implement Split Claim Rendering And Tighter Spacing

**Files:**
- Modify: `inspinia/solutions/pdf_latex.py`
- Modify if needed: `inspinia/solutions/tests.py`

- [ ] **Step 1: Implement a dedicated claim renderer**

Add a focused helper that follows the approved split rules:

```python
def _render_claim_block(*, title: str, body: str) -> list[str]:
    statement = (title or "").strip()
    proof_text = (body or "").strip()
    if statement and proof_text:
        return [
            r"\begin{claim}",
            statement,
            r"\end{claim}",
            r"\begin{proof}",
            proof_text,
            r"\end{proof}",
            "",
        ]
    if statement:
        return [r"\begin{claim}", statement, r"\end{claim}", ""]
    if proof_text:
        return [r"\begin{claim}", proof_text, r"\end{claim}", ""]
    return []
```

Implementation notes:
- Do not route this through `_render_theorem_like_block()` when both title and body are present; that helper intentionally combines content.
- Keep `title` and `body` as raw LaTeX.
- Do not wrap the derived proof in a colored theorem style.

- [ ] **Step 2: Update block dispatch to use the new claim renderer**

In `_render_block(...)`, change the `claim` branch from the shared theorem-like path to the dedicated helper:

```python
if slug == "claim":
    return _render_claim_block(title=block.title or "", body=block.body_source or "")
```

Leave these behaviors unchanged:
- `proof -> _render_proof_block(...)`
- `remark -> remark`
- `observation -> fact`
- all heading and narrative block mappings

- [ ] **Step 3: Reduce the top-level spacing constant**

Change:

```python
_SOLUTION_PDF_BLOCK_VSPACE = r"\addvspace{2\baselineskip}"
```

to:

```python
_SOLUTION_PDF_BLOCK_VSPACE = r"\addvspace{\baselineskip}"
```

- [ ] **Step 4: Run the targeted tests again to verify GREEN**

Run:

```bash
uv run pytest \
  inspinia/solutions/tests.py::test_build_solution_tex_splits_claim_title_from_claim_body \
  inspinia/solutions/tests.py::test_build_solution_tex_claim_body_only_stays_in_claim_box \
  inspinia/solutions/tests.py::test_build_solution_tex_uses_single_line_spacing_between_blocks \
  inspinia/solutions/tests.py::test_build_solution_tex_maps_claim_and_proof_blocks_to_evan_environments \
  -v
```

Expected: PASS.

- [ ] **Step 5: Commit the implementation**

```bash
git add inspinia/solutions/pdf_latex.py inspinia/solutions/tests.py
git commit -m "feat: separate claim and proof rendering in solution pdfs"
```

### Task 3: Full Verification And Manual Sanity Check

**Files:**
- Modify if needed: `inspinia/solutions/pdf_latex.py`
- Modify if needed: `inspinia/solutions/tests.py`

- [ ] **Step 1: Run the full solutions test file**

Run:

```bash
uv run pytest inspinia/solutions/tests.py -q
```

Expected:

```text
55 passed
```

or the updated total if you added one or two new tests while replacing older ones.

- [ ] **Step 2: Run Ruff for the touched app**

Run:

```bash
uv run ruff check inspinia/solutions
```

Expected:

```text
All checks passed!
```

- [ ] **Step 3: Generate one sample `.tex` output for a manual sanity check**

Use a quick shell or Django shell snippet that produces a claim-with-body sample and inspect the rendered LaTeX shape:

```python
tex = build_solution_tex_source(...)
assert r"\begin{claim}" in tex
assert r"\end{claim}" in tex
assert r"\begin{proof}" in tex
assert tex.index(r"\end{claim}") < tex.index(r"\begin{proof}")
assert r"\addvspace{\baselineskip}" in tex
```

If a local TeX compile is available, compile the sample. If it still fails because the machine is missing `yhmath.sty` or other TeX packages, record that the generated `.tex` looks correct and that visual PDF compilation remains environment-blocked.

- [ ] **Step 4: Review the final diff for scope control**

Check:
- only `inspinia/solutions/pdf_latex.py` and `inspinia/solutions/tests.py` changed
- no unrelated wrapper, view, or template changes slipped in
- the claim logic is the only semantic renderer change

- [ ] **Step 5: Commit any final verification-driven cleanup**

```bash
git add inspinia/solutions/pdf_latex.py inspinia/solutions/tests.py
git commit -m "refactor: tighten solution pdf claim spacing behavior"
```

Only make this commit if Step 4 required follow-up cleanup beyond the main implementation commit.

## Handoff Notes

- Work in a dedicated worktree per @superpowers:using-git-worktrees before implementation.
- Follow strict TDD order per @superpowers:test-driven-development; do not edit `pdf_latex.py` before you have watched the split-claim test fail.
- Do not broaden this into a proof-style redesign or a generic theorem-style refactor.
- If implementation reveals that the split claim renderer needs a tiny helper for blank-line handling, keep it local to `pdf_latex.py` and avoid touching unrelated block types.
