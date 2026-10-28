# AsterProof logo concepts

Created on 2026-10-28 with the built-in image generation tool. These raster boards record the original concept exploration.

Each board shows a horizontal wordmark, a standalone symbol, and a smaller symbol preview.

## Selected website identity

Option 3, Geometry Proof, was selected and implemented locally on 2026-10-28. The triangle, four vertices, interior proof line, navy/teal palette, and bold sans-serif wordmark were recreated as clean SVG geometry. The wordmark uses outlined Arial Bold glyphs so rendering does not depend on installed or downloaded fonts. The concept board remains the visual reference; the SVGs are the production asset sources.

Assets under `../../inspinia/static/images/`:

- `asterproof-logo.svg` and `asterproof-logo-light.svg`: transparent horizontal logos for light and dark surfaces.
- `asterproof-mark.svg` and `asterproof-mark-light.svg`: transparent compact icons for collapsed navigation and mobile headers.
- `asterproof-favicon.svg`: geometry mark on a light tile, readable against either browser theme.
- `asterproof-favicon.ico`: PNG-backed 16, 32, 48, and 64-pixel icon frames rendered from the SVG favicon.
- `asterproof-apple-touch-icon.png`: 180-pixel touch icon rendered from the same SVG on an opaque light background.

The shared topbar, sidebar, and base-page favicon links use these assets. The original Inspinia image files remain unused. The branding change preserves the existing CSS framework, layout, and application behavior. Deployment status is recorded by the production workflow.

## Verification

- Django system check and rendering of the real base, topbar, and sidebar templates passed using test settings with dotenv loading disabled.
- All seven assets resolve through Django static-file discovery. SVGs contain no fonts, raster images, scripts, or external references.
- All four ICO frames decode successfully; the touch icon is an opaque 180 x 180 PNG.
- Local Chrome previews cover desktop light/dark, collapsed navigation, and mobile light/dark. The browser uses the actual shared templates and bundled theme assets through offline request routing; it does not connect to production or require a database. External Google Font requests are blocked in the preview.
- Favicon and touch-icon requests return their expected files. No browser page errors were recorded.

Screenshots are saved in [verification/](verification/).

## Options

| Option | Direction | Preview |
| --- | --- | --- |
| 1 | Aster & QED | [PNG](01-aster-qed.png) |
| 2 | AP Monogram | [PNG](02-ap-monogram.png) |
| 3 | Geometry Proof | [PNG](03-geometry-proof.png) |
| 4 | Editorial QED | [PNG](04-editorial-qed.png) |

The geometry mark makes the olympiad-math connection most explicit. The other boards are retained as alternatives from the exploration.

## Generation prompts

### 1. Aster & QED

```text
Use case: logo-brand.
Asset type: custom website logo concept for AsterProof, a competition mathematics and rigorous proof learning platform built with an Inspinia dashboard.
Deliver one polished landscape logo presentation board on a clean white background. Flat, vector-friendly graphic design, precise optical alignment, generous whitespace, professional identity design. At the top center show the full horizontal symbol plus wordmark at a useful readable size. Below, show a large standalone version of exactly the same symbol and a second small version demonstrating favicon legibility. Use only dark charcoal/navy, the existing website's teal/green accent, and white. Color choices should feel natural beside the website's current green-accent dashboard. Exact brand text: "AsterProof" (capital A and P; spell A s t e r P r o o f correctly). No other text, no slogans, no concept numbers, no mockup objects, no gradients, no shadows, no textures, no watermarks. Keep the symbol simple enough to read at 24 pixels and the horizontal lockup usable in a 40-pixel-high website header. This is one coherent logo identity, not a collection of alternative marks.
Primary request: a distinctive mathematical aster/star symbol paired with a modern humanist sans-serif AsterProof wordmark. Design a compact six-arm geometric aster with broad tapering arms and a tiny square-shaped negative-space core, evoking both an asterisk and the QED square. Use teal for the symbol and dark navy for the wordmark. Make it calm, rigorous, memorable, and slightly warm. Avoid the generic four-point AI sparkle and avoid space/rocket imagery. The star is the essential silhouette; no surrounding circle or badge.
```

### 2. AP Monogram

