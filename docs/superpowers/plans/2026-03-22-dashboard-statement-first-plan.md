# Dashboard Statement-First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert dashboard contest/problem analytics and listing flows to use `ContestProblemStatement` as the primary row source while keeping public archive pages on the existing `ProblemSolveRecord` model.

**Architecture:** Add a statement-level active flag and a dashboard-only statement query/enrichment layer, then route dashboard listing and analytics pages through that layer. Preserve solved-date storage in `UserProblemCompletion`, but resolve it from statement rows through `linked_problem` when available.

**Tech Stack:** Django 5.1, Django ORM, Bootstrap/Inspinia templates, pytest, existing statement/contest helpers in `inspinia/pages/views.py`

---

### Task 1: Add statement-level visibility and retire dashboard dependence on `ProblemSolveRecord.is_active`

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/models.py`
- Create: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/migrations/0019_contestproblemstatement_is_active.py`
- Test: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`

- [ ] **Step 1: Write the failing test for statement visibility defaults**

Add a focused test near the dashboard listing tests that creates:
- one active statement row
- one inactive statement row
- both under the same contest/year

Assert that the future statement-first dashboard listing only shows the active statement row.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "statement_visibility"
```

Expected: failure because `ContestProblemStatement` does not yet have `is_active`.

- [ ] **Step 3: Add the model field**

In `/Users/stevenchew/Dev/AsterProof/inspinia/pages/models.py`, add:

```python
is_active = models.BooleanField(default=True)
```

to `ContestProblemStatement`.

- [ ] **Step 4: Create the migration**

Run:

```bash
uv run python manage.py makemigrations pages
```

Expected migration shape:
- add `ContestProblemStatement.is_active`

- [ ] **Step 5: Preserve public-page visibility behavior**

Do **not** reset `ProblemSolveRecord.is_active` in this phase, because public
pages still depend on `_active_problem_records()`.

- [ ] **Step 6: Re-run the focused test**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "statement_visibility"
```

Expected: still failing until dashboard code switches to statement visibility.


### Task 2: Build a shared dashboard statement query/enrichment layer

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`
- Test: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`

- [ ] **Step 1: Write the failing helper-level regression test**

Add a test that creates:
- linked and unlinked `ContestProblemStatement` rows
- linked problem metadata (`topic`, `mohs`, techniques)
- user completion on the linked problem

Assert that the future helper output:
- returns one row per active statement row
- includes linked enrichment when present
- leaves unlinked metadata blank
- carries a statement-level identifier

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "dashboard_statement_row_helper"
```

Expected: failure because no shared statement-first helper exists yet.

- [ ] **Step 3: Add active-statement helper(s)**

In `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`, add helpers with clear boundaries, for example:

```python
def _active_dashboard_statements():
    return ContestProblemStatement.objects.filter(is_active=True)

def _dashboard_statement_rows(base, *, user):
    ...
```

The row shape should include:
- `statement_id`
- `statement_uuid` or `problem_uuid` for display only if still useful
- `contest_name`, `contest_year`, `problem_code`, `day_label`
- linked enrichment: `topic`, `mohs`, `topic_tags`, `linked_problem_uuid`
- completion fields derived from `linked_problem`

- [ ] **Step 4: Reuse existing statement-first logic where possible**

Refactor from existing helpers instead of duplicating:
- `_statement_table_rows`
- `_statement_dashboard_rows`
- `_completion_board_payload`
- `_contest_year_mohs_pivot_payload`

Prefer extracting small reusable maps:
- statement -> linked problem
- linked problem -> completion date
- linked problem -> solutions
- linked problem -> techniques

- [ ] **Step 5: Add a dedicated visibility filter helper**

Make sure dashboard statement queries always start from:

```python
ContestProblemStatement.objects.filter(is_active=True)
```

and never inherit `linked_problem.is_active`.

- [ ] **Step 6: Re-run the focused helper test**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "dashboard_statement_row_helper"
```

Expected: PASS.


### Task 3: Convert completion actions to statement-first payloads with linked-problem writes

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/completion-board.html`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/contest-dashboard-listing.html`
- Test: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`

- [ ] **Step 1: Write the failing test for statement-id completion writes**

Add a test for `pages:completion_board_toggle` that posts:

```python
{
    "action": "set_unknown",
    "statement_id": statement.id,
}
```

and asserts:
- completion is written to `UserProblemCompletion` for `statement.linked_problem`
- response payload contains the updated solved state

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "completion_board_toggle_accepts_statement_id"
```

Expected: failure because the endpoint currently expects `problem_uuid`.

- [ ] **Step 3: Add statement-id resolution helper**

In `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`, update the completion-board resolver to accept:
- `statement_id` first for dashboard callers
- `problem_uuid` as a legacy fallback

Suggested shape:

```python
def _completion_board_get_statement_problem(*, statement_id: str, problem_uuid: str):
    ...
