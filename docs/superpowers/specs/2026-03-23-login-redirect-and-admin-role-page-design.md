# Login Redirect And Admin Role Page Design

## Goal

Make successful login always land on `My activity`, and treat the existing
admin-only `User roles` page as the official place to set user roles.

## Context

The repo already has both pieces of this workflow, but they are not aligned
with the desired product behavior:

- `UserRedirectView` currently branches by role:
  - admin users go to `pages:dashboard`
  - non-admin users go to `pages:user_activity_dashboard`
- an admin-only role-management page already exists at `users:manage_roles`
- that page is already linked from admin navigation in the side menu and
  topbar dropdown

This means the requested work is not a greenfield auth feature. It is a small,
focused adjustment to:

1. simplify the post-login destination, and
2. formalize the existing admin-only role page as the supported role-setting
   UI.

## Scope

### In scope

- change post-login redirect behavior so all successful logins route to
  `pages:user_activity_dashboard`
- keep using the existing `users:manage_roles` page for admin role updates
- improve the page copy enough that it reads like an intentional admin tool
- add focused automated coverage for:
  - the new redirect rule
  - role-page access control
  - successful role changes
  - invalid role submissions
  - audit-event creation on actual role change

### Out of scope

- self-service role changes by regular users
- creating a second role-management page
- changing what each role means in the broader product
- changing role-based access outside the already existing admin checks
- bulk role editing, search, pagination, or other admin tooling expansion
- hardcoding the production URL in Python or templates

## Core decisions

### Single post-login destination

After a successful login, every authenticated user should land on
`pages:user_activity_dashboard`.

Reason:

- the requirement is explicit: always send users to
  `http://18.142.249.181/dashboard/my-activity/`
- using the named route keeps local, test, and production environments aligned
  without baking a host name into application code
- it removes unnecessary role-based branching from login behavior

For this task, "always" includes interactive login requests that arrive with a
`next` parameter from `@login_required` or a manually supplied login URL.
Successful sign-in should still end on `pages:user_activity_dashboard` instead
of honoring `next`.

In production, `reverse("pages:user_activity_dashboard")` resolves to
`/dashboard/my-activity/`, which is the desired destination.

### Reuse the existing admin-only role page

The existing `users:manage_roles` route and `users/manage_roles.html` template
should remain the single role-setting surface.

Reason:

- the app already has the URL, view, template, and admin nav links
- the requested feature is "need a page to set user role", and that page
  already exists
- adding a second page would duplicate behavior and create more admin surface
  area for no product gain

### Keep permissions unchanged

The role page should remain admin-only.

Reason:

- `User.role` is the primary product authorization field
- allowing self-service changes would expand permissions far beyond the request
- the current `_require_app_admin()` boundary is already the correct shape

### Keep the existing one-row save pattern

The page should continue to use one user per row, one role select, and one
save action.

Reason:

- this flow already works with the current view contract
- it is easy to reason about and easy to test
- it avoids turning a small auth/admin task into a broader UX redesign

## UX design

### Login flow

Successful login should follow this simple path:

1. user signs in through allauth
2. post-auth redirect logic ignores any supplied `next` destination for this
   product flow
3. Django resolves `LOGIN_REDIRECT_URL = "users:redirect"` or equivalent
   login redirect logic to the same final destination
4. `UserRedirectView` or equivalent login redirect handling always returns
   `reverse("pages:user_activity_dashboard")`

Admins will still be able to reach the analytics dashboard through the existing
admin navigation after login. The change only affects the first landing page.

### Role page placement

Keep the current navigation placement:

- side nav under the admin section
- topbar account dropdown for admin users

No new route name is needed. `users:manage_roles` remains the canonical admin
entry point.

### Role page copy

Polish the current page copy so it makes the page purpose clearer:

- state that the page is admin-only
- explain that `Admin` unlocks the admin tools and admin navigation
- keep the note that moderator, trainer, and normal are reserved for future
  permissions unless implementation reveals a more accurate product statement
- clarify that changing a role affects what admin surfaces a user can access

This should be done with the existing dashboard card/table structure, not a new
layout.

## Data and save behavior

The current POST contract is already appropriate and should be preserved:

- `user_id` identifies the target user
- `role` must be one of `User.Role.choices`
- invalid user ids or invalid roles show an error flash message
- successful saves show a success flash message
- the view redirects back to `users:manage_roles` after POST

Audit behavior should remain:

- if the submitted role differs from the previous role, create a
  `ROLE_CHANGED` audit event
- if the submitted role is unchanged, do not create a duplicate role-change
  event

## Implementation touch areas

- `inspinia/users/views.py`
  - simplify `UserRedirectView.get_redirect_url()`
  - keep `manage_user_roles_view()` behavior intact unless small copy/context
    additions are needed
- `inspinia/users/adapters.py`
  - likely touch point if ignoring allauth's `next` handling requires login
    redirect behavior earlier than `UserRedirectView`
- `inspinia/templates/users/manage_roles.html`
  - refine explanatory copy while keeping the current table-based admin flow
- `inspinia/users/tests/test_views.py`
  - update redirect expectations
  - add focused tests for the role-management page

No route changes are required unless implementation finds a hidden dependency.

## Testing strategy

Add or update focused tests in `inspinia/users/tests/test_views.py`.

### Required redirect coverage

1. non-admin user redirect returns `reverse("pages:user_activity_dashboard")`
2. admin user redirect also returns `reverse("pages:user_activity_dashboard")`
3. successful login ignores a supplied `next` destination and still lands on
   `pages:user_activity_dashboard`

### Required role-page coverage

1. anonymous user is redirected to login
2. authenticated non-admin user gets `403`
3. authenticated admin user gets `200`
4. admin POST with a valid target user and valid role:
   - updates the user record
   - redirects back to `users:manage_roles`
   - shows the success message
   - creates the expected `ROLE_CHANGED` audit event when the role changes
5. admin POST with an invalid role:
   - does not change the stored role
   - shows the existing error message
6. admin POST with an invalid user id:
   - does not change any user role
   - shows the existing error message

### Optional helpful coverage

- confirm the page renders the expected headings or form controls for an admin
- confirm unchanged-role saves do not emit a new role-change audit event

The unchanged-role audit check is useful, but not required for the first
implementation plan if it would add disproportionate setup cost.

## Risks

### Admin landing-page expectation shift

Admins currently land on `pages:dashboard`. After this change they will land on
`My activity` first. That is intentional, but it is still a behavior change.

Mitigation:

- keep admin navigation to the analytics dashboard unchanged

### Permission regression

The biggest risk is accidentally widening access to role management while
touching login and role-related code in the same change.

Mitigation:

- preserve `_require_app_admin()` in the role-management view
- add direct tests for anonymous and non-admin access

### Overstating role semantics

The current page copy already says moderator and trainer are reserved for future
permissions. That should remain true unless the implementation step uncovers
current behavior that needs a more precise statement.

Mitigation:

- keep the page copy accurate to current product behavior
- avoid inventing new role descriptions in this task

## Acceptance criteria

The work is complete when:

- every successful login redirects through `users:redirect` to
  `pages:user_activity_dashboard`, or equivalent login redirect handling if the
  final implementation must intercept allauth's `next` behavior earlier
- supplied `next` destinations do not override the `My activity` landing page
  for this product flow
- on the live site that route resolves to `/dashboard/my-activity/`
- the existing `users:manage_roles` page remains the single admin-only place to
  set user roles
- admins can change another user's role from that page
- actual role changes create the existing audit event
- focused tests cover redirect behavior and role-page access/save behavior
