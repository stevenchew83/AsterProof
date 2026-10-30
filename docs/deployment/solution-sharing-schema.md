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
it to the installed root-owned migration authority. The bounded source allowance
is `scripts/deployment/solution_sharing_schema.py`; installation remains a
separately authorized bootstrap operation. Do not dispatch it as
`migration_class=none`, apply it over workstation SSH, or substitute a broad
migration command.

The allowance follows the bounded PDF schema precedent in
[solution-pdf-schema.md](solution-pdf-schema.md). It pins this migration and all
four prior solution migrations, admits exactly one `CreateModel` operation, and
checks the one-table catalogue fixture with fingerprint
`323b8aec381d76e850cb3d99e0f24f72b5d3c3c68218a9a885cf7ff4b7bb264e`.
`solution_sharing_schema_rehearsal.py` requires an empty, isolated PostgreSQL
17.9 Actions database. It compares all prior records, sequences, trigger/function
definitions, catalogue objects and migration metadata before and after applying
the exact plan and running the active revision's fixed compatibility check.
Only one migration-recorder row/counter increment and the unused new table's
identity sequence may differ. The table remains empty; existing drafts are not
shared. A hand-authored fixture is not evidence: both PR CI and the protected
release build must verify the actual PostgreSQL delta and preservation checks.
The attested artifact binds that proof to its exact target and active revision.
Additional or modified migrations remain rejected. The existing 2-second lock
and 30-second statement limits and recovery-required behavior remain intact.

After merging, manually run **CI** on `main` with `baseline_sha` equal to the
verified active production SHA. Download its PostgreSQL rehearsal artifact and
verify that `source_sha` is the exact current `main` revision and `active_sha`
matches production. Use the digest of those original bytes in the disclosure;
never rewrite a PR proof's source revision to stand in for a release rehearsal.
The protected production build repeats that same rehearsal and must produce the
identical proof bytes before its attested artifact is accepted.

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
