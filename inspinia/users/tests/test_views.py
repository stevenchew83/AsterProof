from datetime import date
from http import HTTPStatus

import pytest
from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest
from django.http import HttpResponseRedirect
from django.test import Client
from django.test import RequestFactory
from django.urls import reverse
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.users.forms import UserAdminChangeForm
from inspinia.users.models import AuditEvent
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory
from inspinia.users.views import PublicProfileUpdateView
from inspinia.users.views import UserRedirectView
from inspinia.users.views import UserUpdateView
from inspinia.users.views import user_detail_view

pytestmark = pytest.mark.django_db

TEST_PASSWORD = "StrongPass123!"  # noqa: S105


def _verify_email(user: User) -> None:
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": True},
    )
EXPECTED_IMPORTED_COMPLETION_TOTAL = 2
EXPECTED_PROFILE_AVG_MOHS = 4.5
EXPECTED_PROFILE_MAX_MOHS = 5


class TestUserUpdateView:
    """
    TODO:
        extracting view initialization code as class-scoped fixture
        would be great if only pytest-django supported non-function-scoped
        fixture db access -- this is a work-in-progress for now:
        https://github.com/pytest-dev/pytest-django/pull/258
    """

    def dummy_get_response(self, request: HttpRequest):
        return None

    def test_get_success_url(self, user: User, rf: RequestFactory):
        view = UserUpdateView()
        request = rf.get("/fake-url/")
        request.user = user

        view.request = request
        assert view.get_success_url() == f"/users/{user.pk}/"

    def test_get_object(self, user: User, rf: RequestFactory):
        view = UserUpdateView()
        request = rf.get("/fake-url/")
        request.user = user

        view.request = request

        assert view.get_object() == user

    def test_form_valid(self, user: User, rf: RequestFactory):
        view = UserUpdateView()
        request = rf.get("/fake-url/")

        # Add the session/message middleware to the request
        SessionMiddleware(self.dummy_get_response).process_request(request)
        MessageMiddleware(self.dummy_get_response).process_request(request)
        request.user = user

        view.request = request

        # Initialize the form
        form = UserAdminChangeForm()
        form.cleaned_data = {}
        form.instance = user
        view.form_valid(form)

        messages_sent = [m.message for m in messages.get_messages(request)]
        assert messages_sent == [_("Information successfully updated")]

    def test_profile_update_persists_extended_fields(self, user: User, client: Client):
        client.force_login(user)

        response = client.post(
            reverse("users:update"),
            data={
                "name": "Updated Name",
                "school": "Aster Academy",
                "contact_number": "+60 12-345 6789",
                "discord_username": "asterproof",
                "birthdate": "2000-01-15",
                "gender": User.Gender.NON_BINARY,
                "address": "123 Test Street\nKuala Lumpur",
                "postal_code": "50000",
                "country": "Malaysia",
                "social_media_links": "https://discord.com/users/example\nhttps://github.com/example",
            },
        )

        user.refresh_from_db()

        assert response.status_code == HTTPStatus.FOUND
        assert response["Location"] == reverse("users:detail", kwargs={"pk": user.pk})
        assert user.name == "Updated Name"
        assert user.school == "Aster Academy"
        assert user.contact_number == "+60 12-345 6789"
        assert user.discord_username == "asterproof"
        assert user.birthdate == date(2000, 1, 15)
        assert user.gender == User.Gender.NON_BINARY
        assert user.address == "123 Test Street\nKuala Lumpur"
        assert user.postal_code == "50000"
        assert user.country == "Malaysia"
        assert user.social_media_links == "https://discord.com/users/example\nhttps://github.com/example"

    def test_update_page_uses_date_input_for_birthdate(self, user: User, client: Client):
        client.force_login(user)

        response = client.get(reverse("users:update"))

        assert response.status_code == HTTPStatus.OK
        assert 'name="birthdate"' in response.content.decode()
        assert 'type="date"' in response.content.decode()


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


class TestPublicProfileUpdateView:
    def test_get_success_url(self, user: User, rf: RequestFactory):
        view = PublicProfileUpdateView()
        request = rf.get("/fake-url/")
        request.user = user

        view.request = request
        assert view.get_success_url() == "/users/profile/"

    def test_get_object(self, user: User, rf: RequestFactory):
        view = PublicProfileUpdateView()
        request = rf.get("/fake-url/")
        request.user = user

        view.request = request

        assert view.get_object() == user


