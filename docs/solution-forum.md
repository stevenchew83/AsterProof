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

## Local acceptance checklist

Checked items below were verified with synthetic local/test data. Production
cutover and the pinned PostgreSQL 17.9 release gate remain separate.

- [x] Anonymous and unapproved reader/image access is denied.
- [x] Member-published proofs open in the dashboard; drafts preserve existing access.
- [x] Legacy block proofs and continuous documents render without GET-created revisions.
- [x] Old selected-solution links resolve through authorized redirects.
- [x] Upvotes are unique, reversible, private by voter identity, and rank accurately.
- [x] Independent assessments, disagreement and abstention display correctly.
- [x] Only admins can verify; stale or changed targets cannot retain verification.
- [x] Discussion, replies, ownership, reports and moderation preserve access and history.
- [x] Internal images and shared-copy images enforce their separate audiences.
- [ ] Direct media image access is blocked without breaking existing public copies.
- [x] Progress, Training points, AI and notification settings remain unchanged.
- [x] PostgreSQL 15.19 concurrency and schema-preservation checks pass locally.
- [ ] The pinned PostgreSQL 17.9 protected-release rehearsal passes.
- [x] Desktop/mobile and light/dark theme checks pass using synthetic content.
- [x] Semantic controls and visible keyboard focus were inspected in the browser.
- [ ] Native Tab/Enter activation: the available browser automation did not deliver
  native default keyboard actions, so this acceptance check remains unverified.
- [ ] Protected release and immediate production verification evidence is recorded.

This is an implementation and operator checklist. Unchecked items are not claims
of completion or production readiness.
