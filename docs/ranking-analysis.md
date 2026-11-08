# Ranking analysis

The moderator/admin workspace at `/rankings/analysis/` reads assessment results
directly. Its Overview, Students, Schools, Compare and Data quality views retain
separate assessment/category ranks. It does not change weighted ranking formulas.

## Data meaning

- Numeric calculations exclude missing values and retain recorded zeroes.
- Competition ranks and midrank percentiles reference the full assessment/category.
- School-at-assessment is unknown until a reviewed attribution exists. Current
  school is a separate reporting mode.
- Default model maxima are not verified scoring scales. Reviewed scales and
  comparable scope gate raw/percentage comparisons.
- A recorded outcome is not a verified participation/absence record. Undated
  assessments do not receive invented dates.
- Exports exclude NRICs, dates of birth, private notes and raw uploads.

## Corrections

Moderators/admins prepare draft previews and submit proposals. Only admins apply
or reject them. The proposer can withdraw a pending proposal. Applications are
version checked under the same short transaction lock used by imports; before/
after receipts commit atomically with their changes. Repeated apply is harmless.
An inverse correction is a new proposal, not an edit of history.

Student identities and result ownership are preserved. Identity review can confirm
two students are separate but cannot merge students or transfer results. Existing
analytical values in Django admin link to the reviewed correction workflow.

Fresh Results and History reads resolve reviewed school aliases. Verified result
attributions override the legacy source-school label only in Results; History's
school column continues to describe the current recorded school. Original school
links and source remarks remain intact. Existing formula snapshots show a stale
data notice after relevant changes, until their normal recomputation.

All four imports preserve corrected fields. Conflicting source rows are held
entirely unchanged; other rows can apply. The resulting PARTIAL batch is consumed
and cannot be replayed. Admins retain the approved values or prepare a replacement
proposal. Only allowlisted ranking values enter the held-row record.

## Verification

Run the rankings pytest suite with `config.settings.test`, Ruff, system checks,
migration drift checks, JavaScript syntax/tests, and `npm run build`. Lock tests in
`test_correction_concurrency.py` require an explicitly isolated loopback PostgreSQL
database whose name contains `synthetic`; they skip on SQLite. The deployment must
apply the additive migration before serving the new routes. No migration verifies
metadata, rewrites business records, or applies a production correction.

For a code rollback, retain the additive review tables and their durable receipts.
Do not reverse data corrections or drop audit tables as part of reverting the UI.

The implementation was checked on synthetic data at desktop, tablet and 390px
phone widths in both themes, including empty selections, correction review,
chart drilldowns, CSV/XLSX exports, chart PNG downloads and visible-row copying.
The final full PostgreSQL ranking run passed 163 tests, including concurrent
applications and import/correction races. The SQLite ranking, role and JavaScript
wrapper run passed 172 tests with four PostgreSQL-only skips. Eight JavaScript
checks, Ruff, Django system/migration checks and the asset build also passed.