class TestUserDetailView:
    def test_authenticated(self, user: User, rf: RequestFactory):
        request = rf.get("/fake-url/")
        request.user = UserFactory()
        response = user_detail_view(request, pk=user.pk)

        assert response.status_code == HTTPStatus.OK

    def test_not_authenticated(self, user: User, rf: RequestFactory):
        request = rf.get("/fake-url/")
        request.user = AnonymousUser()
        response = user_detail_view(request, pk=user.pk)
        login_url = reverse(settings.LOGIN_URL)

        assert isinstance(response, HttpResponseRedirect)
        assert response.status_code == HTTPStatus.FOUND
        assert response.url == f"{login_url}?next=/fake-url/"

    def test_detail_shows_extended_profile_fields(self, user: User, client: Client):
        user.name = "Profile Owner"
        user.school = "Aster Academy"
        user.contact_number = "+60 12-345 6789"
        user.discord_username = "asterproof"
        user.birthdate = date(2000, 1, 15)
        user.gender = User.Gender.FEMALE
        user.address = "123 Test Street\nKuala Lumpur"
        user.postal_code = "50000"
        user.country = "Malaysia"
        user.social_media_links = "https://github.com/example"
        user.save()

        client.force_login(user)
        response = client.get(reverse("users:detail", kwargs={"pk": user.pk}))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Aster Academy" in content
        assert "+60 12-345 6789" in content
        assert "asterproof" in content
        assert "January 15, 2000" in content
        assert "Female" in content
        assert "123 Test Street" in content
        assert "50000" in content
        assert "Malaysia" in content
        assert "https://github.com/example" in content


