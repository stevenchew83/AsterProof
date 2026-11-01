"""Versioned offline evidence. Content records are immutable; eligibility is separate."""

# ruff: noqa: DJ008, EM101, TRY003
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Evidence is immutable; append a new record.")

    def delete(self):
        raise ValidationError("Use the explicit content-withdrawal service.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Evidence is immutable; append a new record.")

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Evidence cannot be replaced.")
        return super().bulk_create(objs, **kwargs)


class EvidenceRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Evidence is immutable; append a new record.")
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Use the explicit content-withdrawal service.")


class EvaluationAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="evaluation_assignments",
    )
    appointed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    role = models.CharField(max_length=24)
    scope_id = models.UUIDField(db_index=True)
    expertise = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["actor", "role", "scope_id"], name="evaluation_assignment_unique"),
        ]


class EvaluationLifecycle(models.Model):
    target_id = models.UUIDField(primary_key=True)
    generation = models.PositiveIntegerField(default=1)
    eligible = models.BooleanField(default=True)
    reason = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class EvaluationAuditEvent(EvidenceRecord):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    target_id = models.UUIDField(db_index=True)
    kind = models.CharField(max_length=48, db_index=True)
    metadata = models.JSONField(default=dict)


class ReviewInputBundle(EvidenceRecord):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    problem_uuid = models.UUIDField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    digest = models.CharField(max_length=64, db_index=True)


class ReviewBundleAsset(EvidenceRecord):
    bundle = models.ForeignKey(ReviewInputBundle, on_delete=models.CASCADE, related_name="assets")
    original = models.BinaryField()
    normalized = models.BinaryField()
    manifest = models.JSONField(default=dict)


class ReviewerProfile(EvidenceRecord):
    payload = models.JSONField(default=dict)
    digest = models.CharField(max_length=64, unique=True)


class EvaluationProblemFamily(EvidenceRecord):
    title = models.CharField(max_length=200)
    domain = models.CharField(max_length=3)
    metadata = models.JSONField(default=dict)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")


class EvaluationCase(EvidenceRecord):
    family = models.ForeignKey(EvaluationProblemFamily, on_delete=models.PROTECT, related_name="cases")
    bundle = models.OneToOneField(ReviewInputBundle, on_delete=models.PROTECT, related_name="evaluation_case")
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    provenance = models.JSONField(default=dict)
    metadata = models.JSONField(default=dict)
    supersedes = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True)


class CoachJudgment(EvidenceRecord):
    case = models.ForeignKey(EvaluationCase, on_delete=models.PROTECT, related_name="judgments")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    kind = models.CharField(max_length=16, default="independent")
    payload = models.JSONField(default=dict)
    input_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["case", "actor", "kind"], name="evaluation_judgment_unique")]


class EvaluationDatasetSnapshot(EvidenceRecord):
    name = models.CharField(max_length=200)
    manifest = models.JSONField(default=dict)
    digest = models.CharField(max_length=64, unique=True)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")


class EvaluationRun(EvidenceRecord):
    snapshot = models.ForeignKey(EvaluationDatasetSnapshot, on_delete=models.PROTECT, related_name="runs")
    profile = models.ForeignKey(ReviewerProfile, on_delete=models.PROTECT)
    origin = models.CharField(max_length=32)
    protocol = models.JSONField(default=dict)
    reports = models.JSONField(default=dict)
    digest = models.CharField(max_length=64)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")


class EvaluationFindingJudgment(EvidenceRecord):
    run = models.ForeignKey(EvaluationRun, on_delete=models.PROTECT, related_name="finding_judgments")
    case = models.ForeignKey(EvaluationCase, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    payload = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "case", "actor"], name="evaluation_finding_judgment_unique"),
        ]


class ReviewExecutionAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.OneToOneField(
        "solutions.SolutionReview", on_delete=models.SET_NULL, null=True, related_name="execution",
    )
    run = models.ForeignKey(EvaluationRun, on_delete=models.PROTECT, null=True)
    bundle = models.ForeignKey(ReviewInputBundle, on_delete=models.SET_NULL, null=True)
    profile = models.ForeignKey(ReviewerProfile, on_delete=models.PROTECT)
    subject_id = models.UUIDField()
    origin = models.CharField(max_length=32, default="deterministic_fixture")
    status = models.CharField(max_length=24, default="queued")
    receipt = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class ReviewSpendEvent(EvidenceRecord):
    attempt = models.ForeignKey(ReviewExecutionAttempt, on_delete=models.PROTECT, related_name="spend_events")
    kind = models.CharField(max_length=16)
    amount_micros = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="USD")
    idempotency_key = models.CharField(max_length=100)
    metadata = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["attempt", "idempotency_key"], name="evaluation_spend_idempotent"),
        ]


class HintRevealEvent(EvidenceRecord):
    review = models.ForeignKey("solutions.SolutionReview", on_delete=models.CASCADE, related_name="hint_releases")
    finding_id = models.CharField(max_length=64)
    content_digest = models.CharField(max_length=64)
    level = models.PositiveSmallIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["review", "finding_id", "content_digest", "level"], name="evaluation_hint_unique",
            ),
        ]


class AssistancePolicy(EvidenceRecord):
    problem_uuid = models.UUIDField(db_index=True, null=True)
    actor_id_scope = models.PositiveBigIntegerField(null=True)
    mode = models.CharField(max_length=24)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=200)
    appointed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")


class ReviewConsent(EvidenceRecord):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    purpose = models.CharField(max_length=24)
    payload = models.JSONField(default=dict)
    expires_at = models.DateTimeField()


class ReadinessEvidence(EvidenceRecord):
    gate = models.CharField(max_length=1)
    target_id = models.UUIDField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    payload = models.JSONField(default=dict)
    decision = models.CharField(max_length=24)


class ActivationAuthorization(EvidenceRecord):
    activity = models.CharField(max_length=24)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    payload = models.JSONField(default=dict)
    expires_at = models.DateTimeField()