```text
Use case: logo-brand.
Asset type: custom website logo concept for AsterProof, a competition mathematics and rigorous proof learning platform built with an Inspinia dashboard.
Deliver one polished landscape logo presentation board on a clean white background. Flat, vector-friendly graphic design, precise optical alignment, generous whitespace, professional identity design. At the top center show the full horizontal symbol plus wordmark at a useful readable size. Below, show a large standalone version of exactly the same symbol and a second small version demonstrating favicon legibility. Use only dark charcoal/navy, the existing website's teal/green accent, and white. Color choices should feel natural beside the website's current green-accent dashboard. Exact brand text: "AsterProof" (capital A and P; spell A s t e r P r o o f correctly). No other text, no slogans, no concept numbers, no mockup objects, no gradients, no shadows, no textures, no watermarks. Keep the symbol simple enough to read at 24 pixels and the horizontal lockup usable in a 40-pixel-high website header. This is one coherent logo identity, not a collection of alternative marks.
Primary request: a clever custom AP monogram built from two or three bold geometric strokes, paired with a clean engineered sans-serif AsterProof wordmark. The negative space should reveal an A and an upright P through an elegant compact construction, with a diagonal suggesting the rising progress of a mathematical argument. Use dark navy for the symbol with one restrained teal stroke and navy for the wordmark. The monogram must feel designed specifically for AsterProof and remain simple at tiny sizes. No star, no shield, no academic seal, no graduation cap.
```

### 3. Geometry Proof

```text
Use case: logo-brand.
Asset type: custom website logo concept for AsterProof, a competition mathematics and rigorous proof learning platform built with an Inspinia dashboard.
Deliver one polished landscape logo presentation board on a clean white background. Flat, vector-friendly graphic design, precise optical alignment, generous whitespace, professional identity design. At the top center show the full horizontal symbol plus wordmark at a useful readable size. Below, show a large standalone version of exactly the same symbol and a second small version demonstrating favicon legibility. Use only dark charcoal/navy, the existing website's teal/green accent, and white. Color choices should feel natural beside the website's current green-accent dashboard. Exact brand text: "AsterProof" (capital A and P; spell A s t e r P r o o f correctly). No other text, no slogans, no concept numbers, no mockup objects, no gradients, no shadows, no textures, no watermarks. Keep the symbol simple enough to read at 24 pixels and the horizontal lockup usable in a 40-pixel-high website header. This is one coherent logo identity, not a collection of alternative marks.
Primary request: a distinctive olympiad geometry mark paired with a refined, legible AsterProof wordmark. Build the symbol from an asymmetric open triangle with three clear circular vertices and one purposeful interior proof line, arranged so the overall outline gently suggests a capital A. One teal edge or vertex provides focus against dark navy strokes. Use an elegant contemporary sans-serif wordmark with excellent spacing. Let the geometry feel exact and intellectually playful, never cluttered. No compass tool, no book, no seal, no star, no grid, no equations.
```

### 4. Editorial QED

```text
Use case: logo-brand.
Asset type: custom website logo concept for AsterProof, a competition mathematics and rigorous proof learning platform built with an Inspinia dashboard.
Deliver one polished landscape logo presentation board on a clean white background. Flat, vector-friendly graphic design, precise optical alignment, generous whitespace, professional identity design. At the top center show the full horizontal symbol plus wordmark at a useful readable size. Below, show a large standalone version of exactly the same symbol and a second small version demonstrating favicon legibility. Use only dark charcoal/navy, the existing website's teal/green accent, and white. Color choices should feel natural beside the website's current green-accent dashboard. Exact brand text: "AsterProof" (capital A and P; spell A s t e r P r o o f correctly). No other text, no slogans, no concept numbers, no mockup objects, no gradients, no shadows, no textures, no watermarks. Keep the symbol simple enough to read at 24 pixels and the horizontal lockup usable in a 40-pixel-high website header. This is one coherent logo identity, not a collection of alternative marks.
Primary request: a premium editorial mathematics identity led by a beautifully spaced contemporary serif AsterProof wordmark. Design a compact custom serif A as the accompanying symbol, with a small solid teal QED square tucked into its lower-right construction as an intentional detail. The square must feel structural, not a notification dot. Navy typography, subtle thick/thin contrast, sturdy enough for screen rendering. Convey mathematical clarity and timeless scholarship without looking like a school crest. Use the same A-plus-square icon in both standalone demonstrations. No star, no triangle diagram, no script lettering, no laurel, no ornate flourishes.
```
