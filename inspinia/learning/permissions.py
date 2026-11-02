"""Learning access; publisher authority never follows an administrator role."""

from django.conf import settings
from django.core.exceptions import PermissionDenied

from inspinia.users.roles import user_can_access_app_features


def module_enabled():
    return bool(getattr(settings, "LEARNING_MODULE_ENABLED", False))


def can_contribute(user):
    return bool(
        module_enabled()
        and getattr(settings, "LEARNING_CONTRIBUTIONS_ENABLED", False)
        and getattr(user, "is_active", False)
        and user_can_access_app_features(user),
    )


def is_publisher(user):
    expected = getattr(settings, "LEARNING_PUBLISHER_USER_ID", None)
    return bool(
        module_enabled()
        and expected
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and user_can_access_app_features(user)
        and str(getattr(user, "pk", "")) == str(expected),
    )


def require_contributor(user):
    if not can_contribute(user):
        message = "Learning contributions are unavailable for this account."
        raise PermissionDenied(message)


def require_publisher(user):
    if not is_publisher(user):
        message = "Only the configured publisher can perform this action."
        raise PermissionDenied(message)


def require_draft_owner(draft, user, *, allow_archived=False):
    require_contributor(user)
    if draft.author_id is None or draft.author_id != user.pk:
        message = "This private draft belongs to another author."
        raise PermissionDenied(message)
    if draft.is_archived and not allow_archived:
        message = "Reopen this archived draft before editing it."
        raise PermissionDenied(message)


def can_review(proposal, user):
    return bool(is_publisher(user) or (can_contribute(user) and proposal.author_id == user.pk))
