from inspinia.users.models import AuditEvent
from inspinia.users.models import User


def test_user_get_absolute_url(user: User):
    assert user.get_absolute_url() == f"/users/{user.pk}/"


def test_approval_changed_event_uses_warning_badge(db):
    event = AuditEvent.objects.create(
        event_type=AuditEvent.EventType.APPROVAL_CHANGED,
        message="Approved access for learner@example.com.",
    )

    assert event.badge_class == "text-bg-warning"
