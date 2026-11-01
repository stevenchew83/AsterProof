---
date: 2026-11-01
topic: training-lecture-library
---

# AsterProof Training 2.0 requirements and architectural direction

## Problem Frame

AsterProof needs a mathematical knowledge catalogue, reusable teaching content,
and curated curricula. These serve different purposes. A catalogue of 1,109
concepts is not a teaching sequence or a requirement to write 1,109 lectures.
Students should be able to follow a suitable pathway or explore mathematical
ideas, while contributors develop explanations that Steven reviews for release.

This document adopts the architectural and educational redesign supplied on
1 November 2026. The confirmed policies are **users propose edits; Steven alone
approves publication**, and **authors retain their rights and grant AsterProof
permission to publish**. Following Steven's scope clarification on 1 November 2026,
the design and implementation plan cover the **whole module: all four topics and
Foundations**, with Inequalities as the first pilot and staged milestones for all
remaining areas. These documents do not execute implementation, deployment, production
data migration, account changes, external messages or release of actual content.
Pilot qualification precedes expansion; the other topics are committed planning
scope rather than an optional future proposal.

## Architecture Adopted

Three independent layers share stable identities:

| Layer | Responsibility | Existing foundation |
| --- | --- | --- |
| Mathematical knowledge | Subjects, areas, concepts, aliases, semantic relationships, curated prerequisites | `pages.Catalogue*` remains authoritative |
| Teaching content | Overviews, explanations, lectures, technique guides, worked examples, proofs and exercise references | Shared versioned documents; adapt existing editorial and Training content gradually |
| Learning pathways | Audience, objectives, ordered activities, practice, hints and learner activity | Evolve Training without replacing historical completion authority |

Training and the public library are reading experiences built on these layers.
A pathway may add sequencing, hints, and practice around a document. Its approved
body and assets remain the same wherever that document is published.

Foundations remains a first-class cross-topic learning pathway covering proof
writing, induction, parity, extremal reasoning, and other shared methods. It does
not become a fifth catalogue subject without a separate demonstrated need.

### Logical Content Model

The following are responsibilities, not a mandatory one-table-per-name schema.
Detailed Django models and migration boundaries belong in implementation planning.

| Logical entity | Required responsibility |
| --- | --- |
| ContentDocument | Stable identity and content type, independent of one author, problem, topic, or pathway |
| Private working draft | Author-owned autosaved workspace with a known base revision |
| ContentRevision | Immutable checkpoint of source, format, title, authorship, approved metadata, concept associations, asset references and rights information |
| ContentConceptLink | Multiple canonical concept associations, with primary and supporting roles; an area overview can instead have an explicit area association |
| ContributionProposal | Contributor, immutable submitted revision, base revision, feedback and review decisions |
| ContentPublication | One current shared published revision and explicit Training/public channel visibility; channels cannot select different revisions of the same document |
| ContentAsset | Managed file identity, provenance, access, revision references and retention rules; captions, alternative text and credits are revision-bound |
| LearningPath / LearningPathItem | Curated curriculum and activities referencing reusable documents and existing problem identities |
| ContentIssue | Bounded mathematical-error report or classification suggestion routed for review, without a rewritten document |

An approved review is distinct from a publication event. An ordinary save updates
only a private working draft; a checkpoint or submission creates an immutable
revision. Restoring an old revision creates a new draft/checkpoint, rather than
editing history or switching public content automatically. Public author credit
is separate from private audit authorship.

## Requirements

Existing R1–R14 identifiers are retained and refined. R15–R25 capture the adopted
architectural, educational, and pilot additions.

**Knowledge and discovery**

- R1. Reuse the canonical Topic → Area → Concept catalogue for Algebra,
  Combinatorics, Geometry, and Number Theory. Preserve IDs, scoped aliases,
  redirects, narrower/related relationships, and cross-topic memberships. A
  document can teach multiple concepts without copies. Named variants that
  already have separate canonical IDs, such as weighted AM-GM, retain them.
- R2. Provide **Explore** for the complete directory and **Learn** for curated
  pathways. Explore lists every existing area and concept internally, including
  those without notes, and searches canonical names and aliases. Offer role,
  level, lecture-availability and prerequisite filters only from explicit data;
  missing classifications remain unknown rather than inferred. Empty concepts
  offer a contribution entry point without generating placeholder lectures.
- R3. Steven can edit area/concept introductions and teaching documents, including
  titles, summaries, content and lecture arrangement, from the reading page.
  Contributors can use Suggest improvement there. Editorial edits cannot rename,
  merge, or remap canonical concepts. Distinguish Start a lecture, Correct this
  version, Improve explanation, and Report a mathematical error.

