# First-login guide schema release

The first-login experience requires exactly `users.0009_user_solution_guide_status`.
Its reviewed bytes and all eight prior user migrations are frozen in
`scripts/deployment/onboarding_schema.py`. The plan contains one `AddField` and one
`AlterField`, adding only `users_user.solution_guide_status`, a non-null
`varchar(16)` column with the persistent database default `not_enrolled`. Existing
accounts retain their destination. New application code supplies `active`; the
old application can continue creating accounts using the database default. The
AlterField changes the Python default only.

The migration is `backward-compatible-schema`. The catalog delta is frozen in
`scripts/deployment/tests/fixtures/onboarding-schema-delta.json`. The exact
PostgreSQL 17.9 rehearsal must prove that all prior columns, records, sequences,
triggers/functions and migration metadata remain unchanged apart from the new
column and the single migration-recorder row/counter increment. It also verifies
new-account enrollment and old-code account creation in transactions that roll
back, using explicit synthetic primary keys so sequences do not advance.

The rehearsal runs in the pinned empty Actions database, against the exact active
revision and release revision. Its original evidence bytes, migration hash,
catalog fingerprints and fixed compatibility command are bound into the protected
release artifact. A proposed fixture is not a PostgreSQL preservation proof.

Application deployment authorization does not install a new root-owned migration
allowance. Before production activation, separately authorize the supported
bootstrap installer from the reviewed immutable revision, allowing only this
exact pending plan and migration hash. The reviewed support changes are:

- `onboarding_schema.py`, its PostgreSQL rehearsal and regression tests;
- an explicit dispatch case in `additive_schema.py`, `schema_rehearsal.py` and
  `operation_worker.py`;
- the migration classification and CI rehearsal selection.

The installer copies the reviewed authority modules, regenerates the existing
entrypoints/configuration, updates the authority manifest/pointer and reloads
systemd. It must preserve target/audit configuration, marker, forced-command key
and restrictions, existing principals and database roles, app/proxy/scheduler
unit definitions, persistent environment/media and GitHub protections. It does not
migrate the database or restart the application. Do not replace it with workstation
SSH deployment, an unrestricted migration, or an ad hoc authority file copy.

After the separately authorized installation, use **Production deploy** with the
exact current main SHA, full CI, `backward-compatible-schema`, the frozen
disclosure and the normal environment gate. The existing two-second lock and
thirty-second statement limits remain. Failures after entering migration stay
`recovery_required`; reconcile the operation ID before any retry. Code recovery
must retain the preference column and its compatible database default.

Immediate acceptance checks cover active release/process/static evidence, existing
account access, new-account default routing, the optional guide, saving and public
sharing boundaries, and pre-login Writer preservation. Do not create production
test accounts, solutions or public links merely for verification without separate
authorization; use the isolated rehearsal and tests for those writes.
