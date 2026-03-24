# Contest advanced analytics: personal completions and open access

## Goal

The **contest advanced analytics** page (`/dashboard/contests/advanced/`) must show **only the signed-in user’s** `UserProblemCompletion` data in the **heatmap** and **year-by-year solved metrics**, not aggregate completions across all users. **Any authenticated user** may open this page (`@login_required` only). **Admin-only** analytics pages (`contest_analytics_view`, `contest_dashboard_listing_view`, etc.) stay unchanged unless separately specified.

## Context

- **View:** `contest_advanced_analytics_view` in `inspinia/pages/views.py` currently calls `_require_admin_tools_access` and builds completion sets without filtering by `user`, so the heatmap and `solved_problem_total` / `solved_rate` reflect **global** completion activity.
- **Model:** `UserProblemCompletion` is keyed per user with unique constraints on `(user, statement)` and `(user, problem)`.
- **Navigation:** Today, drill-down from the main contest analytics table is admin-gated; non-admins need a **direct path** (sidenav) to the advanced page.
- **Year links:** `year_detail_url` today points at `contest_dashboard_listing`, which remains **`_require_admin_tools_access`** — non-admins would get **403** after this change unless URLs are conditional.

## Decision (approved)

1. **Remove** `_require_admin_tools_access` from **`contest_advanced_analytics_view`** only; keep **`@login_required`**. Anonymous users continue to hit the login flow.
2. **Scope completion-derived data** to **`request.user`**:
   - Heatmap: both `UserProblemCompletion` queries that collect solved statement/problem IDs must include **`user=request.user`**.
   - Year rows: `solved_problem_total` `Count` filters must require **`user_completions__user=request.user`** OR **`linked_problem__user_completions__user=request.user`** (equivalent distinct statement count semantics preserved, but per viewer).
3. **Conditional `year_detail_url`:**
   - If **`user_has_admin_role(request.user)`** (reuse `inspinia.users.roles.user_has_admin_role`): keep current URL to **`contest_dashboard_listing`** with `contest` + `year`.
   - Else: URL to **`pages:contest_problem_list`** for the contest slug plus **`year`** query (same slug resolution pattern as existing `public_contest_url` / `_build_contest_slug_maps`).
4. **Sidenav:** Add a **Personal** (or equivalent) item for **authenticated** users linking to `pages:contest_advanced_dashboard`, controlled by a new context-processor flag (e.g. `show_contest_advanced_dashboard_link`), mirroring patterns like `show_user_activity_dashboard_link`.
5. **Copy:** Replace misleading strings such as **“Solved by at least one user”** with wording that reflects **personal** completion (e.g. “Your completions”), in `contest-advanced-analytics.html` and any related help text on that page.
6. **Leave global** statement aggregates on that page (e.g. MOHS/topic counts over statements) **unchanged** — they are not completion-scoped.

## Out of scope

- Opening **`contest_analytics_view`** or **`contest_dashboard_listing_view`** to non-admins.
- Changing `ProblemSolution` or import pipelines.
- Backend caching or performance work beyond necessary query filters.

## Success criteria

- Logged-in **normal** user: **200** on `/dashboard/contests/advanced/?contest=…`, heatmap and year solved counts match **only** their `UserProblemCompletion` rows.
- Logged-in **admin**: same personal scoping for their own completions (not global completion totals).
- **Non-admin** year row link opens **contest problem list** with year filter, not admin dashboard listing.
- **Anonymous**: redirected to login for this view.
- **Tests** updated/added to lock the above behavior; existing unrelated contest tests still pass.

## Notes for implementation planning

- Update **`test_contest_advanced_analytics_view_renders_selected_contest_breakdown`** so the logged-in user aligns with completion rows (or create completions for the logged-in user).
- Consider a tiny helper in `views.py` for “completion queryset for user + contest slice” only if it reduces duplication without growing `views.py` unnecessarily.
