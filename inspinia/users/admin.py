from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.utils.translation import gettext_lazy as _

from .forms import UserAdminChangeForm
from .forms import UserAdminCreationForm
from .models import AuditEvent
from .models import User
from .models import UserSession

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
        (_("Personal info"), {"fields": ("name", "role", "school", "birthdate", "gender")}),
        (
            _("Contact details"),
            {
                "fields": (
                    "contact_number",
                    "discord_username",
                    "address",
                    "postal_code",
                    "country",
                    "social_media_links",
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
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    list_display = ["email", "name", "school", "role", "is_superuser"]
    search_fields = ["email", "name", "school", "discord_username", "contact_number", "postal_code", "country"]
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


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "session_key",
        "ip_address",
        "last_seen_at",
        "expires_at",
        "ended_reason",
    )
    list_filter = ("ended_reason",)
    search_fields = ("user__email", "session_key", "ip_address", "user_agent")
    readonly_fields = ("created_at", "last_seen_at")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "event_type",
        "actor",
        "target_user",
        "message",
    )
    list_filter = ("event_type",)
    search_fields = ("message", "actor__email", "target_user__email", "session_key", "path")
    readonly_fields = ("created_at",)
