# Dashboard solution forum release

## Status and authority

This runbook specifies preparation and evidence for the two-stage release.
The [2 November 2026 acceptance record](../solution-forum.md#release-acceptance-record--2-november-2026)
records the completed deployments and the limits of their verification.
Application changes follow [Production release](production-release.md). A direct
human deployment request supplies the scoped application-deployment authorization
under the current user policy; resolving its exact SHA does not require another
conversational approval.

The bounded root-owned migration allowance and media-server configuration change
each require their own action-specific authorization. Never install either by
dispatching arbitrary remote shell commands or broadening application deployment
authority. Preserve existing target, identity, secrets, network and environment
controls. No AI, worker, notification or Training activation is part of this work.

## Stage 1: image-aware compatibility baseline

Prepare an independently reviewable code-only artifact against the then-current
production revision. Its manifest must include the image access/URL modules,
access helper, every changed solution-image consumer, the development media deny
route and the relevant tests. Resolve the exact manifest and immutable SHA from
the final reviewed diff; do not ship a guessed subset or include the forum
migration in a `migration_class=none` artifact.

The compatibility artifact must support:

- Authenticated owner/editor and member-published image reads.
- Both old block and continuous-document representations.
- Exact active-share/revision-bound public image reads without snapshot rewrites.
- Per-share image resolution inside personal and curated public collections.
- Existing PDF filesystem reads without expanded PDF permissions.
- No requirement for any forum table merely to read an existing proof image.

Run the ordinary code-only protected build and deploy procedure. Confirm the
image-aware active release before preparing its security configuration cutover.
The existing document-reader floor also freezes changed reader bytes. Its narrow
trusted capability refresh must first recognize the separately reviewed image-only
source set. The prepared source retains the previously accepted document reader
and freezes both the image-only and forum reader sets; it does not treat an
arbitrary future file change as compatible.

Prepare a narrowly scoped proxy rule that denies only raw solution-body image
paths under the verified media prefix. Review the effective server configuration,
including prefix/regex precedence, all relevant virtual hosts and alternate media
origins; normalize and encoded-path probes must not bypass the rule. Validate
configuration before a bounded reload. Do not change unrelated media, static,
TLS, firewall, IAM or secrets settings.

After the approved cutover, anonymously verify raw media denial and working
author-shared images, and verify internal images through approved member access.
The image-aware artifact becomes the minimum recovery baseline. Removing the
proxy protection is not a routine rollback action and requires separate review.

Install the separately reviewed image-reader floor in the root-owned release
registry as `solution-image-reader-required.json`, owned by root and not writable
by group or others, with exactly this JSON:

```json
{"format_version":1,"image_reader_required":true}
```

The trusted worker must contain the reviewed image-reader verifier before this
marker is installed. It checks manifest capability and actual frozen source bytes
for forward deployment and every code recovery path. Malformed, symlinked,
untrusted or disabled markers fail closed. The forum migration additionally
refuses to start without this cutover marker. Installing or removing the marker
is part of the separately authorized proxy/security operation, never an
application self-update.

## Stage 2: exact additive forum schema

The prepared allowance admits only `solutions.0013_solution_forum`, after the
existing `solutions.0012_synthetic_review_prototype` baseline. It creates eight
isolated target, request, assessment, verification, comment, comment-event, vote
and report tables. Existing application records are not backfilled, published,
voted, reviewed or verified by the migration.

The validator, exact migration byte digest, frozen normalized PostgreSQL delta
and preservation rehearsal live in:

- `scripts/deployment/solution_forum_schema.py`
- `scripts/deployment/solution_forum_schema_rehearsal.py`
- `scripts/deployment/tests/fixtures/solution-forum-schema-delta.json`

Use the frozen values from the reviewed source, not values copied from a past
release or this narrative. The normal dispatcher, protected build and trusted
worker must all recognize only this exact allowance. Installing source files in
an application artifact does not update root-owned worker authority.

The authoritative rehearsal requires empty disposable PostgreSQL **17.9**, the
existing exact Actions target guard, disabled/unfunded AI and the verified
image-aware active source. It must prove:

1. Only the eight approved tables and their exact columns, indexes, constraints
   and sequences are added; the existing schema and extensions are preserved.
2. Synthetic prior accounts, problem UUIDs, proofs, authored revisions, shares,
   collections, progress, newsletter rows, triggers and sequence values remain
   unchanged.
3. Only the one expected migration-recorder row is appended.
4. Every new forum table remains empty after applying the schema.
5. The image-aware active application still reads the preserved data and exposes
   the controlled image routes, without changing records/schema during its smoke.

The protected build repeats that proof against the exact release and records its
digest in the attested artifact. A development SQLite run or another PostgreSQL
version may find regressions but cannot satisfy this gate. A frozen expected
schema fixture is not proof that the pinned rehearsal has executed successfully.

## Preflight and deployment

Reconcile current main, the actual active production SHA, migration state and the
image-protection cutover. Unrelated pending migrations must not ride this release.
Obtain a bounded secret-free catalogue snapshot through the established
diagnostic channel; compute expected fingerprints using the exact frozen delta.
Do not export production business rows or invent production fingerprints from CI.

Require green required PR CI and the protected complete release build. Bind the
disclosure to the exact active/release SHAs, migration digest, starting/ending
fingerprints, rehearsal digest and fixed compatibility-command digest. Install
the separately authorized frozen allowance before dispatching the ordinary
protected `backward-compatible-schema` operation.

Record the workflow URL/run ID, exact source SHA, immutable archive digest,
attestation identity, target marker, migration disclosure and durable operation ID.
For cancellation, timeout or ambiguous transport results, reconcile the existing
operation. Do not automatically retry, cancel, reverse a migration or roll back.

## Post-deploy validation and recovery

Compare workflow, artifact, active registry, service cgroup, cache-busted health,
schema fingerprints and representative hashed CSS/JS bytes. With bounded
read-only checks, verify the new reader, old-link redirect, login/approval gates,
existing public pages/collections, image revision checks and raw-media denial.
Inspect only relevant redacted application errors during ten minutes of short
stabilization.

Run the complete publish/vote/comment/request/independent-review/verify/edit
scenario in an isolated synthetic test environment. Production business-record
writes are not implied by deployment approval; an explicitly identified
production fixture would need its own authorization.

Recovery retains all forum tables and audit records and never reopens raw media.
Only the verified image-aware compatibility artifact is an eligible code recovery
target. A schema failure after migration starts remains `recovery_required` until
the existing operation is reconciled. Do not reverse the new migration or erase
reviews, comments, votes or reports.

Release completion requires the synthetic acceptance workflow, all required
source-bound checks, the image privacy cutover, production postflight and short
stabilization. No delayed monitoring or automation is scheduled by this procedure.