**Authoring and review**

- R4. Extract shared mathematical editor utilities from the solution editor for
  completion, preview, undo, text/LaTeX paste and validated clipboard images.
  Teaching documents initially use **Markdown with LaTeX**, with a format/version
  recorded on each revision. Existing solutions remain LaTeX-first and keep their
  current save, share and PDF behaviour. Reusing the editor does not reuse
  problem-solution ownership or the current upload endpoint unchanged. Treat
  source and metadata as untrusted in author previews, revision comparisons,
  review pages and public reading. Preserve HTML/URL sanitisation and resolve
  images only through validated managed-asset references; image support cannot
  enable arbitrary HTML, scripts, unsafe URLs or unapproved remote asset loading.
  Arbitrary rich-HTML/Word formatting conversion remains outside the pilot.
- R5. Users with existing approved workspace access can author private drafts and
  propose revisions. Autosave exposes pending, saved and failed states and
  preserves unsaved work on failure. Explicit checkpoints preserve history.
  Authors cannot edit another user's draft. In the pilot, a submitted proposal
  and its review comments are accessible only to its author and Steven.
- R6. Use Draft → Submitted → Changes requested, Declined, or Approved, with
  publication recorded separately. Submitted revisions are immutable. Editing
  an active submission returns the proposal to Draft and supersedes its pending
  review; previous submissions remain in history. Steven can compare changes,
  request revision, decline with a reason, or revise a proposal in an attributable
  new checkpoint. Any changed version needs approval of that exact version.
- R7. Only Steven can approve, publish, replace or withdraw shared content across the
  whole module. Trainer, staff and administrator labels confer no new publication or
  private-review rights. Trainers may propose pathway content through the same
  review boundary. Steven's own edits also need an explicit publication action;
  approve-and-publish may be one reviewed action with separate audit facts.
  Legacy mathematical notes remain readable during transition, but their old
  authoring/admin routes cannot bypass the same review/publication boundary.
- R8. Bind proposals and saves to their base revision and edit version. A newer
  publication or concurrent edit must cause a visible conflict, preserve the work,
  and require deliberate reconciliation and renewed review. Publication binds the
  exact source, metadata, assets, credits and rights approval. Unfinished uploads
  prevent submission/publication; upload or save failures never erase writing.

**Publication and privacy**

- R9. Maintain one authoritative current published revision per document. New
  drafts and approvals alone do not change it. Training visibility and public
  visibility are explicit channel choices controlled by Steven. For a public
  document, replacement updates the common revision in both channels after an
  explicit preview of that effect. Pathway context may differ; the document body
  and approved assets may not. Historical reading events retain their revision
  provenance without automatically making old revisions publicly accessible.
- R10. Link the public homepage to useful published library content. Preserve
  existing public URLs or provide deliberate redirects when their structure
  changes. Release approved parent navigation and metadata intentionally; do not
  create thin indexable concept pages merely to mirror the catalogue. Withdrawn
  content leaves public reading, search and sitemaps; application caches and asset
  access must respect withdrawal. External copies and caches cannot be recalled.
- R11. Exclude private drafts, review discussions, student solutions, trainer
  feedback, account details and personal progress from public responses, search,
  exports and direct media delivery. Publishing references to practice problems
  does not publish their private solutions or feedback. Public author credit is
  opt-in, with a chosen display credit or no personal credit; do not copy account
  names automatically. Preserve private authorship for review and provenance.

**Continuity and access**

- R12. Preserve materials, submissions, comments, points, levels, completion
  records, problem UUIDs and published links. Keep existing Foundations and
  unmatched legacy material accessible. Audit duplicate, missing and ambiguous
  catalogue links before conversion; map only verified relationships. No
  automatic public release or unverified identity backfill is permitted.
- R13. Keep reading completion, practice activity and concept proficiency distinct.
  Preserve current completion and points semantics without relabelling points or
  reading as mastery. Drafting, reviewing or publishing notes awards no learning
  points and never marks a problem solved. A new proficiency score, mastery claim
  or AI assessment system is outside the pilot.
- R14. Retain the current authenticated dashboard and public-site shells. Support
  mobile and desktop reading, keyboard navigation, source/preview switching,
  accessible mathematical text, and captions/alternative text for meaningful
  diagrams. Provide My drafts and Steven's review queue, with clear empty,
  saving, upload-failure, stale-version, awaiting-review, approved-unpublished,
  published and withdrawn states. Do not replace mathematical notation with
  screenshots as the normal authoring format.

