# User Approval Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-controlled user approval workflow so newly registered users cannot access authenticated AsterProof features until an admin approves them.

**Architecture:** Store approval as an additive boolean on the existing custom `User` model, with admins and superusers treated as approved to avoid lockout. Enforce approval centrally through middleware after Django/allauth authentication, while exempting login/signup/logout/account routes and a new approval-pending page. Extend the existing admin-only `User roles` page into a combined role-and-approval console, recording approval changes in `AuditEvent`.

**Tech Stack:** Django 5.1, django-allauth, custom `inspinia.users.User`, Django middleware, Bootstrap/Inspinia templates, pytest, factory_boy

---

**Implementation rules:** Use @superpowers:test-driven-development for each red/green cycle. Use @superpowers:verification-before-completion before claiming implementation is complete.

## Decisions

- New normal users are unapproved by default.
- Existing admin-role users and Django superusers are approved during migration.
- `UserFactory` defaults to approved so existing tests keep representing users who can use the app; tests that need pending users must pass `is_approved=False`.
- Unapproved authenticated users may access only `/accounts/` allauth routes, `/admin/`, static/media, and `users:approval_pending`.
- Admins and superusers are treated as effectively approved by the helper even if the stored boolean is false.
- The existing page at `users:manage_roles` remains the admin console, but its title and copy become "User access" because it now controls roles and approval.

## File Map

- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/models.py`
  - Add `User.is_approved`.
  - Add `AuditEvent.EventType.APPROVAL_CHANGED`.
  - Return warning badge styling for approval events.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/managers.py`
  - Ensure `create_superuser()` stores `is_approved=True`.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/roles.py`
  - Add `user_can_access_app_features()` and reuse `user_has_admin_role()`.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/middleware.py`
  - Add `RequireApprovedUserMiddleware`.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/config/settings/base.py`
  - Insert approval middleware after allauth account middleware and before session tracking.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/views.py`
  - Add `approval_pending_view()`.
  - Update `manage_user_roles_view()` to save role and approval together.
  - Include approval events in event-log admin action counts.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/urls.py`
  - Add `approval-pending/`.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/admin.py`
  - Expose approval in Django admin list, filters, and fieldsets.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/context_processors.py`
  - Add `is_app_approved` and require approval for feature navigation flags.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/users/manage_roles.html`
  - Rename copy to "User access".
  - Add approval column and per-user approval control.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/users/approval_pending.html`
  - New pending-access page.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/partials/sidenav.html`
  - Hide app feature links for unapproved users.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/partials/topbar.html`
  - Hide profile/app-admin links for unapproved users while leaving email, MFA, and logout available.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/factories.py`
  - Set factory default `is_approved=True`.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_managers.py`
  - Cover default approval state for normal users and superusers.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_roles.py`
  - New helper-level tests.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_approval_gate.py`
  - New middleware and pending-page tests.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_views.py`
  - Extend manage-roles tests for approval saves and page copy.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_models.py`
  - Cover approval audit badge styling.
- `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_context_processors.py`
  - New navigation flag tests.

### Task 1: Add Approval State And Access Helper

**Files:**
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/models.py`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/managers.py`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/roles.py`
- Create: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/migrations/0007_user_is_approved_and_approval_audit_event.py`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/factories.py`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_managers.py`
- Create: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_roles.py`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_models.py`

- [ ] **Step 1: Write the failing manager tests**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_managers.py`, extend the existing tests:

```python
def test_create_user(self):
    user = User.objects.create_user(
        email="john@example.com",
        password="something-r@nd0m!",  # noqa: S106
    )
    assert user.email == "john@example.com"
    assert not user.is_staff
    assert not user.is_superuser
    assert not user.is_approved
    assert user.check_password("something-r@nd0m!")
    assert user.username is None

def test_create_superuser(self):
    user = User.objects.create_superuser(
        email="admin@example.com",
        password="something-r@nd0m!",  # noqa: S106
    )
    assert user.email == "admin@example.com"
    assert user.is_staff
    assert user.is_superuser
    assert user.is_approved
    assert user.username is None
```

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_managers.py -k "create_user or create_superuser" -v
```

Expected: FAIL with `AttributeError` because `User.is_approved` does not exist yet.

- [ ] **Step 2: Write the failing role-helper tests**

Create `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_roles.py`:

```python
from django.contrib.auth.models import AnonymousUser

