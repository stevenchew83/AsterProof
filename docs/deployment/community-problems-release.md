# Community problems release readiness

> **Historical release contract.** This record covers the original submission
> release and its 0042/0043 allowance. Use the
> [Phase 1 release contract](community-proof-library-release.md) for the
> later Community Proof Library migration and recovery procedure.

## Application release

This release adds authenticated community problem posting at
/community/problems/, with mandatory library similarity preflight, human
moderation, and separate default-disabled paid AI statement review.

Approved community posts remain separate from the main library. All existing
canonical statements, solutions, users, and completion identities are retained.
No production AI setting, provider credential, budget, or review-worker service
is activated by this release.

## Frozen migration inputs

| Migration | SHA-256 | Classification |
| --- | --- | --- |
| pages.0042_community_problems | 6d0e0da75b317154aa1102922e08f04387bff62bd1d5ecd485d416619de07b93 | backward-compatible-schema |
| pages.0043_statement_similarity_source | 0c13e1213ecf0686fbd966d22a387438b2ea2b805f932e2afd1fd35ff552dab7 | data-or-non-compatible |

The complete release is data-class because 0043 contains RunPython. Do not
reclassify it as a no-migration or additive-only release. Do not run migrations
through workstation SSH or weaken the pending-plan guard.

0042 creates seven separate tables. 0043 creates the eighth table, seeds only
its singleton revision, and installs exactly one PostgreSQL invoker-security
function and one trigger:

- function: asterproof_statement_similarity_revision()
- trigger: ap_statement_similarity_revision
- source table: pages_contestproblemstatement
- written table: pages_statementsimilaritysource

The function does not update the existing statement rows. Updates that leave the
statement text and active status unchanged do not advance the revision. Existing
catalogue triggers and functions must remain byte-for-byte equivalent.

## Bounded deployment allowance

The `community-problems-maintenance-v1` allowance admits only the two frozen
migrations above, after reporting migration 0041 is already applied. Both migration
bytes and the index/model/management-command initialization sources are hash-bound.
The separate trusted-worker installation and application deployment remain distinct
operations through the existing bootstrap and protected Actions paths.

The allowance preserves the existing frozen maintenance path and includes:

1. An exact two-migration disclosure, with no unrelated pending operation.
2. PostgreSQL 17.9 schema and trigger/function deltas, previous-record/sequence
   preservation evidence, and an active-revision compatibility smoke.
3. The unchanged existing drain, encrypted RPO0 backup, isolated restore proof,
   lock/statement bounds, identity checks, attestation, and protected-environment
   approval gates.
4. A first refresh_statement_similarity_index execution bounded to 600 seconds,
   followed by a 60-second index/AI-off check. The isolated rehearsal verifies
   authenticated routes, trigger invalidation and preserved reporting records.
5. A separate bootstrap installation from a reviewed immutable revision, preserving
   existing marker, target, users, database roles, credentials, key restrictions,
   network settings, application/proxy/scheduler configuration, and data.
6. An explicit recovery procedure. Data-class failure is reconciled through its
   existing operation ID, without automatic retry, cancellation, or rollback.

The authority update may require systemd daemon-reload through the established
bootstrap installer. It must not restart the app, migrate the database, change
credentials or roles, enable AI review, or dispatch the application release as an
installation side effect.

The pinned PostgreSQL 17.9 rehearsal binds the additive eight-table delta
`5207935ea199048e58e8e7796ca79a39757826e976fe139bc1eb33e9178970da`
and the combined catalogue/community trigger metadata
`5d0c68e538f93cc53c865d7e06b18042a5c4e240651f04fb4b8399fa6fd3d698`.
Normal build proof must match both exact source and active release SHAs.

Both plan validation and post-index verification require
`PROBLEM_STATEMENT_AI_REVIEW_ENABLED` to be false. Initialization also rejects
an enabled review policy or any review job. No provider call or review worker
is part of this release. This document does not itself prove installation or deployment.

## Application verification

Focused application coverage passed on both SQLite and an isolated local
PostgreSQL database during implementation, including concurrent review-request
deduplication and daily limits. Desktop and phone layouts were inspected using
synthetic posts. Paid provider calls were not used.

Final CI must run against the exact merged application revision. Production
deployment uses the separately authorized authority scope above only after it is
rehearsed, reviewed, and installed. Data-class failures remain recovery-required;
inspect the existing operation and recovery receipt before any separately
authorized recovery action. Never automatically retry or roll back.
