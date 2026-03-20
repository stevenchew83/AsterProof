from datetime import date
from http import HTTPStatus

import pytest
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
from django.utils.translation import gettext_lazy as _

from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.users.forms import UserAdminChangeForm
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory
from inspinia.users.views import PublicProfileUpdateView
from inspinia.users.views import UserRedirectView
from inspinia.users.views import UserUpdateView
from inspinia.users.views import user_detail_view

pytestmark = pytest.mark.django_db
EXPECTED_IMPORTED_COMPLETION_TOTAL = 2


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
    def test_get_redirect_url(self, user: User, rf: RequestFactory):
        view = UserRedirectView()
        request = rf.get("/fake-url")
        request.user = user

        view.request = request
        assert view.get_redirect_url() == "/users/profile/"


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
        assert "Import completions" in content
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

    def test_profile_post_imports_completion_text_for_current_user(self, user: User, client: Client):
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
        assert UserProblemCompletion.objects.filter(user=user).count() == EXPECTED_IMPORTED_COMPLETION_TOTAL
        dated_completion = UserProblemCompletion.objects.get(user=user, problem=record_with_date)
        assert dated_completion.completion_date == date(2025, 8, 28)
        assert UserProblemCompletion.objects.get(
            user=user,
            problem=record_done,
        ).completion_date is None
        page = response.content.decode()
        assert "Your solving dashboard" in page
        assert "Your recent solved problems" in page
        assert "Avg MOHS" in page
        assert "Hardest solved" in page
        assert "MOHS breakdown" in page
        assert "ISRAEL TST 2026 P2" in page
        assert "Completed 2025-08-28" in page
        assert "Done" in page
        assert page.index("Your recent solved problems") < page.index("Completion import")
        assert response.context["completion_analytics"]["avg_mohs"] == 4.5
        assert response.context["completion_analytics"]["max_mohs"] == 5
        assert response.context["completion_dashboards"]["by_mohs"] == [
            {"label": "MOHS 4", "total": 1, "width_pct": 100},
            {"label": "MOHS 5", "total": 1, "width_pct": 100},
        ]
        assert any(
            "Updated 2 completion row(s). 1 marked Done without an exact date." in str(message)
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
        assert content.index("Your recent solved problems") < content.index("Completion import")
        assert response.context["completion_analytics"]["avg_mohs"] == 4.5
        assert response.context["completion_analytics"]["max_mohs"] == 5
        assert response.context["completion_dashboards"]["by_mohs"] == [
            {"label": "MOHS 4", "total": 1, "width_pct": 100},
            {"label": "MOHS 5", "total": 1, "width_pct": 100},
        ]
