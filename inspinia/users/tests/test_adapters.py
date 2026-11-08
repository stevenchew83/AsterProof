from dataclasses import dataclass

import pytest
from allauth.socialaccount.internal.flows.signup import SignupClosedException
from allauth.socialaccount.internal.flows.signup import process_signup
from allauth.socialaccount.models import SocialLogin
from django.test import RequestFactory

from inspinia.users.adapters import AccountAdapter
from inspinia.users.adapters import SocialAccountAdapter
from inspinia.users.models import UserAccessSettings


@pytest.mark.django_db
def test_social_signup_uses_the_public_registration_setting(rf: RequestFactory):
    request = rf.get("/accounts/social/signup/")
    social_login = SocialLogin()
    assert SocialAccountAdapter().is_open_for_signup(request, social_login)
    assert not UserAccessSettings.objects.exists()

    UserAccessSettings.objects.create(allow_public_registration=False)
    with pytest.raises(SignupClosedException):
        process_signup(request, social_login)


@dataclass
class SignupFormStub:
    cleaned_data: dict[str, str]


@pytest.mark.django_db
def test_signup_user_stays_pending_when_auto_approve_is_disabled(rf: RequestFactory):
    request = rf.post("/accounts/signup/")
    adapter = AccountAdapter()

    user = adapter.save_user(
        request,
        adapter.new_user(request),
        SignupFormStub(
            cleaned_data={
                "email": "pending-signup@example.com",
                "password1": "something-r@nd0m!",
            },
        ),
    )

    assert user.is_approved is False


@pytest.mark.django_db
def test_signup_user_is_approved_when_auto_approve_is_enabled(rf: RequestFactory):
    settings = UserAccessSettings.get_solo()
    settings.auto_approve_new_users = True
    settings.save()
    request = rf.post("/accounts/signup/")
    adapter = AccountAdapter()

    user = adapter.save_user(
        request,
        adapter.new_user(request),
        SignupFormStub(
            cleaned_data={
                "email": "auto-signup@example.com",
                "password1": "something-r@nd0m!",
            },
        ),
    )

    assert user.is_approved is True
