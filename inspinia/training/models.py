from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.text import slugify


def _submission_attachment_upload_to(instance, filename: str) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "upload"
    return f"training-submissions/{instance.submission_id}/{instance.id or 'new'}.{extension}"


class Topic(models.Model):
    title = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "title", "id"]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.title)
        self.title = (self.title or "").strip()
        self.description = (self.description or "").strip()
        super().save(*args, **kwargs)


class Subtopic(models.Model):
    class Level(models.TextChoices):
        CORE = "CORE", "Core"
        ADVANCED = "ADVANCED", "Advanced"
        EXCEPTIONAL = "EXCEPTIONAL", "Exceptional"

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="subtopics")
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180)
    category = models.CharField(max_length=120, blank=True)
    level = models.CharField(max_length=16, choices=Level.choices, blank=True)
    is_imo_syllabus = models.BooleanField("IMO syllabus", default=False, db_index=True)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["topic__order", "order", "title", "id"]
        constraints = [
            models.UniqueConstraint(fields=["topic", "slug"], name="training_subtopic_unique_topic_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.topic.title}: {self.title}"

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.title)
        self.title = (self.title or "").strip()
        self.category = (self.category or "").strip()
        self.description = (self.description or "").strip()
        super().save(*args, **kwargs)


class Material(models.Model):
    subtopic = models.ForeignKey(Subtopic, on_delete=models.CASCADE, related_name="materials")
    title = models.CharField(max_length=180)
    slug = models.SlugField(unique=True)
    content_markdown = models.TextField()
    estimated_minutes = models.PositiveIntegerField(default=10)
    completion_points = models.PositiveIntegerField(default=10)
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="training_materials_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["subtopic__topic__order", "subtopic__order", "order", "title", "id"]
        indexes = [
            models.Index(fields=["is_published", "slug"], name="training_material_pub_slug_idx"),
        ]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.title)
        self.title = (self.title or "").strip()
        self.content_markdown = (self.content_markdown or "").strip()
        super().save(*args, **kwargs)


class Problem(models.Model):
    class Difficulty(models.TextChoices):
        INTRODUCTORY = "introductory", "Introductory"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"
        OLYMPIAD = "olympiad", "Olympiad"

    subtopic = models.ForeignKey(Subtopic, on_delete=models.CASCADE, related_name="problems")
    title = models.CharField(max_length=180)
    slug = models.SlugField(unique=True)
    statement_markdown = models.TextField()
    difficulty = models.CharField(max_length=24, choices=Difficulty.choices, default=Difficulty.INTRODUCTORY)
    mohs_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    source = models.CharField(max_length=180, blank=True)
    tags = models.JSONField(blank=True, default=list)
    expected_method = models.CharField(max_length=180, blank=True)
    max_points = models.PositiveIntegerField(default=40)
    official_solution_markdown = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="training_problems_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["subtopic__topic__order", "subtopic__order", "order", "title", "id"]
        indexes = [
            models.Index(fields=["is_published", "slug"], name="training_problem_pub_slug_idx"),
            models.Index(fields=["difficulty", "is_published"], name="training_problem_diff_pub_idx"),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def difficulty_badge_class(self) -> str:
        return {
            self.Difficulty.INTRODUCTORY: "bg-success-subtle text-success border border-success-subtle",
            self.Difficulty.INTERMEDIATE: "bg-info-subtle text-info border border-info-subtle",
            self.Difficulty.ADVANCED: "bg-warning-subtle text-warning border border-warning-subtle",
            self.Difficulty.OLYMPIAD: "bg-danger-subtle text-danger border border-danger-subtle",
        }.get(self.difficulty, "bg-light text-dark border")

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.title)
        self.title = (self.title or "").strip()
        self.statement_markdown = (self.statement_markdown or "").strip()
        self.source = (self.source or "").strip()
        self.expected_method = (self.expected_method or "").strip()
        self.official_solution_markdown = (self.official_solution_markdown or "").strip()
        self.tags = [str(tag).strip().upper() for tag in self.tags or [] if str(tag).strip()]
        super().save(*args, **kwargs)


class MaterialCompletion(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="training_completions")
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="completions")
    completed_at = models.DateTimeField(auto_now_add=True)
    points_awarded = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-completed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "material"],
                name="training_materialcompletion_unique_user_material",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-completed_at"], name="training_matcomp_user_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} completed {self.material_id}"


class Submission(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        ACCEPTED = "accepted", "Accepted"
        PARTIALLY_ACCEPTED = "partially_accepted", "Partially accepted"
        NEEDS_REVISION = "needs_revision", "Needs revision"
        REJECTED = "rejected", "Rejected"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="training_submissions")
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name="submissions")
    solution_markdown = models.TextField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.SUBMITTED, db_index=True)
    awarded_points = models.PositiveIntegerField(default=0)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="training_submissions_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["status", "-updated_at"], name="training_submission_status_idx"),
            models.Index(fields=["user", "problem", "-updated_at"], name="training_sub_user_prob_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} - {self.problem.title}"

    @property
    def is_accepted_for_progress(self) -> bool:
        return self.status in {self.Status.ACCEPTED, self.Status.PARTIALLY_ACCEPTED}

    @property
    def status_badge_class(self) -> str:
        return {
            self.Status.ACCEPTED: "text-bg-success",
            self.Status.PARTIALLY_ACCEPTED: "text-bg-success",
            self.Status.NEEDS_REVISION: "text-bg-warning",
            self.Status.REJECTED: "text-bg-danger",
            self.Status.SUBMITTED: "text-bg-info",
            self.Status.UNDER_REVIEW: "text-bg-primary",
        }.get(self.status, "text-bg-secondary")


class SubmissionAttachment(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=_submission_attachment_upload_to)
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self) -> str:
        return self.original_name or self.file.name


class SubmissionComment(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="training_comments")
    body_markdown = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"Comment {self.id} on submission {self.submission_id}"


class PointLedger(models.Model):
    class SourceType(models.TextChoices):
        MATERIAL_COMPLETION = "material_completion", "Material completion"
        PROBLEM_SUBMISSION = "problem_submission", "Problem submission"
        MANUAL_ADJUSTMENT = "manual_adjustment", "Manual adjustment"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="training_point_entries")
    source_type = models.CharField(max_length=32, choices=SourceType.choices, db_index=True)
    source_id = models.CharField(max_length=64)
    points = models.IntegerField()
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="training_point_entries_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "source_id"],
                condition=Q(source_type__in=["material_completion", "problem_submission"]),
                name="training_pointledger_unique_award_source",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="training_point_user_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}: {self.points} points"


class LevelThreshold(models.Model):
    level_number = models.PositiveSmallIntegerField(
        unique=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    name = models.CharField(max_length=120)
    minimum_points = models.PositiveIntegerField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["minimum_points", "level_number"]

    def __str__(self) -> str:
        return f"Level {self.level_number}: {self.name}"
