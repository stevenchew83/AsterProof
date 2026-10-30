# Public solution reader analytics schema

The admin public-solutions dashboard requires exactly
`solutions.0006_solution_share_daily_views`. Its frozen hash is recorded in
`scripts/deployment/solution_analytics_schema.py`, together with all five prior
solution migration hashes. The migration creates only
`solutions_solutionsharedailyviews`: an identity primary key, date, non-negative
view count, and cascading share foreign key, with date/FK indexes and a unique
share/date constraint. It has no backfill or existing-record writes and stores no
visitor identifiers.

The classification is `backward-compatible-schema`. This classification and
application deployment authorization do not install new migration authority.
The installed authority must receive the reviewed hash-bound allowance through a
separately authorized bootstrap installation, including its systemd daemon reload.
Never dispatch this release as `none`, run the migration over workstation SSH,
or broaden the pending-plan check.

The allowance follows [the sharing-table procedure](solution-sharing-schema.md).
The PostgreSQL catalogue delta is frozen in
`scripts/deployment/tests/fixtures/solution-analytics-schema-delta.json`, with
fingerprint `3a41023caece29105ac226273d7191d325b3729c59c5d3c7a6f1d7e58fa92568`.
The fixture alone is not a preservation proof. CI and the protected build run
`scripts.deployment.solution_analytics_schema_rehearsal` in the pinned empty
PostgreSQL 17.9 database. The rehearsal seeds existing private solutions, an
active shared proof, and a stopped/cleared share. It verifies all prior records,
sequences, triggers/functions, schema objects, and migration metadata before and
after the exact single-operation migration and the active revision's fixed
compatibility smoke. The new counter table and sequence remain unused. Only one
migration recorder row and its counter increment may change.

After merging, run CI on the exact current `main` with `baseline_sha` set to the
verified active production SHA. Check the original rehearsal artifact's source
and active revisions and hash its unmodified bytes. Production repeats that
rehearsal and binds it, the migration hash, starting/expected fingerprints, and
fixed smoke to the attested release. Do not relabel a PR rehearsal as an exact
merged-release proof.

Before installing the new authority, record and preserve the current target,
audit configuration, marker, key and forced-command restrictions, entrypoint
helpers, app/proxy/scheduler unit definitions, users and database roles, persistent
environment/media, GitHub protections, active release, application PID, and schema
fingerprints. Use only the supported bootstrap installer from the reviewed clean
immutable revision. Its daemon reload must not restart the application or apply
the migration. Verify all preserved controls and installed authority hashes.

After that separately authorized installation, use the protected production
workflow with `backward-compatible-schema`, the exact disclosure, complete CI,
normal environment review, bounded migration, activation, and immediate checks.
The existing two-second lock and thirty-second statement limits remain. A failure
after entering migration stays `recovery_required`; reconcile its operation ID
before further action. Code recovery retains this table and all counters.

Acceptance includes strict admin-only dashboard access, shared-snapshot metadata
without private draft edits, one anonymous browser open appearing in the daily
aggregate, owner/admin and WhatsApp preview fetches not increasing it, logo image
metadata, and stopped links remaining unavailable. Earlier traffic is unavailable;
repeat opens count and automated-traffic filtering is best effort.
