# Olympiad Ranking System Phase 1 Design

## Goal

Build a production-ready, database-backed olympiad ranking foundation that replaces manual wide-sheet maintenance with normalized storage, deterministic snapshot computation, practical admin imports, and a usable ranking table for operations.

This Phase 1 design prioritizes:

- correct data modeling
- deterministic ranking computation
- import practicality for non-technical admins
- sensitive-data safety defaults
- performance-safe read paths via persisted snapshots

## Confirmed Decisions

1. Delivery is split into **two phases**.
2. Phase 1 includes a **minimal ranking UI** for operational validation.
3. Full NRIC handling in Phase 1 is **restricted plaintext storage** (admin-only access), while default UI/export remains masked.
4. The feature is implemented as a **new app**: `inspinia.rankings`.

## Phase Split

### Phase 1 (this spec)

- New ranking domain models and migrations.
- Ranking compute services with tests.
- Snapshot persistence and recompute command/admin action.
- Import Center with preview/apply workflows for:
  - student master import
  - assessment result import
  - legacy wide-sheet migration import
- Minimal operational UI:
  - ranking table with filters/sorting/search/export
  - baseline student/assessment/formula/import pages

### Phase 2 (separate spec)

- Full analytics dashboards:
  - selection dashboard
  - performance dashboard
  - school/region dashboard
  - data-quality dashboard
- Additional reporting/polish and dashboard drill-downs.

## Scope

### In scope

- Normalized ranking data model and storage boundaries.
- Ranking formula versioning and weighted scoring computation.
- Required-assessment and missing-score policy behavior.
- Deterministic tie-break ordering.
- Persisted ranking snapshots for fast reads.
- Admin import previews with issue logs and safe apply flow.
- Main ranking table with practical filters/sorting and CSV export.
- Role-aware sensitive field behavior (masked-by-default, restricted full NRIC).

### Out of scope

- Full dashboard suite described in final product vision (Phase 2).
- OCR for image-only source files.
- New global frontend frameworks or heavy client-side architecture changes.
- Encrypted NRIC-at-rest model in Phase 1 (explicitly deferred by decision).

## Existing Codebase Integration Points

The implementation follows existing project patterns:

- Auth/permission helper patterns:
  - `user_has_admin_role(...)`
  - admin gating helpers in views
- Import and admin audit patterns:
  - preview/apply flows in `inspinia.pages.views`
  - `AuditEvent` via `record_event(...)`
- UI stack:
  - server-rendered templates
  - DataTables for operational tables
  - ApexCharts for chart sections
  - Inspinia/Bootstrap dashboard shell

## Proposed App Structure

Create new app:

- `inspinia/rankings/apps.py`
- `inspinia/rankings/models.py`
- `inspinia/rankings/admin.py`
- `inspinia/rankings/forms.py`
- `inspinia/rankings/urls.py`
- `inspinia/rankings/views.py`
- `inspinia/rankings/services/`
  - `ranking_compute.py`
  - `ranking_normalization.py`
  - `ranking_tiebreak.py`
  - `ranking_snapshot_store.py`
- `inspinia/rankings/imports/`
  - `student_master_import.py`
  - `assessment_result_import.py`
  - `legacy_wide_import.py`
- `inspinia/rankings/management/commands/recompute_rankings.py`
- `inspinia/rankings/tests/`

Project wiring updates:

- `config/settings/base.py`: add `"inspinia.rankings"` to `LOCAL_APPS`.
- `config/urls.py`: include rankings URL namespace, e.g. `path("rankings/", include("inspinia.rankings.urls", namespace="rankings"))`.
- navigation links in existing shared shell templates.

## Data Model Contract (Phase 1)

### `School`

Fields:

- `id`
- `name`
- `normalized_name`
- `short_name` (nullable)
- `state` (nullable)
- `school_type` (nullable)
- `is_active`
- `created_at`
- `updated_at`

Constraints/indexes:

- unique `normalized_name`
- indexes on `name`, `state`

### `Student`

Fields:

- `id`
- `full_name`
- `normalized_name`
- `birth_year` (nullable)
- `date_of_birth` (nullable)
- `gender` (nullable)
- `school` (nullable FK to `School`)
- `state` (nullable)
- `masked_nric` (nullable)
- `full_nric` (nullable, restricted access)
- `external_code` (nullable)
- `legacy_code` (nullable)
- `active`
- `notes` (nullable)
- `created_at`
- `updated_at`

Rules:

- age is derived in views/services, not stored.
- full NRIC is never shown in normal list pages.
- masked NRIC is default display/export identity.

Constraints/indexes:

- partial unique index on non-null `external_code`
- optional partial unique index on non-null `full_nric`
- indexes on `normalized_name`, `birth_year`, `school`
- compound index on `(normalized_name, birth_year)` for duplicate detection

### `Assessment`

Fields:

- `id`
- `code`
- `display_name`
- `season_year`
- `assessment_date` (nullable)
- `category` (contest/test/qualifier/mock/monthly/entrance/other)
- `division_scope` (nullable)
- `max_score` (nullable)
- `default_weight` (nullable)
- `result_type` (score/band/medal/status/text/mixed)
- `is_active`
- `is_ranked_by_default`
- `sort_order`
- `created_at`
- `updated_at`

Constraints/indexes:

- unique `(code, season_year)`
- indexes on `season_year`, `assessment_date`, `division_scope`

### `RankingFormula`

Fields:

- `id`
- `name`
- `season_year`
- `division` (nullable)
- `purpose` (selection/training/reporting)
- `missing_score_policy` (`zero`, `skip_and_rescale`)
- `tiebreak_policy` (JSON)
- `is_active`
- `version`
- `notes`
- `created_at`
- `updated_at`

### `RankingFormulaItem`

Fields:

- `id`
- `ranking_formula` (FK)
- `assessment` (FK)
- `weight`
- `is_required`
- `normalization_method` (`raw`, `percent_of_max`, `zscore`, `fixed_scale`)
- `sort_order`

Constraints:

- unique `(ranking_formula, assessment)`

### `StudentResult`

Fields:

- `id`
- `student` (FK)
- `assessment` (FK)
- `raw_score` (nullable)
- `normalized_score` (nullable)
- `medal` (nullable)
- `band` (nullable)
- `status_text` (nullable)
- `remarks` (nullable)
- `source_url` (nullable)
- `source_file_name` (nullable)
- `imported_by` (nullable FK to user)
- `imported_at` (nullable)
- `created_at`
- `updated_at`

Constraints/indexes:

- unique `(student, assessment)`
- indexes on `assessment`, `student`, `raw_score`, `medal`, `band`

### `StudentSelectionStatus`

Fields:

- `id`
- `student` (FK)
- `season_year`
- `division` (nullable)
- `status` (team/squad/watchlist/senior/junior/primary/pioneer/beginner/none/custom)
- `notes` (nullable)
- `created_by` (nullable FK to user)
- `created_at`
- `updated_at`

Constraint:

- unique `(student, season_year, division, status)`

### `RankingSnapshot`

Fields:

- `id`
- `ranking_formula` (FK)
- `student` (FK)
- `season_year`
- `division`
- `total_score`
- `rank_overall`
- `rank_within_division`
- `score_breakdown_json`
- `last_computed_at`
- `formula_version_label`
- `formula_version_hash`
- `created_at`
- `updated_at`

Constraints/indexes:

- unique `(ranking_formula, student)`
- indexes on `season_year`, `division`, `total_score`, `rank_overall`

### `ImportBatch`

Fields:

- `id`
- `import_type` (`student_master`, `assessment_results`, `legacy_wide_table`)
- `uploaded_file`
- `original_filename`
- `status` (`uploaded`, `previewed`, `applied`, `failed`, `partial`)
- `summary_json`
- `created_by` (FK user)
- `created_at`
- `updated_at`