```

- [ ] **Step 4: Update completion-board payload helpers**

Adjust the backend helper path end-to-end, not just the view:
- `_completion_board_get_statement_problem`
- `_completion_board_response_payload`
- `_completion_board_payload`

Make the response payload return the statement row identifier needed for
frontend updates after a successful write.

- [ ] **Step 5: Keep writes keyed to `linked_problem`**

Do not move solved-state storage. Keep:

```python
UserProblemCompletion.objects.update_or_create(
    user=user,
    problem=problem,
    defaults={"completion_date": completion_date},
)
```

but resolve `problem` from the statement row.

- [ ] **Step 6: Keep the completion board itself on active statements**

When updating the completion board flow, make sure
`completion_board_view` and bulk/toggle helpers still start from active
statement rows rather than all statements.

- [ ] **Step 7: Update template payloads**

In both dashboard templates, switch the primary action payload from problem UUID to statement id:
- `data-statement-id="{{ statement.id }}"`
- include statement id in JS POST bodies

Keep `problem_uuid` available only where solution links still need it.

- [ ] **Step 8: Re-run the completion toggle tests**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "completion_board_toggle"
```

Expected: PASS, including the existing legacy fallback test.


### Task 4: Convert dashboard contest listing to one row per active statement row

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/contest-dashboard-listing.html`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/urls.py`
- Test: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`

- [ ] **Step 1: Write the failing JBMO-style regression**

Add a test that creates:
- 7 `ProblemSolveRecord` rows for a contest/year
- 18 `ContestProblemStatement` rows for the same contest/year

Assert the dashboard contest listing shows 18 rows, not 7.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "contest_dashboard_listing_uses_statement_rows"
```

Expected: failure because the listing currently uses `_active_problem_records()`.

- [ ] **Step 3: Rewrite `_build_contest_problem_listing_context` for a dashboard statement path**

Do not break the public contest page. Instead:
- keep the existing public helper for `contest_problem_list_view`
- add a dashboard-specific statement-first builder, for example:

```python
def _build_dashboard_contest_statement_listing_context(request, *, contest_name: str, contest_slug: str):
    ...
```

Base query:

```python
ContestProblemStatement.objects.filter(
    is_active=True,
    contest_name=contest_name,
)
```

- [ ] **Step 4: Make filters statement-first**

Apply `year`, `q`, and visibility directly on statement rows.

For linked metadata filters:
- `mohs`
- `topic`
- `tag`

filter only where linked metadata exists, while leaving unlinked rows visible when no such filter is active.

- [ ] **Step 5: Change row payload and grouping**

Each row should carry:
- `statement_id`
- `statement` fields (`contest_year_problem`, `day_label`, `problem_code`, `statement_latex`, render segments)
- linked enrichment if available
- completion state resolved through linked problem

Group by `statement.contest_year`.

- [ ] **Step 6: Update bulk inactive route**

Change `contest_dashboard_listing_bulk_update_view` to accept statement ids instead of problem UUIDs and update:

```python
ContestProblemStatement.objects.filter(id__in=selected_ids, is_active=True).update(is_active=False)
```

- [ ] **Step 7: Update the dashboard listing template**

Switch:
- checkbox values
- solved-date editor payloads
- sort metadata

from problem-row identity to statement-row identity.

Render unlinked rows with:
- blank `MOHS` / `Topic`
- `Unlinked` status in solved-date cell
- no completion editor controls

- [ ] **Step 8: Re-run the listing tests**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "contest_dashboard_listing"
```

Expected: PASS.


### Task 5: Convert contest dashboards to statement-row aggregates

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/contest-analytics.html`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/contest-advanced-analytics.html`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/dashboard-analytics.html`
- Test: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`

- [ ] **Step 1: Write failing tests for statement-row totals**

Add focused tests that prove:
- `contest_dashboard` counts statement rows per contest
- `contest_advanced_dashboard` year totals and solved rates are statement-row based
- `dashboard_analytics_view` charts/tables use statement rows as the primary unit

- [ ] **Step 2: Run the focused analytics tests to verify failure**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "contest_dashboard or contest_advanced_analytics or dashboard_analytics"
```

Expected: failures on totals that still use `ProblemSolveRecord`.

- [ ] **Step 3: Convert `contest_analytics_view`**

Replace `_active_problem_records()` contest totals with active statement-row aggregates:

```python
ContestProblemStatement.objects.filter(is_active=True)
```

