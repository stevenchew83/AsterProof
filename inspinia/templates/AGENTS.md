# Templates Guide

This directory contains project templates for pages, users, account/allauth flows, layouts, and partials.

## Layout rules

- Dashboard and authenticated app pages should usually extend `layouts/vertical.html`.
- Shared chrome lives in `partials/topbar.html`, `partials/sidenav.html`, `partials/footer.html`, and `partials/page-title.html`.
- Account/allauth templates should continue using the existing `allauth/layouts/*` and `account/*` structure instead of inventing parallel auth shells.

## Style and assets

- Read [`docs/inspinia-dashboard-style.md`](../../docs/inspinia-dashboard-style.md) before editing dashboard-facing templates.
- Prefer Bootstrap/Inspinia classes and existing component patterns.
- Keep page-specific CSS and JS in `extra_css` and `extra_javascript` blocks.
- Do not duplicate CSS/JS libraries that `base.html` already loads.

## Template discipline

- Use `{% url %}` with namespaced routes instead of hard-coded paths.
- If a template expects a specific context key or JSON payload shape, update the view and tests in the same change.
- Preserve stable DOM IDs and hook points used by tests or page JavaScript unless you update those dependents too.
- Prefer shared partials for repeated markup instead of copying chunks across multiple templates.

## When to escalate to SCSS or JS

- If a visual change needs reusable styling, move it into `inspinia/static/scss/` rather than piling on inline styles.
- If JavaScript is shared across pages, promote it into `inspinia/static/js/`; if it is page-local, keep it close to the template.
