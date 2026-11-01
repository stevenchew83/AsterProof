"""User problem posts remain separate from the canonical contest archive."""

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models


class CommunityProblem(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Admin reviewed"
        CHANGES_REQUESTED = "changes_requested", "Changes requested"
        DECLINED = "declined", "Declined"

    class SourceKind(models.TextChoices):
        ORIGINAL = "original", "My original problem"
        ATTRIBUTED = "attributed", "From another source"

    class Topic(models.TextChoices):
        ALGEBRA = "ALG", "Algebra"
        COMBINATORICS = "COMB", "Combinatorics"
        GEOMETRY = "GEO", "Geometry"
        NUMBER_THEORY = "NT", "Number theory"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="problem_posts")
    title = models.CharField(max_length=160)
    statement_latex = models.TextField()
    topic = models.CharField(max_length=32, choices=Topic.choices)
    mohs = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(60)],
    )
    topic_tags = models.CharField(max_length=1000, blank=True)
    core_ideas = models.TextField(blank=True)
    rationale = models.TextField(blank=True)
    pitfalls = models.TextField(blank=True)
    source_kind = models.CharField(max_length=16, choices=SourceKind.choices)
    source_details = models.CharField(max_length=1000)
    source_url = models.URLField(max_length=500, blank=True)
    contest_name = models.CharField(max_length=128, blank=True)
    contest_year = models.PositiveSmallIntegerField(null=True, blank=True)
    problem_code = models.CharField(max_length=16, blank=True)
    solution_outline = models.TextField(blank=True)
    solution_known = models.BooleanField(default=False)
    public_hint = models.TextField(blank=True)
    embargo_until = models.DateTimeField(null=True, blank=True)
    legacy_member_visible = models.BooleanField(default=False)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True)
    version = models.PositiveIntegerField(default=1)
    similarity_snapshot = models.JSONField(default=dict)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_problem_posts",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]

    def __str__(self):
        return self.title


class CommunityProblemReview(models.Model):
    problem = models.ForeignKey(CommunityProblem, on_delete=models.CASCADE, related_name="decisions")
    version = models.PositiveIntegerField()
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=24, choices=CommunityProblem.Status.choices)
    notes = models.TextField(blank=True)
    content_snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.problem_id}: {self.decision}"


class StatementSimilarityIndex(models.Model):
    singleton_key = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    signature = models.JSONField(default=dict)
    version = models.PositiveSmallIntegerField(default=1)
    built_at = models.DateTimeField(null=True)

    def __str__(self):
        return "Statement similarity index"


class StatementSimilaritySource(models.Model):
    singleton_key = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    revision = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return "Statement similarity source revision"


class StatementSimilarityDocument(models.Model):
    statement = models.OneToOneField("pages.ContestProblemStatement", on_delete=models.CASCADE)
    text_digest = models.CharField(max_length=64, db_index=True)
    structure_digest = models.CharField(max_length=64, db_index=True)
    normalized_text = models.TextField()
    structure_text = models.TextField()

    def __str__(self):
        return f"Statement {self.statement_id}"


class StatementSimilarityTerm(models.Model):
    document = models.ForeignKey(StatementSimilarityDocument, on_delete=models.CASCADE, related_name="terms")
    term = models.CharField(max_length=64, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["document", "term"], name="pages_similarity_term_unique")]

    def __str__(self):
        return self.term


class StatementReviewPolicy(models.Model):
    singleton_key = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    model = models.CharField(max_length=120, blank=True)
    request_budget_micros = models.PositiveBigIntegerField(default=0)
    daily_budget_micros = models.PositiveBigIntegerField(default=0)
    monthly_budget_micros = models.PositiveBigIntegerField(default=0)
    input_price_micros_per_million = models.PositiveBigIntegerField(default=0)
    output_price_micros_per_million = models.PositiveBigIntegerField(default=0)
    pricing_verified_at = models.DateTimeField(null=True, blank=True)
    daily_request_limit = models.PositiveSmallIntegerField(default=20)
    lease_until = models.DateTimeField(null=True, blank=True, editable=False)
    lease_job_id = models.UUIDField(null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Community statement AI review policy"


class StatementAIReview(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        UNKNOWN = "unknown", "Outcome unknown"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    problem = models.ForeignKey(CommunityProblem, on_delete=models.CASCADE, related_name="ai_reviews")
    version = models.PositiveIntegerField()
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True)
    input_snapshot = models.JSONField()
    input_digest = models.CharField(max_length=64)
    model = models.CharField(max_length=120)
    pricing_snapshot = models.JSONField()
    reserved_micros = models.PositiveBigIntegerField()
    accounted_micros = models.PositiveBigIntegerField()
    feedback = models.JSONField(default=dict)
    usage = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True)
    provider_response_id = models.CharField(max_length=200, blank=True)
    provider_request_id = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["problem", "version"], name="pages_statement_review_version")]

    def __str__(self):
        return f"Statement review {self.pk}: {self.status}"
