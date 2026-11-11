# Static Assets Guide

This directory contains frontend source files, compiled assets, images, and vendored plugins.

## Source of truth

- Prefer editing SCSS under `inspinia/static/scss/` and shared JS under `inspinia/static/js/`.
- Treat compiled files under `inspinia/static/css/` as generated artifacts. Do not hand-edit them unless the task is an explicit emergency patch.
- Treat `inspinia/static/plugins/` as vendored third-party assets. Only change them when intentionally upgrading or patching a dependency.

## UI framework rules

- Follow [the INSPINIA 5.2.0 Bootstrap reference](../../docs/inspinia-dashboard-style.md) for theme initialization, asset order, semantic tokens, and component styling.

## Rebuild expectations

- After changing SCSS or shared asset sources, run `npm run build`.
- If you change source assets but skip a rebuild, say so explicitly in your handoff.

Avoid editing minified bundles by hand.
