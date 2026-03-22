# Dashboard Statement-First Design

## Goal

Convert all `/dashboard/...` contest and statement analytics pages to use
`ContestProblemStatement` as their primary row source, while keeping public
archive pages on the existing `ProblemSolveRecord`-first model for now.

## Why

The current dashboard behavior mixes two different units:

- dashboard listings often render rows from `ProblemSolveRecord`
- statement tooling and some analytics already reason in terms of
  `ContestProblemStatement`

This causes visible mismatches, especially for shortlist- or camp-style imports
where one contest/year can have many statement rows that do not map 1:1 to
problem archive rows.

The new rule is simple:

- dashboard pages are statement-first
- one dashboard row means one `ContestProblemStatement` row
- linked problem metadata is enrichment, not the primary identity

## Scope

### In scope

- all `/dashboard/...` pages that currently use contest/problem listing or
  contest analytics data
- dashboard contest listing
- dashboard contest advanced analytics
- dashboard contest summary pages and heatmaps that currently count archive
  problems
- dashboard visibility controls

### Out of scope

- public contest/archive pages
- non-dashboard public search and listing pages
- a full data-model migration away from `ProblemSolveRecord`
- moving solved state off `UserProblemCompletion`

## Core decisions

### Primary row model

Dashboard pages will use `ContestProblemStatement` as the primary query model.

Each dashboard row is keyed by the statement row itself, not by the linked
problem. The default statement row key for dashboard actions is
`ContestProblemStatement.id`.

This dashboard conversion does not require a broader redesign of the current
`problem_uuid` linkage contract. If we later decide to support many statement
rows linked to the same problem record, that should be handled as a separate
follow-up change.

### Linked problem metadata

When `ContestProblemStatement.linked_problem` exists, dashboard pages may enrich
the statement row with:

- topic
- MOHS
- parsed topic tags
- solution counts
- user solved state and solved date

When `linked_problem` is missing:

- the statement row still appears
- topic, MOHS, tags, solution data, and solved-date actions are blank or shown
  as `Unlinked`

### Statement row identity versus completion identity

Dashboard row actions must distinguish between:

- statement row identity for rendering, filtering, and visibility actions
- linked problem identity for completion writes

Default rule:

- bulk inactive and row selection use `ContestProblemStatement.id`
- solved-date writes resolve through the statement row first
- the dashboard solved-date payload should include `statement_id`; the server
  resolves `linked_problem` from that statement row and writes completion for
  the linked problem when present
- the completion endpoint may continue accepting `problem_uuid` as a legacy
  fallback for non-dashboard callers during the transition
- solved-date UI may still carry statement row id so the frontend can update the
  correct row after a successful completion write

### Solved state

Solved state remains stored in `UserProblemCompletion`.

The lookup path remains:

`ContestProblemStatement -> linked_problem -> UserProblemCompletion`

A statement row is counted as solved only if:

- it has a linked problem
- that linked problem has a matching `UserProblemCompletion` in scope

### Metrics and denominators

Dashboard counts use statement rows unless the UI explicitly labels a different
unit.

That means:

- contest totals are statement-row totals
- year totals are statement-row totals
- topic and tag summaries are based on statement rows in scope
- solved rate uses statement-row denominator

Example:

`solved_rate = solved_statement_rows / active_statement_rows_in_scope`

### Visibility model

Add `ContestProblemStatement.is_active` with default `True`.

Dashboard pages filter on statement visibility only:

- use `ContestProblemStatement.is_active`
- do not inherit visibility from `linked_problem.is_active`

`ProblemSolveRecord.is_active` becomes legacy for dashboard behavior only.

Public archive pages still depend on `ProblemSolveRecord.is_active` in this
phase, so those values must remain unchanged until a separate public-page
visibility migration exists.

## Architecture

### Dashboard-only statement query layer

Create a small helper layer in `inspinia/pages/views.py` for dashboard pages.
This layer should:

- query active `ContestProblemStatement` rows
- filter by dashboard contest/year/topic/tag/search inputs
- enrich rows from `linked_problem` where available
- resolve user completion through linked problems
- group rows by contest, year, topic, and other dashboard needs

This keeps the statement-first logic centralized instead of duplicating it in
individual views.

### Public pages remain unchanged

Public listing pages continue using the current
`_build_contest_problem_listing_context` behavior for now.

If later we also want public pages to become statement-first, that should be a
separate follow-up project.

## Rollout plan

### Phase 1: model and migration foundation

1. Add `ContestProblemStatement.is_active = models.BooleanField(default=True)`.
2. Create a migration that:
   - adds the field
3. Add statement-first dashboard query helpers.
4. Update dashboard row-action payloads so selection and bulk visibility use
   statement ids rather than problem UUIDs.

### Phase 2: dashboard contest listing conversion

Convert `/dashboard/contests/listing/` first.

This page is the best proving ground because it already combines:

- row counts
- year grouping
- solved-date editing
- bulk actions
- sort/filter behavior

New behavior:

- one visible row per statement row
- bulk inactive acts on statement rows by statement id
- solved-date controls work only for linked rows
- unlinked statement rows remain visible and read-only for completion

### Phase 3: dashboard analytics conversion

Convert the remaining dashboard analytics pages so that:

- contest/year tables count statement rows
- heatmaps count statement rows
- solved counts count solved statement rows
- rates use statement-row denominators

Linked-problem-only metrics, if still useful, should be exposed explicitly and
not mixed into the main totals.

## UI expectations

### Dashboard contest listing

- filters remain contest/year/topic/MOHS/tag/search based
- row selection targets statement rows by `ContestProblemStatement.id`
- solved-date controls stay in the listing for linked rows
- unlinked rows show a clear non-editable state

### Dashboard analytics

- labels should match the new unit
- if a card or table currently says “Problems” but is actually counting
  statements after the conversion, the label should be reviewed and updated
  where needed

## Testing strategy

Add focused regression tests for each phase.

### Required cases

1. A contest/year with:
   - few `ProblemSolveRecord` rows
   - many `ContestProblemStatement` rows
   - dashboard listing must show statement-row count

2. Unlinked statement rows:
   - remain visible in dashboard listing
   - are included in statement-row totals
   - do not allow solved-date editing

3. Statement visibility:
   - inactive statement rows disappear from dashboard pages
   - `linked_problem.is_active` does not affect dashboard visibility

4. Public archive regression:
   - public contest pages remain unchanged

## Risks

### Partial metadata

Unlinked statement rows will reduce how much topic/MOHS/solution data can be
shown. The UI should make that absence clear instead of fabricating values.

### Large `views.py`

`inspinia/pages/views.py` is already large. The statement-first helper layer
should be extracted as clean internal helpers rather than more inline query
logic.

## Acceptance criteria

The work is complete when:

- dashboard contest listing shows one row per active statement row
- dashboard analytics counts and solved rates are statement-row based
- statement visibility is controlled by `ContestProblemStatement.is_active`
- solved dates still work through linked problems
- public pages keep using `ProblemSolveRecord.is_active` until a separate
  migration changes that contract
- public archive pages continue using their current behavior