**Educational and content architecture**

- R15. Keep knowledge, teaching documents and learning pathways independent.
  A concept may have several explanations for different audiences, and a lecture
  may cover several concepts or serve several pathways. Do not require a note per
  concept, force free-standing examples into separate documents, or treat the
  catalogue's display order as curriculum.
- R16. New canonical area/concept landing pages require their corresponding
  canonical identity. Represent exceptional standalone editorial material with
  an explicit type rather than an unexplained null identity. Existing nullable
  links remain reviewable during migration; do not force guessed associations.
- R17. Add explicit curator-approved **pedagogical prerequisite** edges between
  canonical concepts, separately from narrower and related edges. Reject self
  edges and directed cycles, including after resolving redirects. Do not infer
  prerequisites from names, tags or hierarchy. They are guidance, not access
  locks. Lecture/pathway readiness requirements can add audience-specific context
  without turning every recommendation into a universal prerequisite. Steven is
  the pilot curator; content approval cannot silently apply catalogue changes.
- R18. Offer flexible templates for area overview, concept explanation, lecture,
  and technique guide. A substantial lecture addresses objectives, notation and
  domain assumptions, precise statements, proof and intuition, worked examples,
  equality/boundary cases, recognition cues, misleading cues/common mistakes,
  practice with progressively disclosed hints, and further reading where relevant.
  An area overview emphasises scope, concept map and suggested routes; a concept
  explanation emphasises definition and misconceptions; a technique guide explains
  when and how to use the method. Sections are prompts, not compulsory empty
  headings. Steven reviews correctness and teaching suitability before release.
- R19. Curated pathways specify audience, objectives, sequence, readiness and
  activities using approved teaching documents and existing problems. Include
  worked-example/practice alternation, review opportunities over time and linked
  hints where useful. Foundations is a cross-topic pathway. Preserve historical
  activity when a path changes, and record which approved document revision was
  encountered. Pathway ordering and hints are editorial context, not automatic
  proficiency evidence. No new scheduling or notification service is required.

**Managed assets and contribution rights**

- R20. Use lecture-specific managed assets with validated content, bounded uploads,
  ownership, source credit, reuse permission and accessible descriptions. Resolve
  controlled asset references consistently in editor preview, saved reading and
  public reading. Private assets require authorised delivery rather than a hidden
  page around a public URL. Asset bytes are immutable once referenced by a
  submitted/published revision; changes create a new identity. Deleting a draft
  cannot destroy files retained by revisions or another published document.
  Withdrawal removes public access unless another current authorised publication
  still independently uses the asset. Define bounded orphan cleanup in planning.
- R21. Support mathematical-error reports without requiring rewritten notes.
  Public visitors may submit bounded reports without uploads; reports and any
  reporter details are private to Steven. Apply validation and abuse limits and
  avoid account-disclosing responses. Authenticated users may also suggest
  classification changes. These enter a separate curation queue and never mutate
  the graph or merge concepts as a side effect of approving teaching content.
- R22. Authors retain rights. Obtain an explicit, versioned grant
  for AsterProof to store, edit for review and publish the selected original work;
  public access grants no automatic open reuse rights. Do not apply a Creative
  Commons licence or relicense existing/third-party material by default. Record
  permission and attribution for incorporated material/assets, and resolve any
  required young-contributor/guardian authorisation before accepting their public
  work. Account approval and a credit preference do not establish these rights.
  The exact contributor agreement and withdrawal procedure must be reviewed before
  opening public contribution intake.
- R23. Distinguish publication from distribution. Migration/backfill and every rollout
  publication must not automatically enqueue lecture notices or send email.
  Preserve existing newsletter consent and unrelated automation; implement and
  verify a scoped suppression/baseline policy rather than disabling unrelated
  services. Search, sitemap and cache changes follow the approved publication
  state. Outbound rollout announcements require a separate explicit instruction.

**Whole-module scope and first pilot**

- R24. Prepare one complete **Inequalities and optimization** pilot under canonical
  area `Algebra:inequalities`, exercising multiple concepts,
  lecture templates, practice and all author/reviewer/public-reader boundaries.
  Connect the wider catalogue for exploration without mass-generating notes.
  Evaluate the acceptance scenarios below before executing wider content rollout.
  Inequalities qualifies the shared approach; it does not limit the module's scope.
  Planning the full roadmap is not approval to execute every rollout phase.
