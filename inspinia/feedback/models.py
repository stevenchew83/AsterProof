from django.conf import settings
from django.db import models


class FeedbackType(models.TextChoices):
    FEATURE = "feature", "Feature Request"
    BUG = "bug", "Bug Report"
    PROBLEM_REQUEST = "problem_request", "Problem/Contest Request"


class FeedbackStatus(models.TextChoices):
    NEW = "new", "New"
    UNDER_REVIEW = "under_review", "Under Review"
    PLANNED = "planned", "Planned"
    IMPLEMENTED = "implemented", "Implemented"
    REJECTED = "rejected", "Rejected"


class FeedbackItem(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="feedback_items")
    feedback_type = models.CharField(max_length=32, choices=FeedbackType.choices)
    title = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(max_length=32, choices=FeedbackStatus.choices, default=FeedbackStatus.NEW)
    admin_response = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class FeedbackStatusEvent(models.Model):
    feedback_item = models.ForeignKey(FeedbackItem, on_delete=models.CASCADE, related_name="status_events")
    previous_status = models.CharField(max_length=32, choices=FeedbackStatus.choices, blank=True)
    next_status = models.CharField(max_length=32, choices=FeedbackStatus.choices)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
