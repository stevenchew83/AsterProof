# Login Redirect And Admin Role Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every successful login to `My activity`, even when `next` is present, while keeping role changes on the existing admin-only `User roles` page and adding focused regression coverage around it.

**Architecture:** Use two redirect control points. Override the custom allauth `AccountAdapter` early enough that non-signup logins supply an explicit redirect target and bypass allauth's usual `next` precedence, then simplify `UserRedirectView` so any remaining `LOGIN_REDIRECT_URL` callers also land on `pages:user_activity_dashboard`. Reuse the existing `manage_user_roles_view` and `users/manage_roles.html`, changing only copy and tests rather than adding a new admin workflow.

**Tech Stack:** Django 5.1, django-allauth, Django test client, existing `User` and `AuditEvent` models, Bootstrap/Inspinia templates, pytest

---

**Implementation rules:** Use @superpowers:test-driven-development for each red/green cycle. Use @superpowers:verification-before-completion before claiming a task is complete.

## File Map

- `/Users/stevenchew/Dev/AsterProof/inspinia/users/adapters.py`
  - Custom allauth adapter. Add the login-only redirect override here so non-signup logins ignore `next` and always point at `pages:user_activity_dashboard`.
- `/Users/stevenchew/Dev/AsterProof/inspinia/users/views.py`
  - Keep `UserRedirectView` aligned with the new single landing page and leave `manage_user_roles_view()` as the existing admin-only save surface.
- `/Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py`
  - Add the redirect regression tests and the new role-page access/save tests here. Keep any login helper local to this file; do not import private helpers from another test module.
- `/Users/stevenchew/Dev/AsterProof/inspinia/templates/users/manage_roles.html`
  - Tighten the admin-only explanatory copy while keeping the current table-and-inline-save layout intact.
- `/Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_monitoring.py`
  - Existing login/session smoke coverage. Re-run it after the adapter change to confirm signals and tracked-session behavior still work.

### Task 1: Force every successful login to land on My activity

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/users/adapters.py:16-48`
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/users/views.py:296-305`
- Test: `/Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py:126-142`

- [ ] **Step 1: Write the failing redirect tests**

In `/Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py`, add a local login helper and two redirect assertions:

```python
from allauth.account.models import EmailAddress

TEST_PASSWORD = "StrongPass123!"  # noqa: S105


def _verify_email(user: User) -> None:
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": True},
    )


class TestUserRedirectView:
    def test_get_redirect_url_for_non_admin_user(self, user: User, rf: RequestFactory):
        view = UserRedirectView()
        request = rf.get("/fake-url")
        request.user = user

        view.request = request
        assert view.get_redirect_url() == reverse("pages:user_activity_dashboard")

    def test_get_redirect_url_for_admin_user(self, rf: RequestFactory):
        admin_user = UserFactory(role=User.Role.ADMIN)
        view = UserRedirectView()
        request = rf.get("/fake-url")
        request.user = admin_user

        view.request = request
        assert view.get_redirect_url() == reverse("pages:user_activity_dashboard")


def test_account_login_ignores_next_and_lands_on_my_activity(client: Client):
    user = UserFactory(password=TEST_PASSWORD)
    _verify_email(user)

    response = client.post(
        f"{reverse('account_login')}?next={reverse('users:update')}",
        {"login": user.email, "password": TEST_PASSWORD},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.request["PATH_INFO"] == reverse("pages:user_activity_dashboard")
```

Update the existing `TestUserRedirectView` block instead of creating a duplicate class, and keep the helper in this file so the test stays self-contained.

- [ ] **Step 2: Run the focused redirect tests to verify failure**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py -k "UserRedirectView or ignores_next" -v
```

Expected:
- the admin redirect test fails because `UserRedirectView` still returns `pages:dashboard`
- the login integration test fails because allauth still honors `next`

- [ ] **Step 3: Override the allauth login redirect early enough to bypass `next`**

In `/Users/stevenchew/Dev/AsterProof/inspinia/users/adapters.py`, import `reverse` and add a `post_login()` override that only forces the redirect for non-signup logins:

```python
from django.urls import reverse


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def post_login(
        self,
        request: HttpRequest,
        user: User,
        *,
        email_verification,
        signal_kwargs,
        email,
        signup,
        redirect_url,
    ):
        if not signup:
            redirect_url = reverse("pages:user_activity_dashboard")
        return super().post_login(
            request,
            user,
            email_verification=email_verification,
            signal_kwargs=signal_kwargs,
            email=email,
            signup=signup,
            redirect_url=redirect_url,
        )
