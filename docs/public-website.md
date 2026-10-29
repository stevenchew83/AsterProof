# Public website and learning library

The public website is part of the existing Django application. It uses the
AsterProof identity and existing Bootstrap assets. Account templates, dashboards,
and shared problem lists retain their own flows and access rules.

## Routes and access

| Route | Purpose |
| --- | --- |
| `/` | Public homepage, for signed-in and anonymous visitors |
| `/about/` | AsterProof's purpose and approach |
| `/contact/` | Contact Steven by email |
| `/privacy/` | Privacy Policy |
| `/terms/` | Terms of Use |
| `/library/` | Subject directory and published-resource search |
| `/library/<subject>/` | Published areas in a subject |
| `/library/<subject>/<area>/` | Area overview and concepts |
| `/library/<subject>/<area>/<concept>/` | Concept explanation, prerequisites, lectures |
| `/library/<subject>/<area>/<concept>/<lecture>/` | Lecture and optional source link |
| `/newsletter/subscribe/` | Request an email confirmation |
| `/newsletter/confirm/<token>/` | Confirm the subscription with a POST |
| `/newsletter/unsubscribe/<token>/` | Unsubscribe with a POST |

Signing in still leads to the activity dashboard. The public site's Workspace
link opens that dashboard; account approval rules still apply there. Anonymous
shared problem lists and their login-protected PDF route are unchanged.

## Publishing the library

Use **Public website & library** in Django admin:

1. Create an **area** under Algebra, Geometry, Number theory, or Combinatorics.
2. Add **concepts** to the area, with optional prerequisites.
3. Add **lectures** to each concept, including reading time and source credits.
4. Enter a summary and Markdown in the body. Use `$...$` for inline mathematics
   and `\[...\]` for display mathematics. Headings, lists, tables, and links are
   supported. HTML is sanitized using the existing training renderer; formulas
   use the existing MathJax integration. The admin has a formatted text preview;
   check rendered mathematics on the public page before announcing a resource.
5. Save drafts, review them, then enable **Is published** on the area, concept,
   and lecture. A draft parent hides all its descendants, even if a child is
   marked published. Drafts are excluded from search and prerequisite links.

Slugs are prepopulated in admin and unique within their parent. Keep published
slugs stable so shared URLs continue to work. Order controls display sequence.
No sample lessons or private material are seeded by the migration.

An area's optional `CatalogueArea` link and a concept's optional
`CatalogueConcept` link identify existing catalogue entries without modifying them. Catalogue
notes, progress data, and existing training material are never published
automatically. Public editorial bodies are deliberately separate from private
analytics. Parent deletion is protected while children exist.

This release parses author-entered Markdown and LaTeX only. It does not fetch,
import, summarize, or embed external PDFs or videos. A lecture can link to an
HTTP(S) reference. A future importer should create reviewable drafts with source
credits, rather than publish generated content automatically.

A separate blog is optional later for announcements and longer essays. The
subject/area/concept/lecture library is the main structure for learning material.

## Newsletter consent and delivery

- Subscription is separate from accounts and requires an unchecked consent box
  followed by confirmation sent to the entered address. No account is enrolled
  automatically and staff cannot manually add subscriptions through admin.
- Confirmation links expire after 48 hours. A new request replaces the old link.
  GET requests do not subscribe or unsubscribe; the destination requires a
  CSRF-protected POST, so ordinary email-link scanning does not change consent.
- Unsubscribe links do not expire. Unsubscribing invalidates outstanding
  confirmation links. Resubscribing requires another email confirmation.
- Requests return a generic response to avoid exposing subscription status.
  A hidden bot field, rate limits, and a global budget bound confirmation sends.
  Cache failure prevents sending rather than bypassing the limits.
- Limits: one request per address per minute, three per address per
  24-hour window, ten per `REMOTE_ADDR` per hour, and a shared allowance of 100
  newsletter emails per 24-hour counter window by default. Confirmations, campaign
  emails and tests share that allowance. Counters may consume allowance without a
  successful send. The production reverse proxy can make `REMOTE_ADDR` shared
  across visitors, so the hourly limit is intentionally conservative. Do not
  trust arbitrary forwarded headers; revisit the proxy's trusted-IP policy
  before increasing traffic capacity.
- Confirmation emails reuse the branded account shell, inline logo, and configured
  Gmail sender. They use `DJANGO_PUBLIC_SITE_ORIGIN`, never a request Host header.
  This newsletter budget is separate from account-email limits and does not
  guarantee total Gmail capacity. Preserve capacity for sign-in and resets.
- SMTP failures log a generic warning without addresses or tokens. Users can
  retry after a minute. Delivery to an inbox still depends on the mail provider.
- Subscription records are visible in admin for consent review and deletion on
  request. Review old pending records periodically; no automatic retention job is
  added. Only `confirmed` records are eligible for future newsletter campaigns.

App admins manage newsletters from **Administration → Newsletter** at
`/manage/newsletter/`. The workspace includes subscriber search and opt-out,
branded Markdown drafts and previews, tests to the signed-in administrator,
confirmed-only campaigns, individual unsubscribe links and delivery history.
See [Newsletter operations](newsletter.md) for sending and interrupted-delivery
handling. Automatic lecture alerts and an email-provider migration are outside
this feature.

## Settings and assets

Optional settings (documented in `.env.sample`):

- `DJANGO_PUBLIC_SITE_ORIGIN`: defaults to `https://asterproof.com`.
- `DJANGO_PUBLIC_OPERATOR_NAME`: defaults to `Steven`.
- `DJANGO_NEWSLETTER_DAILY_EMAIL_LIMIT`: defaults to `100`; set `0` to stop
  confirmation sends while retaining the generic request response.

Contact uses `chinchiat83@gmail.com`, the configured project sender. Review the
Privacy Policy and Terms text for the intended launch before publishing it.

Run `npm ci` and `npm run build` to compile public SCSS and the self-hosted Three.js
geometry bundle. Three.js is pinned; esbuild bundles only the homepage entry.
The animation has a pause control, honours reduced motion, pauses when hidden
or outside the viewport, and falls back to SVG without WebGL2 or JavaScript.
Other public pages do not load the Three.js bundle.

The additive `website.0001_initial` migration creates the editorial and consent
tables. Apply it through the normal reviewed release procedure; do not enable
the new app against a database that lacks the migration.

## Local verification

Use test settings with `DJANGO_READ_DOT_ENV_FILE=False` to avoid the ignored Gmail
configuration. Tests use local SQLite and the in-memory email backend:

```sh
DJANGO_READ_DOT_ENV_FILE=False uv run pytest inspinia/website/tests
DJANGO_READ_DOT_ENV_FILE=False uv run python manage.py check --settings=config.settings.test
npm run build
```

For a browser preview, use a separate local database and file email backend.
Set the public origin to the preview's localhost URL. Never test subscription
delivery against real recipients without authorization.
