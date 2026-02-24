
from typing import ClassVar

from django.contrib.auth.models import AbstractUser
from django.db import OperationalError
from django.db import ProgrammingError
from django.db.models import BooleanField
from django.db.models import CharField
from django.db.models import DateTimeField
from django.db.models import EmailField
from django.db.models import FloatField
from django.db.models import ImageField
from django.db.models import QuerySet
from django.db.models import SlugField
from django.db.models import TextField
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class User(AbstractUser):
    """
    Default custom user model for inspinia.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    # First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    handle = SlugField(_("Handle"), max_length=64, unique=True, blank=True, null=True)
    display_name = CharField(_("Display name"), blank=True, max_length=255)
    avatar = ImageField(upload_to="avatars/", blank=True, null=True)
    bio = TextField(blank=True)
    country = CharField(max_length=64, blank=True)
    profile_visibility = CharField(
        max_length=16,
        default="public",
        choices=(
            ("public", "Public"),
            ("semi_private", "Semi-private"),
            ("private", "Private"),
        ),
    )
    is_trusted_user = BooleanField(default=False)
    show_in_leaderboards = BooleanField(default=True)
    is_banned = BooleanField(default=False)
    mute_expires_at = DateTimeField(null=True, blank=True)
    is_readonly = BooleanField(default=False)
    is_shadow_banned = BooleanField(default=False)
    is_profile_hidden = BooleanField(default=False)
    rating = FloatField(default=1200)
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

    @property
    def is_muted_now(self) -> bool:
        if self.mute_expires_at is None:
            return False
        return self.mute_expires_at > timezone.now()

    def _build_candidate_handle(self) -> str:
        base = slugify(self.handle) if self.handle else ""
        if not base:
            if self.display_name:
                base = slugify(self.display_name)
            elif self.name:
                base = slugify(self.name)
            elif self.email:
                base = slugify(self.email.split("@", maxsplit=1)[0])
        if not base:
            base = "user"
        return base[:48]

    def _handle_exists(self, candidate: str) -> bool:
        qs: QuerySet[User] = User.objects.filter(handle=candidate)
        if self.pk is not None:
            qs = qs.exclude(pk=self.pk)
        return qs.exists()

    def _ensure_handle(self):
        base = self._build_candidate_handle()
        candidate = base
        suffix = 1
        while self._handle_exists(candidate):
            suffix += 1
            candidate = f"{base}-{suffix}"[:64]
        self.handle = candidate

    def save(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if self._state.adding and self.profile_visibility == "public":
            try:
                from inspinia.backoffice.services import get_privacy_defaults

                self.profile_visibility = get_privacy_defaults().default_profile_visibility
            except (OperationalError, ProgrammingError):
                pass
        if not self.handle:
            self._ensure_handle()
        super().save(*args, **kwargs)
