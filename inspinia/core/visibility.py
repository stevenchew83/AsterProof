from enum import StrEnum

from inspinia.core.permissions import is_moderator


class VisibilityMode(StrEnum):
    PUBLIC = "public"
    SEMI_PRIVATE = "semi_private"
    PRIVATE = "private"


def can_view_profile(viewer, owner):  # noqa: ANN001
    if getattr(owner, "is_profile_hidden", False):
        return bool(
            getattr(viewer, "is_authenticated", False)
            and (viewer.pk == owner.pk or is_moderator(viewer))
        )
    if owner.profile_visibility == VisibilityMode.PUBLIC:
        return True
    if owner.profile_visibility == VisibilityMode.PRIVATE:
        return bool(getattr(viewer, "is_authenticated", False) and viewer.pk == owner.pk)
    return bool(getattr(viewer, "is_authenticated", False))
