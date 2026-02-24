from django.conf import settings
from django.db import models


class SolutionType(models.TextChoices):
    SKETCH = "sketch", "Sketch"
    FULL = "full", "Full solution"
    HINTS = "hints", "Hints"
    ALTERNATIVE = "alternative", "Alternative"


class PublicSolution(models.Model):
    problem = models.ForeignKey(
        "catalog.Problem",
        on_delete=models.CASCADE,
        related_name="publicsolution",
    )
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    solution_type = models.CharField(max_length=16, choices=SolutionType.choices, default=SolutionType.SKETCH)
    title = models.CharField(max_length=255)
    content = models.TextField()
    is_unlisted = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)
    is_moderator_edited = models.BooleanField(default=False)
    helpful_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class SolutionVote(models.Model):
    solution = models.ForeignKey(PublicSolution, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    is_helpful = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("solution", "user")


class Comment(models.Model):
    problem = models.ForeignKey("catalog.Problem", on_delete=models.CASCADE, null=True, blank=True)
    solution = models.ForeignKey(PublicSolution, on_delete=models.CASCADE, null=True, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    content = models.TextField()
    is_hidden = models.BooleanField(default=False)
    is_moderator_edited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class CommentReaction(models.Model):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    emoji = models.CharField(max_length=16, default="thanks")

    class Meta:
        unique_together = ("comment", "user", "emoji")


class ContentReport(models.Model):
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    solution = models.ForeignKey(PublicSolution, on_delete=models.CASCADE, null=True, blank=True)
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, null=True, blank=True)
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)


class TrustedSuggestionType(models.TextChoices):
    TAG = "tag", "Tag Improvement"
    DUPLICATE = "duplicate", "Duplicate Link"
    DIFFICULTY = "difficulty", "Difficulty Suggestion"
    QUALITY = "quality", "Quality Suggestion"


class TrustedSuggestion(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    problem = models.ForeignKey("catalog.Problem", on_delete=models.CASCADE)
    suggestion_type = models.CharField(max_length=32, choices=TrustedSuggestionType.choices)
    payload = models.TextField(blank=True)
    approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