Use linked enrichment only for optional MOHS/topic summaries.

- [ ] **Step 4: Convert `contest_advanced_analytics_view`**

Base all headline stats and year rows on active statement rows:
- `statement_total`
- `linked_total`
- `solved_statement_total`
- solved rate denominator = statement-row total in scope

Keep `MOHS` metrics derived through linked problems when available.

- [ ] **Step 5: Convert `dashboard_analytics_view`**

Switch the main dashboard charts/table to statement-row counts.

For the contest-year-vs-MOHS pivot:
- start from active statements
- derive MOHS from `linked_problem`
- leave rows without linked MOHS out of MOHS-specific bins instead of fabricating values

- [ ] **Step 6: Update template labels where needed**

If a card or chart is now counting statements, make the wording match.

Examples to audit:
- “Problems”
- “Visible now”
- “Contest totals”

- [ ] **Step 7: Re-run the analytics tests**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "contest_dashboard or contest_advanced_analytics or dashboard_analytics"
```

Expected: PASS.


### Task 6: Align other dashboard statement/technique views with active statement-first behavior

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/problem-statement-analytics.html`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/problem-statement-list.html`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/topic-tag-analytics.html`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/pages/user-activity-dashboard.html`
- Test: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`

- [ ] **Step 1: Write failing tests for active statement filtering**

Add tests asserting inactive statements do not appear in:
- statement list
- statement analytics
- dashboard technique analytics where statement-row counts are shown

- [ ] **Step 2: Run those tests to verify failure**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "problem_statement_list or problem_statement_analytics or topic_tag_analytics"
```

Expected: failure because these pages still use `ContestProblemStatement.objects.all()`.

- [ ] **Step 3: Switch statement pages to active-statement base**

Update statement-first dashboard pages to start from:

```python
_active_dashboard_statements()
```

instead of `ContestProblemStatement.objects.all()`.

- [ ] **Step 4: Review technique analytics semantics**

For `topic_tag_analytics_view`, make statement rows the counting unit where possible:
- build counts from active statements
- enrich tags through linked problems
- unlinked statements simply contribute no technique metadata

Keep labels honest if some cards remain “linked-technique coverage” rather than pure statement totals.

- [ ] **Step 5: Review user activity statement heatmaps**

Update statement-backed user activity totals to use active statement rows only, while keeping completion storage unchanged.

- [ ] **Step 6: Re-run the statement/technique tests**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "problem_statement_list or problem_statement_analytics or topic_tag_analytics or user_activity_dashboard"
```

Expected: PASS.


### Task 7: Verify public pages remain unchanged

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`

- [ ] **Step 1: Add a regression test for public contest listing**

Create a mixed fixture where:
- statement rows outnumber problem rows
- dashboard listing should show statement rows
- public contest page should still show problem-record rows

- [ ] **Step 2: Add public visibility regression coverage**

Extend coverage to:
- `problem_list_view`
- `contest_problem_list_view`
- `problem_detail_view`

so statement visibility work cannot accidentally unhide legacy inactive
`ProblemSolveRecord` rows on public pages.

- [ ] **Step 3: Run the public-page regression before final verification**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py -k "problem_list or contest_problem_list or problem_detail"
```

Expected: PASS with unchanged public behavior.

- [ ] **Step 4: Run the full pages test suite**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py
```

Expected: all page tests green.

- [ ] **Step 5: Run Django system checks**

Run:

```bash
uv run python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Confirm migration state**

Run:

```bash
uv run python manage.py makemigrations --check pages
```

Expected: no pending migrations.


### Task 8: Cleanup, review, and handoff

**Files:**
- Review only: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/views.py`
- Review only: `/Users/stevenchew/Dev/AsterProof/inspinia/pages/tests.py`
- Review only: touched dashboard templates and migration files

- [ ] **Step 1: Review the diff for accidental public-page regressions**

Inspect:

```bash
git diff -- inspinia/pages/views.py inspinia/pages/tests.py inspinia/templates/pages
```

Focus on:
- public contest pages
- completion write paths
- statement visibility rules

- [ ] **Step 2: Review for misleading labels**

Check templates for cards still labeled “Problems” after they now count statements.

- [ ] **Step 3: Review for row-identity consistency**

Confirm:
- dashboard row selection uses `statement_id`
- bulk inactive uses `statement_id`
- solved-date writes resolve from `statement_id`
- legacy `problem_uuid` fallback remains only where intended

- [ ] **Step 4: Prepare final summary**

Include:
- what changed
- which dashboard pages are now statement-first
- what still remains problem-record-first by design
- note that public pages still rely on legacy `ProblemSolveRecord.is_active`