### `ImportRowIssue`

Fields:

- `id`
- `import_batch` (FK)
- `row_number`
- `severity` (`info`, `warning`, `error`)
- `issue_code`
- `message`
- `raw_row_json`

## Core Design Rule Enforcement

1. Raw data (`StudentResult`) is separate from derived ranking output (`RankingSnapshot`).
2. Rankings are computed and persisted, never manually edited.
3. Selection labels are stored in `StudentSelectionStatus`, not score columns.
4. UI may present a wide/pivot table, while storage remains normalized.
5. Legacy sheet migration is explicit and traceable via import batch + issue logs.

## Ranking Engine Design

Service-layer computation (not template logic) with deterministic output.

### Inputs

- one active `RankingFormula`
- related `RankingFormulaItem` rows
- candidate student population and `StudentResult` rows
- optional division/season scope

### Normalization behavior

Per formula item:

- `raw`: use `raw_score`
- `percent_of_max`: `raw_score / max_score * 100`
- `fixed_scale`: prefer `normalized_score`, fallback to percent-of-max when possible
- `zscore`: cohort-based standardization for that assessment (guard stddev=0)

### Missing score policy

- `zero`:
  - missing item contributes `0`
  - full formula weight remains in denominator
- `skip_and_rescale`:
  - missing optional item excluded from denominator
  - total rescaled by available weights
  - required missing item is still treated as penalized `0` (not skipped)

### Tie-break behavior

Stable sort order:

1. `total_score` descending
2. highest score in configured priority assessment(s)
3. more recent assessment score
4. younger student only if explicitly enabled
5. alphabetical `normalized_name` fallback

### Persistence

- compute and upsert all targeted snapshot rows in one transaction.
- replace stale rows for the target formula scope.
- populate readable `score_breakdown_json` for UI/export explanation.
- stamp snapshot rows with formula version label/hash.

## Recompute Entry Points

### Management command

`recompute_rankings` with modes:

- `python manage.py recompute_rankings --formula <id>`
- `python manage.py recompute_rankings --season <year> --division <division>`
- optional: `--dry-run`

### Admin action

Formula admin action:

- recompute snapshots for selected formula(s)

## Import Center Design

### Shared flow

- upload -> parse -> preview -> confirm apply
- every run tracked with `ImportBatch`
- all anomalies captured in `ImportRowIssue`
- no silent data drops

### 1) Student master import

Supported files: CSV/XLSX.

Matching strategy order:

1. exact `external_code`
2. exact full NRIC (privileged/admin-only path)
3. exact `normalized_name + birth_year`
4. fuzzy near-match warning (advisory only)

Preview sections:

- matched existing students
- new students to create
- ambiguous rows
- validation errors

Apply behavior:

- upsert matches
- create new rows
- keep ambiguous rows unresolved unless admin confirms mapping

### 2) Assessment result import

- upload one contest/test result sheet
- choose existing or create target `Assessment`
- column mapping for student id fields and score/medal/band/status fields
- preview matches/creates/conflicts/errors
- apply performs upsert on unique `(student, assessment)`

### 3) Legacy wide-sheet migration import

- classify columns into:
  - student master columns
  - assessment-like columns
  - selection-status-like columns
  - ambiguous columns requiring admin confirmation
- apply behavior:
  - create/update students
  - create missing assessments from assessment columns
  - write numeric-ish values to `StudentResult`
  - write TEAM/SQUAD/etc labels to `StudentSelectionStatus`
  - keep weird/unknown values as issues (never silently dropped)

## Phase 1 UI Design

All views are server-rendered and aligned to existing template conventions.

### Pages

1. **Ranking table (main)**
   - one row per student snapshot
   - filters: season, division, school, state, selection status, active
   - search by student name/school
   - sortable columns via DataTables
   - columns include:
     - overall rank
     - student name
     - birth year / derived age
     - school
     - state
     - selection status
     - total score
     - active formula assessment columns
     - last updated
   - pivot-style display from normalized backing data

