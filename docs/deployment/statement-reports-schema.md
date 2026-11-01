# Statement reports release

Readers can report incorrect statements from authenticated problem pages and
public problem lists. Guest access is checked against the current public list,
its active problem, and the displayed statement on every submission. Reports
are visible only to administrators. The admin inbox supports search, status
counts, pagination, and resolve, dismiss, and reopen actions. Reports preserve
the submitted statement text; the feature does not send email.

The release adds exactly `pages.0041_statement_issue_reports`, creating the
isolated `pages_statementissuereport` table with thirteen columns, nullable
statement/reporter/reviewer references, a unique submission UUID, and a
status/time index. It does not backfill or rewrite existing records.

The migration SHA-256 is
`15367bc1f22fdfa273bdc35893a5b73433d1dbd404fda7edb1506fee319f80cb`.
The PostgreSQL 17.9 catalogue delta is frozen in
`scripts/deployment/tests/fixtures/statement-reports-schema-delta.json`, with
fingerprint
`ae217ed52eaedc3c6159142e85e821737cce739e160db362c385dd4815e66055`.
`scripts/deployment/statement_reports_schema.py` also freezes all prior statement
migration and seed bytes. No other pending migration is admitted.

CI and the protected production build run
`scripts.deployment.statement_reports_schema_rehearsal` against their pinned,
empty PostgreSQL 17.9 database. The rehearsal seeds synthetic users, statements,
progress, private solutions, active/stopped shared copies, and newsletter
records. It compares all existing rows, sequences, schema objects, and trigger
definitions before and after the exact migration and an active-revision smoke.
The report table and its sequence remain unused; only the migration recorder
adds a row and increments its counter. Local rehearsals are supporting evidence,
not substitutes for the exact merged release's Actions proof.

The migration class is `backward-compatible-schema`. Code recovery retains the
new table and reports. Legacy deletion of records referenced by reports can be
rejected by the retained foreign keys; recovery is not permission to remove
reports or reverse the schema.

The installed trusted worker must receive this exact frozen allowance using
the separately authorized [bootstrap installer](production-bootstrap.md).
Application deployment authorization does not install deployment authority.
Review and preserve the current target, audit identity, forced-command key,
service definitions, users/roles, environment/media boundaries, GitHub
protections, active release, and schema fingerprints. Installing authority
reloads systemd without restarting the application or applying the migration.

After merging, obtain the PostgreSQL proof for the exact merged SHA and verified
active revision, then construct the starting/expected metadata disclosure from
the frozen delta. Use the normal protected Production deploy workflow with
`backward-compatible-schema`, complete CI, and the original rehearsal bytes.
Existing two-second lock and thirty-second statement bounds remain. Reconcile
an interrupted or failed operation by its original ID before any new dispatch.

Acceptance includes guest submission through a public list, denied private-list
and non-admin access, unchanged statement contents, private report visibility,
correct counts/search/status actions, and the normal immediate release health,
static-asset, and stabilization checks. Use synthetic fixtures for submissions;
read-only production checks must not create reports.
