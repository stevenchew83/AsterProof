# ruff: noqa: DJ008, EM101, EM102, TRY003
"""Member discussion and revision-bound human decisions, separate from AI jobs."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Verdict(models.TextChoices):
    CORRECT = "correct", "Correct"
    MINOR_GAPS = "minor_gaps", "Minor gaps"
    PARTIAL = "partial", "Partially correct"
    INCORRECT = "incorrect", "Incorrect"
    UNDETERMINED = "undetermined", "Unable to determine"


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Forum history is append-only.")

    def delete(self):
        raise ValidationError("Forum history is removed only with its owning solution.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Forum history is append-only.")

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Forum history cannot be replaced.")
        return super().bulk_create(objs, **kwargs)


class ForumHistory(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding or kwargs.get("force_update"):
            raise ValidationError("Forum history is append-only.")
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Forum history is removed only with its owning solution.")


class SolutionForumTarget(ForumHistory):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    solution = models.ForeignKey("solutions.ProblemSolution", on_delete=models.CASCADE, related_name="forum_targets")
    revision = models.ForeignKey("solutions.SolutionRevision", null=True, on_delete=models.SET_NULL, related_name="+")
    solution_version = models.PositiveIntegerField(default=0)
    solution_updated_at = models.DateTimeField()
    statement_source = models.TextField(blank=True)
    statement_id_value = models.BigIntegerField(null=True)
    key = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    image_paths = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["solution", "key"], name="forum_target_solution_key")]
        ordering = ["-created_at", "-pk"]


class SolutionReviewRequest(models.Model):
    target = models.OneToOneField(SolutionForumTarget, on_delete=models.CASCADE, related_name="review_request")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(
        max_length=12, choices=[("pending", "Pending"), ("answered", "Answered")], default="pending",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status="pending") | models.Q(status="answered"), name="forum_request_state",
            ),
        ]


class SolutionHumanAssessment(ForumHistory):
    reviewer_identity = models.PositiveBigIntegerField()
    target = models.ForeignKey(SolutionForumTarget, on_delete=models.CASCADE, related_name="assessments")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    sequence = models.PositiveIntegerField(default=1)
    verdict = models.CharField(max_length=16, choices=Verdict.choices)
    feedback = models.TextField()
    gaps = models.TextField(blank=True)
    next_steps = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["target", "reviewer_identity", "sequence"], name="forum_assessment_sequence",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(verdict="correct") | models.Q(verdict="minor_gaps") | models.Q(verdict="partial")
                    | models.Q(verdict="incorrect") | models.Q(verdict="undetermined")
                ),
                name="forum_assessment_verdict",
            ),
            models.CheckConstraint(condition=models.Q(sequence__gte=1), name="forum_assessment_positive_seq"),
        ]


class SolutionVerificationDecision(ForumHistory):
    target = models.ForeignKey(SolutionForumTarget, on_delete=models.CASCADE, related_name="decisions")
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(
        max_length=12, choices=[("verify", "Verify"), ("adjudicate", "Adjudicate"), ("revoke", "Revoke")],
    )
    verdict = models.CharField(max_length=16, choices=Verdict.choices, blank=True)
    reason = models.TextField()
    assessment_basis = models.JSONField(default=list)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(action="verify") | models.Q(action="adjudicate") | models.Q(action="revoke"),
                name="forum_decision_action",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(verdict="") | models.Q(verdict="correct") | models.Q(verdict="minor_gaps")
                    | models.Q(verdict="partial") | models.Q(verdict="incorrect") | models.Q(verdict="undetermined")
                ),
                name="forum_decision_verdict",
            ),
            models.CheckConstraint(
                condition=~models.Q(action="verify") | models.Q(verdict="correct"), name="forum_verified_correct_only",
            ),
        ]


class SolutionComment(models.Model):
    solution = models.ForeignKey("solutions.ProblemSolution", on_delete=models.CASCADE, related_name="forum_comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    created_revision = models.ForeignKey(
        "solutions.SolutionRevision", null=True, on_delete=models.SET_NULL, related_name="+",
    )
    body = models.TextField()
    state = models.CharField(
        max_length=12,
        choices=[("visible", "Visible"), ("removed", "Removed"), ("hidden", "Hidden")],
        default="visible",
    )
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["solution", "parent", "created_at"], name="forum_comment_thread")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state="visible") | models.Q(state="removed") | models.Q(state="hidden"),
                name="forum_comment_state",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="forum_comment_positive_ver"),
        ]

    def clean(self):
        super().clean()
        if self.parent_id and (self.parent.solution_id != self.solution_id or self.parent.parent_id):
            raise ValidationError("Replies must belong to a top-level comment on the same solution.")
        if self.created_revision_id and self.created_revision.solution_id != self.solution_id:
            raise ValidationError("The revision must belong to this solution.")


class SolutionCommentEvent(ForumHistory):
    comment = models.ForeignKey(SolutionComment, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=24)
    body = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    version = models.PositiveIntegerField()

    class Meta:
        ordering = ["created_at", "pk"]


class SolutionUpvote(models.Model):
    solution = models.ForeignKey("solutions.ProblemSolution", on_delete=models.CASCADE, related_name="upvotes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="solution_upvotes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["solution", "user"], name="forum_one_upvote_per_member")]


class SolutionForumReport(models.Model):
    comment = models.ForeignKey(SolutionComment, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    reason = models.TextField()
    status = models.CharField(max_length=12, choices=[("open", "Open"), ("resolved", "Resolved")], default="open")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    resolution = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status="open") | models.Q(status="resolved"), name="forum_report_state",
            ),
            models.UniqueConstraint(
                fields=["comment", "reporter"], condition=models.Q(status="open"), name="forum_one_open_report",
            ),
        ]
