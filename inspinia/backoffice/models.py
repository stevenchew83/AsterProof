from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class SingletonModel(models.Model):
    class Meta:
        abstract = True

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.pk = 1
        return super().save(*args, **kwargs)


class ReportReason(models.TextChoices):
    SPAM = "spam", "Spam"
    HARASSMENT = "harassment", "Harassment"
    PLAGIARISM = "plagiarism", "Plagiarism"
    HATE = "hate", "Hate Speech"
    ABUSE = "abuse", "Abusive Conduct"
    OTHER = "other", "Other"


class ReportStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_REVIEW = "in_review", "In Review"
    RESOLVED = "resolved", "Resolved"
    DISMISSED = "dismissed", "Dismissed"
    ESCALATED = "escalated", "Escalated"


class Report(models.Model):
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_submitted")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    reason_code = models.CharField(max_length=32, choices=ReportReason.choices)
    details = models.TextField(blank=True)
    severity = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=16, choices=ReportStatus.choices, default=ReportStatus.OPEN)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports_assigned",
    )
    resolution_note = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "severity", "created_at"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return f"Report #{self.pk} ({self.status})"


class ModerationAction(models.TextChoices):
    HIDE = "hide", "Hide"
    UNHIDE = "unhide", "Unhide"
    REDACT = "redact", "Redact"
    WARN = "warn", "Warn"
    MUTE = "mute", "Mute"
    BAN = "ban", "Ban"
    SHADOW_BAN = "shadow_ban", "Shadow Ban"
    DISMISS = "dismiss", "Dismiss"
    RESOLVE = "resolve", "Resolve"
    ESCALATE = "escalate", "Escalate"


class ModerationLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    report = models.ForeignKey(Report, on_delete=models.SET_NULL, null=True, blank=True, related_name="logs")
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderation_logs",
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")
    action = models.CharField(max_length=32, choices=ModerationAction.choices)
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_user", "created_at"]),
            models.Index(fields=["action", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.actor_id}"


class ContentRevision(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    previous_text = models.TextField()
    new_text = models.TextField()
    edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    moderation_log = models.ForeignKey(
        ModerationLog,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["content_type", "object_id", "created_at"])]


class AbusePolicy(SingletonModel):
    comment_limit_per_minute = models.PositiveIntegerField(default=10)
    comment_limit_per_hour = models.PositiveIntegerField(default=120)
    max_external_links_per_post = models.PositiveIntegerField(default=3)
    bad_word_list = models.TextField(blank=True)
    captcha_on_anonymous_suggestions = models.BooleanField(default=True)
    captcha_new_account_threshold = models.PositiveIntegerField(default=5)
    updated_at = models.DateTimeField(auto_now=True)


class ProblemIngestionStatus(models.TextChoices):
    NEW = "new", "New"
    IN_REVIEW = "in_review", "In Review"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    DUPLICATE = "duplicate", "Duplicate"


class ProblemRequest(models.Model):
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    requested_contest = models.CharField(max_length=255, blank=True)
    requested_year = models.PositiveIntegerField(null=True, blank=True)
    source_url = models.URLField(blank=True)
    attachment = models.FileField(upload_to="problem_requests/", null=True, blank=True)
    suggested_tags = models.CharField(max_length=255, blank=True)
    suggested_difficulty = models.PositiveSmallIntegerField(default=3)
    details = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=ProblemIngestionStatus.choices, default=ProblemIngestionStatus.NEW)
    duplicate_problem = models.ForeignKey(
        "catalog.Problem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="duplicate_requests",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_problem_requests",
    )
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class ProblemSubmission(models.Model):
    submitter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=255)
    statement = models.TextField()
    source_reference = models.URLField(blank=True)
    attachment = models.FileField(upload_to="problem_submissions/", null=True, blank=True)
    proposed_tags = models.CharField(max_length=255, blank=True)
    proposed_difficulty = models.PositiveSmallIntegerField(default=3)
    contest = models.ForeignKey("catalog.Contest", on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=16, choices=ProblemIngestionStatus.choices, default=ProblemIngestionStatus.NEW)
    linked_problem = models.ForeignKey(
        "catalog.Problem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ingested_submissions",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_problem_submissions",
    )
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class FeatureFlagConfig(SingletonModel):
    contests = models.BooleanField(default=True)
    ratings = models.BooleanField(default=True)
    public_dashboards = models.BooleanField(default=True)
    problem_submissions = models.BooleanField(default=True)
    advanced_analytics = models.BooleanField(default=False)


class PrivacyDefaultsConfig(SingletonModel):
    PROFILE_VISIBILITY_CHOICES = (
        ("public", "Public"),
        ("semi_private", "Semi-private"),
        ("private", "Private"),
    )
    default_profile_visibility = models.CharField(max_length=16, choices=PROFILE_VISIBILITY_CHOICES, default="public")
    default_solution_unlisted = models.BooleanField(default=False)


class BrandingConfig(SingletonModel):
    SKIN_CHOICES = (
        ("classic", "Classic"),
        ("saas", "SaaS"),
        ("modern", "Modern"),
        ("material", "Material"),
        ("minimal", "Minimal"),
        ("flat", "Flat"),
        ("galaxy", "Galaxy"),
    )
    default_skin = models.CharField(max_length=16, choices=SKIN_CHOICES, default="classic")
    logo_text = models.CharField(max_length=255, blank=True)
    logo_image = models.ImageField(upload_to="branding/", null=True, blank=True)


class RatingConfig(SingletonModel):
    base_rating = models.FloatField(default=1200)
    k_factor = models.PositiveIntegerField(default=24)
    small_contest_threshold = models.PositiveIntegerField(default=5)
    small_contest_k_multiplier = models.FloatField(default=0.75)
    rating_floor = models.FloatField(null=True, blank=True)
    rating_cap = models.FloatField(null=True, blank=True)


class RatingRunStatus(models.TextChoices):
    APPLIED = "applied", "Applied"
    ROLLED_BACK = "rolled_back", "Rolled Back"
    FAILED = "failed", "Failed"


class RatingRun(models.Model):
    contest = models.ForeignKey("contests.ContestEvent", on_delete=models.CASCADE, related_name="rating_runs")
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=16, choices=RatingRunStatus.choices, default=RatingRunStatus.APPLIED)
    is_rollback = models.BooleanField(default=False)
    parent_run = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="rollback_runs")
    notes = models.TextField(blank=True)
    config_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class RatingRunEntry(models.Model):
    run = models.ForeignKey(RatingRun, on_delete=models.CASCADE, related_name="entries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    previous_rating = models.FloatField()
    new_rating = models.FloatField()
    delta = models.FloatField()

    class Meta:
        unique_together = ("run", "user")