- R25. Plan and deliver the same shared Training module across Algebra, Geometry,
  Number Theory and Combinatorics, with every existing canonical area assigned to
  an explicit rollout milestone. Foundations has a complete first-class starter
  pathway covering all nine existing seed competencies, not only preserved legacy
  access. Distinguish complete catalogue discoverability, accepted area learning
  packages and depth of concept-note coverage. Every rollout reuses the same
  authoring/review/publication, privacy, rights, revision and progress rules; no
  subject is left to an unspecified post-pilot phase and no shallow notes are
  generated to claim coverage.

## Review Disposition

| Proposal | Decision |
| --- | --- |
| Separate catalogue, documents and curriculum | Adopt |
| Multiple concepts per lecture; canonical identity required on new canonical pages | Adopt, with reviewed legacy mapping and preserved URLs |
| Canonical prerequisite graph | Adopt additively with explicit pedagogical meaning and cycle checks |
| Foundations | Adopt as a cross-topic pathway |
| Markdown + LaTeX, shared editor utilities, autosave and immutable checkpoints | Adopt; keep existing solution formats and ownership intact |
| Reusable documents and assets | Adopt logical responsibilities; avoid a new generic framework or speculative table hierarchy |
| Trainer/admin publication rights in the proposed role table | Replace with the confirmed Steven-only policy; delegated review is deferred |
| Channel-specific publication records | Use channel visibility around one shared published revision, avoiding divergent Training/public copies |
| Contributor licence | Confirmed rights-retained publication permission for the pilot; no default open licence |
| Anonymous issue reports | Adopt a small private report intake, not a public discussion platform |
| AI coaching, mastery scoring, real-time co-editing | Defer; not prerequisites for this redesign |

## Phased Delivery and Release Gates

These are sequencing and acceptance gates for later implementation planning, not
execution instructions or operational approvals. Phase 0 can inform the design
through bounded read-only inspection under the existing policy.

| Phase | Deliverable | Gate before advancing |
| --- | --- | --- |
| 0 — Audit | Map legacy Training/public content, concepts, URLs and progress ownership | Duplicate, missing, ambiguous and unmapped links documented; no data changes |
| 1 — Foundation | Shared identities, concept associations, revisions, proposals, assets and publication authority | Additive transition, existing readers/progress intact, private/public boundary verified |
| 2 — Editor | Markdown/LaTeX authoring, preview, clipboard images, autosave and checkpoints | Image persistence, failure recovery, ownership and stale-save checks pass; solution editor regressions pass |
| 3 — Contributions | Drafts, comparisons, feedback, rights/credits and issue intake | No contributor or trainer/admin role can bypass Steven's approval; rights intake reviewed |
| 4 — Training | Learn/Explore, Inequalities pathway, Foundations continuity and linked practice | Existing activity and IDs preserved; hints and revision provenance behave correctly |
| 5 — Public pilot | Approved Inequalities notes, useful navigation, stable URLs and publication controls | Exact-revision parity, media isolation, accessibility, withdrawal and announcement-suppression checks pass; explicit launch request |
| 6 — Whole-module rollout | Complete Foundations starter pathway, then core, extended and specialist areas across all four topics | Every one of the 45 areas has an assigned milestone and accepted useful entry package; shared safeguards and intended public releases verified |

No full-library content generation, production mutation, contributor permission
changes, paid AI request or outbound campaign is part of this requirements work.

## Pilot Acceptance Scenarios

1. Create and submit a new Inequalities lecture with precise assumptions, proof,
   recognition cues, worked examples and linked practice; Steven reviews it.
2. Suggest a correction to a published lecture; readers continue seeing the
   current approved version until Steven explicitly publishes the replacement.
3. Edit concurrently or submit against an older base; retain both contributions,
   reject silent overwrites and require deliberate reconciliation and fresh review.
4. Paste a diagram; save, reopen, submit, publish and render it correctly, with
   alt text/credit. Direct private-media requests fail for other users/visitors.
5. Link one lecture to AM-GM and Cauchy-Schwarz and a third suitable concept; all
   placements resolve to one document and one current published revision.
6. Move from lecture to canonical practice problems and progressively disclosed
   hints without revealing private solutions or marking a problem solved.
7. Rename/redirect a concept in an authorised isolated fixture; legacy links,
   memberships, prerequisite validation and learner provenance remain resolvable.
8. Complete old Training material in an isolated upgrade fixture; preserve its
   completion, points, submission history and Foundations access.
9. Attempt approval/publication as contributor, trainer, staff and generic admin;
   deny it. Verify Steven's exact-revision approval, metadata/asset binding and
   author-credit choice. Restore a historical revision only through a new draft.
