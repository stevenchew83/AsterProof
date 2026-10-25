# Solution PDF Missing Body Images Implementation Plan

> **Status: Historical — implemented.** The original checklist and commands are retained as planning history. The unchecked steps do not represent pending work.

Current behavior is defined by the [PDF exporter](../../../inspinia/solutions/pdf_latex.py), [PDF response handling](../../../inspinia/solutions/views.py), and [regression tests](../../../inspinia/solutions/tests.py). The [fix writeup](../../solutions/integration-issues/solution-pdf-export-missing-body-images-2026-03-29.md) records the final implementation, including ignoring commented-out image references.

**Goal:** Make solution PDF export resolve app-managed pasted images correctly and fail early with a clear unavailable message when referenced pasted images are missing.

**Architecture:** Update `inspinia/solutions/pdf_latex.py` so the generated LaTeX uses valid `graphicx` directory syntax, app-managed `\includegraphics{solution_body_images/...}` references are extracted from saved block bodies, and missing files under `MEDIA_ROOT` raise a dedicated preflight error before LaTeX compilation. Update `inspinia/solutions/views.py` to surface that dedicated error with readable missing-path detail, and extend `inspinia/solutions/tests.py` to cover the exporter and view flow end to end.

**Tech Stack:** Django, pytest, pathlib, regex, LaTeX export via `latexmk`

---

## File structure

- Modify: `inspinia/solutions/pdf_latex.py`
  - Keep the existing renderer/compile pipeline.
  - Add the `\includegraphics` extraction helper, missing-image preflight helper, dedicated error type, and the `\graphicspath` format fix.
- Modify: `inspinia/solutions/views.py`
  - Add a dedicated error-handling branch for missing pasted solution images before the generic `SolutionPdfError` handler.
- Modify: `inspinia/solutions/tests.py`
  - Add targeted exporter tests for `\graphicspath`, includegraphics extraction, preflight missing-image failure, and the view-level unavailable response detail.

### Task 1: Exporter preflight and path-format coverage

**Files:**
- Modify: `inspinia/solutions/tests.py`
- Modify: `inspinia/solutions/pdf_latex.py`

- [ ] **Step 1: Write the failing exporter tests**

Add these imports near the top of `inspinia/solutions/tests.py`:

```python
from inspinia.solutions.pdf_latex import SolutionPdfCompileParams
from inspinia.solutions.pdf_latex import SolutionPdfMissingBodyImagesError
from inspinia.solutions.pdf_latex import _extract_includegraphics_paths
from inspinia.solutions.pdf_latex import _graphicspath_tex
from inspinia.solutions.pdf_latex import compile_solution_to_pdf
```

Add these tests near the existing PDF-export tests:

```python
def test_graphicspath_tex_wraps_directory_for_graphicx():
    assert _graphicspath_tex(Path("/tmp/ap-media")) == r"{/tmp/ap-media/}"


def test_extract_includegraphics_paths_preserves_source_order():
    body = "\n".join(
        [
            r"\includegraphics{solution_body_images/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png}",
            r"\includegraphics [width=0.9\linewidth] {solution_body_images/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg}",
            r"\includegraphics{not-managed/example.png}",
        ],
    )

    assert _extract_includegraphics_paths(body) == [
        "solution_body_images/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
        "solution_body_images/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg",
        "not-managed/example.png",
    ]


def test_compile_solution_to_pdf_raises_when_solution_body_image_missing(monkeypatch, tmp_path):
    user = UserFactory(name="Author")
    problem = _problem()
    solution = _solution_with_blocks(
        problem=problem,
        author=user,
        blocks=[
            (
                "With image",
                r"\includegraphics[width=0.9\linewidth]{solution_body_images/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png}",
                "proof",
            ),
        ],
    )
    blocks = list(solution.blocks.order_by("position"))

    def _unexpected_compile(*args, **kwargs):
        raise AssertionError("compile_solution_tex_to_pdf should not run when preflight fails")

    monkeypatch.setattr("inspinia.solutions.pdf_latex.compile_solution_tex_to_pdf", _unexpected_compile)

    with pytest.raises(SolutionPdfMissingBodyImagesError) as excinfo:
        compile_solution_to_pdf(
            solution,
            blocks,
            SolutionPdfCompileParams(
                media_root=tmp_path,
                problem_label="IMO 2026 P1",
                timeout=60,
                latex_binary="latexmk",
            ),
        )

    assert excinfo.value.missing_paths == [
        "solution_body_images/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
    ]
```

