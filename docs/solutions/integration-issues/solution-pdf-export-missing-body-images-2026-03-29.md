---
title: Solution PDF export failed on pasted body images
date: 2026-03-29
category: integration-issues
module: inspinia.solutions
problem_type: integration_issue
component: tooling
symptoms:
  - "Solution PDF export failed when saved block bodies referenced pasted images via \\includegraphics{solution_body_images/...}."
  - "latexmk/graphicx reported a missing input file under solution_body_images/... during PDF compilation."
  - "The PDF unavailable flow did not clearly explain that the referenced pasted image was missing from server storage."
root_cause: logic_error
resolution_type: code_fix
severity: high
related_components:
  - inspinia.solutions.pdf_latex
  - inspinia.solutions.views
  - inspinia.solutions.tests
  - latexmk
  - graphicx
tags:
  - pdf-export
  - latexmk
  - graphicspath
  - solution-body-images
  - media-root
  - preflight-validation
---

# Solution PDF export failed on pasted body images

## Problem
AsterProof solution PDF export failed when a saved block body referenced a pasted image like `\includegraphics{solution_body_images/...}`. The exporter mixed two failure modes: TeX was not being given a valid `graphicx` search path for `MEDIA_ROOT`, and genuinely missing pasted images were only surfacing later as opaque `latexmk` failures.

## Symptoms
- Clicking **Download PDF** from the solution editor failed instead of returning a PDF.
- The compiler log reported a missing `solution_body_images/...png` input file.
- When the image really was missing, the UI did not initially tell the author that the pasted image was missing from server storage.

## What Didn't Work
- Treating the issue as “the image file must be missing on disk” was incomplete. The file could exist and still fail if LaTeX never searched the right directory.
- Returning a raw directory string for `\graphicspath` was not enough. The generated TeX effectively became `\graphicspath{/abs/media/path/}`, but `graphicx` expects a list of braced directory entries such as `\graphicspath{{/abs/media/path/}}`.
- Naively scanning raw LaTeX for `\includegraphics` would have raised false failures for commented-out lines like `% \includegraphics{...}`.
- Using unresolved media-root paths was unsafe because `latexmk` compiles inside a temporary directory; relative paths could point at the wrong place.

## Solution
The fix had three parts.

First, generate a valid `graphicx` directory entry from the real absolute `MEDIA_ROOT`:

```python
def _graphicspath_tex(media_root: Path) -> str:
    media = media_root.expanduser().resolve().as_posix()
    if not media.endswith("/"):
        media += "/"
    media = media.replace("#", "\\#").replace("%", "\\%")
    return f"{{{media}}}"
```

That makes the emitted TeX effectively:

```tex
\graphicspath{{/absolute/path/to/media/}}
```

Second, preflight saved block bodies before `compile_solution_tex_to_pdf()` runs. The exporter now strips LaTeX comments, extracts `\includegraphics{...}` paths, keeps only app-managed pasted-image paths, and raises a dedicated error when any referenced managed file is missing:

```python
def _extract_includegraphics_paths(value: str) -> list[str]:
    if not value:
        return []
    return [match.group(1).strip() for match in _INCLUDEGRAPHICS_RE.finditer(_strip_latex_comments(value))]


def compile_solution_to_pdf(
    solution: ProblemSolution,
    blocks: Sequence[ProblemSolutionBlock],
    params: SolutionPdfCompileParams,
) -> bytes:
    missing_paths = _missing_solution_body_image_paths(blocks, media_root=params.media_root)
    if missing_paths:
        raise SolutionPdfMissingBodyImagesError(missing_paths)
    ...
```

Third, catch that dedicated error in the view and reuse the unavailable page with explicit server-storage wording and missing-path detail:

```python
except SolutionPdfMissingBodyImagesError as exc:
    missing_paths = ", ".join(exc.missing_paths)
    return render(
        request,
        "solutions/solution_pdf_unavailable.html",
        {
            "problem_data": problem_data,
            "reason": "Pasted solution images are missing from server storage.",
            "detail": f"Pasted body images are missing from server storage: {missing_paths}",
        },
        status=500,
    )
```

## Why This Works
The fix separates “TeX cannot find an existing file because the search path is malformed” from “the referenced pasted image is genuinely missing.” Valid `\graphicspath` lets LaTeX resolve existing files under `MEDIA_ROOT`. Preflight catches true storage problems earlier, before the compile step. Stripping comments keeps detection aligned with what TeX will actually compile, so commented-out `\includegraphics` lines do not trigger false failures. The view-level handling turns a vague compiler failure into a storage problem the author can act on immediately.

## Prevention
- Keep `_graphicspath_tex()` tests tied to resolved absolute paths, not hard-coded platform-specific `/tmp` assumptions.
- Keep preflight limited to allowlisted managed `solution_body_images/...` paths so hand-written external LaTeX asset paths still flow through normal compiler behavior.
- Strip LaTeX comments before scanning for `\includegraphics` so commented-out references do not fail export.
- Preserve targeted regression coverage around both exporter behavior and UI messaging. The key assertions are:

```python
assert _graphicspath_tex(Path("media")) == rf"{{{expected.as_posix()}/}}"
assert _extract_includegraphics_paths(body) == [
    "solution_body_images/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg",
]
with pytest.raises(SolutionPdfMissingBodyImagesError):
    compile_solution_to_pdf(solution, blocks, params)
assert b"Pasted solution images are missing from server storage." in response.content
```

- Re-run the focused verification stack after changes in this area:
  - `pytest inspinia/solutions/tests.py`
  - `ruff check inspinia/solutions`
  - `python manage.py check`

## Related Issues
- Design context: [solution-pdf-missing-body-images-design.md](../../superpowers/specs/2026-03-29-solution-pdf-missing-body-images-design.md)
- Implementation plan: [solution-pdf-missing-body-images.md](../../superpowers/plans/2026-03-29-solution-pdf-missing-body-images.md)
- Upstream pasted-image storage design: [solution-editor-paste-latex-images-design.md](../../superpowers/specs/2026-03-26-solution-editor-paste-latex-images-design.md)
- Historical exporter context: [solution-pdf-evan-template-parity.md](../../superpowers/plans/2026-03-26-solution-pdf-evan-template-parity.md)
- GitHub issues: none found for `solution pdf`, `includegraphics`, `latexmk`, `pdf_latex`, or `solution_body_images`
