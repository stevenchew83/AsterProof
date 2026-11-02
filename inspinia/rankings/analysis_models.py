"""Reviewed analytical metadata and durable ranking correction records."""

from django.db import models
from django.db.models import F
from django.db.models import Q
from django.utils import timezone


class AssessmentAnalysisMetadata(models.Model):
    assessment = models.OneToOneField(
        "rankings.Assessment",
        on_delete=models.CASCADE,
        related_name="analysis_metadata",
    )
    family = models.CharField(max_length=64, blank=True)
    definition = models.TextField(blank=True)
    definition_verified = models.BooleanField(default=False)
    date_verified = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey("users.User", null=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Assessment {self.assessment_id} analysis metadata"


class AssessmentCategoryScale(models.Model):
    assessment = models.ForeignKey("rankings.Assessment", on_delete=models.CASCADE, related_name="analysis_scales")
    band = models.CharField(max_length=32, blank=True)
    max_score = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    verified = models.BooleanField(default=False)
    comparable_scope = models.CharField(max_length=80, blank=True)
    evidence = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["assessment", "band"], name="rank_scale_unique_cohort"),
            models.CheckConstraint(
                condition=Q(max_score__isnull=True) | Q(max_score__gt=0),
                name="rank_scale_positive_max",
            ),
            models.CheckConstraint(
                condition=Q(verified=False) | Q(max_score__isnull=False),
                name="rank_scale_verified_max",
            ),
        ]

    def __str__(self):
        return f"Assessment {self.assessment_id} / {self.band or 'Uncategorized'} scoring scale"


class ResultSchoolAttribution(models.Model):
    result = models.OneToOneField(
        "rankings.StudentResult",
        on_delete=models.CASCADE,
        related_name="school_attribution",
    )
    school = models.ForeignKey("rankings.School", on_delete=models.PROTECT)
    verified = models.BooleanField(default=True)
    evidence = models.TextField()
    reviewed_by = models.ForeignKey("users.User", null=True, on_delete=models.SET_NULL)
    reviewed_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Result {self.result_id} school attribution"


class SchoolAlias(models.Model):
    alias = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, unique=True)
    school = models.ForeignKey("rankings.School", on_delete=models.PROTECT, related_name="analysis_aliases")
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"School alias {self.pk or 'unsaved'}"


class OutcomeAlias(models.Model):
    class Field(models.TextChoices):
        BAND = "band", "Category"
        MEDAL = "medal", "Medal"
        STATUS = "status_text", "Status"

    assessment = models.ForeignKey("rankings.Assessment", on_delete=models.CASCADE, related_name="outcome_aliases")
    field = models.CharField(max_length=16, choices=Field.choices)
    alias = models.CharField(max_length=64)
    normalized_alias = models.CharField(max_length=64)
    canonical = models.CharField(max_length=64)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "field", "normalized_alias"],
                name="rank_outcome_unique_alias",
            ),
        ]

    def __str__(self):
        return f"Assessment {self.assessment_id} / {self.field} alias {self.pk or 'unsaved'}"


class StudentIdentityReview(models.Model):
    class Decision(models.TextChoices):
        POSSIBLE_DUPLICATE = "possible_duplicate", "Needs identity review"
        CONFIRMED_SEPARATE = "confirmed_separate", "Confirmed separate students"

    first_student = models.ForeignKey(
        "rankings.Student",
        on_delete=models.PROTECT,
        related_name="identity_reviews_first",
    )
    second_student = models.ForeignKey(
        "rankings.Student",
        on_delete=models.PROTECT,
        related_name="identity_reviews_second",
    )
    decision = models.CharField(max_length=24, choices=Decision.choices)
    evidence = models.TextField()
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["first_student", "second_student"], name="rank_identity_unique_pair"),
            models.CheckConstraint(
                condition=Q(first_student__lt=F("second_student")),
                name="rank_identity_ordered_pair",
            ),
        ]

    def __str__(self):
        return f"Students {self.first_student_id} / {self.second_student_id}: {self.get_decision_display()}"


class RankingCorrection(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Awaiting admin"
        APPLIED = "applied", "Applied"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    reason = models.TextField()
    evidence = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="ranking_corrections",
    )
    decided_by = models.ForeignKey(
        "users.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="ranking_corrections_decided",
    )
    decision_reason = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True)
    reverses = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"Correction {self.pk or 'unsaved'}: {self.get_status_display()}"


class RankingCorrectionItem(models.Model):
    class Kind(models.TextChoices):
        STUDENT = "student", "Student"
        RESULT = "result", "Result"
        ASSESSMENT = "assessment", "Assessment"
        METADATA = "metadata", "Assessment definition"
        SCALE = "scale", "Category scoring scale"
        ATTRIBUTION = "attribution", "School at assessment"
        SCHOOL_ALIAS = "school_alias", "School alias"
        OUTCOME_ALIAS = "outcome_alias", "Outcome alias"
        IDENTITY = "identity", "Identity review"

    correction = models.ForeignKey(RankingCorrection, on_delete=models.PROTECT, related_name="items")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    target_id = models.PositiveBigIntegerField()
    before = models.JSONField(default=dict)
    changes = models.JSONField(default=dict)

    class Meta:
        ordering = ["kind", "target_id", "pk"]
        indexes = [models.Index(fields=["kind", "target_id"], name="rank_correction_target_idx")]

    def __str__(self):
        return f"Correction {self.correction_id}: {self.kind} {self.target_id}"


class RankingCorrectionReceipt(models.Model):
    correction = models.OneToOneField(RankingCorrection, on_delete=models.PROTECT, related_name="receipt")
    actor = models.ForeignKey("users.User", null=True, on_delete=models.SET_NULL)
    changes = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Correction {self.correction_id} application receipt"


class RankingImportConflict(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting review"
        KEPT = "kept", "Kept approved values"
        REPLACED = "replaced", "Replacement applied"

    batch = models.ForeignKey("rankings.ImportBatch", on_delete=models.PROTECT, related_name="protected_conflicts")
    row_number = models.PositiveIntegerField()
    operations = models.JSONField(default=list)
    conflicts = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    correction = models.ForeignKey(
        RankingCorrection,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="import_conflicts",
    )
    resolved_by = models.ForeignKey("users.User", null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "row_number"], name="rank_import_unique_held_row")]
        ordering = ["-created_at", "pk"]

    def __str__(self):
        return f"Import {self.batch_id}, row {self.row_number}: {self.get_status_display()}"


class RankingWriteLock(models.Model):
    """Short, shared transaction lock for corrections and ranking import writers."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(id=1), name="rank_write_singleton")]

    def __str__(self):
        return "Ranking write lock"
