from __future__ import annotations

from inspinia.users.roles import user_has_admin_role

NRIC_VISIBLE_DIGITS = 4


def user_can_view_full_nric(user) -> bool:
    return user_has_admin_role(user)


def mask_nric(value: str) -> str:
    compact = (value or "").strip()
    if not compact:
        return ""
    if len(compact) <= NRIC_VISIBLE_DIGITS:
        return f"{'*' * len(compact)}"
    return f"{'*' * (len(compact) - NRIC_VISIBLE_DIGITS)}{compact[-NRIC_VISIBLE_DIGITS:]}"
