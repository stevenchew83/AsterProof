import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.text import slugify

PROBLEM_LIST_ITEM_CUSTOM_TITLE_MAX_LENGTH = 160


class ProblemList(models.Model):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private"
        PUBLIC = "public", "Public"

    list_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="problem_lists",
    )
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
        db_index=True,
    )
    share_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    hide_source = models.BooleanField(default=False)
    hide_topic = models.BooleanField(default=False)
    hide_mohs = models.BooleanField(default=False)
    hide_subtopics = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["author", "-updated_at"], name="ps_list_author_upd_idx"),
            models.Index(fields=["visibility", "-published_at"], name="ps_list_vis_pub_idx"),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_public(self) -> bool:
        return self.visibility == self.Visibility.PUBLIC

    @property
    def public_slug(self) -> str:
        return slugify(self.title) or "problem-list"

    def public_url(self) -> str:
        return reverse("problemsets:public_detail", args=[self.share_token, self.public_slug])

    def save(self, *args, **kwargs) -> None:
        self.title = (self.title or "").strip()
        self.description = (self.description or "").strip()
        super().save(*args, **kwargs)


class ProblemListItem(models.Model):
    problem_list = models.ForeignKey(
        ProblemList,
        on_delete=models.CASCADE,
        related_name="items",
    )
    problem = models.ForeignKey(
        "pages.ProblemSolveRecord",
        on_delete=models.CASCADE,
        related_name="problem_list_items",
    )
    position = models.PositiveIntegerField()
    custom_title = models.CharField(max_length=PROBLEM_LIST_ITEM_CUSTOM_TITLE_MAX_LENGTH, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["problem_list", "problem"],
                name="problemsets_listitem_unique_list_problem",
            ),
            models.UniqueConstraint(
                fields=["problem_list", "position"],
                name="problemsets_listitem_unique_list_position",
            ),
        ]
        indexes = [
            models.Index(fields=["problem_list", "position"], name="ps_item_list_pos_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.problem_list_id}:{self.position} {self.problem}"

    def save(self, *args, **kwargs) -> None:
        self.custom_title = (self.custom_title or "").strip()
        super().save(*args, **kwargs)


class ProblemListVote(models.Model):
    class Value(models.IntegerChoices):
        DOWN = -1, "Thumbs down"
        UP = 1, "Thumbs up"

    problem_list = models.ForeignKey(
        ProblemList,
        on_delete=models.CASCADE,
        related_name="votes",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="problem_list_votes",
    )
    value = models.IntegerField(choices=Value.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["problem_list", "user"],
                name="problemsets_vote_unique_list_user",
            ),
            models.CheckConstraint(
                condition=Q(value=-1) | Q(value=1),
                name="problemsets_vote_valid_value",
            ),
        ]
        indexes = [
            models.Index(fields=["problem_list", "value"], name="ps_vote_list_value_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.problem_list_id}:{self.user_id} {self.value}"
