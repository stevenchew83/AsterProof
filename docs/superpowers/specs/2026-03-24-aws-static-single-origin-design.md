# AWS static assets: single-origin `/static/` (approach 1)

## Goal

Production on AWS should match localhost behavior: every asset referenced via
Django `{% static %}` resolves from **one consistent origin** under `/static/`,
with the same built files as the repo’s `inspinia/static/` pipeline. The global
shell (Bootstrap/Inspinia JS/CSS) and page-level plugins (DataTables, ApexCharts,
etc.) load reliably. **S3 remains for user media only**, not as a parallel or
stale source for app static files.

## Context

- **Source tree:** `STATICFILES_DIRS` points at `inspinia/static/`. Gulp
  (`npm run build`) produces compiled `css/*.min.css` and bundled `js/*.min.js` /
  `app.js` consumed by templates.
- **Templates:** `base.html` loads `js/config.js`, `css/vendors.min.css`,
  `css/app.min.css`, `js/vendors.min.js`, `js/app.js`. Many pages add
  `plugins/datatables/*`, `plugins/apexcharts/*`, etc. Some pages load MathJax
  from **jsDelivr** (external CDN) — outside `/static/`.
- **Settings:** `config/settings/production.py` uses S3 for `default`
  (media under `media/`). `staticfiles` uses `StaticFilesStorage` (filesystem);
  comments and WhiteNoise expect `/static/` to be served from collected files
  under `STATIC_ROOT` (`staticfiles/`).

**Observed problem:** On AWS, shell and some pages break; the root cause is
treated as **inconsistent static delivery** (e.g. mixture with an S3 mirror,
missing `collectstatic` output, or edge routing not aligned with `STATIC_ROOT`),
not as a need to hand-upload arbitrary JS into S3 alongside media.

## Decision (approved)

**Approach 1 — Same-origin `/static/` only**

1. **Build before collect:** In every environment that produces a deploy
   artifact, run `npm run build` before `python manage.py collectstatic` so
   minified CSS/JS exist under `inspinia/static/`.
2. **Deploy artifact:** The runnable image or server must include a populated
   `STATIC_ROOT` directory (result of `collectstatic`), or run both steps during
   deploy before the app serves traffic.
3. **HTTP path:** `/static/` must be served only from that collected tree —
   via WhiteNoise, nginx/ALB `alias` to `STATIC_ROOT`, or equivalent — **not**
   from a second location (e.g. an S3 bucket prefix that drifts from the app
   version).
4. **S3:** Continue using the configured bucket for **media** only; do not
   serve Django staticfiles from the same bucket mix without an explicit,
   separate staticfiles backend and `STATIC_URL` change (out of scope for this
   decision).

## Asset inventory (reference)

| Area | Examples |
|------|----------|
| Global (base layout) | `images/*`, `js/config.js`, `js/vendors.min.js`, `js/app.js`, `css/vendors.min.css`, `css/app.min.css` |
| Page-level | `plugins/datatables/*`, `plugins/apexcharts/*`, other `{% static 'plugins/...' %}` references |
| External | `https://cdn.jsdelivr.net/npm/mathjax@3/...` — failures are CSP/network/ad-block, not fixed by S3 static upload |

## Verification

On a production page and the same page on localhost:

1. **Network:** All `/static/...` requests return **200** with correct
   **Content-Type** (`text/css`, `application/javascript` or `text/javascript`).
2. **Parity:** Paths and filenames match between environments for the same page
   (no unexpected redirects to another host for core bundles).
3. **Functional:** After global assets load, sidebar/topbar/theme behave;
   DataTables/ApexCharts pages work where used.
4. **MathJax:** If math pages fail while `/static/` is healthy, treat as a
   separate CDN/CSP follow-up (optional later: vendor MathJax into `static/`).

## Out of scope

- Switching to S3/CloudFront as the **primary** staticfiles backend.
- Changing MathJax to self-hosted assets (unless a follow-up spec).
- Large refactors of `views.py` or template structure beyond what is needed to
  align deployment with this decision.

## Success criteria

- No reliance on a stale or partial S3 copy for paths that templates express as
  `/static/...`.
- Deploy process is documented or scripted so `npm run build` and
  `collectstatic` cannot be skipped accidentally.
- Manual “upload JS to S3 for the site to work” is **not** required for standard
  app pages.
