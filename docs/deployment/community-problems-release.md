# Community problems release readiness

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
| pages.0041_community_problems | ec6e5563f4a5ffb34e9e8d099488bb4d89ea8c3e28e58ccea42a647746cf519c | backward-compatible-schema |
| pages.0042_statement_similarity_source | 33fa41b76b06fa06e997321a58be645b03b68e3fb5b96a9e30f288d93e619024 | data-or-non-compatible |

The complete release is data-class because 0042 contains RunPython. Do not
reclassify it as a no-migration or additive-only release. Do not run migrations
through workstation SSH or weaken the pending-plan guard.

0041 creates seven separate tables. 0042 creates the eighth table, seeds only
its singleton revision, and installs exactly one PostgreSQL invoker-security
function and one trigger:

- function: asterproof_statement_similarity_revision()
- trigger: ap_statement_similarity_revision
- source table: pages_contestproblemstatement
- written table: pages_statementsimilaritysource

The function does not update the existing statement rows. Updates that leave the
statement text and active status unchanged do not advance the revision. Existing
catalogue triggers and functions must remain byte-for-byte equivalent.

## Deployment gate and required separate authorization

The existing installed worker admits specific frozen schema plans. It does not
admit this two-migration plan. An application deployment request does not install
new root-owned deployment authority.

Before production can accept this feature, a separately authorized authority
update must be prepared and reviewed using the existing frozen maintenance path.
Its scope must be limited to these exact migration hashes and initial derived
index materialization. The reviewed change must include:

1. An exact two-migration disclosure, with no unrelated pending operation.
2. PostgreSQL 17.9 schema and trigger/function deltas, previous-record/sequence
   preservation evidence, and an active-revision compatibility smoke.
3. The unchanged existing drain, encrypted RPO0 backup, isolated restore proof,
   lock/statement bounds, identity checks, attestation, and protected-environment
   approval gates.
4. A bounded first refresh_statement_similarity_index execution after migration,
   followed by read-only index readiness and authenticated route checks.
5. A separate bootstrap installation from a reviewed immutable revision, preserving
   existing marker, target, users, database roles, credentials, key restrictions,
   network settings, application/proxy/scheduler configuration, and data.
6. An explicit recovery procedure. Data-class failure is reconciled through its
   existing operation ID, without automatic retry, cancellation, or rollback.

The authority update may require systemd daemon-reload through the established
bootstrap installer. It must not restart the app, migrate the database, change
credentials or roles, enable AI review, or dispatch the application release as an
installation side effect.

This document is a release-readiness proposal, not an installed allowance,
production authorization, PostgreSQL 17.9 attestation, or proof of deployment.

## Application verification

Focused application coverage passed on both SQLite and an isolated local
PostgreSQL database during implementation, including concurrent review-request
deduplication and daily limits. Desktop and phone layouts were inspected using
synthetic posts. Paid provider calls were not used.

Final CI must run against the exact merged application revision. Production
deployment remains blocked until the separate authority scope above is authorized,
implemented, rehearsed, reviewed, and installed.
