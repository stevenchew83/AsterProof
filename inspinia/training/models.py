from __future__ import annotations

import re
import uuid

from django.conf import settings
from django.db import models
from django.db.models import TextChoices
from django.utils import timezone
from django.utils.text import slugify


def normalize_training_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_training_lookup(value: str) -> str:
    return normalize_training_text(value).casefold()


class TrainingTopic(models.Model):
    topic_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    code = models.CharField(max_length=16, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "title", "id"]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs) -> None:
        self.code = normalize_training_text(self.code).upper()
        self.title = normalize_training_text(self.title)
        self.description = (self.description or "").strip()
        self.slug = slugify(self.title) or slugify(self.code) or "topic"

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"code", "title", "description", "slug"}

        super().save(*args, **kwargs)


class TrainingSubtopic(models.Model):
    topic = models.ForeignKey(TrainingTopic, on_delete=models.CASCADE, related_name="subtopics")
    subtopic_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    slug = models.SlugField(max_length=120)
    title = models.CharField(max_length=120)
    normalized_title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_seeded = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["topic__sort_order", "sort_order", "title", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["topic", "slug"],
                name="training_subtopic_unique_topic_slug",
            ),
            models.UniqueConstraint(
                fields=["topic", "normalized_title"],
                name="training_subtopic_unique_topic_norm_title",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.topic.title}: {self.title}"

    def save(self, *args, **kwargs) -> None:
        self.title = normalize_training_text(self.title)
        self.normalized_title = normalize_training_lookup(self.title)
        self.description = (self.description or "").strip()
        self.slug = slugify(self.title) or "subtopic"

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"title", "normalized_title", "description", "slug"}

        super().save(*args, **kwargs)


class TrainingMaterial(models.Model):
    class BodyFormat(TextChoices):
        MARKDOWN = "markdown", "Markdown"

    class Status(TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    material_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, db_index=True)
    summary = models.TextField(blank=True)
    body_source = models.TextField(blank=True)
    body_format = models.CharField(max_length=16, choices=BodyFormat.choices, default=BodyFormat.MARKDOWN)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="training_materials_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="training_materials_updated",
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    estimated_minutes = models.PositiveIntegerField(null=True, blank=True)
    subtopics = models.ManyToManyField(
        TrainingSubtopic,
        through="TrainingMaterialSubtopic",
        related_name="materials",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["status", "-published_at"], name="training_mat_status_pub_idx"),
        ]

    def __str__(self) -> str:
        return self.title

    def publish(self) -> None:
        self.status = self.Status.PUBLISHED
        if self.published_at is None:
            self.published_at = timezone.now()

    def save(self, *args, **kwargs) -> None:
        self.title = normalize_training_text(self.title)
        self.summary = (self.summary or "").strip()
        self.body_source = (self.body_source or "").strip()
        self.slug = slugify(self.title) or "training-material"

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"title", "summary", "body_source", "slug"}

        super().save(*args, **kwargs)


class TrainingMaterialSubtopic(models.Model):
    material = models.ForeignKey(
        TrainingMaterial,
        on_delete=models.CASCADE,
        related_name="material_subtopics",
    )
    subtopic = models.ForeignKey(
        TrainingSubtopic,
        on_delete=models.CASCADE,
        related_name="material_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["subtopic__topic__sort_order", "subtopic__sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["material", "subtopic"],
                name="training_material_subtopic_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.material_id}: {self.subtopic}"


class TrainingMaterialProblem(models.Model):
    material = models.ForeignKey(
        TrainingMaterial,
        on_delete=models.CASCADE,
        related_name="practice_problems",
    )
    problem = models.ForeignKey(
        "pages.ProblemSolveRecord",
        on_delete=models.CASCADE,
        related_name="training_material_links",
    )
    position = models.PositiveIntegerField()
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["material", "problem"],
                name="training_material_problem_unique_problem",
            ),
            models.UniqueConstraint(
                fields=["material", "position"],
                name="training_material_problem_unique_position",
            ),
        ]
        indexes = [
            models.Index(fields=["material", "position"], name="training_mat_problem_pos_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.material_id}:{self.position} {self.problem}"

    def save(self, *args, **kwargs) -> None:
        self.note = (self.note or "").strip()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"note"}
        super().save(*args, **kwargs)

