# Community Proof Library production release preparation

## Current status

This is a local proposal for the separately bounded
`community-proof-library-maintenance-v1` allowance. The PostgreSQL delta hash is
deliberately the fail-closed all-zero sentinel until real pinned PostgreSQL 17.9
discovery is reviewed. No discovery report is accepted as deployment proof.

Application implementation, schema classification, a passing SQLite suite, or this
document does not establish production authority installation or deployment. The
existing 0042/0043 community allowance remains frozen and cannot admit this release.

## Exact input and baseline

| Migration | SHA-256 | Role |
| --- | --- | --- |
| pages.0045_community_proof_library | 63892e34819c93bbba63820cd7ba397afb8a1408d53b016d2063ad212c11be32 | The only permitted pending migration; data-or-non-compatible |
| pages.0044_learning_page_activity | a55e4fe4f34729e7db3f1c4bf67a1deaadeb39f799958b900e2c5d840e9559e2 | Already applied prerequisite |
| solutions.0010_offline_evaluation_contract | 9fee1f590a8cdde9df9d30c201a49caea20a5c31efe2f4b0aa7c92171d4844a8 | Already applied prerequisite |

The prerequisite community migrations 0042/0043 also retain their existing frozen
hashes. The release's active source must contain the same prior migration files as
the candidate. An extra migration, missing prerequisite, changed model operation,
changed constraint identity, backward plan, or modified frozen bytes is No-Go.

0045 adds these nine tables:

- pages_communityattempt
- pages_communityprivateasset
- pages_communityproblemrevision
- pages_communitysolution
- pages_communitycontentreport
- pages_communitysolutionrevision
- pages_communitysolutionasset
- pages_moderationevent
- pages_problempublication

It appends only these four columns to pages_communityproblem, in this order:
embargo_until, legacy_member_visible, public_hint, and solution_known. MOHS becomes
nullable. The blank-form changes to core_ideas, rationale, and topic_tags do not
authorize unrelated catalog changes.

Existing community rows retain every original column, identifier, review note,
private outline, and review history. Their new legacy_member_visible value is true;
embargo_until is NULL, public_hint is empty, and solution_known is false. New ORM
submissions default to legacy_member_visible=false and unknown difficulty. No
publications, consent records, attempts, proofs, assets, reports, moderation events,
or statement revisions are backfilled. The initial publication sequence is unused.

The catalog delta is a normalized object with exactly **add** and **remove**
snapshots. Only the nine ordinary public tables, their columns/constraints/indexes,
the four appended CommunityProblem columns, and the nullable-only MOHS column
replacement are admitted. Existing constraints/indexes, extensions, roles,
memberships, ACLs, functions, and triggers are preserved.

## Disposable discovery, then frozen proof

Use only the established Actions PostgreSQL service:
PostgreSQL 17.9, server_version_num 170009, database
asterproof_schema_rehearsal, user postgres, loopback port 5432. The existing
rehearsal guard requires GITHUB_ACTIONS=true and exactly
postgres://postgres@127.0.0.1:5432/asterproof_schema_rehearsal. It rejects an occupied
database, another server version, SQLite, and alternate connection targets.

The first draft-PR discovery uses this command shape inside that disposable CI job:

```sh
python -m scripts.deployment.community_proof_schema_rehearsal \
  --active-source "$RUNNER_TEMP/active-community-proof" \
  --active-sha "$ACTIVE_SHA" \
  --release-sha "$RELEASE_SHA" \
  --discover-delta \
  --output "$RUNNER_TEMP/community-proof-discovery.json" \
  --delta-output "$RUNNER_TEMP/community-proof-schema-delta.json"
```

The active source is the immutable prerequisite baseline, extracted through the
normal reviewed CI source path. The rehearsal migrates the empty fixture to that
baseline, seeds synthetic existing records, and then executes only the literal
0045 plan. It checks:

1. Every original row's column-value hash and every existing sequence value.
2. Existing community audience and exact new-field defaults.
3. One new Django migration-recorder row and one recorder sequence increment.
4. Existing trigger/function definitions, combined behavior fingerprint, roles,
   memberships, ACLs, default privileges, and extensions.
5. All nine new tables empty, with no public/consent backfill.
6. Disabled and unfunded community/solution AI review policies and both AI flags false.
7. A genuine old-source **read-only** compatibility smoke, with PostgreSQL enforcing
   a read-only transaction. It never exercises old-code writes after the migration.
8. Actual candidate owner/peer/admin/public GET views in rolled-back probes, using
   existing users and RequestFactory to avoid login/session/monitoring sequence writes.
   Synthetic publication rows use explicit fixture identities.
9. The trusted preservation capture before and after compatibility/probe checks.

Discovery writes the actual catalog delta plus a report labelled
**preparation-only-discovery**, with deployment_proof=false. The discovery output
cannot pass the packaged-evidence validator and must never be supplied as release
approval evidence.

Review the actual delta; freeze it at
scripts/deployment/tests/fixtures/community-proof-schema-delta.json and freeze
SHA-256(canonical_json(normalized_delta)) in community_proof_schema.DELTA_SHA256.
Then remove discovery-only CI wiring and repeat the rehearsal **without**
--discover-delta or --delta-output. Only this complete, frozen execution emits the
normal deployment-schema-evidence.json with every required preservation flag true.
Do not substitute a synthetic unit-test delta or locally invented PostgreSQL proof.

The three state/schema/migration fingerprints must change. The behavior fingerprint
must remain exactly
5d0c68e538f93cc53c865d7e06b18042a5c4e240651f04fb4b8399fa6fd3d698.
This differs deliberately from the original community allowance, which installed
new behavior. No similarity-index initialization or catalog refresh belongs here.

## Reviewed production path

After both prerequisite releases are already applied, prepare a data-class
disclosure binding the exact active/target SHAs, input hashes, beginning/ending
fingerprints, frozen PostgreSQL proof digest, and unchanged recovery policy.

The separate trusted-authority installation, if authorized, uses the existing
reviewed bootstrap path. The application must not install or broaden its own
authority. It must not change database roles, credentials, IAM, network controls,
system packages, service configuration, or AI activation as an installation effect.

The protected deployment retains attestation, target identity, full preflight,
drain, encrypted RPO0 backup, complete isolated restore verification, bounded
migration, full preserved-record proof, and activation/postflight checks. The
runtime plan checks both AI flags and disabled/unfunded policies before migration;
the post-migration check repeats them. No index or catalogue initialization is run.

The full record-preservation check projects only the original community columns.
It permits exactly the new recorder row/counter increment and verifies that every
new content table remains empty. The existing recovery manifest and backup scope
remain unchanged.

## Recovery and completion

This is a data-class release. An old reader's compatibility smoke does not certify
old-code writes: the new privacy fields and publication state make ordinary
old-code rollback unsafe. Keep rollback_eligible=false. Failures after drain are
recovery_required; reconcile the existing run/operation before any separately
authorized recovery, retry, cancellation, or rollback.

After activation, require the workflow result, durable operation, active registry,
public cache-busted health, archive digest, expected state/schema fingerprint,
unchanged behavior fingerprint, stable service process set, static bytes, and
short stabilization evidence to agree. Verify new privacy/publication behavior
outside production with synthetic content; do not create public production test
problems or enable a provider merely for validation.

Use immediate preflight/postflight and short stabilization. Delayed monitoring is
optional and requires an explicit request under the project's deployment policy.