class TestPublicProfileView:
    def test_authenticated(self, user: User, client: Client):
        client.force_login(user)

        response = client.get(reverse("users:profile"))

        assert response.status_code == HTTPStatus.OK

    def test_not_authenticated(self, client: Client):
        response = client.get(reverse("users:profile"))
        login_url = reverse(settings.LOGIN_URL)

        assert response.status_code == HTTPStatus.FOUND
        assert response["Location"] == f"{login_url}?next={reverse('users:profile')}"

    def test_detail_shows_extended_profile_fields(self, user: User, client: Client):
        user.name = "Profile Owner"
        user.school = "Aster Academy"
        user.contact_number = "+60 12-345 6789"
        user.discord_username = "asterproof"
        user.birthdate = date(2000, 1, 15)
        user.gender = User.Gender.FEMALE
        user.address = "123 Test Street\nKuala Lumpur"
        user.postal_code = "50000"
        user.country = "Malaysia"
        user.social_media_links = "https://github.com/example"
        user.save()

        client.force_login(user)
        response = client.get(reverse("users:profile"))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Aster Academy" in content
        assert "+60 12-345 6789" in content
        assert "asterproof" in content
        assert "January 15, 2000" in content
        assert "Female" in content
        assert "123 Test Street" in content
        assert "50000" in content
        assert "Malaysia" in content
        assert "https://github.com/example" in content
        assert reverse("users:profile_edit") in content
        assert "Import moved to My activity." in content
        assert reverse("pages:user_activity_dashboard") in content
        assert "Your solving dashboard" in content
        assert "Top contests" in content
        assert "Top topics" in content
        assert "Avg MOHS" in content
        assert "MOHS breakdown" in content

    def test_profile_update_persists_extended_fields(self, user: User, client: Client):
        client.force_login(user)

        response = client.post(
            reverse("users:profile_edit"),
            data={
                "name": "Updated Name",
                "school": "Aster Academy",
                "contact_number": "+60 12-345 6789",
                "discord_username": "asterproof",
                "birthdate": "2000-01-15",
                "gender": User.Gender.NON_BINARY,
                "address": "123 Test Street\nKuala Lumpur",
                "postal_code": "50000",
                "country": "Malaysia",
                "social_media_links": "https://discord.com/users/example\nhttps://github.com/example",
            },
        )

        user.refresh_from_db()

        assert response.status_code == HTTPStatus.FOUND
        assert response["Location"] == reverse("users:profile")
        assert user.name == "Updated Name"
        assert user.school == "Aster Academy"
        assert user.contact_number == "+60 12-345 6789"
        assert user.discord_username == "asterproof"
        assert user.birthdate == date(2000, 1, 15)
        assert user.gender == User.Gender.NON_BINARY
        assert user.address == "123 Test Street\nKuala Lumpur"
        assert user.postal_code == "50000"
        assert user.country == "Malaysia"
        assert user.social_media_links == "https://discord.com/users/example\nhttps://github.com/example"

    def test_update_page_uses_date_input_for_birthdate(self, user: User, client: Client):
        client.force_login(user)

        response = client.get(reverse("users:profile_edit"))

        assert response.status_code == HTTPStatus.OK
        assert 'name="birthdate"' in response.content.decode()
        assert 'type="date"' in response.content.decode()

    def test_profile_post_redirects_completion_import_to_activity_dashboard(self, user: User, client: Client):
        client.force_login(user)
        record_with_date = ProblemSolveRecord.objects.create(
            year=2026,
            topic="NT",
            mohs=4,
            contest="ISRAEL TST",
            problem="P2",
            contest_year_problem="ISRAEL TST 2026 P2",
        )
        record_done = ProblemSolveRecord.objects.create(
            year=2026,
            topic="ALG",
            mohs=5,
            contest="IMO",
            problem="P1",
            contest_year_problem="IMO 2026 P1",
        )

        response = client.post(
            reverse("users:profile"),
            data={
                "source_text": (
                    "PROBLEM UUID Date\n"
                    f"{record_with_date.problem_uuid}\t2025-08-28\n"
                    f"{record_done.problem_uuid}\tDone"
                ),
            },
            follow=True,
        )

        assert response.status_code == HTTPStatus.OK
        assert response.request["PATH_INFO"] == reverse("pages:user_activity_dashboard")
        assert UserProblemCompletion.objects.filter(user=user).count() == 0
        assert any(
            "Completion import moved to My activity." in str(message)
            for message in response.context["messages"]
        )

    def test_profile_shows_existing_completion_history(self, user: User, client: Client):
        client.force_login(user)
        dated_record = ProblemSolveRecord.objects.create(
            year=2026,
            topic="NT",
            mohs=4,
            contest="ISRAEL TST",
            problem="P2",
            contest_year_problem="ISRAEL TST 2026 P2",
        )
        done_record = ProblemSolveRecord.objects.create(
            year=2025,
            topic="ALG",
            mohs=5,
            contest="IMO",
            problem="P1",
            contest_year_problem="IMO 2025 P1",
        )
        UserProblemCompletion.objects.create(
            user=user,
            problem=dated_record,
            completion_date=date(2025, 8, 28),
        )
        UserProblemCompletion.objects.create(
            user=user,
            problem=done_record,
            completion_date=None,
        )

        response = client.get(reverse("users:profile"))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Your solving dashboard" in content
        assert "Top contests" in content
        assert "Top topics" in content
        assert "Avg MOHS" in content
        assert "Hardest solved" in content
        assert "MOHS breakdown" in content
        assert "Recent dated activity" in content
        assert "Your recent solved problems" in content
        assert "ISRAEL TST 2026 P2" in content
        assert "Completed 2025-08-28" in content
        assert "IMO 2025 P1" in content
        assert "Done" in content
        assert "Import moved to My activity." in content
        assert reverse("pages:user_activity_dashboard") in content
        assert response.context["completion_analytics"]["avg_mohs"] == EXPECTED_PROFILE_AVG_MOHS
        assert response.context["completion_analytics"]["max_mohs"] == EXPECTED_PROFILE_MAX_MOHS
        assert response.context["completion_dashboards"]["by_mohs"] == [
            {"label": "MOHS 4", "total": 1, "width_pct": 100},
            {"label": "MOHS 5", "total": 1, "width_pct": 100},
        ]


