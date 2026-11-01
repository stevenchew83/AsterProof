# Continuous solution editor and private review release

This release replaces block authoring with one LaTeX document. Existing blocks
remain frozen; the first explicit save creates an immutable revision. Existing
v1 public copies remain unchanged until their owner explicitly updates sharing.
New public copies use v2 document snapshots. AI review is a separate,
default-disabled capability; deployment does not activate a provider, retrieve a
key, authorize spending, or install a review worker.

## Exact additive schema

The allowance admits only
`solutions.0009_problemsolution_edit_version_solutionreviewpolicy_and_more`.
It freezes this migration and all eight preceding solution migration files.
Its entire pending operation sequence must be exactly: `AddEditVersionField`,
three `CreateModel` operations, `AddField`, two `AddConstraint` operations,
`AddIndex`, and `AddConstraint`. No unrelated pending migration is admitted.

The three new tables hold immutable revisions, private review jobs, and an
explicitly configured review policy. Existing solutions receive only
`edit_version` with a persistent database default of zero and a nullable
`current_revision_id`. No authored block, public copy, collection, account,
completion record, or review activation state is backfilled. The SQLite custom
add-field operation uses native additive SQL to retain existing cross-table
catalogue triggers; PostgreSQL uses the ordinary Django additive operation.

The frozen PostgreSQL delta is
`scripts/deployment/tests/fixtures/solution-document-schema-delta.json`.
The rehearsal uses the existing pinned PostgreSQL 17.9 Actions database guard.
It seeds legacy private solutions, blocks, active/stopped shared copies,
collections, completion data and subscribers, then compares every previous
column value, existing sequence, trigger/function definition and migration
recorder row. New document/review tables must remain empty, the new policy
sequence unused, and every existing solution must have version zero and no
current revision. The old active application must read its legacy proof and
insert a solution using the durable defaults inside a rolled-back transaction.

Local isolated PostgreSQL discovery establishes the catalog delta and migration
preservation behavior. It is not an attested production-build proof. Deployable
evidence requires the independently checked active revision smoke in CI and
the protected build, bound to the exact active/target SHAs, migration hash,
schema delta hash and original proof-file digest. Discovery output cannot pass
the packaged evidence validator.

## Reader compatibility floor

Applying this schema advances the minimum reader version immediately, before
any author saves a document. This deliberately conservative rule removes the
race between an empty-data check and an in-flight author save. The installed
audit helper checks only PostgreSQL metadata through the existing identity; it
does not read private proofs or public-copy JSON and requires no new table
grants. Missing or malformed audit evidence fails closed.

Both deploy and rollback targets must then have the verified document-reader
capability. The build manifest declares that capability only when the critical
adapter, views, PDF renderer and public shared-content template match the
reviewed hashes in `solution_document_compat.py`. The worker checks the actual
file bytes, directory/release identity, and manifest without executing the
candidate reader to establish compatibility. Changing those critical sources
requires a reviewed capability refresh; the artifact builder refuses a
document release with stale capability hashes.

This guard covers older forward deployments, explicit rollback, and automatic
recovery after activation failure. It runs before any recovery symlink change.
A block-only baseline cannot be restored after the schema floor advances,
even while the new tables remain empty. Such activation failures remain
`recovery_required`; reconcile the existing operation instead of dispatching
another deployment, retry, schema reversal, or rollback.

Prepare and verify a document-aware compatibility artifact before schema
activation. The first schema/reader release must keep
`SOLUTION_DOCUMENT_WRITES_ENABLED=false` in production. Local and test settings
enable document writes for verification. Preserve a verified compatible reader
as the recovery target before separately activating document writes. An old
block-only release is never a recovery target after the schema change. Do not
drop revision/review tables, clear pointers, or reconstruct current documents
from frozen blocks to make an old target eligible.

## Preparation and activation

Use the existing reviewed bootstrap procedure to install the exact new schema
allowance and compatibility guard. Installation changes privileged deployment
authority and requires its separate action-specific authorization. Application
artifacts cannot update that authority. Preserve the target contract, audit
identity, users, permissions, environment/media, SSH restrictions, proxy,
application/scheduler units and protected-environment controls.

After a clean immutable release and full CI exist, disclose the frozen migration
and verified starting/ending catalog fingerprints through the normal production
deployment workflow. The protected build repeats the bounded rehearsal; the
installed worker applies only the reviewed plan under the established lock and
statement timeouts before activating the reader. No direct application shell
or generic migration command substitutes for that allowance.

Complete normal immediate preflight, postflight and short stabilization checks:
release/artifact identity, registry and process state, cache-busted health and
hashed assets, legacy and v2 reading, owner-only document access, PDF/image
handling, unchanged shared copies, and revocation/collection behavior. Use
existing authorized data and read-only checks. Production test-account,
solution or public-link creation needs separate authorization. Do not schedule
delayed monitoring unless requested.

AI processing additionally requires the application feature gate, explicit
policy activation, invited users, configured model/key, verified price limits
and owner-approved budgets, and the independently prepared worker operating
through the existing scheduling procedure. Keep provider calls disabled during
ordinary tests; use the deterministic fake provider. Existing ambiguous review
dispatches must be reconciled through their recorded identifiers and must never
be automatically re-dispatched.
