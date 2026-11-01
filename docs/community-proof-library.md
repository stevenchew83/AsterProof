# Community Proof Library — Phase 1

Phase 1 implements private problem sharing and community proof contributions.
The [adopted requirements](plans/2026-11-01-community-proof-library-requirements.md)
remain the roadmap for subsequent phases.

## Submit and share a problem

Post a complete statement, proposed subject, and source/author attribution through
Community problems. Difficulty, method tags, core ideas, rationale, and a solution
outline may be unknown. A numeric difficulty of zero retains its actual meaning;
blank difficulty is displayed as Unknown. Library similarity preflight is still
required, bound to the current content and source index.

New submissions are private to their author and admins. Existing member-visible
posts retain their earlier audience; the migration creates no public publications
or sharing consent. All problems filters statuses only after applying access rules.
For other members, publicly shared problems display the selected public snapshot,
not a new unreviewed edit or the author's private metadata.

Admins use **Publication moderation** to check completeness/safe content,
attribution/permission, and any disclosed competition embargo. Approving the
statement creates no link and does not verify mathematical correctness.

The author then selects **Share & invite solutions**, chooses a public display
name and Private, Unlisted, or Public visibility, previews the exact public copy,
and explicitly confirms sharing. Signed previews expire after 30 minutes and reject
changed content, audiences, authors, versions, or sharing generations.

- Private has no working public link.
- Unlisted permits anyone holding the active link to read, but is excluded from
  discovery and carries noindex/nofollow/noarchive directives.
- Public appears in the public Community proofs directory and is eligible for indexing.
- An active moderation hold or unexpired competition embargo blocks external access.

Copy link and WhatsApp open the user's sharing controls/composer; they send no
message automatically. Stop sharing removes public and nested asset access,
preserves private work, and rotates the link token. A new statement is reviewed and
published explicitly; the previous approved public statement remains stable until
replaced or taken down.

## Solve privately and contribute a proof

The public page leads with **Solve this problem**. Hints, classification details,
proof previews, and proof bodies start collapsed. Guests may reveal published
proofs without creating an attempt; approved account access is required to write
or report. Explicit community solve/report destinations survive sign-in without
changing the application's unrelated login destinations.

The public reading view pairs a compact statement with a private-workspace action,
then optional hints and proofs. Sharing and reporting sit alongside it on desktop
and follow the reading flow on phones. The directory uses full-row problem links.
These surfaces use the compiled `public-community` stylesheet and the existing
public website typography and colors.

The private editor reuses the existing CodeMirror LaTeX editor and safe document
renderer. Saving does not publish a proof or change canonical completion/progress.
Private attempts remain available to their owners after a problem is unshared.
Only separately authored public hints can be revealed; no hint reads the private
outline or starts AI.

After saving, choose **Publish a separate solution**. Preview the selected saved
text and owned images, choose public credit, confirm permission, and submit for
basic publication moderation. Each distinct submission creates an immutable proof revision
associated with the exact statement revision. Several distinct contributions by
one author are allowed; repeated identical submissions reuse the existing copy.
Private saves do not update a submitted or published copy.

Public proofs appear only after approval of the pending contribution. Publication
approval is explicitly labelled independently of mathematical correctness. Withdrawn
proofs require a fresh author submission before any admin can approve them again.
Older-statement proofs remain in a separately labelled historical section. Current
and historical proof bodies paginate independently, ten per page.

PNG, JPEG, and WebP uploads belong to one private attempt. Images are decoded,
size/pixel limited, normalized to PNG without original metadata, and stored as
immutable bytes. Publication copies only referenced, owned assets into the selected
proof revision and verifies their digests. Moderator/owner previews read that
submitted copy, never another learner's private attempt. Every public asset request
rechecks the active problem publication, proof, hold state, and revision ownership.
Public readers invoke no diagram/PDF compiler or paid provider.

## Reporting and moderation

Members can report a problem or published proof for a possible gap, copied content,
abuse, or another concern. Reports and reporter identities are private to admins.
The moderation page lists pending proofs, open reports, and append-only events.
Admins can resolve reports and place or release publication holds with a reason.
Hold controls carry their own version token, so a stale tab cannot clear a newer
hold. A report alone does not make a correctness determination.

Only app admins perform publication moderation in this phase. No trainer/moderator
or trusted-contributor publishing permissions are inferred or expanded. No voting,
Verified badges, Author's picks, step comments, or notifications are added in Phase 1.

## AI and private content

AI review stays disabled. The community AI-request endpoint rejects requests even
if an environment setting is enabled accidentally. Historical AI reports remain
read-only and admin-only. Private outlines, attempts, review notes, and feedback
never enter public snapshots, discovery, page metadata, or public asset responses.
Existing solution-coach configuration and provider credentials are not changed.

## Schema and verification

Migration `pages.0045_community_proof_library` adds separate revisions, publications,
attempts, public contributions, private/public asset copies, moderation events, and
reports. It preserves existing UUIDs, records, outlines, review notes, and trigger
definitions. The legacy audience column is added as true for existing rows, then
defaults to false for new rows; it creates no publication/consent rows.

The migration is classified data-or-non-compatible and is not admitted by the old
0042/0043 deployment allowance. The [separate release procedure](deployment/community-proof-library-release.md)
defines its frozen migration, compatibility, preservation, and recovery checks;
older code does not enforce the new private-post boundary and is not a safe ordinary
rollback target. Historical allowance tests retain the original hash-bound model
fixture and explicitly reject the current model under that old allowance.

Focused coverage lives in `test_proof_models.py`, `test_proof_library.py`,
`test_proof_concurrency.py`, and `users/tests/test_community_handoff.py`. It covers
legacy migration preservation, access/count privacy, preview tampering and expiry
boundaries, immutable copies/assets, moderation, revocation, image syntax, CSRF,
sign-in handoff, and concurrent saves/publication/withdrawal/holds.

Validation performed locally:

- Integrated complete suite: 4,008 passed, 22 skipped; three existing Django URLField warnings.
- Separate PostgreSQL 15.19 run: six real concurrency tests and 39 HTTP/privacy tests passed.
- Django system/migration checks, changed Python lint, and new/changed community
  template lint/format checks passed; existing public-base lint findings are unchanged.
- Browser verification used only synthetic SQLite data on loopback, with both AI
  flags forced off: public solve/reveal, private CodeMirror save, explicit proof
  preview/submission, no auto-publication, math rendering, and phone layout.

The PostgreSQL checks exercise real locks and deferred foreign keys. They are not
a PostgreSQL 17 production migration/backup rehearsal or evidence of deployment.