class TestManageRolesView:
    def test_manage_roles_redirects_anonymous_user_to_login(self, client: Client):
        response = client.get(reverse("users:manage_roles"))

        assert response.status_code == HTTPStatus.FOUND
        assert response.url == f"{reverse(settings.LOGIN_URL)}?next={reverse('users:manage_roles')}"

    def test_manage_roles_forbids_non_admin_user(self, client: Client):
        member = UserFactory(role=User.Role.NORMAL)
        client.force_login(member)

        response = client.get(reverse("users:manage_roles"))

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_manage_roles_admin_can_update_role_and_record_audit_event(self, client: Client):
        admin_user = UserFactory(role=User.Role.ADMIN)
        target_user = UserFactory(role=User.Role.NORMAL)
        client.force_login(admin_user)

        response = client.post(
            reverse("users:manage_roles"),
            {"user_id": target_user.pk, "role": User.Role.MODERATOR, "is_approved": "1"},
            follow=True,
        )

        target_user.refresh_from_db()

        assert response.status_code == HTTPStatus.OK
        assert response.request["PATH_INFO"] == reverse("users:manage_roles")
        assert target_user.role == User.Role.MODERATOR
        assert target_user.is_approved is True
        content = response.content.decode("utf-8")
        assert gettext("Updated access for %(email)s.") % {"email": target_user.email} in content
        assert (
            gettext(
                "Admin-only access settings. Approval unlocks authenticated AsterProof features. "
                "Admin and superuser accounts are always treated as approved.",
            )
            in content
        )
        assert AuditEvent.objects.filter(
            event_type=AuditEvent.EventType.ROLE_CHANGED,
            actor=admin_user,
            target_user=target_user,
        ).exists()

    def test_manage_roles_admin_can_save_all_access_changes(self, client: Client):
        admin_user = UserFactory(role=User.Role.ADMIN)
        first_target = UserFactory(
            email="bulk-first@example.com",
            role=User.Role.NORMAL,
            is_approved=False,
        )
        second_target = UserFactory(
            email="bulk-second@example.com",
            role=User.Role.TRAINER,
            is_approved=True,
        )
        unchanged_target = UserFactory(
            email="bulk-unchanged@example.com",
            role=User.Role.NORMAL,
            is_approved=False,
        )
        client.force_login(admin_user)

        response = client.post(
            reverse("users:manage_roles"),
            {
                "user_ids": [first_target.pk, second_target.pk, unchanged_target.pk],
                f"role_{first_target.pk}": User.Role.MODERATOR,
                f"is_approved_{first_target.pk}": "1",
                f"role_{second_target.pk}": User.Role.NORMAL,
                f"is_approved_{second_target.pk}": "0",
                f"role_{unchanged_target.pk}": User.Role.NORMAL,
                f"is_approved_{unchanged_target.pk}": "0",
            },
            follow=True,
        )

        first_target.refresh_from_db()
        second_target.refresh_from_db()
        unchanged_target.refresh_from_db()

        assert response.status_code == HTTPStatus.OK
        assert first_target.role == User.Role.MODERATOR
        assert first_target.is_approved is True
        assert second_target.role == User.Role.NORMAL
        assert second_target.is_approved is False
        assert unchanged_target.role == User.Role.NORMAL
        assert unchanged_target.is_approved is False
        assert "Saved access changes for 2 users." in response.content.decode("utf-8")
        assert AuditEvent.objects.filter(
            event_type=AuditEvent.EventType.ROLE_CHANGED,
            actor=admin_user,
            target_user=first_target,
        ).exists()
        assert AuditEvent.objects.filter(
            event_type=AuditEvent.EventType.APPROVAL_CHANGED,
            actor=admin_user,
            target_user=second_target,
            metadata__to_approved=False,
        ).exists()

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
        assert 'name="user_ids"' in content
        assert f'name="is_approved_{pending_user.pk}"' in content
        assert "Save all changes" in content

    def test_manage_roles_rejects_invalid_role(self, client: Client):
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
        assert gettext("Invalid user or role.") in response.content.decode("utf-8")

    def test_manage_roles_rejects_invalid_user_id(self, client: Client):
        admin_user = UserFactory(role=User.Role.ADMIN)
        client.force_login(admin_user)

        response = client.post(
            reverse("users:manage_roles"),
            {"user_id": "999999", "role": User.Role.ADMIN},
            follow=True,
        )

        assert response.status_code == HTTPStatus.OK
        assert gettext("Invalid user or role.") in response.content.decode("utf-8")
