from __future__ import annotations

from enum import StrEnum
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
from django.utils import timezone

MODERATOR_GROUP = "moderator"
ADMIN_GROUP = "admin"


class PlatformRole(StrEnum):
    GUEST = "guest"
    REGISTERED = "registered"
    TRUSTED = "trusted"


def is_admin(user) -> bool:  # noqa: ANN001
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    if getattr(user, "groups", None) and user.groups.filter(name=ADMIN_GROUP).exists():
        return True
    return bool(getattr(user, "has_perm", None) and user.has_perm("backoffice.change_ratingconfig"))


def is_moderator(user) -> bool:  # noqa: ANN001
    if not getattr(user, "is_authenticated", False):
        return False
    if is_admin(user):
        return True
    if getattr(user, "groups", None) and user.groups.filter(name=MODERATOR_GROUP).exists():
        return True
    return bool(getattr(user, "has_perm", None) and user.has_perm("backoffice.view_report"))


def is_muted(user) -> bool:  # noqa: ANN001
    if not getattr(user, "is_authenticated", False):
        return False
    mute_expires_at = getattr(user, "mute_expires_at", None)
    if mute_expires_at is None:
        return False
    return mute_expires_at > timezone.now()


def can_post(user) -> bool:  # noqa: ANN001
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_banned", False):
        return False
    if is_muted(user):
        return False
    return True


def can_vote(user) -> bool:  # noqa: ANN001
    return can_post(user)


def can_mutate_learning_state(user) -> bool:  # noqa: ANN001
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_banned", False):
        return False
    if getattr(user, "is_readonly", False):
        return False
    return True


def require_posting_allowed(user):  # noqa: ANN001
    if not can_post(user):
        return HttpResponseForbidden("You cannot post right now.")
    return None


def require_voting_allowed(user):  # noqa: ANN001
    if not can_vote(user):
        return HttpResponseForbidden("You cannot vote right now.")
    return None


def require_learning_state_allowed(user):  # noqa: ANN001
    if not can_mutate_learning_state(user):
        return HttpResponseForbidden("Your account is in read-only mode.")
    return None


def moderator_required(view_func):  # noqa: ANN001
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):  # noqa: ANN002, ANN003
        if not is_moderator(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return _wrapped


def admin_required(view_func):  # noqa: ANN001
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):  # noqa: ANN002, ANN003
        if not is_admin(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return _wrapped


def get_user_role(user):  # noqa: ANN001
    if not getattr(user, "is_authenticated", False):
        return PlatformRole.GUEST
    if getattr(user, "is_trusted_user", False):
        return PlatformRole.TRUSTED
    return PlatformRole.REGISTERED
