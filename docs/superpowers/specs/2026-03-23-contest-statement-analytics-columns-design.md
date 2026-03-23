# Contest problem statement as canonical analytics row

## Goal

Make `ContestProblemStatement` the **long-term primary** table for both statement
content and the analytics-style fields that today usually come from linked
`ProblemSolveRecord` rows. `ProblemSolveRecord` remains **legacy** and will be
removed once nothing depends on it.

## Context

Today, `ContestProblemStatement` is already primary for statement text,
`statement_uuid`, and statement-keyed completion. Many dashboards and listings
still join `linked_problem` to read:

- topic, MOHS, contest/problem labels (where they differ from statement identity)
- `contest_year_problem`-style display strings (statement has its own computed field)
- confidence, IMO slot guess / parsed value
- raw `topic_tags` and parsed searchable techniques (`ProblemTopicTechnique` → `ProblemSolveRecord`)

The transitional `linked_problem_id` exists to supply those values when they are
not stored on the statement row.

## Decision (approved)

**Option A — first-class storage on `ContestProblemStatement`**

- Add nullable analytics columns on `ContestProblemStatement` (wide-row
  approach for the first iteration).
- Add a **statement-keyed** parsed-technique model (parallel to
  `ProblemTopicTechnique`, FK to `ContestProblemStatement`).
- During migration, **backfill** from `linked_problem` when statement fields are
  empty.
- At read time in transition, use **`coalesce(statement_field,
  linked_problem_field)`** (and equivalent for techniques) until the FK is
  dropped.
- Remove `linked_problem_id` only after dependents (notably **solutions**) no
  longer require `ProblemSolveRecord`.

## Field mapping

### Columns to own on `ContestProblemStatement`

Store these on the statement row when they are part of the product’s analytics
surface (exact Django field names to be chosen during implementation to avoid
clashes with existing CPS fields such as `contest_name`, `contest_year`,
`problem_code`, `contest_year_problem`):

| Legacy source (`ProblemSolveRecord`) | Notes |
|--------------------------------------|--------|
| `topic` | New CPS column unless a single existing field is agreed to hold the same meaning. |
| `mohs` | New CPS column. |
| `contest` | May overlap `contest_name`; **avoid duplicating** identity if already represented. |
| `problem` | May overlap `problem_code`; **avoid duplicating** identity if already represented. |
| `contest_year_problem` | CPS already has a computed `contest_year_problem`; use it as the canonical string where appropriate. |
| `confidence` | New CPS column. |
| `imo_slot_guess` | Raw text; new CPS column. |
| `imo_slot_guess_value` | Derived on save from `imo_slot_guess` (reuse `ProblemSolveRecord` parsing logic or shared helper). |
| `topic_tags` | Raw workbook-style text; new CPS column. Parsed rows live in the new technique table. |
| `rationale`, `rationale_value` | New CPS columns; same derivation pattern as today on PSR if desired. |
| `pitfalls`, `pitfalls_value` | Same as rationale. |

**Invariant:** Raw `topic_tags` on CPS + statement-keyed technique rows mirror the
existing split between `ProblemSolveRecord.topic_tags` and
`ProblemTopicTechnique`.

### Parsed techniques

- **New model** (working name: `StatementTopicTechnique`): `ForeignKey` to
  `ContestProblemStatement`, `technique`, `domains` JSON, unique on
  `(statement, technique)`, uppercase normalization on save (same rules as
  `ProblemTopicTechnique`).
- **Data migration:** copy techniques from `ProblemTopicTechnique` for each
  statement whose `linked_problem_id` matches the technique’s `record_id`, when
  the statement has no techniques yet (or merge policy TBD — default: copy if
  empty to avoid duplicates).

## Transition semantics

### Backfill

1. One-off migration (and optional idempotent management command): for each
   `ContestProblemStatement` with null analytics scalars/text and non-null
   `linked_problem_id`, copy from the linked `ProblemSolveRecord`.
2. Run technique copy as above.
3. Re-runnable command useful after bulk imports.

### Read path (until `linked_problem_id` removal)

- Implement a small helper or resolver (e.g. build an “effective analytics”
  struct per statement) that applies **per-field** `coalesce(CPS, PSR)`.
- Dashboards and APIs should use this helper so behavior is consistent during
  the transition.

### Write path

- Admin/editor and import code should **prefer updating CPS** fields as they are
  added.
- Optionally stop writing `ProblemSolveRecord` once CPS is authoritative (later
  phase; not required for phase 1).

## Phased removal of `ProblemSolveRecord`

1. **Phase 1 — CPS analytics + dual read:** new columns, new technique table,
   backfill, `coalesce` reads, keep `linked_problem_id`.
2. **Phase 2 — Reanchor dependents:** `inspinia.solutions.ProblemSolution` (and
   any other FKs to `ProblemSolveRecord`) must be migrated to use
   `problem_uuid` and/or `ContestProblemStatement` before the archive table can
   be dropped.
3. **Phase 3 — Drop legacy:** remove `linked_problem_id`, `ProblemSolveRecord`,
   and `ProblemTopicTechnique` when no code references them.

## Implementation touch areas (non-exhaustive)

- `inspinia/pages/models.py`: new fields and `StatementTopicTechnique`; shared
  parse/normalize helpers where duplicated with PSR.
- `inspinia/pages/views.py` (and any statement/import modules): replace
  `linked_problem__*` usage with effective analytics; update aggregations and
  filters.
- Workbook/import paths: upsert CPS analytics when statements are created or
  matched.
- `inspinia/pages/tests.py` (and solutions tests if phase 2): backfill,
  coalesce behavior, constraints, normalization.

## Testing expectations

- Backfill: statement with null CPS analytics + linked PSR → CPS populated.
- Coalesce: CPS value wins when both exist (or document opposite rule if product
  prefers legacy).
- Techniques: uniqueness and uppercase invariant on the new table.
- Dashboard/query smoke tests for statement-first rows with and without link.

## Related documents

- `docs/superpowers/specs/2026-03-22-dashboard-statement-first-design.md` —
  statement-first **dashboard** behavior (complementary; this spec is the **data
  model** path to full CPS ownership of analytics fields).

## Open points for implementation planning

- Final Django field names and which legacy `contest` / `problem` strings are
  redundant with existing CPS identity fields.
- Whether `imo_slot_guess_value` / `rationale_value` / `pitfalls_value` are
  computed only in `save()` like PSR or also exposed in forms.
- Merge policy when both CPS and PSR have non-null conflicting values during
  transition (default: CPS wins on write; read uses CPS first).
