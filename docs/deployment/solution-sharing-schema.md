# Public solution sharing schema release

The public-sharing feature requires `solutions.0005_solutionpublicshare`. Its
SHA-256 is `0309eeb67b809651c59b6ab9e49bac7955ed00b38083fa060742d3031537bb77`.
The migration contains exactly one `CreateModel` operation for
`solutions_solutionpublicshare`, including its primary key, unique UUID token,
revision, active flag, snapshot, preview image, timestamps, and one-to-one
solution foreign key. It has no data migration or backfill. Existing solution,
block, account, catalogue, and completion rows remain unchanged.

The migration is classified `backward-compatible-schema` in
`deployment/migration-classifications.yml`. Classification alone does not admit
it to the installed root-owned migration authority. The current bounded schema
selector has no allowance for this migration. Do not dispatch it as
`migration_class=none`, apply it over workstation SSH, or substitute a broad
migration command.

Before deployment, separately authorize preparation, review, and installation of
a frozen allowance for this exact migration through the existing bootstrap
procedure. Follow the bounded PDF schema precedent in
[solution-pdf-schema.md](solution-pdf-schema.md): hash-bind this migration and its
prior dependencies, require an exact pending plan, freeze the PostgreSQL 17.9
catalogue delta, prove prior records/sequences/triggers and the active revision
remain unchanged, and bind the evidence to the exact release and artifact.
Reject additional or modified migrations. Retain the existing lock/statement
limits and recovery-required behavior after migration failure.

The separately authorized authority installation must preserve target and audit
configuration, marker, key identity and forced command, users, database
roles/privileges, environment/media, app/scheduler/proxy units, and all GitHub
protections. Its supported bootstrap procedure installs reviewed root-owned
helpers and runs `systemctl daemon-reload`; it does not itself migrate or restart
the application. Verify preserved hashes and unchanged active application/health
before the protected release proceeds. Application deployment authorization does
not itself authorize this authority update.

Only after that allowance is installed may the merged release use
`backward-compatible-schema` with its exact disclosure, complete CI, protected
production review, bounded migration, activation, and immediate/stabilization
checks. Verify anonymous page/JPEG metadata, private draft separation, explicit
snapshot update, and revocation. Retain share rows and revocation state during
code recovery; do not drop the new table or retry an ambiguous migration.
