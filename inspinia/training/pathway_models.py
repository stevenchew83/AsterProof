"""Curated curricula and revision-aware reading, independent of legacy points."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class ImmutablePathQuerySet(models.QuerySet):
    def update(self, **kwargs):
        msg = "Pathway revisions cannot be changed. Create a new revision."
        raise ValidationError(msg)

    def delete(self):
        msg = "Retained pathway history cannot be deleted."
        raise ValidationError(msg)

    def bulk_update(self, objs, fields, batch_size=None):
        msg = "Pathway revisions cannot be changed. Create a new revision."
        raise ValidationError(msg)

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            msg = "Pathway revisions cannot be changed. Create a new revision."
            raise ValidationError(msg)
        return super().bulk_create(objs, **kwargs)


class ImmutablePathRecord(models.Model):
    objects = ImmutablePathQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding or kwargs.get("force_update"):
            msg = "Pathway history is immutable."
            raise ValidationError(msg)
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        msg = "Retained pathway history cannot be deleted."
        raise ValidationError(msg)


class LearningPath(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=120, unique=True)
    subject = models.ForeignKey("pages.CatalogueSubject", null=True, blank=True, on_delete=models.PROTECT)
    area = models.ForeignKey("pages.CatalogueArea", null=True, blank=True, on_delete=models.PROTECT)
    is_foundations = models.BooleanField(default=False)
    current_revision = models.ForeignKey(
        "LearningPathRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for_paths",
    )
    version = models.PositiveIntegerField(default=0)
    training_visible = models.BooleanField(default=False)
    public_visible = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["slug"]
        constraints = [
            models.CheckConstraint(
                condition=Q(public_visible=False) | Q(training_visible=True),
                name="training_path_public_needs_training",
            ),
            models.CheckConstraint(
                condition=Q(is_foundations=False) | (Q(subject__isnull=True) & Q(area__isnull=True)),
                name="training_foundations_cross_topic",
            ),
        ]

    def __str__(self):
        return self.current_revision.title if self.current_revision_id else self.slug


class LearningPathRevision(ImmutablePathRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    path = models.ForeignKey(LearningPath, on_delete=models.PROTECT, related_name="revisions")
    sequence = models.PositiveIntegerField()
    title = models.CharField(max_length=180)
    summary = models.CharField(max_length=500, blank=True)
    audience = models.CharField(max_length=500, blank=True)
    readiness = models.JSONField(default=list)
    snapshot = models.JSONField(default=dict)
    source_digest = models.CharField(max_length=64)
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    review_context_digest = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["path_id", "sequence"]
        constraints = [models.UniqueConstraint(fields=["path", "sequence"], name="training_path_revision_sequence")]

    def __str__(self):
        return f"{self.title} (revision {self.sequence})"


class LearningPathItem(ImmutablePathRecord):
    class Kind(models.TextChoices):
        DOCUMENT = "document", "Lecture note"
        PROBLEM = "problem", "Canonical practice problem"
        LEGACY = "legacy", "Existing Training material"
        EXERCISE = "exercise", "Original practice"

    revision = models.ForeignKey(LearningPathRevision, on_delete=models.PROTECT, related_name="items")
    item_key = models.SlugField(max_length=80)
    position = models.PositiveIntegerField()
    title = models.CharField(max_length=180)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    document = models.ForeignKey(
        "learning.ContentDocument", null=True, blank=True, on_delete=models.PROTECT, related_name="pathway_items",
    )
    problem = models.ForeignKey(
        "pages.ProblemSolveRecord",
        to_field="problem_uuid",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="learning_path_items",
    )
    legacy_material = models.ForeignKey(
        "training.Material", null=True, blank=True, on_delete=models.PROTECT, related_name="pathway_items",
    )
    exercise_source = models.TextField(blank=True)
    hints = models.JSONField(default=list)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["revision", "item_key"], name="training_path_item_key"),
            models.UniqueConstraint(fields=["revision", "position"], name="training_path_item_position"),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind="document",
                        document__isnull=False,
                        problem__isnull=True,
                        legacy_material__isnull=True,
                        exercise_source="",
                    )
                    | Q(
                        kind="problem",
                        document__isnull=True,
                        problem__isnull=False,
                        legacy_material__isnull=True,
                        exercise_source="",
                    )
                    | Q(
                        kind="legacy",
                        document__isnull=True,
                        problem__isnull=True,
                        legacy_material__isnull=False,
                        exercise_source="",
                    )
                    | (
                        Q(kind="exercise", document__isnull=True, problem__isnull=True, legacy_material__isnull=True)
                        & ~Q(exercise_source="")
                    )
                ),
                name="training_path_item_typed_target",
            ),
        ]


class PathReading(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="path_readings")
    path_revision = models.ForeignKey(LearningPathRevision, on_delete=models.PROTECT)
    item = models.ForeignKey(LearningPathItem, on_delete=models.PROTECT)
    document_revision = models.ForeignKey("learning.ContentRevision", on_delete=models.PROTECT)
    completed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reading {self.pk}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "path_revision", "item", "document_revision"],
                name="training_reading_once_per_revision",
            ),
        ]


class ContentPackImport(models.Model):
    """Private import receipt: data files cannot manufacture editorial approval."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    pack_key = models.CharField(max_length=160)
    source_digest = models.CharField(max_length=64)
    draft_ids = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.pack_key

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "pack_key"], name="training_pack_once_per_author")]
