from django.conf import settings
from django.db import models


class ContestKind(models.TextChoices):
    OFFICIAL = "official", "Official"
    PRACTICE = "practice", "Practice"
    VIRTUAL = "virtual", "Virtual"


class ContestVisibility(models.TextChoices):
    DRAFT = "draft", "Draft"
    INTERNAL = "internal", "Internal"
    PUBLIC = "public", "Public"


class ContestEvent(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    contest_kind = models.CharField(max_length=16, choices=ContestKind.choices, default=ContestKind.OFFICIAL)
    visibility_state = models.CharField(max_length=16, choices=ContestVisibility.choices, default=ContestVisibility.DRAFT)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_rated = models.BooleanField(default=False)
    rules = models.TextField(blank=True)


class ContestRegistration(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contest_registrations")
    contest = models.ForeignKey(ContestEvent, on_delete=models.CASCADE, related_name="registrations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "contest")


class ContestProblem(models.Model):
    contest = models.ForeignKey(ContestEvent, on_delete=models.CASCADE, related_name="contest_problems")
    problem = models.ForeignKey("catalog.Problem", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=1)
    max_score = models.PositiveIntegerField(default=7)

    class Meta:
        unique_together = ("contest", "problem")
        ordering = ["position"]


class Submission(models.Model):
    class MarkingStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        PARTIAL = "partial", "Partial"
        REJECTED = "rejected", "Rejected"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions")
    contest = models.ForeignKey(ContestEvent, on_delete=models.CASCADE, related_name="submissions")
    problem = models.ForeignKey("catalog.Problem", on_delete=models.CASCADE)
    content = models.TextField(blank=True)
    pdf = models.FileField(upload_to="submissions/", null=True, blank=True)
    score = models.FloatField(default=0)
    marking_status = models.CharField(max_length=16, choices=MarkingStatus.choices, default=MarkingStatus.PENDING)
    grader_note = models.TextField(blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="graded_submissions",
    )
    graded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ScoreEntry(models.Model):
    contest = models.ForeignKey(ContestEvent, on_delete=models.CASCADE, related_name="score_entries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contest_scores")
    score = models.FloatField(default=0)
    rank = models.PositiveIntegerField(default=0)
    rating_delta = models.FloatField(default=0)

    class Meta:
        unique_together = ("contest", "user")


class RatingSnapshot(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rating_snapshots")
    value = models.FloatField(default=1200)
    created_at = models.DateTimeField(auto_now_add=True)


class RatingDelta(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rating_deltas")
    contest = models.ForeignKey(ContestEvent, on_delete=models.CASCADE, related_name="rating_deltas")
    previous_rating = models.FloatField()
    new_rating = models.FloatField()
    delta = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
