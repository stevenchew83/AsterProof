# LaTeX Preview Classic Render Style Implementation Plan

> **Status: Historical — implemented.** The original checklist and commands are retained as planning history. The unchecked steps do not represent pending work.

Current behavior is defined by the [shared render partial](../../../inspinia/templates/partials/statement-render-content.html), [preview handler](../../../inspinia/pages/views.py), and [regression tests](../../../inspinia/pages/tests.py). The template example below uses the same direct comparisons as the implemented partial.

**Goal:** Restore the previous neutral rendered-preview style on `/tools/latex-preview/` while keeping Evan-style rendering as the default on contest/solution pages.

**Architecture:** Keep one shared render partial and add a style variant switch keyed by `render_style`. The LaTeX preview page and AJAX endpoint explicitly request `classic`; all other callers remain unchanged and continue to get Evan mode by default. Cover this with targeted tests that validate both the tool-specific classic output and the default Evan fallback.

**Tech Stack:** Django templates/views, pytest, MathJax preview flow, Asymptote render segment partial

---

## File structure

- Modify: `inspinia/templates/partials/statement-render-content.html`
  - Add a small `render_style` branch (`classic` vs default) for wrapper and Asymptote panel classes.
- Modify: `inspinia/templates/pages/latex-preview.html`
  - Pass `render_style='classic'` for parsed-preview includes and remove Evan class from the live preview output shell.
- Modify: `inspinia/pages/views.py`
  - Pass `render_style: "classic"` when rendering HTML for `statement_render_preview_view`.
- Modify: `inspinia/pages/tests.py`
  - Update render-preview endpoint expectation for classic output and add a fallback test proving shared-partial default remains Evan.

### Task 1: Add style-variant wiring with TDD lock-in

**Files:**
- Modify: `inspinia/pages/tests.py`
- Modify: `inspinia/templates/partials/statement-render-content.html`
- Modify: `inspinia/templates/pages/latex-preview.html`
- Modify: `inspinia/pages/views.py`

- [ ] **Step 1: Write the failing tests first**

In `inspinia/pages/tests.py`, add the template loader import:

```python
from django.template.loader import render_to_string
```

Update `test_statement_render_preview_returns_rendered_asymptote_html` assertions to lock classic style for the tool endpoint:

```python
    assert "statement-evan-box" not in payload["html"]
    assert "border rounded-3 bg-body-tertiary p-3" in payload["html"]
```

Add a new test right below it to lock default partial behavior:

```python
def test_statement_render_content_defaults_to_evan_style():
    html = render_to_string(
        "partials/statement-render-content.html",
        {
            "segments": [
                {"kind": "text", "content": "Prove $x=y$."},
            ],
        },
    )

    assert "statement-evan-box" in html
```

- [ ] **Step 2: Run targeted tests to confirm failure**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_statement_render_preview_returns_rendered_asymptote_html \
  inspinia/pages/tests.py::test_statement_render_content_defaults_to_evan_style \
  -q
```

Expected:

- `test_statement_render_preview_returns_rendered_asymptote_html` fails because the endpoint still returns Evan style.
- `test_statement_render_content_defaults_to_evan_style` passes (confirms baseline default behavior before wiring).

- [ ] **Step 3: Implement minimal style-variant wiring**

In `inspinia/templates/partials/statement-render-content.html`, branch on `render_style`:

```django
<div class="statement-render-content d-flex flex-column gap-3{% if render_style != 'classic' %} statement-evan-box{% endif %}">
  {% for segment in segments %}
    {% if segment.kind == "text" %}
      {% if segment.content %}
      <div class="statement-text-fragment" data-mathjax-scope>{{ segment.content }}</div>
      {% endif %}
    {% elif segment.kind == "asymptote" %}
      <div class="{% if render_style == 'classic' %}border rounded-3 bg-body-tertiary p-3{% else %}statement-asymptote-panel{% endif %}">
        <div class="d-flex flex-wrap align-items-center gap-2 mb-3">
          <span class="badge bg-info-subtle text-info">
            <i class="ti ti-wave-sine me-1"></i> Asymptote
          </span>
          {% if segment.backend_label %}
          <span class="text-muted fs-xs">{{ segment.backend_label }}</span>
          {% endif %}
        </div>
        {% if segment.svg_markup %}
        <div class="asymptote-svg-frame">
          {{ segment.svg_markup|safe }}
        </div>
        {% else %}
        <div class="alert alert-warning mb-0">
          Could not render this Asymptote block{% if segment.error %}: {{ segment.error }}{% endif %}
        </div>
        {% endif %}
        <details class="mt-3">
          <summary class="text-muted fs-xs">Show Asymptote source</summary>
          <pre class="mt-2 mb-0"><code>{{ segment.code }}</code></pre>
        </details>
      </div>
    {% endif %}
  {% endfor %}
</div>
```

In `inspinia/templates/pages/latex-preview.html`, switch both tool render paths to classic:

```django
<div id="latex-preview-output" class="latex-preview-surface"></div>
```

```django
{% include 'partials/statement-render-content.html' with segments=problem.statement_render_segments render_style='classic' %}
```

In `inspinia/pages/views.py`, pass the variant in `statement_render_preview_view`:

```python
    html = render_to_string(
        "partials/statement-render-content.html",
        {
            "segments": render_payload["statement_render_segments"],
            "render_style": "classic",
        },
        request=request,
    )
```

- [ ] **Step 4: Run focused verification**

Run:

```bash
uv run pytest \
  inspinia/pages/tests.py::test_statement_render_preview_returns_rendered_asymptote_html \
  inspinia/pages/tests.py::test_statement_render_content_defaults_to_evan_style \
  inspinia/pages/tests.py::test_latex_preview_parse_action_builds_structured_preview_without_saving \
  -q
```

Expected:

- All listed tests pass.
- Endpoint HTML remains Asymptote-capable and text-inclusive, but now classic-styled for the tool route.
- Shared partial default still emits Evan class when no `render_style` is provided.

- [ ] **Step 5: Commit the feature slice**

Run:

```bash
git add \
  inspinia/pages/tests.py \
  inspinia/pages/views.py \
  inspinia/templates/pages/latex-preview.html \
  inspinia/templates/partials/statement-render-content.html
git commit -m "fix: restore classic latex preview render style"
```
