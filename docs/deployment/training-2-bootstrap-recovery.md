# Training 2.0 bootstrap and staged recovery

The owner explicitly approved the bootstrap/recovery work and deployment on
2026-11-01, retaining the requirement that all starter notes stay unpublished.
This record describes the scoped sequence; it is not standing operational authority.

## Assessment → Community → Training baseline

The coordinated owner order is Assessment, then Community, then Training.
Assessment PR #398 (`ae895563`) adds `solutions.0011_problem_evaluation_packages`
and `solutions.0012_synthetic_review_prototype`; both must be applied before
Training. Preserve Assessment and Community source, schema, privacy and AI-off
controls. This order grants no AI activation, provider use, funded policy or access.
Community includes `pages.0045_community_proof_library`; Training prerequisites use
`pages.0046_prerequisitegraphstate_catalogueprerequisite`. The Training bundle stays
at four migrations and 20 new tables, with 95 historical migration sources.
This ordering is a release gate, not a claim that Community is already deployed.
If its actual data-class release remains ineligible for automatic rollback, establish
eligibility
through an ordinary protected `none` release first. Its packaged application,
settings, locks, workflows and static bytes must be identical to the healthy
Community release, with only documentation and expected release identity differing.
Require an empty pending migration plan, unchanged database fingerprints and full
postflight. Do not flip an eligibility flag or add another recovery selector.

This initial qualification has no automatic fallback while its baseline is
ineligible. The strict bridge gate requires the actual active Community baseline
to be rollback-eligible before bridge preparation or activation; a compatible source
checkout or healthy endpoint alone cannot supply eligibility. Keep the operator
available, and reconcile any failure under its exact operation ID; the approval does not authorize an unspecified database restore or
manual rollback. The Training bridge itself rejects an ineligible baseline.

## Stage 1: establish a real compatible recovery release

The first release contains the shared reader and the exact four future migrations,
but its frozen production settings force the module, contributions and publication
off. The installed worker may defer those migrations only for this byte-verified
bridge, for migration class `none`, without a schema disclosure. It validates the
28 reader files, the exact four migrations and all 95 historical migration sources
after Assessment 0011/0012 and Community 0045.
The bridge's production settings file is frozen in `learning_bridge.py`. Its exact
pending plan is prerequisite 0046, learning 0001/0002 and training 0006; no Assessment
or Community migration may remain pending or be silently deferred with it.

Before activation, the candidate runs as the application account with PostgreSQL
transactions forced read-only and bounded timeouts. It must use production
settings, have all three learning flags false, observe no learning schema floor,
and report exactly the four pending migrations and their operation types. No
migration is executed, recorded or faked. Existing database fingerprints must match
before and after. Every other candidate retains ordinary `migrate --check`.

Normal protected GitHub activation, process-bound health, static checks and short
stabilization qualify this actual release as the recovery baseline. Probe public
home/library/search, anonymous assets and authenticated legacy Training while the
new tables are absent. A working `/healthz/` alone is insufficient. A malformed
bridge, extra pending migration, enabled flag, missing source or changed fingerprint
fails before activation. An already-present floor never uses the deferral exception.

## Stage 2: apply the reviewed schema

A separate successor commit removes the bridge settings override while preserving
the exact compatible reader files. The migration disclosure identifies the four
migrations deliberately deferred by the active bridge even though their files were
already delivered. The database's real pending plan and frozen PostgreSQL delta
remain authoritative; an empty Git migration diff does not mean an empty DB plan.

The existing pre-DDL gate still requires the actual eligible baseline's manifest
and guarded files to verify as a compatible reader. Build and attestation repeat
the exact PostgreSQL rehearsal. Starting and expected fingerprints bind the actual
production target. Apply only the four frozen migrations, retain empty new content
tables, verify the ending audit and activate through the protected workflow.
The actual active bridge must remain rollback-eligible and pass its verified
manifest, guarded-file and process-bound checks before schema application.
Automatic and explicit recovery retain the reader floor. Do not relabel an old
manifest, invent a recovery target, drop tables, or bypass a required check.

## PostgreSQL restore comparison

The Training identity constraint `learning_document_canonical_identity` has one
observed PostgreSQL 17.9 dump/restore representation difference: its array-wide
`varchar[]` to `text[]` cast is distributed over the three literal elements.
The complete OR expression, its null predicates and its permitted document kinds
are unchanged. The recovery comparison recognizes only that exact full definition
for the named public-table CHECK, including its constraint type. It preserves
every other definition and object identity for strict comparison.

A local PostgreSQL 17.9 schema-only dump/restore checked all 119 new constraints,
including 24 CHECKs. This was the sole additional Training mismatch; the two
Assessment CHECK differences are handled by the preceding recovery fix.
Regression coverage rejects changed names, schemas, tables, types, literals,
operators and null predicates. This schema-only proof does not establish record
preservation; the populated migration rehearsal remains a separate required check.
No migration bytes or production schema fingerprints are changed by this comparison.
The historical catalogue rehearsal excludes later Teaching dependencies from its
initial baseline, then prepares the full current schema for encrypted and isolated
restore verification. The new Training CHECK therefore participates in the Linux
recovery checks rather than being omitted by an older baseline target.

## Evidence for the new baseline

Existing Training PostgreSQL validation reports describe the earlier prerequisite
0045 bundle and 92 historical sources. Keep those reports unchanged as historical
evidence. Any executed 93-source baseline reports remain historical too. None
qualifies the Assessment-and-Community 0046/95 bundle. A fresh proof, including
full Assessment and Community preservation, remains pending until the exact qualified
baseline and bridge/successor source identities are known and release-bound. The
frozen delta and packaged evidence must then match that actual rehearsal.

## Bootstrap and activation boundaries

Use the established separately staged root-owned Git checkout and the existing
`bootstrap.install_authority` procedure at the merged, verified SHA. Preserve the
target contract, audit identity, deployment key and restrictions, sudoers, systemd
security configuration, environment, database fingerprints, active release and
application PID. Verify all protected hashes and the installed authority afterward.
Installation reloads systemd; it does not restart the app or install schema.

Enable the module only after schema and recovery verification. Authoring also
requires persistent private assets, the configured existing Steven account and the
reviewed rights-retained contributor agreement. Keep `LEARNING_PUBLICATION_ENABLED`
false and `LEARNING_CONTENT_PACK_ROOT` empty. No starter manuscripts are shipped,
imported or published by either release. No lecture announcements are sent. The 103 private originals and their local
review ZIP remain outside Git; their source bytes are unchanged by this release
ordering and migration renumbering.

Complete immediate checks and short stabilization for each activation. No delayed
monitoring is scheduled. Retain command/run IDs, exact SHAs, artifact digests,
preflight/postflight evidence and any limits in the local release packet.

## Combined-candidate local verification

The populated PostgreSQL 17.9 rehearsal against archived combined previous source
`c479355eb4d94fe0b938dc292613de3b2384725b` preserved all Assessment and Community
fixtures, sequences, schema objects and routines. The exact four Training migrations
still add 20 empty tables with normalized delta
`351ffd6792fc2dfbcd3f670cd78576391f7ebaeced08d7ff317bd3ad19603c24`.
The frozen production bridge passed 29 HTTP/privacy probes both before and after
the synthetic upgrade. All Learning, synthetic-prototype and AI-review flags stayed
off; no provider was dispatched. The first reports deliberately use
`source_sha=null` because they preceded the integration commit. This local evidence
does not establish installed authority, a production baseline or release acceptance;
the final source and actual deployed baselines must still be bound and verified.
