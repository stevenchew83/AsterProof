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
    current_revision = models.ForeignKey(
        "SolutionRevision", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="current_for_solutions",
    )
    edit_version = models.PositiveIntegerField(default=0, db_default=0)
    pdf_show_author = models.BooleanField(default=True, db_default=True)
    pdf_show_date = models.BooleanField(default=True, db_default=True)
    pdf_show_footer = models.BooleanField(default=True, db_default=True)
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

    def clean(self):
        super().clean()
        if self.current_revision_id and self.current_revision.solution_id != self.pk:
            message = "The current revision must belong to this solution."
            raise ValidationError({"current_revision": message})


class ImmutableRevisionQuerySet(models.QuerySet):
    def delete(self):
        message = "Saved revisions are removed only with their owning solution."
        raise ValidationError(message)

    def update(self, **kwargs):
        message = "Saved solution revisions cannot be changed. Save a new revision instead."
        raise ValidationError(message)

    def bulk_update(self, objs, fields, batch_size=None):
        message = "Saved solution revisions cannot be changed. Save a new revision instead."
        raise ValidationError(message)

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            message = "Saved solution revisions cannot be changed. Save a new revision instead."
            raise ValidationError(message)
        return super().bulk_create(objs, **kwargs)


class SolutionRevision(models.Model):
    """An immutable authored document; legacy blocks remain untouched."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    solution = models.ForeignKey(ProblemSolution, on_delete=models.CASCADE, related_name="revisions")
    sequence = models.PositiveIntegerField()
    body_source = models.TextField(blank=True)
    syntax_version = models.PositiveSmallIntegerField(default=1)
    title = models.CharField(max_length=160, blank=True)
    summary = models.TextField(blank=True)
    pdf_show_author = models.BooleanField(default=True)
    pdf_show_date = models.BooleanField(default=True)
    pdf_show_footer = models.BooleanField(default=True)
    source_digest = models.CharField(max_length=64)
    conversion_version = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableRevisionQuerySet.as_manager()

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["solution", "sequence"], name="solution_revision_unique_sequence"),
            models.CheckConstraint(condition=models.Q(sequence__gte=1), name="solution_revision_positive_sequence"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding or kwargs.get("force_update"):
            message = "Saved solution revisions cannot be changed. Save a new revision instead."
            raise ValidationError(message)
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Solution {self.solution_id}, revision {self.sequence}"

    def delete(self, *args, **kwargs):
        message = "Saved revisions are removed only with their owning solution."
        raise ValidationError(message)


class SolutionPublicShare(models.Model):
    """An explicitly shared copy; editor saves never change this snapshot."""

    solution = models.OneToOneField(ProblemSolution, on_delete=models.CASCADE, related_name="public_share")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    revision = models.UUIDField(default=uuid.uuid4, editable=False)
    is_active = models.BooleanField(default=False)
    snapshot = models.JSONField(default=dict)
    preview_image = models.BinaryField(default=bytes, editable=False)
    source_updated_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Public share for solution {self.solution_id}"


class SolutionShareDailyViews(models.Model):
    """Aggregate page opens; no visitor identifiers or request details are retained."""

    share = models.ForeignKey(SolutionPublicShare, on_delete=models.CASCADE, related_name="daily_views")
    day = models.DateField(db_index=True)
    views = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["share", "day"], name="solutions_share_views_unique_day"),
        ]

    def __str__(self):
        return f"Share {self.share_id}: {self.day}"


class SolutionCollection(models.Model):
    """An ordered public page of personal or site-curated shared copies."""

    class Kind(TextChoices):
        PERSONAL = "personal", "Personal"
        ADMIN_CURATED = "admin_curated", "Admin curated"

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PERSONAL, db_default=Kind.PERSONAL)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="solution_collections", null=True, blank=True,
    )
    title = models.CharField(max_length=160)
    introduction = models.TextField(blank=True, max_length=2000)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    revision = models.UUIDField(default=uuid.uuid4, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind="personal", owner__isnull=False)
                    | models.Q(kind="admin_curated", owner__isnull=True)
                ),
                name="solution_collection_kind_owner",
            ),
        ]

    def __str__(self):
        return self.title


class SolutionCollectionEntry(models.Model):
    collection = models.ForeignKey(SolutionCollection, on_delete=models.CASCADE, related_name="entries")
    share = models.ForeignKey(SolutionPublicShare, on_delete=models.CASCADE, related_name="collection_entries")
    anchor = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    position = models.PositiveIntegerField()
    # Bind to this sharing session. Stop + reshare must not revive old collections.
    share_token = models.UUIDField()

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["collection", "share"], name="solutions_collection_unique_share"),
        ]

    def __str__(self):
        return f"Collection {self.collection_id}: solution share {self.share_id} at {self.position}"


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


from inspinia.solutions.evaluation_models import ActivationAuthorization  # noqa: E402, F401
from inspinia.solutions.evaluation_models import AssistancePolicy  # noqa: E402, F401
from inspinia.solutions.evaluation_models import CoachJudgment  # noqa: E402, F401
from inspinia.solutions.evaluation_models import EvaluationAssignment  # noqa: E402, F401
from inspinia.solutions.evaluation_models import EvaluationAuditEvent  # noqa: E402, F401
from inspinia.solutions.evaluation_models import EvaluationCase  # noqa: E402, F401
from inspinia.solutions.evaluation_models import EvaluationDatasetSnapshot  # noqa: E402, F401
from inspinia.solutions.evaluation_models import EvaluationFindingJudgment  # noqa: E402, F401
from inspinia.solutions.evaluation_models import EvaluationLifecycle  # noqa: E402, F401
from inspinia.solutions.evaluation_models import EvaluationProblemFamily  # noqa: E402, F401
from inspinia.solutions.evaluation_models import EvaluationRun  # noqa: E402, F401
from inspinia.solutions.evaluation_models import HintRevealEvent  # noqa: E402, F401
from inspinia.solutions.evaluation_models import ReadinessEvidence  # noqa: E402, F401
from inspinia.solutions.evaluation_models import ReviewBundleAsset  # noqa: E402, F401
from inspinia.solutions.evaluation_models import ReviewConsent  # noqa: E402, F401
from inspinia.solutions.evaluation_models import ReviewerProfile  # noqa: E402, F401
from inspinia.solutions.evaluation_models import ReviewExecutionAttempt  # noqa: E402, F401
from inspinia.solutions.evaluation_models import ReviewInputBundle  # noqa: E402, F401
from inspinia.solutions.evaluation_models import ReviewSpendEvent  # noqa: E402, F401
from inspinia.solutions.problem_evaluation_models import EvaluationPackageApproval  # noqa: E402, F401
from inspinia.solutions.problem_evaluation_models import ProblemEvaluationPackage  # noqa: E402, F401
from inspinia.solutions.prototype_models import SyntheticHintReveal  # noqa: E402, F401
from inspinia.solutions.prototype_models import SyntheticReview  # noqa: E402, F401
from inspinia.solutions.review_models import SolutionReview  # noqa: E402, F401
from inspinia.solutions.review_models import SolutionReviewPolicy  # noqa: E402, F401
