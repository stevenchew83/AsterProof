"""Private, revision-bound coaching jobs and explicitly activated operating policy."""

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models


class SolutionReviewPolicy(models.Model):
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    enabled = models.BooleanField(default=False)
    model = models.CharField(max_length=120, default="gpt-6-astra")
    daily_budget_micros = models.PositiveBigIntegerField(default=0)
    monthly_budget_micros = models.PositiveBigIntegerField(default=0)
    request_budget_micros = models.PositiveBigIntegerField(default=0)
    input_price_micros_per_million = models.PositiveBigIntegerField(default=10_000_000)
    output_price_micros_per_million = models.PositiveBigIntegerField(default=50_000_000)
    image_token_bound = models.PositiveIntegerField(default=16_384)
    pricing_verified_at = models.DateTimeField(null=True, blank=True)
    user_daily_limit = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(3)],
    )
    global_daily_limit = models.PositiveSmallIntegerField(
        default=20, validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    worker_seen_at = models.DateTimeField(null=True, blank=True, editable=False)
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_until = models.DateTimeField(null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(singleton_key=1), name="solutions_review_policy_singleton"),
        ]
        verbose_name_plural = "solution review policy"

    def __str__(self):
        return "Solution AI review policy"


class SolutionReview(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        OUTCOME_UNKNOWN = "outcome_unknown", "Outcome unknown"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey("solutions.SolutionRevision", on_delete=models.CASCADE, related_name="reviews")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="solution_reviews")
    idempotency_key = models.UUIDField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True)
    input_snapshot = models.JSONField(default=dict)
    input_digest = models.CharField(max_length=64)
    model = models.CharField(max_length=120)
    prompt_version = models.CharField(max_length=32, default="coach-v1")
    rubric_version = models.CharField(max_length=32, default="olympiad-coach-v1")
    schema_version = models.PositiveSmallIntegerField(default=1)
    reserved_micros = models.PositiveBigIntegerField()
    accounted_micros = models.PositiveBigIntegerField()
    pricing_snapshot = models.JSONField(default=dict)
    feedback = models.JSONField(default=dict)
    provider_request_id = models.CharField(max_length=200, blank=True)
    provider_response_id = models.CharField(max_length=200, blank=True)
    usage = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True)
    acknowledged_at = models.DateTimeField()
    dispatched_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["author", "idempotency_key"], name="solutions_review_idempotency"),
        ]
        indexes = [models.Index(fields=["author", "created_at"])]

    def __str__(self):
        return f"Review {self.pk}: {self.status}"
