from django.conf import settings
from django.db import models
from django.utils import timezone


class ProblemStatus(models.TextChoices):
    UNATTEMPTED = "unattempted", "Unattempted"
    ATTEMPTED = "attempted", "Attempted"
    SOLVED = "solved", "Solved"
    REVISITING = "revisiting", "Revisiting"


class ProblemProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="problem_progress",
    )
    problem = models.ForeignKey(
        "catalog.Problem",
        on_delete=models.CASCADE,
        related_name="progress_records",
    )
    status = models.CharField(
        max_length=16,
        choices=ProblemStatus.choices,
        default=ProblemStatus.UNATTEMPTED,
    )
    confidence = models.PositiveSmallIntegerField(default=0)
    first_solved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "problem")

    def save(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if self.status == ProblemStatus.SOLVED and self.first_solved_at is None:
            self.first_solved_at = timezone.now()
        super().save(*args, **kwargs)


class ProblemFavourite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favourites")
    problem = models.ForeignKey("catalog.Problem", on_delete=models.CASCADE, related_name="favourites")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "problem")


class ProblemDifficultyVote(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    problem = models.ForeignKey("catalog.Problem", on_delete=models.CASCADE, related_name="difficulty_votes")
    value = models.PositiveSmallIntegerField(default=3)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "problem")


class ProblemQualityVote(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    problem = models.ForeignKey("catalog.Problem", on_delete=models.CASCADE, related_name="quality_votes")
    value = models.PositiveSmallIntegerField(default=3)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "problem")
