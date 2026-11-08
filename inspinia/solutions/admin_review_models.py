"""Settings and durable drafts for administrator-published AI feedback."""

import uuid

from django.conf import settings
from django.db import models

MODEL_CHOICES = (
    ("gpt-6-astra", "GPT-6 Astra"),
    ("gpt-6.1-sol", "GPT-6.1 Sol"),
    ("gpt-6.1-terra", "GPT-6.1 Terra"),
    ("gpt-6-luna", "GPT-6 Luna"),
)
EFFORT_CHOICES = (("low", "Low"), ("medium", "Medium"), ("high", "High"), ("xhigh", "Extra high"), ("max", "Maximum"))
DEFAULT_PROMPT = (
    "Review this olympiad solution as a constructive coach. Check each material inference, including "
    "the assumptions, boundary cases, and the conclusion. Accept valid alternative approaches. "
    "Explain what earns credit, identify the first important gap, and suggest a next step. "
    "Be concise and avoid giving a complete replacement proof."
)


class AdminSolutionReviewSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    version = models.UUIDField(default=uuid.uuid4, editable=False)
    key_version = models.UUIDField(default=uuid.uuid4, editable=False)
    encrypted_key = models.BinaryField(default=bytes, editable=False)
    models_enabled = models.JSONField(default=list)
    effort = models.CharField(max_length=10, choices=EFFORT_CHOICES, default="medium")
    output_limit = models.PositiveIntegerField(default=25_000)
    # Legacy setting retained for schema and rollback compatibility.
    daily_limit = models.PositiveSmallIntegerField(default=10)
    prompt = models.TextField(default=DEFAULT_PROMPT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="solutions_admin_review_singleton")]

    def __str__(self):
        return "Admin AI review settings"


class AdminSolutionReview(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Reviewing"
        COMPLETED = "completed", "Draft ready"
        FAILED = "failed", "Could not generate"
        UNKNOWN = "unknown", "Outcome unknown"

    class Notification(models.TextChoices):
        NONE = "", "Not scheduled"
        PENDING = "pending", "Email queued"
        SENDING = "sending", "Sending email"
        SENT = "sent", "Email accepted"
        FAILED = "failed", "Email not sent"
        UNKNOWN = "unknown", "Email outcome unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target = models.ForeignKey("solutions.SolutionForumTarget", on_delete=models.CASCADE, related_name="ai_reviews")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    solver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    batch_id = models.UUIDField()
    key_version = models.UUIDField()
    problem_label = models.CharField(max_length=300)
    model = models.CharField(max_length=120, choices=MODEL_CHOICES)
    effort = models.CharField(max_length=10, choices=EFFORT_CHOICES)
    output_limit = models.PositiveIntegerField()
    instructions = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    score = models.PositiveSmallIntegerField(null=True)
    feedback = models.TextField(blank=True)
    response_text = models.TextField(blank=True)
    provider_response_id = models.CharField(max_length=200, blank=True)
    error = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    published_at = models.DateTimeField(null=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    taken_down_at = models.DateTimeField(null=True)
    taken_down_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    notification = models.CharField(max_length=10, choices=Notification.choices, blank=True)
    notification_started_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="solutions_admin_ai_jobs_idx"),
            models.Index(fields=["notification", "published_at"], name="solutions_admin_ai_mail_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["target", "batch_id", "model"], name="solutions_admin_ai_batch_model"),
            models.UniqueConstraint(
                fields=["target", "problem_label"],
                condition=models.Q(published_at__isnull=False),
                name="solutions_admin_ai_one_publication",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="completed", score__isnull=False, score__gte=0, score__lte=7)
                    | (~models.Q(status="completed") & models.Q(score__isnull=True))
                ),
                name="solutions_admin_ai_score",
            ),
            models.CheckConstraint(
                condition=models.Q(published_at__isnull=True) | models.Q(status="completed"),
                name="solutions_admin_ai_publish_complete",
            ),
        ]

    @property
    def is_live(self):
        return self.status in {self.Status.QUEUED, self.Status.RUNNING}

    @property
    def publication_status(self):
        if self.published_at:
            return "Published to solver"
        if self.taken_down_at:
            return "Taken down"
        if self.status == self.Status.COMPLETED:
            return "Unpublished"
        return "—"

    @property
    def will_notify_on_publish(self):
        return self.notification in {self.Notification.NONE, self.Notification.FAILED}

    def __str__(self):
        return f"Admin AI review {self.pk}"


class SelfSolutionReviewUsage(models.Model):
    """Keep quota and request accounting when a solution or account is removed."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    review = models.OneToOneField(
        AdminSolutionReview, on_delete=models.SET_NULL, null=True, related_name="self_request",
    )
    problem_uuid = models.UUIDField()
    batch_id = models.UUIDField()
    succeeded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "batch_id"), name="solutions_self_review_user_batch")]

    def __str__(self):
        return f"Self-requested review usage {self.pk}"
