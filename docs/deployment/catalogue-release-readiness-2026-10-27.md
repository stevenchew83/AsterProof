# Catalogue release readiness — 27 October 2026

## Current status

Application PR #311 and verification/audit PR #312 are merged. The user subsequently authorized creation of a production database backup, verification of an isolated restore, and the catalogue migration/deployment. That opens the bounded backup-authority scope required by the earlier release gate.

The prepared implementation now follows [catalogue backup and maintenance](catalogue-backup-and-maintenance.md): private matching PG17 runtime, root-only encrypted backup, full isolated local restore, deterministic data/schema hashes, durable drain/backup states, exact migration plan and post-migration original-record verification. Existing protections and fixed target identities remain in force. Production backup/restore/migration outcomes must be recorded from the eventual operation; preparation and CI tests do not establish their success.

The earlier PostgreSQL schema proof remains valid: source identity preservation, prior-revision compatibility and frozen schema/behaviour fingerprints were verified in runs 40485838675 and 40487423449. The newly added native-runtime and complete encrypted-restore rehearsal must also pass before host installation or activation.

## Recorded boundary before authorization

The application release has been requested. Production activation is not ready: the current protected deployment workflow and installed authority contract allow only migration-free releases and the exact earlier `pages.0036_concept_assignment_reviews` exception. This release requires migrations 0037–0039. Application deployment authorization does not authorize replacing its root-owned deployment authority, changing protection rules, or declaring these migrations migration-free.

The existing migration classifier requires RunPython migrations to be `data-or-non-compatible`. Accordingly, 0037 is registered as backward-compatible schema, while 0038 and 0039 require recovery and disable automatic code rollback. Their data effects are limited to the new tables and revision counter; classification must not be weakened to fit the existing workflow.

## Frozen migration inputs

| File | SHA-256 |
| --- | --- |
| `0037_catalogue_tables.py` | `5eccd458a588eab19bc3bbfd4d58a2b7a0ab40bcefabbd7b53fcf226acb2ca18` |
| `0038_seed_catalogue.py` | `ea1fedfed7c0220a89dad21d5cb5bd1d7edc5ebe2a3e74746254429fa7577d16` |
| `0038_catalogue_seed.json` | `e98f5329e697597ef4dcadeb77d912213237365b05d3207d76391581222386f6` |
| `0039_catalogue_revision_triggers.py` | `03c531d47c50320c3f99f557ffd94df15e869b9cfceb5efa5b30700766c0c5ed` |

0037 creates eleven catalogue, membership-generation and derived-summary models, with references to existing identities. 0038 inserts four subjects, 45 areas, 1,163 concept ID rows, 1,140 memberships, 262 relations, and 4,836 scoped aliases/holds into the new tables only. Existing concept IDs, original problems, reviewed assignments, completion rows, users and study notes are preserved.

0039 creates `asterproof_catalogue_revision()` and fourteen `ap_catalogue_*` triggers. Those triggers increment only `pages_cataloguestate.source_revision` when relevant source/catalogue/published-evidence rows change. Installation does not rewrite the existing source rows. The PostgreSQL implementation has passed the pinned rehearsal described above; SQLite execution is also verified.

## Separately authorized deployment-support scope needed

Authorize preparation, review and installation of a frozen, narrowly bounded deployment-authority update for **these three migrations and this seed**, through the existing bootstrap and protected GitHub Actions paths. It should:

- retain the repository, main-SHA/artifact/attestation/OIDC binding, target marker, existing principals, environment approval, forced-command transport and current release controls;
- accept only this exact ordered plan and reviewed file/seed hashes; keep arbitrary migrations, SQL, shell dispatch and unrelated maintenance disabled;
- audit exact trigger/function definitions as well as table, migration and state fingerprints, because the current table/schema fingerprint alone does not certify trigger behaviour;
- execute PostgreSQL 17.9 rehearsal against the existing pinned image, test source/identity preservation, trigger invalidation, stale-generation handling and active-revision compatibility before installation/activation;
- require bounded lock/statement timeouts, independent restore/recovery evidence and staffed recovery ownership for the data-class release; no automatic code/database rollback or blind operation retry;
- install only the reviewed authority files at a frozen revision using the supported bootstrap procedure, retaining owner/mode/hash read-back and its disclosed systemd daemon-reload effect;
- introduce no IAM, account, database-role, credential, firewall, DNS, network or secret changes.

The application PR did not implement or install an authority patch. Verification/audit preparation is now in PR #312; maintenance enablement and authority installation remain pending the required recovery evidence. Its exact revision and effects must be frozen and checked before any separately authorized installation. If the existing recovery evidence or bootstrap cannot satisfy this bounded scope, stop and disclose the additional requirement.

## Activation acceptance

After supported migration execution, publish the initial shared generation through the existing maintenance command. The catalogue can render independently, but example problems/progress remain visibly updating until a valid generation is published. Preserve the current assignment activation state and existing user completion authority. Verify the immutable release, process, schema/trigger audit, health/static artifacts, retained IDs and representative authenticated catalogue/progress routes. Re-measure production TTFB against the recorded 35.1-second baseline; local timings are not production performance evidence.

No workflow dispatch, production migration, deployment-authority replacement, service restart or production record write is performed by preparing this readiness record.
