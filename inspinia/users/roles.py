"""Application role checks (beyond Django's built-in staff/superuser flags)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from inspinia.users.models import User

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

# Legacy Django auth group from initial migration; prefer ``User.role`` / ``User.Role.ADMIN``.
ADMIN_GROUP_NAME = "Admin"


def user_has_admin_role(user: AbstractBaseUser | None) -> bool:
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = getattr(user, "role", None)
    return role == User.Role.ADMIN
