# Shared learning release and recovery

The repository implements Training 2.0 for all four subjects and Foundations,
with Inequalities as the first editorial pilot. The 2 November 2026 production
release deployed `fd2bb2bc737004652d4e72d4b44f1b80170cc67d`. The starter manuscripts
remained private and unpublished at release verification.
[Production release record](https://github.com/stevenchew83/AsterProof/actions/runs/41392266006)

Runtime configuration controls feature enablement. Contribution intake has a
separate switch. Content publication requires editorial approval of the exact
revision and a separate publication action. Teaching-package qualification is
also a separate step.

This runbook grants no operational authority. For operational actions, follow
the authorization and approval rules in the
[production release procedure](production-release.md).

## Current bundle and historical evidence

The exact additive bundle is:

- pages.0046_prerequisitegraphstate_catalogueprerequisite
- learning.0001_initial
- learning.0002_contentdraft_is_archived
- training.0006_learningpath_learningpathrevision_learningpathitem_and_more

The coordinated order is Assessment → Community → Training. Assessment PR #398
(`ae895563`) includes `solutions.0011_problem_evaluation_packages` and
`solutions.0012_synthetic_review_prototype`; both must be applied before Training.
Community follows with `pages.0045_community_proof_library`. Training
then adds exactly these four migrations and 20 new tables. Its allowance must bind
the renumbered migration files and all 95 historical migration sources, preserving
Assessment and Community schema, records, visibility and AI-off controls. This
ordering enables no AI execution, provider use, funded policy or access grant.
Confirm the Community production baseline and its qualification for the release
being prepared. See the [Phase 1 release record](../community-proof-library.md)
for the historical Community deployment.

The learning_schema.py deployment module binds the accepted migration files to their
real SHA-256 digests. A local SQLite rehearsal upgrades the preceding schema and checks
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

Historical PostgreSQL 17.9 verification passed for the earlier bundle, where the
Training prerequisite migration was numbered 0045 and the prior-source count was 92.
See [the historical PostgreSQL verification record](../validation/training-2-postgresql17-verification.md).
Those reports retain their original identifiers and proof claims; they do not
qualify the new Assessment-and-Community baseline or the renumbered 0046 bundle.
Earlier 93-source baseline reports likewise remain historical evidence; their
executed identifiers and proof claims are not rewritten as 95-source proof.

For this baseline, bind the actual Assessment-and-Community-qualified source
and Training bridge/successor identities to a fresh PostgreSQL 17.9 rehearsal.
Before dispatch, verify its exact delta, all 95 historical sources, Assessment and
Community preservation, release identities, and compatible reader. CI and the
protected release build must repeat the proof on the pinned Linux PostgreSQL 17.9
container. Production authority installation remains a separate operation.

The pre-DDL worker check also requires a real, rollback-eligible compatible baseline
with verified learning-reader bytes. An ordinary previous reader cannot qualify.
A production baseline without that verified reader cannot qualify; installation
of schema support alone does not satisfy this recovery prerequisite.

The approved [Assessment/Community qualification and two-stage bootstrap/recovery sequence](training-2-bootstrap-recovery.md)
establishes that baseline through a real no-DDL bridge activation before the schema
release. It does not waive the pre-DDL recovery check or migration validation.

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
A private local review ZIP and its SHA-256 index retain byte-identical originals
and exact Markdown copies. That archive is outside Git and has not been uploaded
or imported; renumbering the software migrations changes no manuscript source.

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
