from inspinia.users.models import AuditEvent
from inspinia.users.models import User
from inspinia.users.models import UserAccessSettings


def test_user_get_absolute_url(user: User):
    assert user.get_absolute_url() == f"/users/{user.pk}/"


def test_approval_changed_event_uses_warning_badge(db):
    event = AuditEvent.objects.create(
        event_type=AuditEvent.EventType.APPROVAL_CHANGED,
        message="Approved access for learner@example.com.",
    )

    assert event.badge_class == "text-bg-warning"


def test_user_access_settings_default_to_manual_approval(db):
    settings = UserAccessSettings.get_solo()

    assert settings.auto_approve_new_users is False


def test_user_access_settings_reuses_singleton(db):
    settings = UserAccessSettings.get_solo()
    settings.auto_approve_new_users = True
    settings.save()

    assert UserAccessSettings.get_solo().pk == settings.pk
    assert UserAccessSettings.get_solo().auto_approve_new_users is True
