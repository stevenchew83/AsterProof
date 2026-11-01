# Offline mathematical evaluation release

This release adds the coach evidence workspace while leaving student AI review
and real-provider execution disabled. It creates no worker, provider credential,
funded policy, appointment, approved dataset, or activation authorization.
The separately approved authority installation and deployment completed on
2026-11-01. This historical record grants no new production operation or AI
activation. See [the readiness evidence](../solutions/ai-solution-checking-readiness.md)
for PRs, exact release, checks and limitations.

## Exact migration allowance

Only `solutions.0010_offline_evaluation_contract` is admitted. It contains exactly
19 `CreateModel` operations, 131 columns, 62 constraints and 65 indexes. All new
tables were empty at release acceptance. The existing document-compatible migration
0009 must already be applied. No data backfill, existing-table change, or unrelated
pending migration is admitted.

- Migration SHA-256: `9fee1f590a8cdde9df9d30c201a49caea20a5c31efe2f4b0aa7c92171d4844a8`.
- Normalized PostgreSQL 17.9 delta fingerprint: `e34c2715374cba7a9aab59c473d3308c4dcd656896509c76165972cf568842d0`.
- Frozen delta: `scripts/deployment/tests/fixtures/solution-evaluation-schema-delta.json`.
- Validator: `scripts/deployment/solution_evaluation_schema.py`.
- Release rehearsal: `scripts/deployment/solution_evaluation_schema_rehearsal.py`.

The validator freezes every prior solution migration, the exact model operation
names and order, the compatibility command, and the packaged proof. The request's
OIDC audience binds its starting/expected fingerprints, active/target SHAs and
proof digest. The worker checks starting state again immediately before migrating
and verifies ending state before activation. Two-second lock and thirty-second
statement timeouts remain. Both solution and statement AI flags must be disabled
for the plan check and application smoke. No release check invokes a provider.

CI and the protected release build rehearse on fresh PostgreSQL 17.9 using
synthetic users, statements, progress, blocks, an immutable current document,
active/revoked public shares, collections, counters and newsletter data. All prior
rows, columns, constraints, indexes, triggers, sequences and foreign keys must be
preserved; only one migration-recorder row may be added. The verified active code
then reads the preserved block/current document and runs normal application and
catalogue checks. The proof rejects any mutation by that smoke.

The class is `backward-compatible-schema`. Code recovery retains the evidence,
private assets, consent and independent accounting tables. It never reverses the
migration or erases evidence. Foreign keys may reject legacy deletion of referenced
objects; successful old-code read compatibility does not authorize arbitrary data
changes under recovered code. A later release that enables evidence use must review
its own recovery and lifecycle implications.

## Completed operation and procedure for future releases

The reviewed allowance source was `8b09bf548aa96c857b2b74a24ac06633d929c585`.
The successful application artifact was
`c0c7ff57829a32a33bb4a4351ff151c70055ff94`, deployment
[41295842073](https://github.com/stevenchew83/AsterProof/actions/runs/41295842073).
The original failed run did not activate an artifact; the corrected deployment
had its own explicit approval. Installation preserved target/audit configuration,
marker, operation unit, sudoers and forced-command public key byte-for-byte.
Immediate postflight confirmed the exact additive migration and disabled AI.

The following sequence records the schema-release procedure and provides a
reference for separately reviewed future schema releases. Migration 0010 is already
applied: do not reinstall its allowance or add its delta again for an ordinary code
release. Resolve the current state and applicable release class first. Past
authorization and success do not authorize another dispatch or authority change.

1. Merge the reviewed PR under normal protections; bind CI and release evidence to
   the exact resulting SHA and then-current verified active revision. Do not reuse
   a branch rehearsal as the final merged release proof.
2. Under separate explicit authority-installation authorization, use the existing
   [bootstrap procedure](production-bootstrap.md) to install this exact trusted
   allowance. Preserve the target, identities, forced-command transport, service,
   environment, media, audit configuration and all existing allowances. Application
   deployment cannot install or enlarge its own root-owned authority.
3. Obtain a bounded, secret-free catalogue snapshot using the established diagnostic
   path. Build starting/expected state, schema and migration fingerprints with
   `solution_evaluation_schema.expected_catalog_audit(start, frozen_delta)`. Starting
   production fingerprints are deliberately not invented or copied from CI.
4. Form the exact `validate_disclosure` contract: format version, active/target SHA,
   migration and migration hash, starting/expected fingerprint triples, PostgreSQL
   rehearsal file digest and `COMPATIBILITY_SMOKE_SHA256`. Validate it through the
   normal dispatch validator. No configuration or authority change is implied.
5. Only after an explicit deployment request, use the protected manual Production
   deploy workflow with `backward-compatible-schema`, complete CI and the frozen
   disclosure. Preserve disabled AI flags, offline execution mode, zero budgets and
   inactive workers. Reconcile an ambiguous operation by its existing ID; do not
   automatically retry, cancel or roll back.
6. Complete immediate health/release/schema/static and short stabilization checks.
   Verify editor save, autocomplete, managed image paste and ordinary preview,
   scoped coach access, private asset denial and disabled AI delivery. Synthetic
   write checks require their own approved environment; read-only production
   checks must not create learner data. Schedule no delayed monitoring.

Dataset rights and coach judgments remain provisional. Model and pedagogical
readiness remain untested. Deployment of this offline foundation establishes
none of those claims and would not activate AI.
