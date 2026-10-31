# Admin-curated collection schema release

Admin curation requires exactly
`solutions.0008_solutioncollection_kind_and_nullable_owner`, after the already
applied, unchanged collection migration `0007`. Its operations add the `kind`
column with a persistent `personal` database default, allow a null owner, and
add `solution_collection_kind_owner`. The check permits precisely a personal
collection with an owner or an admin-curated collection without an owner.
Existing rows remain personal with their original owners. Curation writes only
collection/container entries; it cannot publish or refresh a source public copy.

## Exact allowance and preservation proof

`scripts/deployment/curated_collections_schema.py` pins the new migration and all
seven previous solution migrations. The original `0007` allowance is unchanged.
The approved pending plan is one migration containing exactly `AddField`,
`AlterField`, and `AddConstraint`; any missing prerequisite or extra pending
migration fails closed.

The normalized catalogue alteration is frozen in
`scripts/deployment/tests/fixtures/curated-collections-schema-delta.json`. Unlike
the earlier two-table addition, this delta records removed and added catalogue
rows. It requires the exact original owner column before replacing only its
nullability, and adds the kind/default and check. The fixture is catalogue
metadata, not deployment preservation evidence.

The PostgreSQL 17.9 rehearsal populates personal collections, active/stopped
shares, entry ordering and anchors, counters, completion records, and unrelated
fixtures before migration. It hashes all prior column values, excluding only the
new kind column, and separately checks that every original collection remains
personal with a non-null owner. All existing entry IDs, positions, anchors,
tokens, snapshots, counters, identity sequences, and unrelated schema/trigger
definitions must remain unchanged. Only the one migration-recorder row and its
sequence advancement may differ.

An older-application subprocess proves that its ORM can still insert a personal
collection while omitting `kind`, and can read the migrated schema. Its fixed
synthetic rollback probe creates site-owned fixtures within that same process,
checks safe empty curated guest rendering, and exercises account deletion.
Deleting an unrelated former curator preserves the container and all entries;
deleting a contributor removes only that contributor's share/entries. All probe
inserts use explicit primary keys. Deferred constraints are forced before
rollback, then fixture hashes and sequences are checked again.

The populated SQLite migration regression also covers a possible table rebuild
and insertion by the historical model.

CI additionally runs real author-update/stop versus publication races on a
separate disposable PostgreSQL 17.9 container. These tests observe actual lock
waits, ordered source-row acquisition, fresh state after waiting, and guest
revocation after serialized publication. Ordinary SQLite runs skip these three
checks; the dedicated CI step executes them against its test-prefixed database.

## Release procedure

This is a separate `backward-compatible-schema` release. A previous completed
collection release does not authorize installation or deployment of this one.
For an authorized release, resolve and record the exact merged revision and
fresh active production baseline. Run exact-main CI with that baseline and
retain the original PostgreSQL 17.9 rehearsal artifact and its byte digest.
Compute the expected fingerprints from the bounded production catalogue audit
and the frozen alteration.

Install this exact reviewed allowance through the supported
[production bootstrap](production-bootstrap.md) installer. It copies the
deployment package, including the dedicated curated module. Preserve the target
contract, audit configuration, forced-command/key restrictions, sudoers,
application/proxy/scheduler unit definitions, accounts, environment/media, and
GitHub protections. Installation must not migrate or restart the application.

Dispatch the protected deployment with the exact schema disclosure,
`migration_class=backward-compatible-schema`, and `skip_ci=false`. The protected
build independently repeats the pinned rehearsal and verifies identical proof
bytes. The installed worker validates exact migration bytes, the complete
pending plan, and starting fingerprints, applies only `0008` with the existing
two-second lock and thirty-second statement bounds, then validates ending
fingerprints before activation. After migration has started, an ambiguous or
failed result remains `recovery_required`; reconcile its original operation/run
ID before another action.

Complete immediate and short stabilization checks in
[production release](production-release.md): active immutable release, registry,
process cgroup, cache-busted health, schema fingerprints, hashed assets, login
and role boundaries, and public contents/anchors. Creation, revocation, deletion,
and race tests use isolated synthetic fixtures; do not create production test
content solely for postflight. Any genuine existing public curated link may be
read without mutation. Delayed monitoring requires a separate explicit request.

## Code recovery

Retain the schema, persistent default, collection data, anchors, and revocation
state on code recovery. Do not reverse the migration or assign curated
collections to a user. Older code has no curated management routes and its
owner/author guard renders curated collections with an empty reading view.
Restoring curation requires a forward application release.
