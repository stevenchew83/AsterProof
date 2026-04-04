# LaTeX preview: restore classic rendered-preview style without changing Evan style elsewhere

## Goal

Use the previous neutral render style on `/tools/latex-preview/` in the **Rendered preview** area, while keeping Evan-styled statement rendering on contest and solution pages.

## Scope

- In scope:
  - `/tools/latex-preview/` page preview container.
  - `/tools/render-statement/` AJAX response used by the same page.
  - Shared statement render partial behavior when explicitly requested.
- Out of scope:
  - Contest dashboard/problem list rendered statement style.
  - Solution pages rendered statement style.
  - PDF/LaTeX compile style (`evan.sty`) and any solution export behavior.

## Current problem

The shared statement render partial now always includes `statement-evan-box`, and the LaTeX preview output container also carries that class. This makes the LaTeX tool preview look Evan-themed (purple box) instead of the previous neutral style requested for this tool page.

## Requirements

1. `/tools/latex-preview/` rendered preview must use the previous neutral style.
2. All other pages that render statements through the shared partial must remain Evan-styled by default.
3. Asymptote render behavior and fallback errors must remain unchanged.
4. Change should be low-risk and avoid duplicating templates.

## Approaches considered

1. CSS-only override on LaTeX preview page:
   - Smallest patch, but keeps Evan-specific class semantics in markup.
2. Render-style variant flag in shared partial (recommended):
   - Explicit, reusable, and keeps default behavior stable.
3. Duplicate partial for LaTeX preview only:
   - Isolated but introduces drift risk and maintenance overhead.

## Selected design

Use a `render_style` variant in `partials/statement-render-content.html` with default fallback to Evan mode.

- Default mode (`render_style` absent or not `"classic"`):
  - Preserve existing Evan classes and look.
- Classic mode (`render_style == "classic"`):
  - Do not apply `statement-evan-box` at partial root.
  - Use previous neutral asymptote panel classes (`border rounded-3 bg-body-tertiary p-3`).

The LaTeX preview page and its AJAX render endpoint will explicitly pass `render_style="classic"`.

## Detailed change plan

### 1. Shared partial variant handling

File: `inspinia/templates/partials/statement-render-content.html`

- Add an `is_classic` flag from `render_style`.
- Root wrapper class:
  - Evan: includes `statement-evan-box`.
  - Classic: excludes `statement-evan-box`.
- Asymptote panel wrapper:
  - Evan: keep `statement-asymptote-panel`.
  - Classic: use neutral bootstrap-style panel classes.

### 2. LaTeX preview template wiring

File: `inspinia/templates/pages/latex-preview.html`

- Remove `statement-evan-box` from `#latex-preview-output` class list so initial surface is neutral.
- In parsed preview include, pass `render_style='classic'`:
  - `{% include 'partials/statement-render-content.html' with segments=... render_style='classic' %}`

### 3. AJAX preview endpoint wiring

File: `inspinia/pages/views.py`

- In `statement_render_preview_view`, pass `render_style: "classic"` into `render_to_string(...)` context.

## Data flow

1. User types or clicks **Render preview** on `/tools/latex-preview/`.
2. Frontend posts source text to `/tools/render-statement/`.
3. View builds render segments (unchanged).
4. View renders shared partial with `render_style="classic"`.
5. Frontend injects classic-styled HTML into preview surface.
6. MathJax typesets scoped nodes (unchanged).

Contest/solution pages continue including the same partial without `render_style`, so they stay in Evan mode.

## Error handling and compatibility

- No changes to parser/segment generation or Asymptote backend calls.
- No changes to JSON shape from preview endpoint.
- Missing/unknown `render_style` safely defaults to existing Evan behavior.

## Testing plan

Update minimal affected tests in `inspinia/pages/tests.py`:

1. `test_statement_render_preview_returns_rendered_asymptote_html`
   - Ensure payload still includes Asymptote badge, backend label, SVG, and text fragments.
   - Switch style assertion to verify classic output for tool endpoint (e.g., no `statement-evan-box`, contains neutral panel class markers).

Optional template smoke check can remain implicit via existing page render tests.

## Risks

- Risk: classic/evan class branching in one partial could drift over time.
  - Mitigation: keep branch narrow (wrapper + asymptote panel only), default mode unchanged.
- Risk: accidental regression on non-tool pages.
  - Mitigation: explicit style flag only in LaTeX preview paths; default fallback to Evan.

## Acceptance criteria

1. `/tools/latex-preview/` shows rendered preview in neutral classic style.
2. `/tools/render-statement/` response HTML for LaTeX preview does not include `statement-evan-box`.
3. Contest and solution pages still render Evan-styled boxes.
4. Asymptote rendering and error messaging behave exactly as before.
