import uuid

from django.conf import settings
from django.db import models


class ListVisibility(models.TextChoices):
    PRIVATE = "private", "Private"
    UNLISTED = "unlisted", "Unlisted"
    PUBLIC = "public", "Public"


class ProblemList(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="problem_lists")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    visibility = models.CharField(max_length=16, choices=ListVisibility.choices, default=ListVisibility.PRIVATE)
    share_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ProblemListItem(models.Model):
    problem_list = models.ForeignKey(ProblemList, on_delete=models.CASCADE, related_name="items")
    problem = models.ForeignKey("catalog.Problem", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("problem_list", "problem")
        ordering = ["position", "id"]


class ActivityType(models.TextChoices):
    VIEWED = "viewed", "Problem Viewed"
    SOLVED = "solved", "Problem Solved"
    NOTE_EDITED = "note_edited", "Note Edited"
    SOLUTION_POSTED = "solution_posted", "Solution Posted"


class ActivityEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="activity_events")
    problem = models.ForeignKey("catalog.Problem", on_delete=models.CASCADE, null=True, blank=True)
    event_type = models.CharField(max_length=32, choices=ActivityType.choices)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
