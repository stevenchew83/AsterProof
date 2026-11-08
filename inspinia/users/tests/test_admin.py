import contextlib
from http import HTTPStatus
from importlib import reload

import pytest
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from inspinia.users.models import User
from inspinia.users.models import UserAccessSettings


class TestUserAdmin:
    def test_changelist(self, admin_client):
        url = reverse("admin:users_user_changelist")
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK
        content = response.content.decode("utf-8")
        assert "Approved for app access" in content or "Is approved" in content

    def test_search(self, admin_client):
        url = reverse("admin:users_user_changelist")
        response = admin_client.get(url, data={"q": "test"})
        assert response.status_code == HTTPStatus.OK

    def test_add(self, admin_client):
        UserAccessSettings.objects.create(allow_public_registration=False)
        url = reverse("admin:users_user_add")
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK

        response = admin_client.post(
            url,
            data={
                "email": "new-admin@example.com",
                "password1": "My_R@ndom-P@ssw0rd",
                "password2": "My_R@ndom-P@ssw0rd",
            },
        )
        assert response.status_code == HTTPStatus.FOUND
        assert User.objects.filter(email="new-admin@example.com").exists()

    def test_view_user(self, admin_client):
        user = User.objects.get(email="admin@example.com")
        url = reverse("admin:users_user_change", kwargs={"object_id": user.pk})
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK

    @pytest.fixture
    def _force_allauth(self, settings):
        settings.DJANGO_ADMIN_FORCE_ALLAUTH = True
        # Reload the admin module to apply the setting change
        import inspinia.users.admin as users_admin

        with contextlib.suppress(admin.sites.AlreadyRegistered):  # type: ignore[attr-defined]
            reload(users_admin)

    @pytest.mark.django_db
    @pytest.mark.usefixtures("_force_allauth")
    def test_allauth_login(self, rf, settings):
        request = rf.get("/fake-url")
        request.user = AnonymousUser()
        response = admin.site.login(request)

        # The `admin` login view should redirect to the `allauth` login view
        target_url = reverse(settings.LOGIN_URL) + "?next=" + request.path
        assertRedirects(response, target_url, fetch_redirect_response=False)


def test_django_admin_can_set_auto_approval_but_cannot_change_registration(admin_client):
    response = admin_client.post(
        reverse("admin:users_useraccesssettings_add"), {"auto_approve_new_users": "on"},
    )
    assert response.status_code == HTTPStatus.FOUND
    access_settings = UserAccessSettings.get_solo()
    assert access_settings.auto_approve_new_users
    assert access_settings.allow_public_registration

    access_settings.allow_public_registration = False
    access_settings.save(update_fields=["allow_public_registration"])
    url_kwargs = {"object_id": access_settings.pk}
    response = admin_client.post(
        reverse("admin:users_useraccesssettings_change", kwargs=url_kwargs), {"allow_public_registration": "on"},
    )
    assert response.status_code == HTTPStatus.FOUND
    access_settings.refresh_from_db()
    assert not access_settings.auto_approve_new_users
    assert not access_settings.allow_public_registration
    response = admin_client.post(reverse("admin:users_useraccesssettings_delete", kwargs=url_kwargs), {"post": "yes"})
    assert response.status_code == HTTPStatus.FORBIDDEN
