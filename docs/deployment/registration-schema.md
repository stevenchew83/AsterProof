# Public registration schema release

The allowance covers only `users.0010_public_registration`. It adds
`public.users_useraccesssettings.allow_public_registration`, a non-null Boolean
with a persistent database default of `true`. The audit event choice changes
Django metadata. The PostgreSQL catalog delta is one column.

The release build rehearses the exact forward plan on a disposable PostgreSQL
17.9 instance. It verifies that existing settings, audit events, records, schema
objects, triggers, and sequences are preserved, and that Django appends exactly
one migration record. The previous application reads the settings and can insert
a settings row with the database default. The new reader enforces both the
stored policy and the deployment override.

Obtain the starting metadata with the installed `catalog-snapshot` audit command
through the approved read-only route. Match the fingerprints to the live health
response. Derive the ending fingerprints with
`registration_schema.expected_catalog_audit` and the frozen one-column fixture.
Bind the PostgreSQL rehearsal, catalog fingerprints, active SHA, migration hash,
and exact target SHA into the protected release disclosure.

Install the exact reviewed worker revision with the separately authorized
[production bootstrap procedure](production-bootstrap.md#installation-review).
Preserve the existing target contract, audit role, account permissions, forced
command, service definitions, and release safeguards. The registration reader
check uses catalog and Django migration metadata through the existing audit role.

Once the column or migration record exists, activation and both recovery paths
require a release whose attested files include the reviewed registration gate.
Older code can read the additive schema but cannot enforce a stored closure.
Before approval, identify the recovery owner and a path to an independently
verified registration-aware release. Keep the migration and settings during
code recovery. Changes to the frozen reader files require review before the
trusted reader allowance can accept them.

Dispatch **Production deploy** for the exact current `main` SHA with
`migration_class=backward-compatible-schema`. An approved `skip_ci=true` skips
automated quality checks. The protected PostgreSQL rehearsal, artifact
attestation, approval, and activation checks still run. Check the active SHA,
artifact digest, schema fingerprint, process restart, and public account entry
after activation. The switch starts on unless server configuration closes it.