- [ ] **Step 2: Run the targeted exporter tests to confirm they fail**

Run:

```bash
uv run pytest \
  inspinia/solutions/tests.py::test_graphicspath_tex_wraps_directory_for_graphicx \
  inspinia/solutions/tests.py::test_extract_includegraphics_paths_preserves_source_order \
  inspinia/solutions/tests.py::test_compile_solution_to_pdf_raises_when_solution_body_image_missing \
  -q
```

Expected:

- `ImportError` for the new helper/error names, or
- assertion failure because `_graphicspath_tex(...)` still returns the unwrapped path, or
- `compile_solution_to_pdf(...)` reaches the compile function instead of failing early

- [ ] **Step 3: Implement the minimal exporter changes**

In `inspinia/solutions/pdf_latex.py`, make these focused changes:

```python
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from django.utils import timezone

from inspinia.solutions.body_image_paths import is_allowed_includegraphics_path
```

Add the regex and dedicated error type below the message constants:

```python
_INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")


class SolutionPdfMissingBodyImagesError(SolutionPdfError):
    def __init__(self, missing_paths: list[str]) -> None:
        self.missing_paths = missing_paths
        self.detail = "Missing paths: " + ", ".join(missing_paths)
        super().__init__(
            "One or more pasted solution images referenced by this solution are missing from server storage."
        )
```

Update `_graphicspath_tex(...)` so it returns a `graphicx` directory entry:

```python
def _graphicspath_tex(media_root: Path) -> str:
    media = media_root.resolve().as_posix()
    if not media.endswith("/"):
        media += "/"
    escaped = media.replace("#", "\\#").replace("%", "\\%")
    return "{" + escaped + "}"
```

Add the two helper functions above `build_solution_tex_source(...)`:

```python
def _extract_includegraphics_paths(value: str) -> list[str]:
    if not value:
        return []
    return [match.group(1).strip() for match in _INCLUDEGRAPHICS_RE.finditer(value)]


def _missing_solution_body_image_paths(
    blocks: Sequence[ProblemSolutionBlock],
    *,
    media_root: Path,
) -> list[str]:
    media_base = media_root.resolve()
    missing: list[str] = []
    seen: set[str] = set()

    for block in blocks:
        for raw_path in _extract_includegraphics_paths(block.body_source or ""):
            if not is_allowed_includegraphics_path(raw_path):
                continue
            canonical = raw_path.strip().replace("\\", "/").lstrip("/")
            if canonical in seen:
                continue
            seen.add(canonical)

            candidate = (media_base / canonical).resolve()
            try:
                candidate.relative_to(media_base)
            except ValueError:
                missing.append(canonical)
                continue
            if not candidate.is_file():
                missing.append(canonical)

    return missing
```

Run preflight at the top of `compile_solution_to_pdf(...)`:

```python
def compile_solution_to_pdf(
    solution: ProblemSolution,
    blocks: Sequence[ProblemSolutionBlock],
    params: SolutionPdfCompileParams,
) -> bytes:
    missing_paths = _missing_solution_body_image_paths(blocks, media_root=params.media_root)
    if missing_paths:
        raise SolutionPdfMissingBodyImagesError(missing_paths)

    tex = build_solution_tex_source(
        solution=solution,
        blocks=blocks,
        media_root=params.media_root,
        problem_label=params.problem_label,
        problem_statement_latex=params.problem_statement_latex,
    )
    return compile_solution_tex_to_pdf(
        tex,
        timeout=params.timeout,
        latex_binary=params.latex_binary,
    )
```

- [ ] **Step 4: Run the targeted exporter tests again and make sure they pass**

Run:

```bash
uv run pytest \
  inspinia/solutions/tests.py::test_graphicspath_tex_wraps_directory_for_graphicx \
  inspinia/solutions/tests.py::test_extract_includegraphics_paths_preserves_source_order \
  inspinia/solutions/tests.py::test_compile_solution_to_pdf_raises_when_solution_body_image_missing \
  -q
```

Expected:

- all three tests pass

