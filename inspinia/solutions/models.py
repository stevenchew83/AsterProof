import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import TextChoices


def _solution_body_image_upload_to(_instance, filename: str) -> str:
    lower = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    ext = lower if lower in {"png", "jpg", "jpeg", "gif", "webp"} else "png"
    if ext == "jpeg":
        ext = "jpg"
    return f"solution_body_images/{uuid.uuid4().hex}.{ext}"


class ProblemSolution(models.Model):
    class Status(TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    problem = models.ForeignKey(
        "pages.ProblemSolveRecord",
        on_delete=models.CASCADE,
        related_name="solutions",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="problem_solutions",
    )
    title = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    summary = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["problem", "author"],
                name="solutions_problemsolution_unique_problem_author",
            ),
        ]
        indexes = [
            models.Index(fields=["problem", "status"]),
            models.Index(fields=["author", "status"]),
        ]

    def __str__(self) -> str:
        title = self.title.strip()
        if title:
            return title
        return f"{self.author.email} - {self.problem.contest_year_problem or self.problem}"


class SolutionBlockType(models.Model):
    slug = models.SlugField(unique=True)
    label = models.CharField(max_length=64)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_system = models.BooleanField(default=True)
    allows_children = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "label", "id"]

    def __str__(self) -> str:
        return self.label


class ProblemSolutionBlock(models.Model):
    class BodyFormat(TextChoices):
        LATEX = "latex", "LaTeX"
        PLAIN_TEXT = "plain_text", "Plain text"

    solution = models.ForeignKey(
        ProblemSolution,
        on_delete=models.CASCADE,
        related_name="blocks",
    )
    parent_block = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    block_type = models.ForeignKey(
        SolutionBlockType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="solution_blocks",
    )
    position = models.PositiveIntegerField()
    title = models.CharField(max_length=160, blank=True)
    body_format = models.CharField(
        max_length=16,
        choices=BodyFormat.choices,
        default=BodyFormat.LATEX,
    )
    body_source = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["solution", "position"],
                name="solutions_problemsolutionblock_unique_solution_position",
            ),
        ]
        indexes = [
            models.Index(fields=["solution", "parent_block", "position"]),
        ]

    def clean(self) -> None:
        super().clean()
        if self.parent_block_id is None:
            return
        if self.pk is not None and self.parent_block_id == self.pk:
            msg = "A solution block cannot be its own parent."
            raise ValidationError({"parent_block": msg})
        if self.solution_id and self.parent_block.solution_id != self.solution_id:
            msg = "Parent block must belong to the same solution."
            raise ValidationError({"parent_block": msg})

    def __str__(self) -> str:
        title = self.title.strip()
        if title:
            return f"{self.solution_id}:{self.position} {title}"
        if self.block_type_id is not None:
            return f"{self.solution_id}:{self.position} {self.block_type.label}"
        return f"{self.solution_id}:{self.position} Block"


class SolutionSourceArtifact(models.Model):
    class ArtifactType(TextChoices):
        PDF = "pdf", "PDF"
        TEXT = "text", "Text"
        TEX = "tex", "TeX"
        IMAGE = "image", "Image"
        URL = "url", "URL"

    solution = models.ForeignKey(
        ProblemSolution,
        on_delete=models.CASCADE,
        related_name="source_artifacts",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="solution_source_artifacts",
    )
    artifact_type = models.CharField(max_length=16, choices=ArtifactType.choices)
    file = models.FileField(upload_to="solution-artifacts/%Y/%m/%d/", blank=True)
    original_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=128, blank=True)
    source_text = models.TextField(blank=True)
    source_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def clean(self) -> None:
        super().clean()
        source_text = self.source_text or ""
        source_url = self.source_url or ""
        has_payload = bool(self.file or source_text.strip() or source_url.strip())
        if has_payload:
            return
        msg = "Provide a file, source text, or source URL."
        raise ValidationError(msg)

    def __str__(self) -> str:
        return f"{self.get_artifact_type_display()} - solution {self.solution_id}"


class SolutionBodyImage(models.Model):
    """Image pasted into solution block bodies; referenced via \\includegraphics{path}."""

    solution = models.ForeignKey(
        ProblemSolution,
        on_delete=models.CASCADE,
        related_name="body_images",
    )
    file = models.ImageField(upload_to=_solution_body_image_upload_to)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="solution_body_images_uploaded",
    )

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self) -> str:
        return f"Body image {self.pk} → solution {self.solution_id}"
