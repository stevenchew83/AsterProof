# Solution PDF export: fix body image resolution and preflight missing pasted images

## Goal

Make PDF export for solution editor content reliable when a saved block body contains app-managed pasted-image references such as `\includegraphics{solution_body_images/<hex>.png}`.

This fix has two jobs:

1. Correct the generated LaTeX so `graphicx` actually searches `MEDIA_ROOT` for pasted solution images.
2. Fail early with a clear AsterProof error when a saved solution references app-managed pasted images that are missing from server storage.

## Problem summary

The current PDF exporter builds LaTeX with a `\graphicspath` line intended to let `\includegraphics{solution_body_images/...}` resolve against `MEDIA_ROOT`.

Today that line is emitted in a malformed form:

```latex
\graphicspath{/abs/media/path/}
```

But `graphicx` expects a list of directory entries, where each entry is wrapped in its own braces:

```latex
\graphicspath{{/abs/media/path/}}
```

When the directory list is malformed, LaTeX does not search `MEDIA_ROOT` as intended. That can surface as a compile failure saying a pasted image file under `solution_body_images/...` is missing, even when the file exists on disk.

Separately, if a saved solution references an app-managed pasted image that really is gone from storage, the current export path does not detect that before compile. The author sees a raw `latexmk` failure instead of an app-level explanation.

## Context

- Pasted solution images are stored by `SolutionBodyImage.file` using canonical relative paths under `solution_body_images/`.
- Block bodies store LaTeX-first references such as `\includegraphics[width=0.9\linewidth]{solution_body_images/<hex>.png}`.
- The live preview resolves those paths in JavaScript using `MEDIA_URL`.
- PDF export compiles a generated `.tex` file using `latexmk`, vendored `evan.sty`, and `Path(settings.MEDIA_ROOT)` as the intended media root.
- Production currently uses Django `FileSystemStorage` for media.

## Locked decisions

1. **Scope of preflight validation**
   - Only validate app-managed image paths under `solution_body_images/...`.
   - Leave any manually written non-app-managed asset paths to normal LaTeX compiler behavior.

2. **Failure mode**
   - Missing app-managed pasted images must fail before invoking `latexmk`.
   - The user must receive a controlled AsterProof error explaining that pasted solution images are missing from server storage.

3. **No auto-repair**
   - Do not silently remove missing image references.
   - Do not auto-rewrite block bodies.
   - Do not auto-copy or regenerate missing media.

4. **No storage redesign in this fix**
   - Keep the current local-disk media model.
   - Do not add remote-storage abstraction or temp-tree materialization in this change.

## Approach

### 1. Correct `\graphicspath`

Update the LaTeX builder so the generated line uses the `graphicx`-expected nested-brace form:

```latex
\graphicspath{{/abs/media/path/}}
```

This keeps the existing strategy of compiling against the server’s `MEDIA_ROOT`, but makes the directory search syntax valid.

### 2. Add app-managed image preflight

Before invoking the LaTeX compiler:

- scan saved block `body_source` values for `\includegraphics...{...}` occurrences
- normalize and filter paths through the existing allowlist semantics used for app-managed pasted images
- resolve each allowed canonical path against `MEDIA_ROOT`
- collect any referenced files that do not exist on disk

If any are missing, abort export before compile.

## Detailed design

### Export-time path scanning

Add a small helper in the PDF export module to extract `\includegraphics` targets from saved block bodies.

Requirements:

- match `\includegraphics{...}` and `\includegraphics[...]{...}`
- allow the same optional whitespace currently tolerated in the browser preview parser
- return raw candidate paths in source order

The helper is not a full LaTeX parser. It only needs to support the editor’s canonical `\includegraphics` pattern well enough for app-managed image preflight.

### App-managed filtering

For each extracted path:

- pass it through the existing `solution_body_images/...` allowlist logic
- ignore anything that does not match the app-managed pattern
- keep matching canonical paths exactly as stored in block bodies for error reporting

This keeps the guardrail tightly scoped to assets the solution editor itself inserts.

### File existence validation

For each app-managed canonical path:

- join it to `MEDIA_ROOT`
- resolve the resulting filesystem path under the configured media root
- treat the file as present only if it exists as a regular file

If one or more referenced app-managed images are missing, raise a dedicated PDF export error before compile.

### Error type and surfacing

Add a dedicated PDF export error for missing pasted media as a `SolutionPdfError` subclass that carries:

- a user-facing reason string
- the missing canonical `solution_body_images/...` paths

The existing PDF unavailable/error view flow can be reused, but the missing-media case should surface a specific message such as:

> One or more pasted solution images referenced by this solution are missing from server storage.

The response detail shown to the author should include the missing canonical paths in a short readable list.

### What remains unchanged

- upload endpoint behavior
- live preview behavior
- block saving behavior
- normal LaTeX compile failures unrelated to app-managed missing images
- tool-missing and timeout handling

## Testing

Add or update focused tests in `inspinia/solutions/tests.py`:

1. `_graphicspath_tex(...)` returns the nested-brace form expected by `graphicx`
2. app-managed `\includegraphics{solution_body_images/...}` paths are extracted correctly from block bodies
3. missing app-managed image files trigger the new preflight PDF export error before compile
4. the PDF export view returns a controlled error page for the missing-media case
5. existing generic compile-error tests remain unchanged

Testing stays unit- and view-level only. This fix does not require real TeX compilation in tests.

## Risks and non-goals

### Risks

- The `\includegraphics` extraction helper is intentionally narrow and should not be treated as a general LaTeX parser.
- If a future storage backend stops using local filesystem reads, this design will need revisiting.

### Non-goals

- supporting arbitrary non-app-managed asset preflight
- automatic repair of broken image references
- migration to remote storage
- editor UX changes around pasted images

## Acceptance criteria

- Exported LaTeX uses a valid `\graphicspath{{...}}` form.
- A saved solution that references existing app-managed pasted images no longer fails because of malformed `\graphicspath`.
- A saved solution that references missing app-managed pasted images fails before compile with a clear app-level error and lists the missing canonical paths.
- Other LaTeX failures still use the existing compile-error behavior.
