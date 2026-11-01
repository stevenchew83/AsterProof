# Signed-in learning activity

The View analytics dashboard keeps measured learning activity separate from existing archive page-open counts. Historical opens have no inferred duration or clicks.

## Coverage and meaning

`inspinia/pages/learning_activity.py` lists eligible routes explicitly. Coverage includes training, submissions, personal progress, problem browsing, community problems, lists, and private solution workspaces. Public, authentication, account, trainer-management, and admin routes are excluded. Admin accounts using a learning page are measured, but the dashboard's existing **Include admins** setting excludes them by default.

A measured visit is a rendered learning page that successfully reports from JavaScript. Visible time uses a monotonic browser clock, pauses when hidden, and clamps long execution gaps caused by device sleep or browser suspension. Back-forward-cache restores resume the same visit without charging the time away. This estimates visible-tab time, not attention or confirmed reading. No input-idle timeout is used, so silent reading and mathematical thinking continue to count. A visible page left open can therefore accumulate time.

Snapshots are sent on load, every 30 seconds while visible, after button interactions, and on hide/unload. Delivery is best effort: abrupt closure or failed connectivity may lose the last interval. Legacy page-open counts, measured visits, and signed-in account counts have different denominators.

Click reporting uses the fixed action vocabulary and selectors in `ACTION_RULES`. It covers primary save, publish, draft, editor-view, PDF, share, completion, submission, search/filter, and list actions. Unmatched controls are explicitly grouped as **Other button (unclassified)**; adding an action requires an explicit catalog entry. Form submission by keyboard is counted, while a click followed by its submit event counts once. Counts measure interaction, not successful completion of the underlying operation. These are summaries, not a click-by-click session replay.

## Data and controls

The new tables store the account, canonical path without query strings, route name, page-open/report times, cumulative visible milliseconds, and counts for fixed action keys. No DOM labels, form values, keystrokes, proof content, IP addresses, cross-site IDs, browser fingerprints, or recordings are added. Account deletion removes the visit and action rows. Existing data retention remains governed by the service policy; this feature adds no automatic deletion or scheduling job.

A server-signed, expiring page token binds reporting to the account and eligible page. The endpoint requires the existing approved session and CSRF protection. Body size, action vocabulary, counts, visible time, sequence, and request frequency are bounded. Row locking and cumulative snapshots prevent duplicate/out-of-order requests from double-counting. User-reported browser measurements are not suitable for security, attendance, billing, or grading decisions.

`DJANGO_LEARNING_ACTIVITY_ENABLED` defaults to true and disables both configuration emission and collection when false. Reporting failures do not block learning pages. The collector returns 503 if its tables are unavailable; the dashboard reports that its activity schema is unavailable. Install the schema before enabling collection in any release.

## Local verification and release

The feature adds `pages.0044_learning_page_activity`, an additive two-table migration with no backfill. Classification alone does not install production authority. Production releases use the frozen allowance and PostgreSQL preservation proof described in [Learning activity schema release](deployment/learning-activity-schema.md). Installing that allowance is a separately authorized host-administration step; the protected application deployment then applies the exact migration before activation.

Focused checks:

```bash
DJANGO_READ_DOT_ENV_FILE=False uv run pytest inspinia/pages/test_learning_activity.py scripts/tests/test_page_view_analytics_js.py
node --test scripts/tests/learning_activity.test.cjs
npm run build
```
