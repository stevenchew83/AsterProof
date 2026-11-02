# Dashboard solution forum

The solution forum is an authenticated dashboard feature. A member publication
is readable by approved signed-in members; it is not a public website
publication. The author remains responsible for explicitly creating or updating
an independent public-share copy.

## Read and discuss

**Open solution** opens `/solutions/entries/<solution_id>/` in the dashboard.
The reader presents the author, publication status, assessment summary, problem,
proof, independent trainer assessments, and discussion. Existing problem-workspace
links containing `?solution=<id>` redirect to this reader after access checks.
Drafts remain available to their authors and admins. Trainers gain no general
access to other members' drafts. Removing member publication hides the reader,
discussion, assessments and internal images from other members immediately.

Approved members can upvote another author's published solution once and remove
their vote later. Votes measure usefulness, not correctness. **Top voted** sorts
published solutions within a problem by votes, publication time and identity;
**Newest** provides chronological browsing. A verification badge does not add
votes. The author's personal solution stays separate from the ranked list.

Comments support sanitized Markdown, mathematics and one level of replies.
Members can revise or remove their own comments and privately report a comment.
Admins can hide or restore comments with a reason and inspect retained history.
Removed or hidden comments retain a neutral placeholder where replies need it.
Reporter identities and moderation history are not visible to ordinary members.

## Assessment and verification

Publication, mathematical assessment and admin verification are separate:

| Information | Meaning |
|---|---|
| Published to members | Approved account access permits reading |
| Trainer assessment | One trainer's mathematical opinion on the exact saved proof and statement |
| Green Verified badge | An admin explicitly verified that exact target as correct |

Trainer verdicts are Correct, Minor gaps, Partially correct, Incorrect and Unable
to determine. Minor gaps does not qualify as complete correctness. Trainers
publish independent assessments. Revising one assessment retains its history and
does not replace another trainer's opinion. Differing substantive verdicts are
shown as disagreement; Unable to determine is an abstention.

Only an admin can verify, adjudicate or revoke verification. An explanation is
required. An admin may inspect a proof directly without waiting for a trainer.
Self-assessment, self-verification and self-upvotes are not allowed.

Verification belongs to a saved proof and statement, not permanently to a
solution identity. A new saved version or changed statement requires review.
A new conflicting trainer assessment outside the admin's adjudication basis
also requires renewed review. Existing opinions remain visible after an admin
resolves their disagreement. Votes and ordinary comments do not change this
decision.

The forum stores only snapshots captured while a proof was member-published.
It never exposes the author's complete private revision history. Review forms
reject stale target versions rather than attaching decisions to changed proofs.

## Sharing and image privacy

Public copies retain their existing author confirmation, snapshot, token and
revocation rules. Forum comments, votes, reviews, reports and verification
decisions do not enter those copies. Editing the internal proof does not update
an existing public copy.

Solution images use permission-checked routes. Internal routes enforce the
solution audience and image ownership. Public-share routes enforce active
sharing, the exact sharing revision, ownership and inclusion in the shared copy.
Images for a collection are checked separately for every included share.
Direct access to the solution-image media prefix must also be blocked by the
local media server and production proxy before image privacy is considered
released. See [the release procedure](deployment/solution-forum-release.md).

## Acceptance checklist

Application behavior and the role matrix were verified with isolated synthetic
data. Release gates and read-only production checks are recorded separately
below. Production acceptance did not submit votes, comments, assessments or
verification decisions.

- [x] Anonymous and unapproved reader/image access is denied.
- [x] Member-published proofs open in the dashboard; drafts preserve existing access.
- [x] Legacy block proofs and continuous documents render without GET-created revisions.
- [x] Old selected-solution links resolve through authorized redirects.
- [x] Upvotes are unique, reversible, private by voter identity, and rank accurately.
- [x] Independent assessments, disagreement and abstention display correctly.
- [x] Only admins can verify; stale or changed targets cannot retain verification.
- [x] Discussion, replies, ownership, reports and moderation preserve access and history.
- [x] Internal images and shared-copy images enforce their separate audiences.
- [x] Direct media image access is blocked without breaking existing public copies.
- [x] Progress, Training points, AI and notification settings remain unchanged.
- [x] PostgreSQL 15.19 concurrency and schema-preservation checks pass locally.
- [x] The pinned PostgreSQL 17.9 protected-release rehearsal passes.
- [x] Desktop/mobile and light/dark theme checks pass using synthetic content.
- [x] Semantic controls and visible keyboard focus were inspected in the browser.
- [x] Tab navigation shows visible focus; Enter opens and closes the problem
  statement, trainer assessment form and additional admin decisions in the live
  Chrome reader.
- [x] Protected release and immediate production verification evidence is recorded.

### Release acceptance record — 2 November 2026

- The image compatibility release, [PR #414](https://github.com/stevenchew83/AsterProof/pull/414),
  deployed through [protected run 41401380312](https://github.com/stevenchew83/AsterProof/actions/runs/41401380312).
  The installed proxy rule denied all 27 external and 27 host-local normalized
  and encoded raw-image requests. A controlled public image still returned 200;
  obsolete share revisions and unissued tokens were denied.
- The forum and design release, [PR #415](https://github.com/stevenchew83/AsterProof/pull/415),
  deployed commit `d3b8b99745dcf5b1db4a1f84ebff6918ae7302ff` through
  [protected run 41405964397](https://github.com/stevenchew83/AsterProof/actions/runs/41405964397).
  Its protected quality suite passed with **4,807 passed / 31 skipped**, and
  **49 PostgreSQL forum/image checks passed**. Both the
  [merged-commit CI run](https://github.com/stevenchew83/AsterProof/actions/runs/41404275431)
  and protected build passed PostgreSQL 17.9 preservation rehearsals for the
  additive `solutions.0013_solution_forum` migration. Production schema evidence
  matched the frozen release disclosure.
- Read-only postflight verified the reader and legacy redirect, anonymous login
  gates, trainer/admin queues, protected internal images, existing public shares,
  compiled assets, and desktop/phone layouts in light and dark themes. The
  07:41:17–07:51:17 UTC stabilization window had no application errors or proxy
  5xx responses. Nonadmin/pending-role scenarios and write workflows remained
  synthetic checks; no production curated-collection fixture existed.
- The keyboard follow-up used tab-scoped native input in the existing approved
  admin Chrome session. Actual focus movement and disclosure `open` states
  confirmed Tab navigation and Enter activation, replacing the earlier
  automation limitation. All disclosures were restored closed and the temporary
  QA tab was closed. Shift+Tab attempts were inconclusive and are not claimed as
  verified; a full screen-reader audit was outside this check's scope.
