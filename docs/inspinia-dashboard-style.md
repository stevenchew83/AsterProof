# Inspinia dashboard style rules (AsterProof)

Keep new admin/dashboard UI consistent with the **Inspinia 4.x / Bootstrap 5** seed bundled under `inspinia/`. These rules describe the **language of the template** (structure, classes, tokens)—not every demo page in the upstream theme.

**Cursor / agents:** Project rule [`.cursor/rules/inspinia-dashboard.mdc`](../.cursor/rules/inspinia-dashboard.mdc) attaches this document when editing files under `inspinia/` (so assistants treat this file as the contract). Set `alwaysApply: true` there if you want the same reminder on every chat.

## Non‑negotiables

1. **Use the theme stack, not parallel CSS frameworks**  
   Pages should load `vendors.min.css` → `app.min.css` via `base.html`. Prefer Bootstrap utilities and Inspinia component classes over ad‑hoc stylesheets.

2. **Preserve the shell**  
   Authenticated dashboard views should extend `layouts/vertical.html` unless you intentionally use the horizontal layout (`layouts/horizontal.html`). Do not remove or rename: `wrapper`, `sidenav-menu`, `content-page`, or the topbar/footer includes unless you are replacing the entire layout system.

3. **Load order**  
   `config.js` must stay **before** app CSS in the `<head>` (see `base.html`). It applies skin/theme/menu attributes on `<html>` on first paint.

4. **Theme is attribute‑driven**  
   Skin and chrome are controlled by `data-*` attributes on `<html>`, merged with `sessionStorage` key `__INSPINIA_CONFIG__`. Defaults include `data-skin` (e.g. `classic`), `data-bs-theme` (`light` / `dark`), `data-menu-color`, `data-topbar-color`, `data-layout-position`, `data-sidenav-size`, `data-sidenav-user`. Avoid hard‑coding colors that fight these modes.

## Page anatomy

| Region | Pattern |
|--------|---------|
| Main width | `container-fluid` for dashboard content (matches demo density). |
| Title row | Include `partials/page-title.html` with `title` / `subtitle`, or match its markup: `page-title-head`, uppercase small title, breadcrumb right. |
| Vertical rhythm | Use `row` + **`g-3`** gutters; stack sections with `mt-0` / `mt-1` / `mt-4` sparingly to match existing pages. |
| Cards | `card`; headers often `card-header border-0 pb-0` with `h4.header-title` and `p.text-muted.fs-xs`; body `card-body` with **`pt-2`** when the header is tight. |

## Components and micro‑patterns

- **KPI / stat tiles**: `card` → `card-body` → `d-flex align-items-center` → icon in `flex-shrink-0` → copy in `flex-grow-1 ms-2`. Icons live in `span.avatar-title.bg-{primary\|info\|warning\|success}-subtle.text-{same}.rounded` with **`i.ti.ti-*.fs-24`** (Tabler icons).
- **Labels**: Uppercase muted labels: `text-muted mb-0 fs-xs text-uppercase fw-semibold`. Headline numbers: `h3.mb-0` or `fs-lg` on `h3` when needed.
- **Alerts / tables / buttons**: Use Bootstrap 5 variants (`alert-info`, `btn-primary`, etc.) so they track `data-bs-theme` and Inspinia’s component SCSS.
- **Icons**: Stick to **`ti ti-*`** (Tabler) with Inspinia size utilities (`fs-22`, `fs-24`, …), not mixed icon sets on the same strip unless the template already does.

## Typography scale (template)

Prefer theme utilities over raw font sizes: `fs-xs`, `fs-sm`, `fs-lg`, `fs-12`; weights `fw-semibold`, `fw-bold`; color `text-muted` for secondary copy.

## SCSS and customization

- Design tokens and overrides live under `inspinia/static/scss/` (`_variables.scss`, `config/_theme-*.scss`, `components/*`).  
- If you change variables or SCSS, **rebuild** assets (`npm install`, `npx gulp build` per `README.md`) so `app.min.css` stays the single source of truth in production templates.

## Django‑specific notes

- **Crispy / allauth**: Account pages under `inspinia/templates/allauth/` use theme‑aligned field/button partials—reuse those patterns for forms inside the dashboard when possible.
- **Extra assets**: Page‑specific CSS/JS belongs in `{% block extra_css %}` / `{% block extra_javascript %}`; do not duplicate jQuery/Bootstrap loads that `base.html` already provides.

## Checklist before shipping a new dashboard screen

- [ ] Extends `layouts/vertical.html` (or documented exception).
- [ ] Uses `container-fluid` + `page-title-head` (or `page-title.html`).
- [ ] Cards and stats follow the flex + `avatar-title` + `ti` icon pattern where applicable.
- [ ] No inline colors that break light/dark or skin variants; use Bootstrap semantic + `-subtle` pairs.
- [ ] No new global CSS unless it belongs in `inspinia/static/scss/` and is compiled.

---

*Reference implementations in this repo: `inspinia/templates/layouts/vertical.html`, `inspinia/templates/pages/dashboard-analytics.html`, `inspinia/templates/partials/page-title.html`, `inspinia/static/js/config.js`.*
