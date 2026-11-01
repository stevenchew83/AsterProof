# Shared learning release and recovery

The local implementation serves all four subjects and Foundations. Inequalities
is the first editorial pilot. Installing software, enabling contribution intake,
publishing reviewed content and qualifying a teaching package are separate steps.
This document records implemented safeguards; it grants no operational authority.

## Current evidence

The exact additive bundle is:

- pages.0045_prerequisitegraphstate_catalogueprerequisite
- learning.0001_initial
- learning.0002_contentdraft_is_archived
- training.0006_learningpath_learningpathrevision_learningpathitem_and_more

The learning_schema.py deployment module binds these migration files to their real
SHA-256 digests. A local SQLite rehearsal upgrades the preceding schema and checks
every historical table, existing schema object and sequence. Synthetic fixtures
cover the four subjects and Foundations, old lecture IDs, completions, points,
submissions and feedback, private solution content, public solution snapshots and
newsletter subscriber status. The new content tables must remain empty.

Run the bounded rehearsal using a new directory and files:

    DJANGO_READ_DOT_ENV_FILE=False python -m scripts.deployment.learning_schema_rehearsal \
      --sqlite /private/tmp/learning-rehearsal/learning.sqlite3 \
      --output /private/tmp/learning-rehearsal/evidence.json

Create the parent directory first. Existing database and output files are rejected.
The command sets SQLite and the local email backend explicitly, ignores .env,
disables learning feature flags and uses synthetic data only.

PostgreSQL 17.9 verification now also passes on an isolated source-built runtime.
See [the PostgreSQL verification record](../validation/training-2-postgresql17-verification.md).
The actual normalized delta is frozen in `tests/fixtures/learning-schema-delta.json`;
the four migration files and all 94 historical migration sources are hash-bound.
The strict allowance validates the exact pending plan, release identities,
preservation proof, current catalogue fingerprints and required learning reader.
Precommit evidence remains nondeployable until repeated for a real immutable SHA.
CI and the protected release build repeat the proof on the existing pinned Linux
PostgreSQL 17.9 container. This local evidence does not install production authority.

The pre-DDL worker check also requires a real, rollback-eligible compatible baseline
with verified learning-reader bytes. An ordinary previous reader cannot qualify.
The currently observed production baseline has no such reader; installation of
schema support alone does not satisfy this recovery prerequisite.

## Durable reader floor

The presence of any shared-learning content, publication, legacy-bridge or pathway
table establishes reader capability version 1, including partial installation and
empty tables. The audit reads only to_regclass metadata through the existing
identity-bound, time-bounded read-only helper. It never reads private notes.
Withdrawal, feature flags and emptying a catalogue cannot lower this floor.
Dropping learning tables is not a supported recovery procedure.

The learning_compat.py module binds the capability to reviewed source bytes.
Release build, archive preparation and activation verify the manifest and actual
guarded files. The worker checks the floor before accepting the candidate and
immediately before activation. Explicit rollback and automatic activation recovery
apply the same check before changing release links. The existing global operation
lock serializes schema operations and release selection. A missing/malformed floor
audit or changed reader bytes fails closed.

The trusted worker, migration-audit helper, release builder and preparation helper
must receive the reviewed capability together before any schema installation.
An application artifact cannot install that authority. Pre-floor legacy readers
may remain available during additive rehearsal but cannot become a recovery target
after the floor exists. Prepare a verified compatible recovery release first.

## Private starter manuscripts

The GitHub repository is public. The 103 unreviewed starter manuscripts and their
14 exercise/hint pathway templates are retained only in the ignored local
`.learning-content-packs/` directory, with private directory/file permissions.
They are not part of Git, release archives, public CI artifacts or migrations.
Public source contains the canonical coverage manifest and generic synthetic
fixtures only. Set `LEARNING_CONTENT_PACK_ROOT` to an independently provisioned
private directory to make packs available to the configured publisher; production
defaults to an empty path. Importing still creates private drafts, never publication.
The content-publication switch remains disabled until Steven reviews the notes.

## Activation gates

Keep production module, contribution and publication switches off until the
associated configuration, code and content are reviewed. Activation requires:

- The configured publisher is Steven's verified existing user primary key; no
  administrator or superuser fallback.
- A persistent private asset root outside public media/static/release trees,
  correct ownership, limits and paired database/file recovery.
- Approved contributor-agreement copy/version and the applicable contributor
  authorization process. Authors retain rights; a checked permission is bound to
  the exact immutable revision. Public credit is optional.
- The pinned migration delta, historical preservation, previous-reader evidence,
  PostgreSQL concurrency and compatible recovery artifact are verified.
- A bounded reviewed mapping/cutover set, selected approved revisions and intended
  Training/public channels. Old public content cannot bypass the shared publisher.
- Clipboard save/reopen/read/publish, actual native browser behavior, private/public
  access, withdrawal, accessible mathematics/diagrams and representative learner
  tasks pass. More catalogue rows do not establish teaching coverage.

No local rehearsal publishes content, awards points, sends announcements, enrolls
subscribers or rewrites legacy sources. Publication always uses a reviewed immutable
revision and an explicit owner action. Legacy newsletter discovery excludes reviewed
cutovers without disabling unrelated campaigns.

## Recovery

Recover database revisions and private files as one reviewed set. Verify every
published file exists and matches its recorded size/hash before reopening readers.
Retained revision references protect historical assets; deleting a private draft
cannot erase a published diagram. Missing or mismatched published assets fail
recovery acceptance. Do not reverse migrations, select a legacy reader or copy
mutable old body fields over a published revision to recover availability.

A publisher can propose restoration of an earlier submitted, permission-bound
revision. It retains the original source, image references and contributor grant,
creates a new review proposal against the current publication version, and requires
normal approval and a separate publication action. Never-submitted private
checkpoints are excluded from publisher restoration history.

Any future deployment or recovery action still needs the authorization required
by the current task and enforced operational safeguards. This local work includes
no production migration, deployment, feature activation or public manuscript release.
