
from typing import ClassVar

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import CharField
from django.db.models import DateField
from django.db.models import EmailField
from django.db.models import TextChoices
from django.db.models import TextField
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class User(AbstractUser):
    """
    Default custom user model for inspinia.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    class Role(TextChoices):
        ADMIN = "admin", _("Admin")
        MODERATOR = "moderator", _("Moderator")
        TRAINER = "trainer", _("Trainer")
        NORMAL = "normal", _("Normal user")

    class Gender(TextChoices):
        FEMALE = "female", _("Female")
        MALE = "male", _("Male")
        NON_BINARY = "non_binary", _("Non-binary")
        OTHER = "other", _("Other")
        PREFER_NOT_TO_SAY = "prefer_not_to_say", _("Prefer not to say")

    # First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    school = CharField(_("School"), blank=True, max_length=255)
    contact_number = CharField(
        _("Contact number"),
        blank=True,
        help_text=_("Include the country code, for example +60 12-345 6789."),
        max_length=32,
    )
    discord_username = CharField(_("Discord username"), blank=True, max_length=50)
    birthdate = DateField(_("Birthdate"), blank=True, null=True)
    gender = CharField(
        _("Gender"),
        blank=True,
        choices=Gender.choices,
        max_length=20,
    )
    address = TextField(_("Address"), blank=True)
    postal_code = CharField(_("Postal code"), blank=True, max_length=20)
    country = CharField(_("Country"), blank=True, max_length=100)
    social_media_links = TextField(
        _("Social media links"),
        blank=True,
        help_text=_("Add one profile URL per line."),
    )
    role = CharField(
        _("Role"),
        max_length=20,
        choices=Role.choices,
        default=Role.NORMAL,
        db_index=True,
    )
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]
    email = EmailField(_("email address"), unique=True)
    username = None  # type: ignore[assignment]

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects: ClassVar[UserManager] = UserManager()

    def get_absolute_url(self) -> str:
        """Get URL for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"pk": self.id})


class UserSession(models.Model):
    class Status(TextChoices):
        ACTIVE = "active", _("Active")
        LOGGED_OUT = "logged_out", _("Logged out")
        REVOKED = "revoked", _("Revoked")
        EXPIRED = "expired", _("Expired")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tracked_sessions",
    )
    session_key = models.CharField(max_length=40, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ended_reason = models.CharField(max_length=20, choices=Status.choices, blank=True)

    class Meta:
        ordering = ["-last_seen_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "ended_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} [{self.session_status}]"

    @property
    def session_status(self) -> str:
        if self.ended_at is None and self.expires_at > timezone.now():
            return self.Status.ACTIVE
        if self.ended_reason:
            return self.ended_reason
        return self.Status.EXPIRED

    @property
    def session_status_label(self) -> str:
        return str(self.Status(self.session_status).label)

    @property
    def session_status_badge_class(self) -> str:
        status = self.Status(self.session_status)
        return {
            self.Status.ACTIVE: "text-bg-success",
            self.Status.LOGGED_OUT: "text-bg-secondary",
            self.Status.REVOKED: "text-bg-danger",
            self.Status.EXPIRED: "text-bg-warning",
        }[status]


class AuditEvent(models.Model):
    class EventType(TextChoices):
        LOGIN_SUCCEEDED = "auth.login_succeeded", _("Login succeeded")
        LOGIN_FAILED = "auth.login_failed", _("Login failed")
        LOGOUT = "auth.logout", _("Logout")
        SIGNUP = "auth.signup", _("Signup")
        ROLE_CHANGED = "users.role_changed", _("Role changed")
        SESSION_REVOKED = "sessions.revoked", _("Session revoked")
        IMPORT_PREVIEWED = "imports.previewed", _("Workbook previewed")
        IMPORT_COMPLETED = "imports.completed", _("Workbook imported")
        IMPORT_FAILED = "imports.failed", _("Workbook import failed")

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="targeted_audit_events",
    )
    event_type = models.CharField(max_length=64, choices=EventType.choices, db_index=True)
    message = models.CharField(max_length=255)
    session_key = models.CharField(max_length=40, blank=True)
    path = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["target_user", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_event_type_display()}: {self.message}"

    @property
    def badge_class(self) -> str:
        if self.event_type == self.EventType.LOGIN_FAILED:
            return "text-bg-danger"
        if self.event_type in {
            self.EventType.LOGIN_SUCCEEDED,
            self.EventType.SIGNUP,
            self.EventType.IMPORT_COMPLETED,
        }:
            return "text-bg-success"
        if self.event_type in {
            self.EventType.LOGOUT,
            self.EventType.IMPORT_PREVIEWED,
        }:
            return "text-bg-info"
        if self.event_type in {
            self.EventType.ROLE_CHANGED,
            self.EventType.SESSION_REVOKED,
        }:
            return "text-bg-warning"
        return "text-bg-secondary"