from inspinia.users.models import User
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.tests.factories import UserFactory


def test_anonymous_user_cannot_access_app_features():
    assert user_can_access_app_features(AnonymousUser()) is False


def test_unapproved_normal_user_cannot_access_app_features():
    user = UserFactory(role=User.Role.NORMAL, is_approved=False)

    assert user_can_access_app_features(user) is False


def test_approved_normal_user_can_access_app_features():
    user = UserFactory(role=User.Role.NORMAL, is_approved=True)

    assert user_can_access_app_features(user) is True


def test_admin_role_can_access_app_features_even_if_boolean_is_false():
    user = UserFactory(role=User.Role.ADMIN, is_approved=False)

    assert user_can_access_app_features(user) is True


def test_superuser_can_access_app_features_even_if_boolean_is_false():
    user = UserFactory(is_superuser=True, is_approved=False)

    assert user_can_access_app_features(user) is True
```

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_roles.py -v
```

Expected: FAIL on import because `user_can_access_app_features` does not exist.

- [ ] **Step 3: Write the failing audit badge test**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_models.py`, add:

```python
from inspinia.users.models import AuditEvent
from inspinia.users.models import User


def test_approval_changed_event_uses_warning_badge(db):
    event = AuditEvent.objects.create(
        event_type=AuditEvent.EventType.APPROVAL_CHANGED,
        message="Approved access for learner@example.com.",
    )

    assert event.badge_class == "text-bg-warning"
```

Keep the existing `test_user_get_absolute_url()` in the same file.

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_models.py -v
```

Expected: FAIL because `AuditEvent.EventType.APPROVAL_CHANGED` does not exist.

- [ ] **Step 4: Add the model field and audit event type**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/models.py`, add the approval field after `role`:

```python
    is_approved = models.BooleanField(
        _("Approved for app access"),
        default=False,
        db_index=True,
        help_text=_("Unapproved users can sign in but cannot use AsterProof features."),
    )
```

Add the audit event type:

```python
        APPROVAL_CHANGED = "users.approval_changed", _("Approval changed")
```

Include the new event in warning badges:

```python
        if self.event_type in {
            self.EventType.ROLE_CHANGED,
            self.EventType.APPROVAL_CHANGED,
            self.EventType.SESSION_REVOKED,
        }:
            return "text-bg-warning"
```

- [ ] **Step 5: Make superusers stored-approved by default**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/managers.py`, update `create_superuser()`:

```python
    def create_superuser(self, email: str, password: str | None = None, **extra_fields):  # type: ignore[override]
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_approved", True)
```

- [ ] **Step 6: Add the app-access helper**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/roles.py`, add:

```python
def user_can_access_app_features(user: object | None) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user_has_admin_role(user):
        return True
    return bool(getattr(user, "is_approved", False))
```

- [ ] **Step 7: Keep existing test users approved by default**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/factories.py`, add:

```python
class UserFactory(DjangoModelFactory[User]):
    email = Faker("email")
    name = Faker("name")
    is_approved = True
```

- [ ] **Step 8: Create the migration**

Create `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/migrations/0007_user_is_approved_and_approval_audit_event.py`:

```python
from django.db import migrations
from django.db import models
from django.db.models import Q


def approve_existing_privileged_users(apps, schema_editor):
    User = apps.get_model("users", "User")
    User.objects.filter(Q(is_superuser=True) | Q(role="admin")).update(is_approved=True)


def reverse_noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0006_user_country_user_postal_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_approved",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Unapproved users can sign in but cannot use AsterProof features.",
                verbose_name="Approved for app access",
            ),
        ),
        migrations.AlterField(
            model_name="auditevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("auth.login_succeeded", "Login succeeded"),
                    ("auth.login_failed", "Login failed"),
                    ("auth.logout", "Logout"),
                    ("auth.signup", "Signup"),
                    ("users.role_changed", "Role changed"),
                    ("users.approval_changed", "Approval changed"),
                    ("sessions.revoked", "Session revoked"),
                    ("imports.previewed", "Workbook previewed"),
                    ("imports.completed", "Workbook imported"),
                    ("imports.failed", "Workbook import failed"),
                ],
                db_index=True,
                max_length=64,
            ),
        ),
        migrations.RunPython(approve_existing_privileged_users, reverse_noop),
    ]
```

