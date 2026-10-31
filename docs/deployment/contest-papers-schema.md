# Contest papers and statement authoring release

The application release requires exactly `pages.0040_statement_authoring_metadata`
with SHA-256 `38094d06e4f6f5bbd02ec68bce8d55600d11cb680b469ec86a4972e998322466`.
The statement UUID remains canonical. The explicit writing action prepares a
legacy solution anchor under that same UUID; it never creates another statement.

On PostgreSQL 17.9 this migration changes only three existing columns of
`pages_problemsolverecord`:

| Column | Before | After |
| --- | --- | --- |
| `mohs` | Non-null integer | Nullable integer |
| `contest` | `varchar(64)` | `varchar(128)` |
| `contest_year_problem` | `varchar(128)` | `varchar(160)` |

The two `RunPython` operations preserve catalogue triggers across SQLite table
rebuilds and do nothing on PostgreSQL. Existing rows, UUIDs, statements, solutions,
accounts, completion records, sequences, indexes, constraints, functions and
triggers must remain unchanged. The sole new migration-recorder row and its
sequence increment are disclosed separately.

This release is `data-or-non-compatible`. After activation, authoring can create
unknown difficulty values that the previous application cannot safely consume.
Ordinary automatic or manual code rollback is disabled. A failure after drain or
migration requires reconciliation of the original operation ID and separately
authorized recovery; never retry or restore blindly.

## Proposed bounded authority update

`scripts/deployment/statement_authoring_schema.py` freezes the migration bytes,
the imported trigger-preservation migration, exact pending operation list, three
column changes and unchanged trigger fingerprint. The existing maintenance
validator and worker select this allowance only for the literal
`statement-authoring-maintenance-v1` disclosure. Unknown plans and extra pending
migrations remain rejected. This source proposal does not install authority.

The separately authorized bootstrap installation must use the reviewed immutable
revision of this proposal. It installs the frozen helper modules, updates the
existing authority manifest/pointer and entrypoints, and reloads systemd. It must
preserve the target/audit configuration, marker, existing principals and database
roles, forced-command key and restrictions, GitHub protections, app/proxy/scheduler
units, and persistent environment/media. It must not migrate the database,
restart the application, change IAM/networking/credentials, or install system
packages. The existing private PostgreSQL 17.9 recovery runtime is reused.

## Rehearsal and deployment

CI and the protected release build run `statement_authoring_rehearsal.py` against
the pinned, initially empty PostgreSQL 17.9 service. It compares every prior
migration source with the active revision, checks the exact three-column schema
change, hashes every pre-existing table's complete records, checks all prior
sequences and trigger/function definitions, and runs the active application's
coverage and saved-solution smoke. An explicit-PK, rolled-back probe verifies
unknown difficulty and full-length labels without advancing a source sequence.
The evidence is bound to the exact release/active SHAs and packaged attestation.

After separately approved authority installation, deploy through **Production
deploy** with full CI, `migration_class=data-or-non-compatible`, and the frozen
schema disclosure. The existing maintenance worker drains the app and paired
scheduler, creates an encrypted recovery point, verifies a full isolated restore,
then applies only the frozen migration with the existing lock/statement limits.
It verifies unchanged original records and catalogue behaviour, refreshes the
derived catalogue, activates the immutable application/static release and resumes
the scheduler only after successful checks. No new cloud resources or roles are
part of this operation.

Immediate postflight covers the authoritative release/process/health/static
evidence, contest/year selection, complete grouped statements, default-hidden
review clues, and the editor GET for an existing linked statement. Writing and
saving were tested on synthetic databases; do not create production test records
or public shares solely for postflight without separate authorization. Delayed
monitoring is optional and requires an explicit request.
