# Solution collections schema release

For the later site-owned admin curation alteration, see
[admin-curated collection schema release](curated-collections-schema.md).

The collection feature requires exactly
`solutions.0007_solutioncollection_solutioncollectionentry`. The hash-bound
allowance in `scripts/deployment/solution_collections_schema.py` pins that file
and all six earlier solution migrations. Its only operations are two
`CreateModel` operations for `solutions_solutioncollection` and
`solutions_solutioncollectionentry`. Existing solutions, shared proofs, reader
counts, users, catalogue records and completion rows are not rewritten or shared.

The normalized PostgreSQL delta is frozen in
`scripts/deployment/tests/fixtures/solution-collections-schema-delta.json`. The
fixture is catalogue metadata, not preservation evidence. CI and the protected
production build must independently rehearse the actual migration on the pinned
empty PostgreSQL 17.9 Actions database. The rehearsal seeds existing private
solutions, active and stopped public copies, reader counts, completion records
and subscribers. It verifies that all previous schema objects, records,
sequences and trigger/function definitions are unchanged. Only the one migration
recorder row and its counter increment may differ; both new tables and their
identity sequences remain unused. The verified active application revision then
runs its fixed compatibility smoke without changing that state.

The migration classification is `backward-compatible-schema`. Before deployment,
install this exact reviewed allowance with the supported bootstrap installer
from the clean immutable merged revision, following
[production bootstrap](production-bootstrap.md). Installation and its systemd
daemon reload require explicit task-specific authorization covering the schema
allowance. Preserve the existing contract, audit configuration,
marker, key/forced-command restrictions, sudoers, application/proxy/scheduler
units, users/roles, environment/media and GitHub protections. The allowance
installation must not migrate or restart the application.

After merging, dispatch CI on exact current `main` with `baseline_sha` equal to
the verified active production SHA. Download the original rehearsal artifact,
verify its source and active revisions, and hash its unmodified bytes. Compute
the expected catalogue fingerprints from the bounded production catalogue audit
and the frozen delta. Pass that disclosure to **Production deploy** with
`migration_class=backward-compatible-schema` and `skip_ci=false`. The protected
build repeats the pinned rehearsal and must produce identical proof bytes.

The installed worker checks the complete pending plan and exact migration bytes,
verifies the starting fingerprints, applies only the two-table migration with
the established two-second lock and thirty-second statement timeouts, and checks
the expected ending fingerprints before activation. A failure after entering
`migrating` remains `recovery_required`; reconcile the original run/operation ID
before any further action. Code recovery retains collection links and revocation
state and must not drop the new tables.

Complete immediate and short stabilization checks under
[production release](production-release.md), including the active release,
registry, process cgroup, cache-busted health and hashed assets. Verify collection
routes and owner authentication, anonymous contents/anchor rendering, shared-copy
separation and revocation. Do not create production test accounts, solutions or
public collections solely for verification without separate authorization.
