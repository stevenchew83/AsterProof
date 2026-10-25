# Reviewed algebra tag cleanup

The first batch contains 76 exact, same-field name mappings and the reviewed
APMO 2010 correction guarded by the shared problem UUID. The packaged plan is
`inspinia/pages/data/algebra_cleanup_review_v1.json`, SHA-256
`b2687717e4497714f624f8ef4c4f887dbc78453fce57c2762280569f7b0d4b60`.

The command changes parsed tags on active primary-algebra records only. Statement
scope uses its own trimmed topic, falling back to the linked problem's topic.
Invalid, corrupt and metadata tags, inactive parents, raw workbook cells,
completion records, shared UUIDs and benchmark scores are preserved. The only
deletion is a redundant parsed-tag row whose fields and sources are retained on
the survivor. Conflicting metadata or source overflow blocks application.

## Code release and activation

Use the normal [production release procedure](deployment/production-release.md)
for code. This introduces no schema migration and performs no cleanup at startup.
The production data operation requires separate maintenance authorization;
deploying code does not authorize it.

Import normalization activates when all three reviewed new benchmark aliases and
all nine corrected shadow aliases have their expected targets. Before activation,
imports retain existing behavior. Partial installation fails closed. Both problem
and statement import paths share normalization with the problem import preview.
Legacy global cleanup and layer-backfill commands skip active algebra after
activation. Alias searches retain old names without creating extra coverage facts.

## Generate a review

Run in the intended application's established environment:

```sh
python manage.py cleanup_algebra_tags --report /approved/output/algebra-review.json
```

Default mode is dry-run. On PostgreSQL it uses a repeatable-read, read-only
transaction with a 15-second statement timeout. It reads parsed tags, parent
identity/scope, benchmark definitions/aliases and aggregate alias usage across
topics. It never calls model saves, creates catalog state or marks caches stale.
The report records exact before/after values, conflicts, source fingerprint,
database target and affected catalog statements. Its output path must be new.
It also records separate guard fingerprints for benchmark definitions, parent
identities and excluded parsed-tag rows, for direct postflight comparison.

Review the report and compute its SHA-256. Review the exact database target,
counts, merge survivor and provenance, alias IDs and targets, exclusions,
benchmark binding checks, cross-topic usage and mirror discrepancies. Any
conflict is a stop condition. A changed source requires a fresh report and review.

`--snapshot-input` supports offline replay of previously authorized captures. It
cannot be combined with `--apply`. An offline report lacking the database target
cannot pass the live application target check.

Keep production report files on the server unless their transfer is explicitly
authorized. A server-side planner can return aggregate counts and hashes to
compare with an existing reviewed report without exporting production rows.

## Apply the exact approved report

This is a separate production database mutation. Execute only after explicit
authorization for the reviewed report, database target, deployed code revision,
maintenance window and effects. Use the existing approved maintenance channel;
the normal deployment workflow's migration gate must remain intact.

```sh
python manage.py cleanup_algebra_tags --apply \
  --review-report /approved/output/algebra-review.json \
  --expected-report-sha256 REVIEWED_FILE_SHA256 \
  --audit-directory /approved/output/algebra-operation-UNIQUE
```

The audit parent directory must exist and the operation directory must be new.
The command creates it with mode 0700 and audit files with mode 0600, fsyncs the
before/after report and prepared receipt before any tag or alias writes, and
applies all database changes in one transaction. The report file hash, database
target and freshly calculated report must match the reviewed artifact.

PostgreSQL application takes an exclusive advisory transaction lock shared with
the import paths, then NOWAIT row locks on affected parents and their tags and on
all benchmark definitions and existing aliases. An active import, unavailable
lock or changed before-value aborts application. Lock timeout is one second and
statement timeout is 30 seconds. This is a short maintenance operation; benchmark
editing must be paused for its duration. Imports use the shared lock for the
activation handover. Dry-run acquires no write/advisory locks.

The same transaction marks the technique progress catalog stale for the affected
statements. No rating values are updated and no automatic catalog rebuild runs.

## Verify and recover

After a confirmed commit, run another dry-run. Require zero tag actions, zero
alias actions and zero conflicts; verify that activation is complete, the shared
UUIDs and benchmark definitions/scores still match the before-image, excluded
rows are unchanged, and each merged source survives on its recorded survivor.
Require the three `identity.guard_fingerprints` values to match the approved
before-image. A mismatch requires investigation even if the planner is idempotent.
For each audit action, fetch its parsed-tag row by recorded source and primary
key and compare every `TAG_FIELDS` value with `after`; a `merge_remove` row must
be absent and its `merge_into_id` survivor must match its recorded after-image.
Check aliases by `(kind, alias_key)` against every recorded after-image. These
bounded SELECT checks supply exact row verification in addition to idempotence.

Rebuild the derived catalog through the established catalog command after the
data verification, under the same maintenance authorization if expressly
included. Catalog rebuild is a separate database write. Verify old-name search
and canonical coverage labels afterward.

```sh
python manage.py recompute_technique_progress_catalog --if-stale --catalog-only
```

Use a full rebuild to clear the global stale flag. `--catalog-only` excludes the
independent duplicate-report cache refresh from this maintenance operation.

A `failed_before_commit` receipt records a rolled-back database operation. A
`prepared` receipt or an error saying commit was attempted requires read-only
reconciliation against the existing operation's audit and database. Do not retry
or restore until the outcome is established. A receipt filesystem failure after
commit must never be treated as a database rollback.

The audit preserves the deleted row's original ID, parent, fields and survivor
before/after values, and all alias before-images. A restoration must first prove
the current rows still match these after-images and account for subsequent
imports, added aliases and catalog state. Restoring deleted rows/aliases is a new
reviewed database mutation requiring separate authorization. There is no
automatic rollback command, and reverting application code alone does not
restore taxonomy data.
