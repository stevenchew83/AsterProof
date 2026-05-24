from dataclasses import dataclass

import pytest
from django.test import RequestFactory

from inspinia.users.adapters import AccountAdapter
from inspinia.users.models import UserAccessSettings


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
