# Solution PDF Evan Template Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update solution-editor PDF export so saved solutions render as genuine Evan-style olympiad writeups instead of paragraph-labeled LaTeX dumps.

**Architecture:** Keep the existing download view, auth checks, temp-dir compilation flow, and error pages. Replace the current generic block-to-LaTeX builder with semantic rendering helpers in `inspinia/solutions/pdf_latex.py`, and drive the change with focused generated-TeX tests in `inspinia/solutions/tests.py`.

**Tech Stack:** Django, pytest, Ruff, TeX Live/`latexmk`, vendored `inspinia/solutions/latex/evan.sty`.

---

## File Map

- Modify: `inspinia/solutions/pdf_latex.py`
  - Keep compile behavior unchanged.
  - Add small helpers for top-matter construction and per-block semantic rendering.
  - Switch wrapper output to `11pt` + `[sexy,noasy]`.
- Modify: `inspinia/solutions/tests.py`
  - Replace paragraph-style assertions with Evan-template assertions.
  - Add targeted tests for theorem-like, proof, structural, and narrative block mappings.
- Reference only: `inspinia/solutions/migrations/0002_seed_solution_block_types.py`
  - Use the seeded slugs as the source of truth for block-type mappings.
- Reference only: `docs/superpowers/specs/2026-03-26-solution-pdf-evan-template-parity-design.md`
  - Match the approved design exactly; do not broaden scope into unsaved export or preview changes.

## Constraints And Guardrails

- Preserve saved block order exactly.
- Treat `title` and `body_source` as raw LaTeX in the PDF builder.
- Do not change `inspinia/solutions/views.py` unless implementation reveals a real integration gap.
- Do not add schema changes or migrations.
- Keep `\graphicspath` behavior intact so pasted images still resolve.
- Keep compile failures explicit; do not auto-escape malformed theorem titles.

### Task 1: Upgrade The Wrapper And Problem Statement Frame

**Files:**
- Modify: `inspinia/solutions/tests.py`
- Modify: `inspinia/solutions/pdf_latex.py`
- Reference: `docs/superpowers/specs/2026-03-26-solution-pdf-evan-template-parity-design.md`

- [ ] **Step 1: Write the failing wrapper tests**

Add or replace builder tests so they assert the new document shell:

```python
def test_build_solution_tex_uses_evan_sexy_wrapper_and_problem_title():
    tex = build_solution_tex_source(...)
    assert r"\documentclass[11pt]{scrartcl}" in tex
    assert r"\usepackage[sexy,noasy]{evan}" in tex
    assert r"\title{USAMO 2026 P4}" in tex
    assert r"\subtitle{My Title}" in tex
    assert r"\author{Test User}" in tex


def test_build_solution_tex_wraps_problem_statement_in_mdpurplebox():
    tex = build_solution_tex_source(...)
    assert r"\begin{mdframed}[style=mdpurplebox,frametitle={Problem Statement}]" in tex
    assert r"\end{mdframed}" in tex
```

- [ ] **Step 2: Run the targeted tests to confirm the current builder fails**

Run: `uv run pytest inspinia/solutions/tests.py -k "build_solution_tex and (wrapper or problem or subtitle)" -v`

Expected: FAIL because the builder still emits `\documentclass{scrartcl}`, `\usepackage[noasy]{evan}`, and `\section*{Problem}`.

- [ ] **Step 3: Implement the wrapper changes in the builder**

Update `build_solution_tex_source()` so the preamble and problem statement match the approved design:

```python
lines = [
    r"\documentclass[11pt]{scrartcl}",
    r"\usepackage[sexy,noasy]{evan}",
    rf"\graphicspath{{{gp}}}",
    rf"\title{{{latex_escape_plain_text(problem_label)}}}",
    rf"\author{{{author}}}",
    rf"\date{{{date_str}}}",
]
if subtitle:
    lines.append(rf"\subtitle{{{subtitle}}}")
...
if stmt_body:
    lines.extend(
        [
            r"\begin{mdframed}[style=mdpurplebox,frametitle={Problem Statement}]",
            stmt_body,
            r"\end{mdframed}",
            "",
        ],
    )
```

Implementation notes:
- Keep `problem_label` escaped as plain text.
- Suppress `\subtitle{...}` when the solution title is empty or exactly `Untitled solution`.
- Leave `\graphicspath`, date formatting, and compile flow untouched.

