# Sidebar Regrouping Design

## Goal

Regroup the authenticated app sidebar so it reads like a balanced product
navigation for both everyday users and admin operators.

The desired outcome is not a new permission model or a new route structure. It
is a clearer information architecture that helps people predict where a page
lives based on what they are trying to do:

- work on their own activity and progress
- browse the library
- operate rankings
- inspect analytics and records
- maintain archive data
- use standalone helper tools
- perform system administration

## Confirmed Decisions

1. The sidebar should optimize for a **balanced mix** of user and
   admin/operator workflows.
2. Renaming section titles and selected menu labels is allowed when it improves
   clarity.
3. Existing destinations should remain available; the change is primarily about
   grouping, ordering, and labeling.
4. Existing permission gates should remain unchanged.

## Current Repo Context

The current sidebar is defined directly in
`inspinia/templates/partials/sidenav.html` and uses role/context flags from
`inspinia/users/context_processors.py`.

Relevant current behavior:

- `show_user_activity_dashboard_link`,
  `show_contest_advanced_dashboard_link`, and
  `show_solution_workspace_link` expose authenticated user pages.
- `show_analytics_dashboard_link` and `show_problem_import_link` expose
  operator/admin tools.
- `is_app_admin`, `show_session_monitor_link`, and `show_event_log_link`
  control true admin-only pages.

The current grouping mostly follows implementation ownership and permission
flags rather than user jobs. That creates a few navigation mismatches:

- data-maintenance pages and read-only records are split across `Analytics`,
  `Curation`, and `Tools`
- ranking operations are grouped well internally, but their import workflow is
  labeled too generically as `Import center`
- helper utilities and archive-maintenance tools both live under `Tools` or
  nearby sections even though they serve very different purposes

## Design Principles

### Group by user job, not by app ownership

The sidebar should answer "what am I here to do?" before it answers which app
or code module owns a page.

### Preserve familiar product areas

`Rankings` is already a coherent product area and should stay together.

### Separate reading from changing

Read-heavy dashboards and record inventories should not be mixed with imports,
editing, deduplication, or deletion workflows.

### Keep permissions stable

This regrouping should not widen or narrow access. A page that is hidden today
should stay hidden for the same users after the regrouping.

## Proposed Sidebar Architecture

### Home

- `Overview`

### Workspace

- `My account`
- `My activity`
- `Contest progress`
- `My solutions`

### Library

- `Problem statements`

### Rankings

- `Ranking table`
- `Ranking dashboard`
- `Students`
- `Assessments`
- `Formulas`
- `Ranking imports`

### Insights

- `Problem analytics`
- `Contest analytics`
- `Technique analytics`
- `Statement analytics`
- `Completion records`
- `Solution records`

### Operations

- `Problem data`
- `Contest names`
- `Contest details`
- `Statement links`
- `Statement editor`
- `Statement metadata`
- `Statement duplicates`
- `Delete statement`

### Utilities

- `LaTeX preview`
- `Handle parser`

### Admin

- `User roles`
- `Session monitor`
- `Event log`

## Labeling Rules

### Section titles

- `Workspace` means "things I do for myself"
- `Library` means "browse reference content"
- `Rankings` means "ranking models, students, assessments, and ranking data
  operations"
- `Insights` means "analysis and read-only record inspection"
- `Operations` means "import, curate, relink, backfill, dedupe, edit, or
  delete archive data"
- `Utilities` means "standalone helper tools"
- `Admin` means "authorization, monitoring, and audit"

### Page labels

Approved label adjustments:

- `Import center` becomes `Ranking imports`
- `Delete statement (UUID)` is shortened in the menu to `Delete statement`

Labels that should remain unchanged in this design:

- `Problem data`
- `Contest names`
- `Contest details`
- `Statement links`
- `Statement editor`
- `Statement metadata`
- `Statement duplicates`
- `LaTeX preview`
- `Handle parser`

Keeping these names reduces change surface while still making the overall
navigation easier to scan.

## Placement Decisions For Ambiguous Pages

### `Completion records` and `Solution records`

These belong under `Insights`, not `Workspace` or `Operations`.

Reason:

- they are cross-user inventories, not personal working surfaces
- they support inspection and reporting more than data mutation

### Statement pages

Statement pages split into two groups:

- `Statement analytics` belongs under `Insights`
- `Statement links`, `Statement editor`, `Statement metadata`,
  `Statement duplicates`, and `Delete statement` belong under `Operations`

Reason:

- analytics is read-oriented
- linker/editor/metadata/dedup/delete flows are maintenance operations

### Helper tools

`LaTeX preview` and `Handle parser` belong under `Utilities`, not
`Operations`.

Reason:

- they are standalone helper workspaces
- they do not directly represent archive curation or ranking maintenance flows

## Implementation Shape

This should be implemented as a focused navigation change.

### Primary touch points

- `inspinia/templates/partials/sidenav.html`
  - reorder section titles
  - reorder links within sections
  - rename selected menu labels
- `inspinia/pages/tests.py`
  - update sidebar assertions to match the new grouping and ordering

### Keep unchanged

- `inspinia/users/context_processors.py`
  - continue using the current role/visibility flags
- routes, URL names, and page-level permission checks
- page titles unless implementation discovers a specific mismatch that is
  confusing enough to justify a separate change

### Non-goals

- no permission changes
- no route changes
- no new dynamic sidebar abstraction
- no topbar redesign as part of this task
- no reclassification of ownership between the `pages`, `rankings`, or
  `users` apps

## Expected User Experience Outcome

After the regrouping:

- personal workflow pages are found together under `Workspace`
- the library explorer remains easy to find
- rankings remains a clear dedicated product area
- analytics and records are easier to discover under one read-oriented section
- maintenance tools stop feeling scattered between `Analytics`, `Curation`,
  and `Tools`
- standalone utilities stop competing with archive-maintenance pages

## Validation Strategy

### Automated checks

Run the nearest navigation-focused tests in `inspinia/pages/tests.py`,
including the existing sidebar ordering assertions that cover an admin-visible
page.

Update the sidebar assertions to verify:

- presence of the new section titles
- presence of the expected links
- relative ordering across the new section boundaries

### Manual sanity checks

Confirm that:

- authenticated non-admin users still only see the sections allowed by the
  current flags
- admin users still see the full operator and admin navigation
- admin-only links remain hidden from non-admin users

## Risks

### Muscle-memory disruption

Users who know the current layout may need a short adjustment period, even
though the new grouping is clearer.

Mitigation:

- keep page labels mostly familiar
- preserve the actual destinations and permissions

### Test brittleness

Existing tests assert concrete menu ordering and section names.

Mitigation:

- update those tests in the same change as the template
- keep the assertions focused on meaningful structure rather than every single
  adjacent pair

### Boundary ambiguity

Some pages naturally sit between categories, especially records vs analytics or
tools vs operations.

Mitigation:

- codify the placement rules in this design so future additions follow the same
  logic

## Recommended Implementation Follow-up

The implementation plan for this design should stay intentionally small:

1. update the sidebar partial
2. update the matching sidebar tests
3. run focused verification for navigation rendering

This is a navigation IA improvement, not a broader dashboard refactor.
