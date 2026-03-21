# Static Assets Guide

This directory contains frontend source files, compiled assets, images, and vendored plugins.

## Source of truth

- Prefer editing SCSS under `inspinia/static/scss/` and shared JS under `inspinia/static/js/`.
- Treat compiled files under `inspinia/static/css/` as generated artifacts. Do not hand-edit them unless the task is an explicit emergency patch.
- Treat `inspinia/static/plugins/` as vendored third-party assets. Only change them when intentionally upgrading or patching a dependency.

## UI framework rules

- The project uses Bootstrap 5 plus the Inspinia theme conventions.
- Keep `config.js` behavior and `data-*` theme configuration intact.
- Use the existing design tokens and semantic color patterns; do not introduce a second styling system.

## Rebuild expectations

- After changing SCSS or shared asset sources, run `npm run build`.
- If you change source assets but skip a rebuild, say so explicitly in your handoff.

## Safe editing checklist

- Check whether a change belongs in SCSS, template markup, or page-local JS before editing static files.
- Avoid editing minified bundles by hand.
- Keep iconography and component styling consistent with the rest of the dashboard.