- [ ] **Step 9: Run focused tests**

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_managers.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_roles.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_models.py -v
```

Expected: PASS.

- [ ] **Step 10: Commit the model/helper foundation**

```bash
git add /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/models.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/managers.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/roles.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/migrations/0007_user_is_approved_and_approval_audit_event.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/factories.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_managers.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_roles.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_models.py
git commit -m "feat: add user approval state"
```

### Task 2: Gate Authenticated Features With Middleware

**Files:**
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/middleware.py`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/config/settings/base.py`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/views.py`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/urls.py`
- Create: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/users/approval_pending.html`
- Create: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_approval_gate.py`

- [ ] **Step 1: Write failing middleware and pending-page tests**

Create `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_approval_gate.py`:

```python
from http import HTTPStatus

from django.urls import reverse

from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory


def test_unapproved_user_is_redirected_from_app_feature(client):
    user = UserFactory(is_approved=False)
    client.force_login(user)

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("users:approval_pending")


def test_unapproved_user_can_view_approval_pending_page(client):
    user = UserFactory(is_approved=False)
    client.force_login(user)

    response = client.get(reverse("users:approval_pending"))

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode("utf-8")
    assert "Approval pending" in content
    assert "Your account is waiting for admin approval." in content


def test_unapproved_user_can_open_logout_page(client):
    user = UserFactory(is_approved=False)
    client.force_login(user)

    response = client.get(reverse("account_logout"))

    assert response.status_code == HTTPStatus.OK


def test_approved_user_can_open_app_feature(client):
    user = UserFactory(is_approved=True)
    client.force_login(user)

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.OK


def test_admin_role_can_open_app_feature_without_stored_approval(client):
    admin_user = UserFactory(role=User.Role.ADMIN, is_approved=False)
    client.force_login(admin_user)

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.OK


