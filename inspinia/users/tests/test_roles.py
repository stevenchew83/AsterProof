import pytest
from django.contrib.auth.models import AnonymousUser

from inspinia.users.models import User
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


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
