"""Durable assignment decisions; source tags and assessment records stay separate."""

import uuid

from django.conf import settings
from django.db import models


class ProblemConceptAssignment(models.Model):
    class Disposition(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        SUGGESTED = "suggested", "Suggested"
        REJECTED = "rejected", "Rejected"

    problem_uuid = models.UUIDField(db_index=True)
    concept_id = models.CharField(max_length=160)
    disposition = models.CharField(max_length=16, choices=Disposition.choices, default=Disposition.SUGGESTED)
    decision_origin = models.CharField(max_length=24, default="auto_direct_tag")
    roles = models.JSONField(default=list)
    subject_context = models.CharField(max_length=32, blank=True)
    area_context = models.CharField(max_length=180, blank=True)
    evidence = models.JSONField(default=list)
    reasons = models.JSONField(default=list)
    source_fingerprint = models.CharField(max_length=64)
    concept_signature = models.CharField(max_length=64)
    is_stale = models.BooleanField(default=False)
    is_current = models.BooleanField(default=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="concept_assignment_reviews",
    )
    rationale = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["problem_uuid", "concept_id"], name="pages_pca_uuid_concept_uniq"),
        ]
        indexes = [models.Index(fields=["disposition", "is_stale", "concept_id"], name="pages_pca_state_concept_idx")]

    def __str__(self):
        return f"{self.problem_uuid}: {self.concept_id} ({self.disposition})"


class ConceptAssignmentReviewBatch(models.Model):
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    preview_sha256 = models.CharField(max_length=64)
    registry_fingerprint = models.CharField(max_length=64)
    kind = models.CharField(max_length=24, default="review")
    manifest = models.JSONField(default=dict)
    receipt = models.JSONField(default=dict)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="concept_review_batches",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.operation_id)


class ConceptAssignmentReviewEvent(models.Model):
    batch = models.ForeignKey(ConceptAssignmentReviewBatch, on_delete=models.PROTECT, related_name="events")
    problem_uuid = models.UUIDField(db_index=True)
    concept_id = models.CharField(max_length=160)
    action = models.CharField(max_length=24)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="concept_review_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.problem_uuid}: {self.action} {self.concept_id}"


class ConceptAssignmentState(models.Model):
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    enabled = models.BooleanField(default=False)
    initial_seed_complete = models.BooleanField(default=False)
    revision = models.PositiveBigIntegerField(default=0)
    registry_fingerprint = models.CharField(max_length=64, blank=True)
    needs_refresh = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Assignment projection {self.revision}"