def test_approved_user_is_redirected_away_from_pending_page(client):
    user = UserFactory(is_approved=True)
    client.force_login(user)

    response = client.get(reverse("users:approval_pending"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("pages:user_activity_dashboard")
```

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_approval_gate.py -v
```

Expected: FAIL because `users:approval_pending` and the middleware do not exist.

- [ ] **Step 2: Add the pending-access view**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/views.py`, import the helper:

```python
from inspinia.users.roles import user_can_access_app_features
```

Add the view near the other simple user views:

```python
@login_required
def approval_pending_view(request):
    if user_can_access_app_features(request.user):
        return redirect("pages:user_activity_dashboard")
    return render(request, "users/approval_pending.html")
```

- [ ] **Step 3: Add the pending-access route**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/urls.py`, import and register the view:

```python
from .views import approval_pending_view

urlpatterns = [
    path("approval-pending/", view=approval_pending_view, name="approval_pending"),
    path("~redirect/", view=user_redirect_view, name="redirect"),
```

- [ ] **Step 4: Create the pending-access template**

Create `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/users/approval_pending.html`:

```django
{% extends 'layouts/vertical.html' %}

{% load i18n %}

{% block title %}{% translate "Approval pending" %}{% endblock title %}

{% block page_content %}
<div class="container-fluid">
  {% include 'partials/page-title.html' with title='Approval pending' subtitle='Account access' %}

  <div class="row mt-3">
    <div class="col-xl-7 col-lg-9">
      <div class="card">
        <div class="card-body">
          <div class="d-flex gap-3">
            <span class="avatar-title bg-warning-subtle text-warning rounded fs-24 flex-shrink-0">
              <i class="ti ti-lock-check"></i>
            </span>
            <div>
              <h4 class="header-title mb-1">{% translate "Your account is waiting for admin approval." %}</h4>
              <p class="text-muted mb-3">
                {% translate "You can stay signed in, update account security settings, or log out. AsterProof features will unlock after an admin approves this account." %}
              </p>
              <div class="d-flex flex-wrap gap-2">
                <a href="{% url 'account_email' %}" class="btn btn-sm btn-outline-secondary">
                  <i class="ti ti-mail me-1"></i>{% translate "Email settings" %}
                </a>
                <a href="{% url 'mfa_index' %}" class="btn btn-sm btn-outline-secondary">
                  <i class="ti ti-shield-lock me-1"></i>{% translate "MFA" %}
                </a>
                <a href="{% url 'account_logout' %}" class="btn btn-sm btn-danger">
                  <i class="ti ti-logout-2 me-1"></i>{% translate "Log out" %}
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
{% endblock page_content %}
```

- [ ] **Step 5: Add the approval middleware**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/middleware.py`, add imports and the middleware class:

```python
from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse

from inspinia.users.monitoring import touch_tracked_session
from inspinia.users.roles import user_can_access_app_features


class RequireApprovedUserMiddleware:
    exempt_path_prefixes = ("/accounts/", "/admin/", "/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            not getattr(user, "is_authenticated", False)
            or user_can_access_app_features(user)
            or self._is_exempt_path(request.path)
        ):
            return self.get_response(request)

        pending_url = reverse("users:approval_pending")
        if request.path == pending_url:
            return self.get_response(request)
        return redirect("users:approval_pending")

    def _is_exempt_path(self, path: str) -> bool:
        return path.startswith(self.exempt_path_prefixes)
```

Keep `TrackActiveSessionMiddleware` below this class in the same file.

- [ ] **Step 6: Register the middleware in the correct order**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/config/settings/base.py`, insert approval middleware after allauth account middleware:

```python
    "allauth.account.middleware.AccountMiddleware",
    "inspinia.users.middleware.RequireApprovedUserMiddleware",
    "inspinia.users.middleware.TrackActiveSessionMiddleware",
```

- [ ] **Step 7: Run middleware tests**

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_approval_gate.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit the gate**

```bash
git add /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/middleware.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/config/settings/base.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/views.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/urls.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/users/approval_pending.html /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_approval_gate.py
git commit -m "feat: gate app access by user approval"
```

### Task 3: Extend User Access Admin Page

**Files:**
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/views.py`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/users/manage_roles.html`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_views.py`

- [ ] **Step 1: Write failing approval-management tests**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_views.py`, extend `TestManageRolesView`:

```python
    def test_manage_roles_admin_can_approve_user_and_record_audit_event(self, client: Client):
        admin_user = UserFactory(role=User.Role.ADMIN)
        target_user = UserFactory(role=User.Role.NORMAL, is_approved=False)
        client.force_login(admin_user)

        response = client.post(
            reverse("users:manage_roles"),
            {"user_id": target_user.pk, "role": User.Role.NORMAL, "is_approved": "1"},
            follow=True,
        )

        target_user.refresh_from_db()

        assert response.status_code == HTTPStatus.OK
        assert target_user.role == User.Role.NORMAL
        assert target_user.is_approved is True
        content = response.content.decode("utf-8")
        assert gettext("Updated access for %(email)s.") % {"email": target_user.email} in content
        assert AuditEvent.objects.filter(
            event_type=AuditEvent.EventType.APPROVAL_CHANGED,
            actor=admin_user,
            target_user=target_user,
            metadata__from_approved=False,
            metadata__to_approved=True,
        ).exists()

    def test_manage_roles_admin_can_revoke_normal_user_approval(self, client: Client):
        admin_user = UserFactory(role=User.Role.ADMIN)
        target_user = UserFactory(role=User.Role.NORMAL, is_approved=True)
        client.force_login(admin_user)

        response = client.post(
            reverse("users:manage_roles"),
            {"user_id": target_user.pk, "role": User.Role.NORMAL, "is_approved": "0"},
            follow=True,
        )

        target_user.refresh_from_db()

        assert response.status_code == HTTPStatus.OK
        assert target_user.is_approved is False
        assert AuditEvent.objects.filter(
            event_type=AuditEvent.EventType.APPROVAL_CHANGED,
            actor=admin_user,
            target_user=target_user,
            metadata__from_approved=True,
            metadata__to_approved=False,
        ).exists()

    def test_manage_roles_admin_role_is_stored_as_approved(self, client: Client):
        admin_user = UserFactory(role=User.Role.ADMIN)
        target_user = UserFactory(role=User.Role.NORMAL, is_approved=False)
        client.force_login(admin_user)

        response = client.post(
            reverse("users:manage_roles"),
            {"user_id": target_user.pk, "role": User.Role.ADMIN, "is_approved": "0"},
            follow=True,
        )

        target_user.refresh_from_db()

        assert response.status_code == HTTPStatus.OK
        assert target_user.role == User.Role.ADMIN
        assert target_user.is_approved is True

    def test_manage_roles_page_shows_approval_controls(self, client: Client):
        admin_user = UserFactory(role=User.Role.ADMIN)
        pending_user = UserFactory(email="pending@example.com", is_approved=False)
        client.force_login(admin_user)

        response = client.get(reverse("users:manage_roles"))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode("utf-8")
        assert "User access" in content
        assert "Approval" in content
        assert pending_user.email in content
        assert 'name="is_approved"' in content
```

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_views.py -k ManageRolesView -v
```

Expected: FAIL because the page and view do not handle approval.

- [ ] **Step 2: Update `manage_user_roles_view()` to save role and approval**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/views.py`, replace the successful POST branch in `manage_user_roles_view()` with:

```python
        if target is None or new_role not in allowed_roles:
            messages.error(request, _("Invalid user or role."))
        else:
            previous_role = target.role
            previous_is_approved = target.is_approved
            posted_is_approved = request.POST.get("is_approved") == "1"
            new_is_approved = posted_is_approved or new_role == User.Role.ADMIN or target.is_superuser

            target.role = new_role
            target.is_approved = new_is_approved
            target.save(update_fields=["role", "is_approved"])
            messages.success(
                request,
                _("Updated access for %(email)s.") % {"email": target.email},
            )
            if previous_role != new_role:
                record_event(
                    event_type=AuditEvent.EventType.ROLE_CHANGED,
                    message=(
                        f"Changed role for {target.email} from "
                        f"{User.Role(previous_role).label} to {target.get_role_display()}."
                    ),
                    request=request,
                    actor=request.user,
                    target_user=target,
                    metadata={
                        "from_role": previous_role,
                        "to_role": new_role,
                    },
                )
            if previous_is_approved != new_is_approved:
                action = "Approved" if new_is_approved else "Revoked approval for"
                record_event(
                    event_type=AuditEvent.EventType.APPROVAL_CHANGED,
                    message=f"{action} {target.email}.",
                    request=request,
                    actor=request.user,
                    target_user=target,
                    metadata={
                        "from_approved": previous_is_approved,
                        "to_approved": new_is_approved,
                    },
                )
```

- [ ] **Step 3: Include approval events in event-log admin counts**

In `event_log_view()`, update `admin_action_types`:

```python
    admin_action_types = {
        AuditEvent.EventType.ROLE_CHANGED,
        AuditEvent.EventType.APPROVAL_CHANGED,
        AuditEvent.EventType.SESSION_REVOKED,
        AuditEvent.EventType.IMPORT_COMPLETED,
    }
```

- [ ] **Step 4: Update the manage-roles template copy and table headers**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/users/manage_roles.html`, update title strings:

```django
{% block title %}{% translate "User access" %}{% endblock title %}
{% include 'partials/page-title.html' with title='User access' subtitle='Admin' %}
<h4 class="header-title mb-0">{% translate "User access" %}</h4>
<p class="text-muted fs-xs mb-0">
  {% translate "Admin-only access settings. Approval unlocks authenticated AsterProof features. Admin and superuser accounts are always treated as approved." %}
</p>
<p class="text-muted fs-xs mb-0 mt-2">
  {% translate "Use this page to approve users and set each user's application role one account at a time." %}
</p>
```

Update table headers:

```django
<th scope="col" class="text-nowrap">{% translate "Approval" %}</th>
<th scope="col">{% translate "Role" %}</th>
```

Replace each row form body with:

```django
<td>
  {% if u.is_superuser or u.role == 'admin' %}
  <span class="badge text-bg-success">{% translate "Auto-approved" %}</span>
  {% elif u.is_approved %}
  <span class="badge text-bg-success">{% translate "Approved" %}</span>
  {% else %}
  <span class="badge text-bg-warning">{% translate "Pending" %}</span>
  {% endif %}
</td>
<td>
  <form method="post" class="row g-2 align-items-center">
    {% csrf_token %}
    <input type="hidden" name="user_id" value="{{ u.pk }}">
    <input type="hidden" name="is_approved" value="0">
    <div class="col-auto">
      <select name="role" class="form-select form-select-sm" style="min-width: 11rem" aria-label="{% translate 'Role' %}">
        {% for value, label in role_choices %}
        <option value="{{ value }}" {% if u.role == value %}selected{% endif %}>{{ label }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-auto">
      <div class="form-check form-switch mb-0">
        <input
          class="form-check-input"
          type="checkbox"
          role="switch"
          name="is_approved"
          value="1"
          id="approve-user-{{ u.pk }}"
          {% if u.is_approved or u.is_superuser or u.role == 'admin' %}checked{% endif %}
          {% if u.is_superuser %}disabled{% endif %}
        >
        <label class="form-check-label fs-sm" for="approve-user-{{ u.pk }}">{% translate "Approved" %}</label>
      </div>
    </div>
    <div class="col-auto">
      <button type="submit" class="btn btn-sm btn-primary">
        <i class="ti ti-device-floppy me-1"></i>{% translate "Save" %}
      </button>
    </div>
  </form>
</td>
```

Update the empty-state colspan from `4` to `5`.

- [ ] **Step 5: Run approval-management tests**

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_views.py -k ManageRolesView -v
```

Expected: PASS.

- [ ] **Step 6: Commit the admin console update**

```bash
git add /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/views.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/users/manage_roles.html /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_views.py
git commit -m "feat: manage user approvals"
```

### Task 4: Update Navigation And Django Admin

**Files:**
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/context_processors.py`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/partials/sidenav.html`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/partials/topbar.html`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/admin.py`
- Create: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_context_processors.py`
- Modify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_admin.py`

- [ ] **Step 1: Write failing context processor tests**

Create `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_context_processors.py`:

```python
from django.contrib.auth.models import AnonymousUser

from inspinia.users.context_processors import app_roles
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory


def test_anonymous_user_has_no_approved_feature_links(rf):
    request = rf.get("/")
    request.user = AnonymousUser()

    flags = app_roles(request)

    assert flags["is_app_approved"] is False
    assert flags["show_user_activity_dashboard_link"] is False
    assert flags["show_solution_workspace_link"] is False


def test_unapproved_user_has_no_approved_feature_links(rf):
    request = rf.get("/")
    request.user = UserFactory(is_approved=False)

    flags = app_roles(request)

    assert flags["is_app_approved"] is False
    assert flags["show_user_activity_dashboard_link"] is False
    assert flags["show_completion_quick_update_link"] is False
    assert flags["show_solution_workspace_link"] is False
    assert flags["show_my_progress_analytics_link"] is False


def test_approved_user_keeps_personal_feature_links(rf):
    request = rf.get("/")
    request.user = UserFactory(is_approved=True)

    flags = app_roles(request)

    assert flags["is_app_approved"] is True
    assert flags["show_user_activity_dashboard_link"] is True
    assert flags["show_completion_quick_update_link"] is True
    assert flags["show_solution_workspace_link"] is True


def test_admin_keeps_admin_links_without_stored_approval(rf):
    request = rf.get("/")
    request.user = UserFactory(role=User.Role.ADMIN, is_approved=False)

    flags = app_roles(request)

    assert flags["is_app_approved"] is True
    assert flags["is_app_admin"] is True
    assert flags["show_event_log_link"] is True
    assert flags["show_session_monitor_link"] is True
```

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_context_processors.py -v
```

Expected: FAIL because `is_app_approved` is missing and feature flags do not check approval.

- [ ] **Step 2: Require approval in role-derived navigation flags**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/context_processors.py`, import the helper and update `app_roles()`:

```python
from inspinia.users.roles import user_can_access_app_features


def app_roles(request):
    """Navigation and UI flags derived from roles."""
    approved = user_can_access_app_features(request.user)
    admin = user_has_admin_role(request.user)
    can_access_rankings = approved and user_has_moderator_or_admin_role(request.user)
    can_access_admin_tools = approved and (admin or settings.DEBUG)
    return {
        "is_app_admin": admin,
        "is_app_approved": approved,
        "show_rankings_link": can_access_rankings,
        "show_analytics_dashboard_link": can_access_admin_tools,
        "show_event_log_link": approved and admin,
        "show_my_progress_analytics_link": approved,
        "show_problem_import_link": can_access_admin_tools,
        "show_session_monitor_link": approved and admin,
        "show_solution_workspace_link": approved,
        "show_completion_quick_update_link": approved,
        "show_user_activity_dashboard_link": approved,
        "show_contest_advanced_dashboard_link": approved,
    }
```

- [ ] **Step 3: Hide side navigation feature groups when not approved**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/partials/sidenav.html`, change the authenticated workspace check:

```django
{% if request.user.is_authenticated and is_app_approved %}
<li class="side-nav-title">Workspace</li>
```

Wrap the Library block:

```django
{% if is_app_approved %}
<li class="side-nav-title">Library</li>

<li class="side-nav-item">
    <a href="{% url 'pages:problem_statement_list' %}" class="side-nav-link">
        <span class="menu-icon"><i class="ti ti-file-text"></i></span>
        <span class="menu-text">Problem statements</span>
    </a>
</li>
{% endif %}
```

Keep all existing `show_*` guarded sections as they are after the context processor change.

- [ ] **Step 4: Hide topbar profile/admin links when not approved**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/partials/topbar.html`, wrap app profile links:

```django
{% if is_app_approved %}
<a href="{% url 'users:detail' request.user.pk %}" class="dropdown-item">
    <i class="ti ti-user-circle me-2 fs-17 align-middle"></i>
    <span class="align-middle">Profile</span>
</a>
<a href="{% url 'users:update' %}" class="dropdown-item">
    <i class="ti ti-settings-2 me-2 fs-17 align-middle"></i>
    <span class="align-middle">Edit profile</span>
</a>
{% endif %}
```

Leave these allauth routes outside the approval wrapper:

```django
<a href="{% url 'account_email' %}" class="dropdown-item">
<a href="{% url 'mfa_index' %}" class="dropdown-item">
<a href="{% url 'account_logout' %}" class="dropdown-item text-danger fw-semibold">
```

Keep the existing `{% if is_app_admin %}` admin block after the profile wrapper.

- [ ] **Step 5: Expose approval in Django admin**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/admin.py`, add `is_approved` to the permissions fieldset:

```python
                "fields": (
                    "is_approved",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
```

Update `list_display` and add filters:

```python
    list_display = ["email", "name", "school", "role", "is_approved", "is_superuser"]
    list_filter = ["role", "is_approved", "is_superuser", "is_staff", "is_active"]
```

- [ ] **Step 6: Add a Django admin assertion**

In `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_admin.py`, update `test_changelist()`:

```python
    def test_changelist(self, admin_client):
        url = reverse("admin:users_user_changelist")
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK
        content = response.content.decode("utf-8")
        assert "Approved for app access" in content or "Is approved" in content
```

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_context_processors.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_admin.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit navigation and admin updates**

```bash
git add /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/context_processors.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/partials/sidenav.html /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/templates/partials/topbar.html /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/admin.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_context_processors.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests/test_admin.py
git commit -m "feat: hide app navigation until approval"
```

### Task 5: Full Verification And Deployment Checks

**Files:**
- Verify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users`
- Verify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/pages/tests.py`
- Verify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/solutions/tests.py`
- Verify: `/Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/rankings/tests`

- [ ] **Step 1: Check migrations are stable**

Run:

```bash
uv run python manage.py makemigrations users --check --dry-run
```

Expected: "No changes detected in app 'users'".

- [ ] **Step 2: Run the full users suite**

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/users/tests -v
```

Expected: PASS.

- [ ] **Step 3: Run affected app suites**

Run:

```bash
uv run pytest /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/pages/tests.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/solutions/tests.py /Users/stevenchew/.codex/worktrees/5653/AsterProof/inspinia/rankings/tests -v
```

Expected: PASS. The updated `UserFactory(is_approved=True)` should prevent broad unrelated failures from the new middleware.

- [ ] **Step 4: Run Django and lint checks**

Run:

```bash
uv run python manage.py check
uv run ruff check config inspinia
```

Expected: both commands PASS.

- [ ] **Step 5: Manual smoke test in a browser**

Start the server with the project’s usual command:

```bash
uv run python manage.py runserver 127.0.0.1:8000
```

Smoke flow:

1. Log in as an admin.
2. Open `/users/manage-roles/`.
3. Confirm the page title is `User access`.
4. Confirm existing admin-role users display `Auto-approved`.
5. Create or select a normal user with `is_approved=False`.
6. Log in as that user.
7. Confirm `/dashboard/my-activity/` redirects to `/users/approval-pending/`.
8. Confirm `/accounts/logout/` is reachable.
9. Log back in as admin and approve the user.
10. Log in as the approved user and confirm `/dashboard/my-activity/`, `/solutions/`, and `/dashboard/problem-statements/` load.
11. Revoke approval for that normal user.
12. Confirm the next feature request redirects back to `/users/approval-pending/`.

- [ ] **Step 6: Production rollout notes**

Before deploy:

```bash
uv run python manage.py migrate --plan
```

Expected: migration `users.0007_user_is_approved_and_approval_audit_event` is listed with `AddField`, `AlterField`, and `RunPython`.

After deploy:

1. Run the migration.
2. Log in as an admin account that had role `admin` or `is_superuser=True` before deploy.
3. Open `/users/manage-roles/`.
4. Approve the existing normal users who should be allowed into the site.
5. Leave untrusted or smoke-test accounts pending.
6. Check `/users/monitor/events/` for `Approval changed` audit rows.

- [ ] **Step 7: Final diff review**

Run:

```bash
git diff --check
git diff --stat
git diff
```

Review for:

- `RequireApprovedUserMiddleware` is registered after authentication/allauth and before session tracking.
- `/accounts/` and `users:approval_pending` are exempt to avoid redirect loops.
- Admin and superuser accounts cannot be locked out by a false stored approval value.
- `UserFactory` defaults to approved while `User.objects.create_user()` defaults to unapproved.
- `AuditEvent.EventType.APPROVAL_CHANGED` is reflected in badge styling, event-log counts, page tests, and migration state.
- No unrelated page, rankings, solution, or import logic changed.

- [ ] **Step 8: Commit verification fixes or finish**

If verification required small fixes, commit them:

```bash
git add /Users/stevenchew/.codex/worktrees/5653/AsterProof
git commit -m "test: verify user approval gate"
```

If no fixes were needed, leave the branch with the four feature commits from Tasks 1-4.

## Self-Review

- Spec coverage: The plan adds approval storage, an admin approval UI, central feature gating, a pending page, navigation hiding, audit logging, migration/backfill behavior, and verification.
- Placeholder scan: No implementation step depends on unspecified code or an unnamed file.
- Type consistency: The plan uses one helper name, `user_can_access_app_features()`, throughout middleware, views, context processors, and tests.
- Risk check: The two important lockout protections are explicit: admins/superusers are effective-approved, and the migration approves existing privileged users.