10. Publish and withdraw a pilot note; verify Training/public parity, navigation,
    search, sitemap, cache and asset behaviour, plus zero unintended newsletter
    notices or outbound email. Check draft deletion cannot break published images.

Educational evaluation asks whether a learner can find the appropriate
prerequisite, explain a theorem's assumptions, recognise when it applies, use a
hint appropriately, and attempt a related problem. Capture pilot observations
without adding learner surveillance or claiming causal learning gains from page
views. More pages or points do not demonstrate better learning. Numerical rollout
thresholds should be set with a trainer after the pilot tasks and audience are
identified; technical acceptance alone does not approve full expansion.

## Evidence and Limits

Repository inspection at `0f3ad3a46734a51b757bbfb2d3fdc3276a25cfaf` confirms:

- `inspinia/pages/catalogue_models.py`: stable catalogue entities and many-area
  membership; current relation types are narrower and related.
- `inspinia/website/models.py`: optional canonical links, one area per editorial
  concept and one concept per lecture. These require deliberate adaptation.
- `inspinia/training/models.py` and `taxonomy.py`: separate learning hierarchy,
  historical activity models and a Foundations seed topic.
- `inspinia/training/markdown.py`: sanitised Markdown currently excludes ordinary
  image tags. Clipboard JavaScript alone cannot deliver lecture image support.
- `inspinia/static/js/solution-document-editor.js` and
  `docs/solutions/continuous-solution-editor.md`: reusable editor capabilities,
  with solution-specific ownership and revision behaviour.
- `inspinia/website/automation.py`: enabled lecture automation discovers newly
  public LibraryLecture rows. New publication/backfill needs scoped handling.
- `inspinia/templates/website/terms.html`: existing text retains author rights
  and does not promise unrestricted redistribution. No policy text is changed here.

The checked seed contains 4 subjects, 45 areas, 1,109 canonical concepts, 54
redirect IDs and 1,140 memberships. This is not a live content/rights inventory.
No claim is made that the inspected checkout equals current GitHub main or the
currently deployed release; verify target revisions during implementation planning.

Educational design draws on the [IES practice guide](https://ies.ed.gov/ncee/wwc/PracticeGuide/1),
which supports spaced learning, worked-example/practice interleaving and combining
visuals with explanations. Its general evidence does not establish effectiveness
for AsterProof's pilot or require a new scheduling feature. Mathematical markup
and accessibility direction reference [W3C Math](https://www.w3.org/Math/);
browser/assistive-technology compatibility still needs direct testing.

The [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) summaries were
checked as alternatives; neither is adopted. Public availability is separate from
permission to redistribute, and any future open-licence proposal needs a separate
rights decision for the affected work.

## Planning Follow-through

No architecture decision remains blocked by the licensing question: Steven chose
rights-retained publication permission on 1 November 2026. Before implementation,
maintain a reviewed whole-module plan with Inequalities first and explicit
remaining-area/Foundation milestones, covering:

- Exact Django ownership/schema boundaries, additive migration and legacy URL
  mapping, preservation checks, and safe recovery. No automatic rollback of
  ambiguous production operations.
- Verified binding of Steven's existing identity and a separate graph-curation
  boundary; no creation of a privileged account or role-based permission shortcut.
- Private asset storage/delivery, revision-bound metadata and permission handling,
  shared-asset retention and bounded orphan cleanup.
- Preserve sanitisation in every rendering surface and test malformed Markdown,
  LaTeX, unsafe URL schemes and unauthorised asset references in both preview and
  publication. Extending image support must not weaken the existing renderer.
- Concrete contributor agreement/credit flows and any applicable young-contributor
  requirements, resolved before public intake without copying another site's terms.
- Canonical-document URLs versus area/context placements, pathway versioning and
  revision provenance, source/preview/diff mobile layouts, and unknown filter states.
  Preserve the reader's Learn/Explore entry context and route back to the relevant
  pathway or topic without duplicating the document.
- Preview every affected Training/public placement before publication. Define how
  Steven checks that changed audience, assumptions or prerequisites remain suitable
  for all pathways using the document, and reconciles unsuitable placements before
  replacing the shared revision.
- Atomic publication/visibility changes and scoped newsletter suppression compatible
  with the existing automation; verification in an isolated environment.
- Named audiences for the pilot and later topic/Foundation pathways, substantial
  lectures, safe practice/hint sources, educational review tasks and per-area gates
  for the planned full-module expansion.

Local implementation, production deployment of a scoped rollout batch and
publication of real lecture notes each need an explicit request for their scope. Existing
standing read-only inspection and direct-deployment authorisation rules still
apply; this document introduces no repeated confirmation requirement.
