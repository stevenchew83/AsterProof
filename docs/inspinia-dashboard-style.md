# AsterProof web UI reference

Use the licensed INSPINIA 5.2.0 Bootstrap release as the design source for
AsterProof browser pages. The release archive is named
`Inspinia - Multipurpose Admin Dashboard Template 5.2.0.zip`. Use
`Inspinia_v5.2.0/Bootstrap/Django/inspinia` for templates, theme configuration,
and SCSS, and `Inspinia_v5.2.0/Bootstrap/HTML/Admin/dist` for rendered examples.
The shipped Bootstrap sources retain some 5.1.0 labels. Identify the reference
by its archive and paths.

Apply the release's semantic palette, typography, spacing, component markup,
interaction states, and responsive behavior. Use the release defaults and its
provided theme options. Keep the reference files unmodified. Remove project
requirements and overrides that conflict with the release.

| Surface | Reference |
| --- | --- |
| Public navigation, landing page and footer | `landing.html` |
| Account entry and error pages | `auth-*.html` and `error-*.html` |
| Workspace and application administration | Django `layouts/vertical.html` and the topbar, sidenav, page title, and footer partials |
| Colors, typography, buttons, forms, alerts, badges, cards, tabs, and overlays | `ui-*.html` and `form-*.html` |
| Tables, pagination, search and filtering | `tables-*.html` |
| Charts and statistics | `charts-apex-*.html` and dashboard examples |

Keep AsterProof navigation, branding assets, mathematics, editor operations,
routes, permissions, and data contracts. Compose application-specific controls
using the reference's tokens and components. Retain keyboard access, accessible
names, visible focus, validation messages, and access to overflowing tables
and mathematical content. Keep third-party integration styles scoped to their
widgets. Where deployment integrity checks pin a template's exact bytes,
style its existing markup with scoped selectors that reuse reference utilities
and tokens.

After changing shared SCSS or frontend assets, run `npm run build`. Verify the
affected pages against the matching reference examples at desktop and phone
widths, with relevant populated, empty, loading, validation, and theme states.
