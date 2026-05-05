"""Application role checks (beyond Django's built-in staff/superuser flags)."""

from __future__ import annotations

from inspinia.users.models import User

# Legacy Django auth group from initial migration. Prefer ``User.role`` / ``User.Role.ADMIN``.
ADMIN_GROUP_NAME = "Admin"


def user_has_admin_role(user: object | None) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    role = getattr(user, "role", None)
    return role == User.Role.ADMIN


def user_has_moderator_or_admin_role(user: object | None) -> bool:
    if user_has_admin_role(user):
        return True
    role = getattr(user, "role", None)
    return role == User.Role.MODERATOR


def user_can_access_app_features(user: object | None) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user_has_admin_role(user):
        return True
    return bool(getattr(user, "is_approved", False))
