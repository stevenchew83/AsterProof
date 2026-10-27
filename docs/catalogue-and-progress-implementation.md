# Catalogue exploration and derived progress

Implemented on 27 October 2026 and integrated against main `29a2053d9622113a66e34538dade876f0e11b7c5`. Production activation requires the separately authorized support described in [release readiness](deployment/catalogue-release-readiness-2026-10-27.md).

## Behaviour

`/dashboard/topic-tags/` is now the Mathematics catalogue. It browses subjects, areas, concepts, explicit narrower-concept relationships, scoped names, topic tags and roles. Breadcrumbs and an Up one level action support drill-up; a subject/area sidebar supports switching scope. The sidebar collapses on mobile. Search accepts canonical names, existing IDs and aliases. Problem examples are an explicit tab and read published memberships.

Catalogue navigation reads only catalogue tables. It does not load original problems, tags, completions or the whole problem membership snapshot. Empty catalogue concepts remain discoverable independently of problem availability. Contextual and unresolved labels retain their qualification rather than becoming unconditional synonyms.

The existing Area & Concepts Progress routes and CSV exports use derived memberships and cached per-user summaries. Original completion tools continue writing `UserProblemCompletion`. Statement completion precedence, solved-status rules, difficulty statistics, distinct UUID counts, zero-problem states and user-selection permissions are preserved. Counts across overlapping concepts/areas are never simply added to produce an overall total.

## Catalogue storage and identity preservation

The catalogue tables are `CatalogueSubject`, `CatalogueArea`, `CatalogueConcept`, `CatalogueConceptArea`, `CatalogueConceptRelation` and `CatalogueConceptAlias`.

The frozen, SHA-256-checked seed contains:

| Data | Count |
| --- | ---: |
| Subjects | 4 |
| Areas | 45 |
| Canonical concepts | 1,109 |
| Retained redirect IDs | 54 |
| Total concept ID records | 1,163 |
| Concept/area memberships | 1,140 |
| Explicit narrower-concept relationships | 262 |
| Scoped aliases and held mappings | 4,836 |

This includes every ID in the current subject catalogues, the reviewed identity merges, and 23 older redirects that are no longer standalone catalogue entries. Redirect rows remain stored under their original IDs and resolve to their existing canonical destination. There are no new automatic mathematical merges. Historical area keys retain their exact spelling, including spaces in some Combinatorics keys.

The frozen catalogue and alias-policy sources match the current main baseline. Assignment-review models and migration 0036 are existing prerequisites, not new production migrations in this release. The existing assignment activation state and reviewed records are preserved.

Catalogue tables drive navigation. Existing versioned assessment profiles and reviewed assignment-validation policies remain compatible with their established IDs; this change does not reinterpret a catalogue edit as a newly approved problem assignment. It does not introduce a catalogue editing/approval workflow or independent mastery records.

## Derived data and freshness

`ConceptLibrarySnapshot`, `CatalogueState`, `CatalogueProblem` and `CatalogueProblemConcept` store published generations of lightweight problem identities, accepted memberships and scope totals. Source resolution, full-library traversal, hashing and evidence validation happen during maintenance. Publication checks the source revision and assignment state again and commits the generation and publication pointer atomically. Failed or superseded builds preserve the preceding publication.

`UserConceptProgressSummary` stores scope-keyed derived counts under a user, membership generation and completion fingerprint. A cold personal summary reads the selected user's completions and matching published memberships. A warm lookup performs two reads: that user's completion records and the matching summary. Completion fingerprints detect ordinary edits, bulk status updates and deletions without rewriting the original records or rescanning the library. The existing user-selection authorization is reused before reading or creating a personal summary.

Migration 0039 installs narrowly scoped revision triggers on original source/assignment tables, catalogue tables and published solution evidence. The triggers update only the new `CatalogueState.source_revision` counter. They cover ORM saves, bulk updates and direct maintenance SQL. Private draft solution edits do not invalidate shared memberships. Assignment revision and activation metadata provide an additional generation guard. No user, completion, source problem or assignment row is changed by installing these triggers.

When mapping inputs change, examples and personal progress display an updating state until maintenance publishes a valid replacement. The catalogue remains browsable. Completion-only changes appear on the next progress read without waiting for a library rebuild. A missing/stale shared generation never invokes a synchronous library rebuild in a GET. CSV requests return 503 while shared summaries are unavailable, rather than exporting false zero totals.

Maintenance retains the current/recent shared generations and recent personal-summary versions. Cleanup affects only disposable derived rows.

## Migrations and maintenance

- 0036 is the unchanged existing assignment-review prerequisite from the inspected deployed source.
- 0037 creates additive catalogue and projection tables, referencing existing source/user identities without altering their fields.
- 0038 loads the frozen catalogue into the new tables only.
- 0039 installs reversible revision triggers for SQLite and PostgreSQL.

After applying migrations through the project's approved procedure, `refresh_concept_summaries` publishes memberships. `--all-users` optionally warms users with completion records; repeated `--user-id` options warm specific users, and `--force` explicitly rebuilds shared memberships. These commands write derived data only.

The existing `recompute_technique_progress_catalog` maintenance command also refreshes concept summaries, including when older technique facts are already current. A concept-summary failure is reported independently and does not prevent the existing duplicate-report maintenance. No new timer, service, dependency, permission or infrastructure was introduced.

The initial shared generation is created by maintenance rather than the migration or a web request. Production deployment still requires the established schema-change/release procedure; the routine migration-free release path must not be treated as approval to bypass that procedure.

## Verification

- **2,074 tests passed** in the full repository suite on the integrated release candidate. Assignment-progress regressions explicitly publish the shared snapshot before checking accepted memberships and CSV output. The obsolete dashboard test was reproduced on unchanged main, then updated for the current area explorer while retaining counts, role union and self-heading suppression assertions.
- The isolated upgrade test starts with existing users, UUIDs, linked statements, both completion forms, notes and accepted assignments at migration 0036. It verifies all their fields remain unchanged after the catalogue upgrade.
- Regression checks cover all retained IDs, redirects, scoped alias search, drill-up/down, query bounds, source-free catalogue GETs, mapping invalidation, interrupted publication, assignment activation/revision changes, bulk/direct SQL updates, published/private evidence, status rules, completion precedence, deduplication, permissions and exports.
- Django system checks, migration/model drift checks and whitespace checks pass. Focused implementation Ruff checks pass. The shared `views.py` retains pre-existing lint findings; the catalogue changes introduce no new finding categories there.
- Browser verification used the real Django routes with 80 synthetic problems and a synthetic learner. Subject → area → concept navigation, explicit examples and the personal progress link were exercised. Desktop at 1440 × 900 and mobile at 390 × 844 were inspected. The mobile document measured 375 px wide, without page-level horizontal overflow, and its scope navigation expanded successfully. Temporary viewport overrides were restored.
- Captured local catalogue, example and progress requests made **zero reads of original problem/tag source tables**. These are synthetic local observations, not production latency claims. Production performance needs remeasurement after a separately requested deployment.

### PostgreSQL verification limit

The SQLite migration and trigger paths were executed. PostgreSQL 15 is installed locally, but temporary cluster initialization failed because macOS could not allocate a System V shared-memory segment (`shmget`, OS shared-memory quota). No OS setting, existing database or existing service was changed to work around it. PostgreSQL trigger runtime verification remains outstanding before production schema activation.
