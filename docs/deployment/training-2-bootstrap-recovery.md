# Training 2.0 bootstrap and staged recovery

The owner explicitly approved the bootstrap/recovery work and deployment on
2026-11-01, retaining the requirement that all starter notes stay unpublished.
This record describes the scoped sequence; it is not standing operational authority.

## Community-first baseline

The owner subsequently ordered Community deployment before Training. Preserve that
order and all Community source, schema, privacy and AI-off controls. Community
includes `pages.0045_community_proof_library`; Training prerequisites therefore use
`pages.0046_prerequisitegraphstate_catalogueprerequisite`. The Training bundle stays
at four migrations and 20 new tables, with 93 historical migration sources.
This ordering is a release gate, not a claim that Community is already deployed. If its actual
data-class release remains ineligible for automatic rollback, establish eligibility
through an ordinary protected `none` release first. Its packaged application,
settings, locks, workflows and static bytes must be identical to the healthy
Community release, with only documentation and expected release identity differing.
Require an empty pending migration plan, unchanged database fingerprints and full
postflight. Do not flip an eligibility flag or add another recovery selector.

This initial qualification has no automatic fallback while its baseline is
ineligible. The strict bridge gate requires the actual active Community baseline
to be rollback-eligible before bridge preparation or activation; a compatible source
checkout or healthy endpoint alone cannot supply eligibility. Keep the operator
available, and reconcile any failure under its exact
operation ID; the approval does not authorize an unspecified database restore or
manual rollback. The Training bridge itself rejects an ineligible baseline.

## Stage 1: establish a real compatible recovery release

The first release contains the shared reader and the exact four future migrations,
but its frozen production settings force the module, contributions and publication
off. The installed worker may defer those migrations only for this byte-verified
bridge, for migration class `none`, without a schema disclosure. It validates the
28 reader files, the exact four migrations and all 93 historical migration sources
after Community 0045.
The bridge's production settings file is frozen in `learning_bridge.py`. Its exact
pending plan is prerequisite 0046, learning 0001/0002 and training 0006; no Community
migration may remain pending or be silently deferred with it.

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

## Evidence for the new baseline

Existing Training PostgreSQL validation reports describe the earlier prerequisite
0045 bundle and 92 historical sources. Keep those reports unchanged as historical
evidence. They cannot qualify the Community-first 0046/93 bundle. A fresh proof,
including full Community preservation, remains pending until the exact qualified
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