- [ ] **Step 4: Run the targeted tests again**

Run: `uv run pytest inspinia/solutions/tests.py -k "build_solution_tex and (wrapper or problem or subtitle)" -v`

Expected: PASS.

- [ ] **Step 5: Commit the wrapper change**

```bash
git add inspinia/solutions/pdf_latex.py inspinia/solutions/tests.py
git commit -m "feat: use evan wrapper for solution pdfs"
```

### Task 2: Render Claim, Remark, Observation, And Proof Blocks Semantically

**Files:**
- Modify: `inspinia/solutions/tests.py`
- Modify: `inspinia/solutions/pdf_latex.py`
- Reference: `inspinia/solutions/migrations/0002_seed_solution_block_types.py`

- [ ] **Step 1: Write failing tests for theorem-like and proof block mappings**

Add tests covering the semantic environments and raw-title behavior:

```python
def test_build_solution_tex_maps_claim_and_proof_blocks_to_evan_environments():
    tex = build_solution_tex_source(...)
    assert r"\begin{claim}" in tex
    assert "1 is solitary." in tex
    assert r"\end{claim}" in tex
    assert r"\begin{proof}[Induction step]" in tex
    assert r"\end{proof}" in tex


def test_build_solution_tex_maps_observation_to_fact_and_preserves_raw_latex_titles():
    tex = build_solution_tex_source(...)
    assert r"\begin{fact}" in tex
    assert r"$n$ is solitary" in tex
    assert r"\$n\$ is solitary" not in tex


def test_build_solution_tex_maps_remark_to_remark_environment():
    tex = build_solution_tex_source(...)
    assert r"\begin{remark}" in tex
    assert r"\end{remark}" in tex
```

- [ ] **Step 2: Run only the new theorem/proof tests**

Run: `uv run pytest inspinia/solutions/tests.py -k "claim or proof or observation or remark" -v`

Expected: FAIL because the builder still emits `\paragraph{...}` headings and escapes block titles as plain text.

- [ ] **Step 3: Implement theorem-like and proof render helpers**

Add a small renderer layer in `inspinia/solutions/pdf_latex.py`:

```python
def _block_slug(block: ProblemSolutionBlock) -> str:
    return ((block.block_type.slug if block.block_type_id and block.block_type else "") or "").strip()


def _join_block_text(title: str, body: str) -> str:
    parts = [part for part in [title.strip(), body.strip()] if part]
    return "\n\n".join(parts)


def _render_theorem_like_block(env_name: str, *, title: str, body: str) -> list[str]:
    content = _join_block_text(title, body)
    return [rf"\begin{{{env_name}}}", content, rf"\end{{{env_name}}}", ""]


def _render_proof_block(*, title: str, body: str) -> list[str]:
    head = rf"\begin{{proof}}[{title.strip()}]" if title.strip() else r"\begin{proof}"
    return [head, body.strip(), r"\end{proof}", ""]
```

Use these mappings:
- `claim -> claim`
- `remark -> remark`
- `observation -> fact`
- `proof -> proof`

Implementation notes:
- `title` stays raw LaTeX for these block types.
- Use blank-line separation between title text and body text when both exist.
- Keep block spacing (`\par` + `\addvspace{2\baselineskip}`) between blocks.

- [ ] **Step 4: Re-run the theorem/proof test slice**

Run: `uv run pytest inspinia/solutions/tests.py -k "claim or proof or observation or remark" -v`

Expected: PASS.

- [ ] **Step 5: Commit the semantic theorem/proof mapping**

```bash
git add inspinia/solutions/pdf_latex.py inspinia/solutions/tests.py
git commit -m "feat: render semantic evan theorem blocks"
```

### Task 3: Render Structural And Narrative Blocks Without Regressing Plain Blocks

**Files:**
- Modify: `inspinia/solutions/tests.py`
- Modify: `inspinia/solutions/pdf_latex.py`
- Reference: `inspinia/solutions/migrations/0002_seed_solution_block_types.py`

- [ ] **Step 1: Write failing tests for section/part/case/plain/narrative behavior**

Add or update tests for the non-theorem block types:

```python
def test_build_solution_tex_maps_section_and_part_blocks_to_headings():
    tex = build_solution_tex_source(...)
    assert r"\section*{Reduction}" in tex
    assert r"\subsection*{Part A}" in tex


def test_build_solution_tex_renders_case_and_idea_blocks_as_bold_lead_ins():
    tex = build_solution_tex_source(...)
    assert r"\textbf{Case 1.}" in tex
    assert r"\textbf{Idea.}" in tex
    assert r"\paragraph{" not in tex


def test_build_solution_tex_plain_block_omits_heading_and_title():
    tex = build_solution_tex_source(...)
    assert "This starts the solution body." in tex
    assert "Lead paragraph" not in tex
```

- [ ] **Step 2: Run the structural/narrative tests to verify failure**

Run: `uv run pytest inspinia/solutions/tests.py -k "section or part or case or plain or idea or computation or conclusion" -v`

Expected: FAIL because the builder still uses paragraph headings for non-plain blocks.

- [ ] **Step 3: Implement structural and narrative render helpers**

Extend the builder with focused helpers:

```python
def _render_heading_block(command: str, *, title: str, fallback: str, body: str) -> list[str]:
    heading = title.strip() or fallback
    lines = [rf"\{command}*{{{heading}}}"]
    if body.strip():
        lines.extend([body.strip(), ""])
    else:
        lines.append("")
    return lines


def _render_bold_leadin(label: str, *, title: str, body: str) -> list[str]:
    lead = title.strip() or label
    lines = [rf"\textbf{{{lead}.}}"]
    if body.strip():
        lines.extend([body.strip(), ""])
    else:
        lines.append("")
    return lines
```

Use these mappings:
- `section -> \section*{...}`
- `part -> \subsection*{...}`
- `case`, `subcase`, `idea`, `computation`, `conclusion` -> bold lead-ins
- `plain -> raw body only`

Implementation notes:
- Do not escape titles for these blocks; they remain raw LaTeX by design.
- Use the block-type label as the fallback heading when `section` or `part` is missing a title.
- Do not emit empty wrappers for blank `plain` bodies.

- [ ] **Step 4: Run the structural/narrative tests again**

Run: `uv run pytest inspinia/solutions/tests.py -k "section or part or case or plain or idea or computation or conclusion" -v`

Expected: PASS.

- [ ] **Step 5: Commit the structural/narrative mapping**

```bash
git add inspinia/solutions/pdf_latex.py inspinia/solutions/tests.py
git commit -m "feat: map solution blocks to evan-style structure"
```

### Task 4: Regression Sweep And Manual Sanity Check

**Files:**
- Modify if needed: `inspinia/solutions/pdf_latex.py`
- Modify if needed: `inspinia/solutions/tests.py`

- [ ] **Step 1: Run the full solutions test file**

Run: `uv run pytest inspinia/solutions/tests.py -v`

Expected: PASS.

- [ ] **Step 2: Run Ruff on the solutions app**

Run: `uv run ruff check inspinia/solutions`

Expected: `All checks passed!`

- [ ] **Step 3: If TeX is installed locally, run one manual PDF export smoke check**

Suggested command:

```bash
uv run python manage.py shell -c "from pathlib import Path; from django.conf import settings; from inspinia.solutions.pdf_latex import build_solution_tex_source; print('manual smoke only')"
```

Manual expectation:
- generated `.tex` shows `11pt`, `[sexy,noasy]`, `mdpurplebox`, and semantic environments
- if a local end-to-end export is convenient, visually verify the PDF resembles the approved Evan style

- [ ] **Step 4: Review the final diff for scope control**

Check:
- no changes outside `inspinia/solutions/pdf_latex.py`, `inspinia/solutions/tests.py`, and any unavoidable tiny follow-up
- no accidental auth, template, or compile-pipeline changes

- [ ] **Step 5: Commit any final verification-driven cleanup**

```bash
git add inspinia/solutions/pdf_latex.py inspinia/solutions/tests.py
git commit -m "test: cover evan template parity for solution pdfs"
```

## Handoff Notes

- Work strictly in TDD order. Do not start by rewriting the builder wholesale.
- Prefer small helper functions inside `inspinia/solutions/pdf_latex.py` over introducing a new module unless the file becomes clearly unwieldy.
- If implementation reveals that `case` / `subcase` need a different lead-in style to compile or read well, keep the change local and update the plan-facing tests first.
- Do not introduce preview changes in this implementation pass; the approved scope is PDF export parity only.