```

This keeps signup behavior unchanged while ensuring login requests no longer let `next` override the product landing page.

- [ ] **Step 4: Simplify the fallback redirect view**

In `/Users/stevenchew/Dev/AsterProof/inspinia/users/views.py`, make `UserRedirectView` unconditionally return `pages:user_activity_dashboard`:

```python
class UserRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self) -> str:
        return reverse("pages:user_activity_dashboard")
```

Do not touch any unrelated admin-routing logic in this step.

- [ ] **Step 5: Re-run the focused redirect tests**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py -k "UserRedirectView or ignores_next" -v
```

Expected: PASS.

- [ ] **Step 6: Smoke-test existing login/session behavior**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_monitoring.py -k "login_creates_tracked_session_and_login_event or logout_marks_tracked_session_as_logged_out" -v
```

Expected: PASS, proving the adapter override did not break login signals, tracked sessions, or logout handling.

- [ ] **Step 7: Commit the redirect change**

```bash
git add /Users/stevenchew/Dev/AsterProof/inspinia/users/adapters.py /Users/stevenchew/Dev/AsterProof/inspinia/users/views.py /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py
git commit -m "fix auth redirect to always land on My activity"
```


### Task 2: Tighten the existing admin role page and add direct coverage

**Files:**
- Modify: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/users/manage_roles.html:24-82`
- Test: `/Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py`

- [ ] **Step 1: Write the failing role-page tests**

In `/Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py`, add a new `TestManageRolesView` block that covers access control, successful saves, invalid submissions, and the new page copy:

```python
from inspinia.users.models import AuditEvent


class TestManageRolesView:
    def test_redirects_anonymous_user_to_login(self, client: Client):
        response = client.get(reverse("users:manage_roles"))

        assert response.status_code == HTTPStatus.FOUND
        assert response.url == f"{reverse(settings.LOGIN_URL)}?next={reverse('users:manage_roles')}"

    def test_forbids_non_admin_user(self, client: Client):
        member = UserFactory(role=User.Role.NORMAL)
        client.force_login(member)

        response = client.get(reverse("users:manage_roles"))

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_admin_can_update_role_and_record_audit_event(self, client: Client):
        admin_user = UserFactory(role=User.Role.ADMIN)
        target_user = UserFactory(role=User.Role.NORMAL)
        client.force_login(admin_user)

        response = client.post(
            reverse("users:manage_roles"),
            {"user_id": target_user.pk, "role": User.Role.MODERATOR},
            follow=True,
        )

        target_user.refresh_from_db()

        assert response.status_code == HTTPStatus.OK
        assert response.request["PATH_INFO"] == reverse("users:manage_roles")
        assert target_user.role == User.Role.MODERATOR
        assert f"Updated role for {target_user.email}" in response.content.decode("utf-8")
        assert "Admin-only role settings" in response.content.decode("utf-8")
        assert AuditEvent.objects.filter(
            event_type=AuditEvent.EventType.ROLE_CHANGED,
            actor=admin_user,
            target_user=target_user,
        ).exists()

    def test_rejects_invalid_role(self, client: Client):
        admin_user = UserFactory(role=User.Role.ADMIN)
        target_user = UserFactory(role=User.Role.NORMAL)
        client.force_login(admin_user)

        response = client.post(
            reverse("users:manage_roles"),
            {"user_id": target_user.pk, "role": "owner"},
            follow=True,
        )

        target_user.refresh_from_db()

        assert response.status_code == HTTPStatus.OK
        assert target_user.role == User.Role.NORMAL
        assert "Invalid user or role." in response.content.decode("utf-8")

    def test_rejects_invalid_user_id(self, client: Client):
        admin_user = UserFactory(role=User.Role.ADMIN)
        client.force_login(admin_user)

        response = client.post(
            reverse("users:manage_roles"),
            {"user_id": "999999", "role": User.Role.ADMIN},
            follow=True,
        )

        assert response.status_code == HTTPStatus.OK
        assert "Invalid user or role." in response.content.decode("utf-8")
```