2. **Students (baseline)**
   - searchable list + detail page
   - detail includes result history, selection statuses, ranking history, and simple trend chart

3. **Assessments (baseline CRUD)**

4. **Ranking formulas (baseline CRUD)**
   - item weights/rules preview
   - recompute trigger

5. **Import center**
   - upload, preview, apply, issue logs, batch history

### Export

- Phase 1 baseline: filtered CSV export from ranking table
- default export excludes full NRIC and uses masked identifier fields

## Permissions and Privacy

- normal staff users: ranking views with masked identifiers only
- admin/privileged users:
  - import apply flows
  - full NRIC view/edit in restricted paths only
- full NRIC is never shown on default listing screens
- full NRIC is excluded from default ranking exports
- import/apply and major actions emit audit events consistent with existing monitoring patterns

## Performance Plan

- ranking pages read from `RankingSnapshot` instead of recomputing.
- use `select_related` / `prefetch_related` to avoid N+1.
- apply indexes defined in model contract for filter/sort paths.
- paginate operational tables sensibly.
- keep formula-assessment column hydration precomputed per page request.

## Testing Strategy

Add focused tests under `inspinia/rankings/tests/`.

### Model/constraint tests

- uniqueness constraints and index-backed assumptions
- duplicate-detection key behavior
- snapshot uniqueness per `(formula, student)`

### Ranking service tests

- weighted contribution computation
- normalization methods
- missing score policy behavior
- required-assessment behavior
- tie-break deterministic ordering

### Import tests

- preview matching buckets for each import type
- apply/upsert behavior for result rows
- ambiguous/invalid issue logging
- legacy migration status-vs-score split

### Permission/privacy tests

- masked NRIC default behavior
- full NRIC restricted access checks
- exports omit full NRIC by default

### View tests

- ranking table filters/search/sort
- export response and field safety
- recompute command/admin action coverage

## Migration and Rollout Plan

1. Deploy migrations for new ranking tables.
2. Configure schools/assessments/formulas (manual or import-assisted).
3. Run student master import.
4. Run assessment/legacy imports.
5. Recompute snapshots via command/admin action.
6. Validate ranking table against selected legacy-sheet slices.
7. Move operations from manual wide sheet to import + recompute workflow.

## Operational Commands (Phase 1)

- `uv run python manage.py migrate`
- `uv run python manage.py recompute_rankings --formula <id>`
- `uv run python manage.py recompute_rankings --season <year> --division <division>`
- `uv run pytest inspinia/rankings/tests`
- `uv run ruff check inspinia/rankings config`
- `uv run python manage.py check`

## Risks and Mitigations

1. Legacy sheet ambiguity can cause incorrect auto-mapping.
   - Mitigation: explicit preview buckets + required confirmation for ambiguous columns.
2. Restricted plaintext NRIC is sensitive.
   - Mitigation: strict role-gated access, masked defaults, no default export exposure, auditable actions.
3. Formula complexity can introduce ranking surprises.
   - Mitigation: snapshot breakdown JSON and deterministic tie-break tests.
4. Performance can degrade with large cohorts.
   - Mitigation: snapshot-first reads, indexes, select/prefetch discipline.

## Acceptance Criteria (Phase 1)

Phase 1 is complete when:

1. Admin can import legacy wide sheets with preview + issue reporting.
2. Student and assessment results are stored in normalized tables.
3. Active formulas compute persisted snapshots correctly.
4. Ranking table supports practical sort/filter/search and safe export.
5. Sensitive identifiers are masked by default.
6. Recompute command/admin action are operational.
7. Focused ranking/import/privacy tests pass.
8. Implementation follows existing project conventions and does not break existing pages.

## Phase 2 Follow-up

Phase 2 will add the complete analytics dashboards and advanced operational reporting on top of this Phase 1 foundation.
