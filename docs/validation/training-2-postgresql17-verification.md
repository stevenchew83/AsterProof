# Training 2.0 PostgreSQL 17.9 verification

## Local candidate evidence — 2026-11-01

The Training 2.0 migration and application checks ran against an isolated
PostgreSQL **17.9** server, not SQLite or the existing PostgreSQL 15 service.
The runtime was compiled with the existing Apple compiler from the
[official PostgreSQL source](https://ftp.postgresql.org/pub/source/v17.9/).
The downloaded archive matched its
[official SHA-256 checksum](https://ftp.postgresql.org/pub/source/v17.9/postgresql-17.9.tar.bz2.sha256):

    3b9a62538a8da151e807a3ddb1198e8605f2032544d78f403ae883d27ecf1ee4

Core and contrib binaries were installed only in a task-specific temporary
directory. No system package, Homebrew dependency or existing service changed.
The test server listened only on localhost at a separate high port. Before
creating synthetic databases, the wrapper matched its version, address, port
and cluster identifier to the newly initialized temporary cluster.

## Results

- **193 passed, no skips** in the final PostgreSQL learning, Training, prerequisite,
  announcement and public-integration suite, after moving the real manuscripts
  into ignored private storage and replacing public test packs with synthetic fixtures.
- **115 passed** in the local allowance, worker, capability and dispatcher checks.
- Both competing-publication and stale-tab autosave races passed with real
  PostgreSQL row locks.
- The asset cleanup/reference race passed. Its initial fixture placed private
  files beneath the global test media directory; the storage guard correctly
  rejected that setup. The test now supplies separate private and public roots.
- The migration rehearsal passed twice in fresh synthetic databases. The final
  run also compared all existing public helper-function definitions.
- The previous application source, archived from
  c0c7ff57829a32a33bb4a4351ff151c70055ff94, passed its read-only smoke against
  the upgraded schema.
- Existing schema objects, historical records, sequences, migration history,
  triggers and helper functions remained unchanged. This includes synthetic
  Training completions, points, submissions, feedback, private solutions, fixed
  public solution copies and newsletter subscriber state.
- All new shared-learning/pathway tables remained empty after schema installation.
  The empty schema established reader capability floor 1; the previous reader
  remains ineligible for activation or recovery.

The additive bundle is pages.0045, learning.0001, learning.0002 and training.0006.
Its migration-file bundle SHA-256 is:

    e2a7fe56af416b0deddd8446fe5ec04709169e389c12c668880433ecf01fdce7

The normalized, actually observed PostgreSQL catalogue delta SHA-256 is:

    351ffd6792fc2dfbcd3f670cd78576391f7ebaeced08d7ff317bd3ad19603c24

## Evidence boundaries

The initial reports deliberately record source_sha as null: this verification
preceded the feature commit. A separate identity record binds the exact migration
and reader bytes, official source checksum, build configuration and local target.
It does not pretend the uncommitted changes were the baseline commit.
Release evidence must bind the eventual immutable target SHA through a fresh
rehearsal or the existing CI build process.

The raw local reports, delta, identity records and JUnit output are retained in
/private/tmp/asterproof-pg17-verify.6h4PpS, using the schema-precommit-2 and
broad-private-precommit-3 prefixes. This is a source-built macOS PostgreSQL 17.9 result;
it is not a claim that the Linux container or production ran these checks.

Only synthetic fixture data and local email/cache/storage were used. The starter
notes remain unpublished. These results do not establish production installation,
real contributor permission, educational acceptance or approval to publish notes.

The worker also rejects schema installation before DDL unless its actual existing
recovery baseline is both eligible and a byte-verified Learning reader. An ordinary
previous release does not become compatible by updating a manifest label.
The concrete compatible-recovery requirement remains an operational No-Go until
that real artifact and supported recovery path have been prepared.
