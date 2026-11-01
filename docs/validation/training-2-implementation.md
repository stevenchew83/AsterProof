# Training 2.0 local implementation evidence

Date: 1 November 2026. Scope: all four canonical subjects and Foundations, with
Inequalities first in the staged editorial rollout. This records local work only;
no production database, accounts, deployment, public manuscripts or external
messages were changed.

## Delivered behavior

- Learn separates reviewed pathways from Explore's complete canonical directory.
  The source catalogue contains four subjects, 45 areas and 1,109 canonical concepts.
  Foundations is a cross-topic pathway, without a new catalogue subject.
- Shared documents support canonical area/concept landing identities and several
  concept placements per lecture. Immutable revisions retain source, authorship,
  asset references and exact contributor permission.
- Contributors can create private drafts, paste text/LaTeX/images, edit with
  CodeMirror and live preview, autosave, save checkpoints and submit proposals.
  Stale writes fail visibly; ambiguous saves pause writes until reconciliation.
- Authors can archive/reopen drafts while preserving source and history. The
  25-active-draft limit remains in place and no longer caps lifetime contributions.
- Only the configured existing publisher can approve, publish, withdraw, curate
  prerequisites/pathways or propose restoration of a submitted historical revision.
  Administrator and superuser status do not supply this authority.
- Training and public reading use the same approved immutable body and assets.
  Drafts and submitted changes never replace it automatically. Public credits are
  optional and revision-bound. Authors retain rights; no open licence is asserted.
- Curated prerequisite edges have cycle/redirect checks and optimistic versions.
  Both concept pages and filters fail closed on stale graph validation.
- Ordered pathways reference approved documents, original exercises, canonical
  archive problems and existing Training materials. Reading records an exact
  revision separately from existing practice/completion/point records.
- Public home/library/subject discovery and sitemaps include only released shared
  notes/pathways. Legacy cutovers cannot fall back to old text when disabled or
  withdrawn. Legacy mathematical admin/material forms cannot bypass review.
- Reports and classification/pathway suggestions create private review records.
  Closing contribution intake preserves existing public reading.
- A bounded baseline audit, private pack preview/import, rollout manifest and
  approved-note pathway-template resolver support progressive migration. No
  title-based mapping, consent, publication or problem UUID is inferred.

## Editorial coverage and milestones

There are 14 private versioned teaching packs and 14 private pathway templates, containing 103
original **unreviewed starter drafts**. Manuscript bodies and exercise/hint templates
are retained only under ignored `.learning-content-packs/`; they are excluded from
the public GitHub source and release artifacts. Public code ships metadata and
generic synthetic test fixtures, with no automatic content import. They include six Inequalities documents,
all nine Foundations competencies, entry overviews and representative teaching
units across all 45 areas. This is neither 1,109 completed explanations nor
educational acceptance of every area.

The explicit rollout remains M0 shared module, M1 Inequalities, M2a Foundations,
M2b–M2e 19 core-entry areas, M3 17 extended areas, M4 eight specialist areas, and
M5 whole-module acceptance. The manifest assigns every area once and keeps draft,
accepted and released states distinct. Canonical practice selection, coaching
review, rights confirmation and actual publication remain explicit editorial work.

## Verification

All Python commands used test settings with dotenv reading disabled. Migration
checks and tests use disposable local/test databases. A separate localhost preview
used only synthetic users, notes, permission records and images.

- Django system checks and migration drift checks passed.
- Focused content, curriculum, prerequisite, website and shared-solution tests run
  against actual migrations, including access/CSRF, stale edits, publication
  isolation, rendering, image persistence, archive/reopen and legacy preservation.
- The existing pages/user request-chain regression run passed 1,104 tests.
- Deployment/tooling suites exercise exact migration bytes, schema-floor guards,
  incompatible-reader recovery rejection, build/manifest checks and editor scripts.
- Node tests exercise asynchronous preview ordering, lost-save responses, canonical
  metadata comparison, image-paste transport and submission/upload races.
- Ruff, compiled asset build and whitespace checks passed. The asset build reported
  only the existing stale Browserslist-data notice; dependencies were not upgraded.
- Independent correctness/security/frontend-race reviews found and resolved stale
  form retry context, legacy activity rendering, stale prerequisite filters,
  pathway edit payload conversion, malformed PNG handling, public image layout,
  metadata comparison, image-submit races and lifetime-draft quota issues.

Native browser checks verified normal sign-in, complete topic navigation, the
Inequalities pathway, CodeMirror/live mathematical rendering, actual clipboard
image paste, required description editing, checkpoint save/reopen, and rendering
of the same managed image after synthetic approval on the public surface. At a
390-pixel viewport, topic browsing had no horizontal page overflow and the public
note remained readable. MathJax produced accessible mathematical markup; browser
console error checks were clear for the final screens.

Final non-overlapping local regression groups passed **2,366 tests**:
394 content/curriculum/website/shared-solution tests, 1,104 existing pages/user
tests, and 868 deployment/tooling tests. Seven tests were explicitly skipped:
three PostgreSQL concurrency cases and four tooling environment cases. These
counts do not include additional overlapping focused review runs.

The final browser pass also verified archive followed by reopen through My notes,
with the source and public publication retained. The disposable server and
agent-created preview tab were stopped after verification.

## Release qualification still required

Production flags default off. Activation needs Steven's verified existing user ID,
approved contributor agreement/process, persistent private file storage and the
normal scoped deployment authorization. No technical access grants were created.

The additive SQLite and real PostgreSQL 17.9 rehearsals preserve synthetic
historical schema, rows, sequences, functions, triggers and identities. The broad
PostgreSQL suite passed 193 tests without skips, including the concurrency cases.
The source-built runtime and precommit evidence boundary are recorded in
[PostgreSQL verification](training-2-postgresql17-verification.md). The actual
four-migration allowance and delta are now frozen; the target still needs separately
authorized installed authority and an independently verified compatible recovery
baseline. Neither local verification nor a GitHub merge supplies either condition.

Representative learner/coaching evaluation has not occurred. M1 educational
acceptance and subsequent staged release are not inferred from passing software
tests or the number of draft documents. No learning-gain or proficiency claim is
made.

## Release preparation update

Current main was integrated before release preparation, preserving the existing
learning-activity and offline-evaluation work. The new prerequisite migration is
pages.0045 to follow the already released pages.0044 activity migration. The full
integrated application suite passed 2,987 tests (15 PostgreSQL/platform-specific
skips); the separate PostgreSQL run executes the database concurrency cases without
skips. The deployment/tooling suite passed 1,093 tests (four platform-specific
skips). System checks, migration drift, focused Ruff checks and the static build
passed. The final private-manuscript audit found all 103 drafts, complete entry
packages for 45 areas and nine Foundations competencies, no manuscript excerpts
among the 169 proposed public source paths, and no publication or automatic import.
CI and a fresh committed-source PostgreSQL rehearsal bind the release evidence to
the final immutable source.