- [ ] **Step 5: Commit the exporter preflight slice**

Run:

```bash
git add inspinia/solutions/pdf_latex.py inspinia/solutions/tests.py
git commit -m "fix: preflight missing solution pdf body images"
```

### Task 2: View-level unavailable response for missing pasted images

**Files:**
- Modify: `inspinia/solutions/tests.py`
- Modify: `inspinia/solutions/views.py`

- [ ] **Step 1: Write the failing view test**

Reuse the import added in Task 1; do not add a duplicate line. The import should remain:

```python
from inspinia.solutions.pdf_latex import SolutionPdfMissingBodyImagesError
```

Add this test near the existing PDF response tests:

```python
def test_problem_solution_pdf_missing_body_images_renders_unavailable_detail(monkeypatch, client):
    user = UserFactory()
    client.force_login(user)
    problem = _problem()
    _solution_with_blocks(problem=problem, author=user, blocks=[("X", "y", "idea")])

    def _boom(*args, **kwargs):
        raise SolutionPdfMissingBodyImagesError(
            ["solution_body_images/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"],
        )

    monkeypatch.setattr("inspinia.solutions.views.compile_solution_to_pdf", _boom)

    url = reverse("solutions:problem_solution_pdf", args=[problem.problem_uuid])
    response = client.get(url)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert b"missing from server storage" in response.content
    assert b"solution_body_images/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png" in response.content
```

- [ ] **Step 2: Run the targeted view test to confirm it fails**

Run:

```bash
uv run pytest \
  inspinia/solutions/tests.py::test_problem_solution_pdf_missing_body_images_renders_unavailable_detail \
  -q
```

Expected:

- FAIL because `_solution_pdf_http_response(...)` currently falls through the generic `SolutionPdfError` branch and does not expose the missing-path detail

- [ ] **Step 3: Implement the dedicated view branch**

Update the imports at the top of `inspinia/solutions/views.py`:

```python
from inspinia.solutions.pdf_latex import SolutionPdfMissingBodyImagesError
```

Add a specific `except` block before the generic `except SolutionPdfError as exc` branch:

```python
    except SolutionPdfMissingBodyImagesError as exc:
        return render(
            request,
            "solutions/solution_pdf_unavailable.html",
            {
                "problem_data": problem_data,
                "reason": str(exc),
                "detail": exc.detail,
            },
            status=500,
        )
```

- [ ] **Step 4: Run the targeted view test again and make sure it passes**

Run:

```bash
uv run pytest \
  inspinia/solutions/tests.py::test_problem_solution_pdf_missing_body_images_renders_unavailable_detail \
  -q
```

Expected:

- the test passes

- [ ] **Step 5: Commit the view error-handling slice**

Run:

```bash
git add inspinia/solutions/views.py inspinia/solutions/tests.py
git commit -m "fix: surface missing solution pdf image details"
```

### Task 3: Full verification for the touched area

**Files:**
- Verify: `inspinia/solutions/pdf_latex.py`
- Verify: `inspinia/solutions/views.py`
- Verify: `inspinia/solutions/tests.py`

- [ ] **Step 1: Run the full solutions test module**

Run:

```bash
uv run pytest inspinia/solutions/tests.py -q
```

Expected:

- all tests in `inspinia/solutions/tests.py` pass

- [ ] **Step 2: Run lint for the touched app**

Run:

```bash
uv run ruff check inspinia/solutions
```

Expected:

- `All checks passed!`

- [ ] **Step 3: Run Django system checks**

Run:

```bash
uv run python manage.py check
```

Expected:

- `System check identified no issues (0 silenced).`

- [ ] **Step 4: Inspect the final diff for accidental scope creep**

Run:

```bash
git diff --stat HEAD~2..HEAD
git diff --check HEAD~2..HEAD
```

Expected:

- only `inspinia/solutions/pdf_latex.py`, `inspinia/solutions/views.py`, and `inspinia/solutions/tests.py` are included
- `git diff --check` reports no whitespace or merge-marker issues

- [ ] **Step 5: Stop if verification is clean**

No additional code changes or commit are needed if all verification passes. If a verification command reveals a real defect in the touched files, fix only that defect, rerun the relevant command, and create one final follow-up commit with a narrowly scoped message.