The explicit `"Admin-only role settings"` assertion is the intentional red test for the copy change.

- [ ] **Step 2: Run the focused role-page tests to verify failure**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py -k "manage_roles" -v
```

Expected: failure because the new admin-only explanatory copy is not present yet. If any access/save assertion also fails, fix only that specific branch in the next step.

- [ ] **Step 3: Update the role-page copy without redesigning the workflow**

In `/Users/stevenchew/Dev/AsterProof/inspinia/templates/users/manage_roles.html`, keep the current table and inline save UI, but change the header copy to something in this shape:

```django
<div class="card-header border-0 pb-0">
  <h4 class="header-title mb-0">{% translate "User roles" %}</h4>
  <p class="text-muted fs-xs mb-0">
    {% translate "Admin-only role settings. Admin unlocks the admin tools and admin navigation. Moderator, trainer, and normal are reserved for future permissions." %}
  </p>
  <p class="text-muted fs-xs mb-0 mt-2">
    {% translate "Use this page to set each user's application role one account at a time." %}
  </p>
</div>
```

Do not add search, pagination, bulk actions, or a second route in this task.

- [ ] **Step 4: Fix only any real logic gap the new tests expose**

If one of the new access/save assertions fails, patch only the failing branch in:

```python
manage_user_roles_view()
```

inside `/Users/stevenchew/Dev/AsterProof/inspinia/users/views.py`, while preserving:
- `@login_required`
- `_require_app_admin(request)`
- the existing POST contract (`user_id`, `role`)
- redirect-back-to-self behavior after POST
- `ROLE_CHANGED` audit creation only when the role actually changes

No broader refactor belongs in this task.

- [ ] **Step 5: Re-run the focused role-page tests**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py -k "manage_roles" -v
```

Expected: PASS.

- [ ] **Step 6: Commit the role-page work**

```bash
git add /Users/stevenchew/Dev/AsterProof/inspinia/templates/users/manage_roles.html /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py
git commit -m "test and clarify admin role management"
```


### Task 3: Run the full users-app verification slice and review the diff

**Files:**
- Review only: `/Users/stevenchew/Dev/AsterProof/inspinia/users/adapters.py`
- Review only: `/Users/stevenchew/Dev/AsterProof/inspinia/users/views.py`
- Review only: `/Users/stevenchew/Dev/AsterProof/inspinia/templates/users/manage_roles.html`
- Review only: `/Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py`
- Review only: `/Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_monitoring.py`
- Review only: `/Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_urls.py`

- [ ] **Step 1: Run the full targeted users test slice**

Run:

```bash
uv run pytest /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_monitoring.py /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_urls.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run users-app linting**

Run:

```bash
uv run ruff check /Users/stevenchew/Dev/AsterProof/inspinia/users
```

Expected: `All checks passed!`

- [ ] **Step 3: Run Django system checks**

Run:

```bash
uv run python /Users/stevenchew/Dev/AsterProof/manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Review the final diff for scope control**

Inspect:

```bash
git diff -- /Users/stevenchew/Dev/AsterProof/inspinia/users/adapters.py /Users/stevenchew/Dev/AsterProof/inspinia/users/views.py /Users/stevenchew/Dev/AsterProof/inspinia/templates/users/manage_roles.html /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py
```

Confirm:
- login redirect changes stay inside `adapters.py` and `UserRedirectView`
- no signup behavior was intentionally widened unless tests proved it necessary
- role-page changes are copy and regression coverage, not a new workflow
- permission checks still rely on `_require_app_admin(request)`

- [ ] **Step 5: Commit only if verification cleanup changed files**

If the verification pass required any last small cleanup, commit it with:

```bash
git add /Users/stevenchew/Dev/AsterProof/inspinia/users/adapters.py /Users/stevenchew/Dev/AsterProof/inspinia/users/views.py /Users/stevenchew/Dev/AsterProof/inspinia/templates/users/manage_roles.html /Users/stevenchew/Dev/AsterProof/inspinia/users/tests/test_views.py
git commit -m "polish auth redirect and role page verification"
```

If no files changed after Task 2, skip this step and leave the branch on the Task 2 commit.
