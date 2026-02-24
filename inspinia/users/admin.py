from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.utils.translation import gettext_lazy as _

from .forms import UserAdminChangeForm
from .forms import UserAdminCreationForm
from .models import User

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    # Force the `admin` sign in process to go through the `django-allauth` workflow:
    # https://docs.allauth.org/en/latest/common/admin.html#admin
    admin.autodiscover()
    admin.site.login = secure_admin_login(admin.site.login)  # type: ignore[method-assign]


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Personal info"),
            {
                "fields": (
                    "name",
                    "handle",
                    "display_name",
                    "avatar",
                    "bio",
                    "country",
                    "profile_visibility",
                    "is_profile_hidden",
                    "rating",
                ),
            },
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "is_trusted_user",
                    "show_in_leaderboards",
                    "is_banned",
                    "mute_expires_at",
                    "is_readonly",
                    "is_shadow_banned",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    list_display = [
        "handle",
        "email",
        "display_name",
        "profile_visibility",
        "is_profile_hidden",
        "rating",
        "is_trusted_user",
        "is_banned",
        "is_readonly",
    ]
    list_filter = ["is_trusted_user", "is_banned", "is_readonly", "is_shadow_banned", "profile_visibility"]
    search_fields = ["name", "display_name", "handle", "email"]
    ordering = ["id"]
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )
