# Community Proof Library: adopted requirements

Date: 2026-11-01

Status: adopted product direction. [Phase 1 is implemented](../community-proof-library.md)
and verified. Phases 2–5 remain future work.
The original release remains documented in [Community problems](../community-problems.md).

## Purpose and adopted decisions

Help learners discover, compare, improve, and validate mathematical proofs while
preserving the opportunity to solve a problem independently.

- Adopt Private, Unlisted, and Public publication visibility, with explicit author consent.
- Require basic publication moderation before a new contributor's content becomes
  available to other learners, including through an unlisted link.
- Adopt Option B: one current preferred-explanation vote per member per problem.
  Members can change or remove that choice. Votes express comparative preference.
- Display Community Favorite, Author's pick, and Verified as separate indicators.
  Multiple approaches can receive independent human verification.
- Separate private attempts, problem publications, and published community proofs.
- Support problem authors who do not know a solution or the difficulty.
- Reuse the existing editor, rendering, and public-snapshot patterns while keeping
  community problems separate from the canonical problem library.
- Keep AI review disabled. Future AI assistance is advisory, separately authorized,
  private by default, and cannot publish content or confer Verified status.
- Defer reputation points, leaderboards, prizes, and automatic trust promotion.

This replaces the earlier suggestions to share unreviewed problems immediately
and to allow several helpful upvotes per member on one problem.

## Repository findings that shape implementation

| Current behavior | Required change or boundary |
| --- | --- |
| [Community listing and detail views](../../inspinia/pages/community_views.py) require sign-in; All problems reads every submission. | Filter lists, counts, and detail access by the caller's actual audience permissions before applying the status tab. |
| [The current form](../../inspinia/pages/community_forms.py) requires numeric MOHS, tags, core ideas, and a difficulty rationale. | Allow an explicit unknown difficulty and unavailable solution-dependent metadata. Unknown is not MOHS zero or an invented technique. |
| Community problem edits update mutable fields and increment a version counter. | Add immutable statement revisions before allowing external publication or solutions. Existing human-review snapshots remain history. |
| [ProblemSolution and SolutionRevision](../../inspinia/solutions/models.py) require an archive ProblemSolveRecord. | Reuse editor components without creating dummy archive records or changing existing solution ownership. Community attempts and proofs need their own explicit problem association. |
| [Public solution sharing](../solutions/public-solution-sharing.md) already separates private saves from explicitly shared snapshots and supports revocation. | Reuse these boundaries for community content, including explicit preview, public-field allowlists, and current-state checks on every public endpoint. |
| [Canonical catalogue identities](../../inspinia/pages/catalogue_models.py) and [reviewed assignments](../problem-concept-assignments.md) already exist. | Reference canonical areas/concepts through community-specific associations; preserve archive coverage and progress semantics. |

## Problem submission and publication

### Submission without a known solution

The author supplies a title, complete statement, proposed subject, and attribution
or composition context. The statement must include its assumptions, domains, and
exact task. Existing similarity preflight remains mandatory before submission.
Similarity results remain advisory and do not establish originality or equivalence.

The author can select **I do not know a solution yet**. Core ideas, solution outline,
pitfalls, technique tags, difficulty rationale, and numeric difficulty may be absent.
Show unknown difficulty explicitly. A provisional subject or classification can be
corrected during review without forcing the author to invent an answer.

New submissions remain accessible only to their author and authorized publication
reviewers until the intended publication is approved and explicitly enabled. An
unknown answer is not a reason to reject an otherwise suitable problem. Publication
approval does not certify that a problem is solvable, original, or correctly rated.

### Three publication visibility levels

Visibility, moderation status, and mathematical verification are separate state.
Approval alone never changes visibility or creates a working share link.

| Visibility | Reader access | Discovery | Preconditions |
| --- | --- | --- | --- |
| Private, the default | Author; authorized reviewers when submitted for review | Absent from other users' lists, counts, previews, and search | No public link; private attempts retain their own narrower access rules |
| Unlisted | Anyone possessing the active link, including guests | Excluded from discovery, sitemap, and search indexing | Exact statement revision approved; author reviewed the public preview and explicitly enabled sharing |
| Public | Anyone, including guests | Discoverable in community browsing and eligible for indexing | Same publication approval and consent; explicit Public selection |

An unlisted link can be forwarded; it is not access-controlled private storage.
Requests for disallowed content, assets, and inactive share links return a neutral
unavailable response without exposing private titles, authors, counts, or excerpts.

The public preview includes only selected statement content, attribution, public
display credit, and approved metadata. It excludes private attempts, solution
outlines, teacher feedback, internal moderation notes, and AI assessments. Never
use account email as public credit. Hints require their own explicit publication.

After moderation, the author chooses **Share & invite solutions**, previews the
exact content, then enables Unlisted or Public. Provide Copy link, WhatsApp composer,
visibility controls, and Stop sharing. No sharing action sends a message automatically.
Stopping sharing or returning to Private immediately removes public access and
discovery, including nested solutions and assets on that problem's public surface.
It preserves contributors' private work and moderation history. Re-enabling an
unlisted publication rotates its token; old links remain inactive.

### Moderation and existing data

The launch review covers statement completeness, safe content, attribution/source,
the contributor's permission to publish, and any disclosed active-competition
embargo. Unresolved concerns hold publication. Embargo expiry never substitutes
for the other checks or author consent. Known embargoes prevent external problem,
hint, and solution access until release is permitted.

Basic reporting, hold, takedown, and an audit trail ship before anonymous access.
Publication review is distinct from checking a proof's correctness. Apply basic
content moderation to new public proof contributions as well. Reports are private;
public report controls lead members to the reporting flow and guests to sign-in.
Admins can suspend external access independently of the author's selected visibility.

Admins perform publication moderation at launch. Trusted contributors initially
receive priority review rather than bypassing it. Any later publishing capability
must be explicitly granted, scoped, auditable, and revocable. Account approval,
trainer/moderator roles, votes, and tenure do not silently grant this authority.

Preserve existing member-visible community submissions and their identities under
their existing audience contract. They receive no active public publication, no
new external access, and no inferred consent from the old signed-in sharing checkbox.
Their existing review notes must not become public. New private submissions do not
inherit this legacy member visibility. The signed-in Admin reviewed / All problems
tabs remain status filters over authorized rows; All never bypasses privacy or a
moderation hold. Legacy migration must be rehearsed and disclosed before rollout.

## Solve first, then compare proofs

The main public action is **Solve this problem**. Guests sign in before creating a
private attempt. Saving an attempt never publishes a solution, changes a vote, or
records a canonical library completion.

Show the solution count with **Reveal community solutions**. Initially collapse
proof bodies, preview summaries, method labels, concept hints, and discussion text
that could spoil an approach. Exclude proof excerpts from problem-page social cards.
Area/concept detail and author hints are explicitly revealed by the learner; request
hints exposes only deliberately published hints while AI is disabled. Do not impose
a timer or require a completed attempt before revealing proofs.

Each learner can save drafts, request an explicitly published hint, and return to
compare their approach. Teacher comments and any future private assessments stay
with the private attempt. Publishing is a separate preview-and-confirm operation
that copies only the selected authored proof into a community contribution. Proof
authors choose public credit and can withdraw their contribution. Problem authors
cannot publish or edit another person's attempt or proof.

Published assets follow the same visibility and moderation rules as their parent
snapshot. Bind the selected image/attachment bytes to that published revision;
replacing an asset cannot silently change a voted-on proof. Private upload URLs
must not become public merely because the editor's text references them.

Allow distinct methods by the same contributor without copying private feedback.
Use the existing LaTeX editor/rendering components and Inspinia shell. Public reads
consume approved snapshots rather than compiling untrusted source or reading drafts.

## Comparison, preference, and verification

### One preferred explanation

Use **My preferred explanation** and **Change my vote**. Eligible approved, signed-in
members have one current choice per community problem, enforced by a database unique
constraint on `(member, community_problem)`. They may remove it. No self-voting.
Optional reasons are Most rigorous, Most elegant, or Easiest to understand; these
are voter opinions and do not create verification badges or extra weighted votes.

Only current, published, accessible, non-suspended solution revisions for the same
statement revision are eligible. Validate ownership relationships and eligibility
again inside the vote transaction. Changing a vote atomically replaces the choice;
repeated requests cannot create extra votes. Retain CSRF and bounded write limits.

Community Favorite identifies the highest positive current count. Ties are displayed
as ties; zero votes produce no favorite. Keep method exploration and Newest available
alongside preference sorting and a Verified filter. Compare selected proofs against
the same statement version; do not blend votes from different questions or methods
into a mathematical correctness score.

### Separate human judgments

- **Author's pick:** the problem author's declared preference, independent of votes.
  If it is their own proof, show that authorship explicitly.
- **Verified:** an independent human reviewer checked the exact published proof
  against the exact statement revision. Show reviewer credit and review date;
  retain the decision and rationale. Admins verify at launch, excluding their own
  proofs. Later qualified-reviewer permissions require an explicit grant.
- **Publication approved:** basic suitability for publication, without a correctness
  claim. This does not confer Verified status on a statement or proof.

Multiple solutions can be Verified. A confirmed gap can withdraw verification;
preserve the prior review and display the current status. A reported concern alone
does not automatically establish an error or remove votes. Staff can place a proof
on hold during investigation, excluding it from the current comparison and tally.

### Statement and proof revisions

Save immutable statement and proof revisions from Phase 1. Each public proof names
the statement revision it answers. Publishing an edited statement requires a fresh
review and explicit update of the public version. The existing approved version
stays stable while a replacement is reviewed, unless withdrawn or placed on hold.

After a statement replacement, prior proofs remain historical with a clear older-
statement label; they do not count toward current-version favorites or verification.
Contributors explicitly review and publish an updated proof for the new statement.

For the first voting release, any published proof-body change creates a new public
revision and requires vote reconfirmation and renewed verification. This avoids an
unreliable automatic distinction between cosmetic and mathematical edits. Title or
display-metadata edits do not replace the proof body or alter its mathematical claim.
Preserve old preferences, verification, and author picks as history; never transfer
or silently reactivate them after an edit, rollback, or withdrawal/republication.
The one current vote per member/problem remains the rule across all revisions.

Step comments later bind to an immutable proof revision and stable step/selection
anchor. Edited or removed steps leave comments attached to their original location,
marked as belonging to an older revision. Questions, suspected gaps, corrections,
resolutions, and abuse reports have distinct visible purposes.

## Areas, concepts, and editorial reuse

Reference existing `CatalogueArea` and `CatalogueConcept` identities and valid
memberships, with community-specific associations. Distinguish suggested links from
reviewed, evidence-supported links. A newly submitted problem can remain awaiting
classification rather than pretending a solution method is known. Every published
problem must expose its classification state; Phase 4 adds complete discovery and
review tools. Do not count provisional links as accepted coverage.

Published, voluntarily contributed proof evidence can support classification;
private attempts and teacher/AI feedback cannot establish public concept coverage.
Do not create archive `CatalogueProblem`, `ProblemSolveRecord`, or canonical statement
rows merely to attach community concepts, votes, solutions, or progress.

Editorial promotion to `LibraryConcept` / `LibraryLecture` content is a separate
reviewed action. Record permission from each proof's contributor for the selected
revision, intended reuse, and attribution. A public link, problem-author consent,
or curation into a collection does not imply permission to adapt another person's
proof into lecture notes. Respect third-party source restrictions. Track source
revision, editorial changes, contributor credit, permission, and revocation status;
withdrawal prevents new reuse and places affected controlled live excerpts on hold
for editorial review. Existing downloaded copies cannot be recalled through a
website control.

## Data ownership and proposed entities

These are logical responsibilities. Implement only the entities needed by the
current phase; do not rewrite existing archive or training data to fit this model.

| Entity | Responsibility | First needed |
| --- | --- | --- |
| `CommunityProblem` | Existing contribution identity and submission workflow; remains separate from the main library | Existing |
| `CommunityProblemRevision` | Immutable statement and public-metadata candidate; private submission fields excluded | Phase 1 |
| `ProblemPublication` | Selected statement revision, audience, share generation/token, explicit consent, and publication hold state | Phase 1 |
| `CommunityAttempt` | Owner's private working document and restricted review context; distinct from a public proof | Phase 1 |
| `CommunitySolution` | Contribution identity, publication lifecycle, and current public revision, associated with one community problem and contributor | Phase 1 |
| `CommunitySolutionRevision` | Immutable authored proof copies, bound asset digests, source digest, and statement revision | Phase 1 |
| `ModerationEvent` / content report | Append-only decisions and private reporting with actor, reason, subject, revision, and time | Phase 1 |
| `SolutionVote` | One current preference per member/problem, exact selected public proof revision, optional reason, and invalidation; preference changes retain separate history | Phase 2 |
| Proof verification | Independent revision-bound human decision and withdrawal history | Phase 2 |
| Step discussion / author's pick | Anchored questions, gaps, corrections, and declared author preference | Phase 3 |
| Community concept assignment / editorial permission | Canonical concept links, evidence, reuse consent, credit, and provenance | Phase 4 |

The existing `solutions.SolutionRevision` is archive-owned. Use a distinct
`CommunitySolutionRevision` model name while reusing editor/rendering services;
do not redirect that existing foreign key or duplicate a student's private attempt
as a public row automatically. Any broader shared document abstraction needs its
own justified implementation design and compatibility review.

## Revised implementation sequence

| Phase | Deliverable | Release gate |
| --- | --- | --- |
| 1 — Publication and solving | Three visibility levels, explicit public snapshots, moderation before sharing, reporting/takedown, private attempt editor, published community proofs, immutable statement/proof revisions, solve-before-reveal UI | Privacy/access matrix, legacy preservation, and all public endpoint checks pass; AI stays off |
| 2 — Comparison and validation | One preferred vote per problem, optional reasons, side-by-side comparison, Community Favorite, independent Verified labels, revision invalidation | Uniqueness, concurrent voting, revision changes, self-vote/self-verification, holds and withdrawals pass |
| 3 — Discussion and improvement | Step comments, questions/gaps/corrections, visible revision comparison, Author's pick, consented notifications | Private review context stays separate; stale anchors and notification audiences are tested |
| 4 — Structured knowledge | Area/concept discovery and reviewed mapping, editorial promotion with contributor permission and credit | Canonical identity/evidence rules and reuse-consent checks pass; no archive/progress pollution |
| 5 — Optional AI assistance | Private educational feedback and proof-gap/comparison suggestions | Separate implementation, financial/activation approval, and evaluation; no automatic correctness or publication |

Moderation/reporting and immutable storage move into Phase 1 because later public
access, voting, and verification depend on them. Phase 3 adds the full history and
discussion experience; it does not introduce immutable storage for the first time.

## Acceptance scenarios for implementation

1. An author without a solution submits a complete statement with unknown difficulty
   and unavailable method tags, and receives no fabricated MOHS or technique values.
2. Before approval and explicit sharing, guests and unrelated members cannot discover
   a new private problem through lists, counts, IDs, previews, nested URLs, or assets.
3. Approved Private content has no working public link. Approved Unlisted content
   works through its current link but stays out of discovery and indexing. Approved
   Public content is discoverable. An embargo or moderation hold blocks external access.
4. Existing member-visible posts retain their original audience and UUIDs, with zero
   automatic public publications or inferred public consent.
5. Sharing a problem or proof exposes only the reviewed public snapshot. Attempts,
   private outlines, teacher comments, AI reports, and internal moderation notes remain
   absent from HTML, metadata, JSON, media, exports, and anonymous responses.
6. Saving a private attempt does not publish content, send notifications, start AI,
   or change canonical completion/progress. A guest can reveal proofs without being
   forced to create an attempt; sign-in is required only for protected contributions.
7. Hidden solution previews, methods, concept hints, and discussions are revealed
   deliberately; author hints never read the private outline implicitly.
8. Concurrent preference changes leave at most one current vote per member/problem.
   Cross-problem, self, stale, hidden, and suspended-proof targets are rejected.
9. Published body/statement changes invalidate current endorsements appropriately;
   old counts and verification remain historical and cannot silently return on re-share.
10. Two independent methods may both be Verified. Author's pick and Community Favorite
    never create or inherit human verification. Reviewers cannot verify their own proofs.
11. Reporting, hold, withdrawal, token rotation, and Stop sharing preserve private
    work/history and block stale public access, including nested content and assets.
12. Area/concept links use canonical identities and supported evidence; unknown or
    suggested mappings do not become accepted global coverage or archive progress.
13. Editorial publication rejects absent/revoked contributor permission or a mismatched
    source revision, while retaining attribution and private review boundaries.
14. All phases preserve existing library solutions, training submissions, account
    roles, and AI configuration; new public access is limited to reviewed routes.

Implementation will require new schema and access-control changes. Deliver the
phases through the existing project verification and release procedures.
