"""Community publication records remain separate from private work and the archive."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class ImmutableProofQuerySet(models.QuerySet):
    def update(self, **kwargs):
        message = "Saved proof records cannot be changed. Create a new record instead."
        raise ValidationError(message)

    def delete(self):
        message = "Saved proof records are removed only with their owning content."
        raise ValidationError(message)

    def bulk_update(self, objs, fields, batch_size=None):
        message = "Saved proof records cannot be changed. Create a new record instead."
        raise ValidationError(message)

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            message = "Saved proof records cannot be changed. Create a new record instead."
            raise ValidationError(message)
        return super().bulk_create(objs, **kwargs)


class ImmutableProofRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableProofQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding or kwargs.get("force_update"):
            message = "Saved proof records cannot be changed. Create a new record instead."
            raise ValidationError(message)
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        message = "Saved proof records are removed only with their owning content."
        raise ValidationError(message)


class CommunityProblemRevision(ImmutableProofRecord):
    problem = models.ForeignKey("CommunityProblem", on_delete=models.CASCADE, related_name="statement_revisions")
    number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    snapshot = models.JSONField(default=dict)
    content_digest = models.CharField(max_length=64)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["problem", "number"], name="pages_cpr_problem_number_unique"),
            models.CheckConstraint(condition=models.Q(number__gte=1), name="pages_cpr_number_positive"),
        ]

    def __str__(self):
        return f"Problem {self.problem_id}, revision {self.number}"


class ProblemPublication(models.Model):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private"
        UNLISTED = "unlisted", "Unlisted"
        PUBLIC = "public", "Public"

    problem = models.OneToOneField("CommunityProblem", on_delete=models.PROTECT, related_name="publication")
    statement_revision = models.ForeignKey(
        CommunityProblemRevision, null=True, blank=True, on_delete=models.PROTECT, related_name="publications",
    )
    visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.PRIVATE)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    generation = models.UUIDField(default=uuid.uuid4, editable=False)
    version = models.PositiveIntegerField(default=0)
    public_credit = models.CharField(max_length=128, blank=True)
    consented_at = models.DateTimeField(null=True, blank=True)
    is_held = models.BooleanField(default=False)
    hold_reason = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Publication for problem {self.problem_id}"

    def clean(self):
        super().clean()
        if self.statement_revision_id and self.statement_revision.problem_id != self.problem_id:
            message = "The published statement revision must belong to this problem."
            raise ValidationError({"statement_revision": message})


class CommunityAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    problem = models.ForeignKey("CommunityProblem", on_delete=models.PROTECT, related_name="private_attempts")
    statement_revision = models.ForeignKey(
        CommunityProblemRevision, on_delete=models.PROTECT, related_name="attempts",
    )
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="community_attempts")
    title = models.CharField(max_length=160, blank=True)
    body_source = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "problem", "statement_revision"], name="pages_ca_owner_problem_revision_unique",
            ),
        ]

    def __str__(self):
        return f"Private attempt {self.pk}"

    def clean(self):
        super().clean()
        if self.statement_revision_id and self.statement_revision.problem_id != self.problem_id:
            message = "The attempt statement revision must belong to this problem."
            raise ValidationError({"statement_revision": message})


class CommunitySolution(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        CHANGES_REQUESTED = "changes_requested", "Changes requested"
        DECLINED = "declined", "Declined"
        WITHDRAWN = "withdrawn", "Withdrawn"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    problem = models.ForeignKey("CommunityProblem", on_delete=models.PROTECT, related_name="community_solutions")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="community_solutions")
    current_revision = models.ForeignKey(
        "CommunitySolutionRevision", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="current_for_solutions",
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True)
    version = models.PositiveIntegerField(default=0)
    is_held = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]

    def __str__(self):
        return f"Community solution {self.pk}"

    def clean(self):
        super().clean()
        if self.current_revision_id and self.current_revision.solution_id != self.pk:
            message = "The current revision must belong to this solution."
            raise ValidationError({"current_revision": message})


class CommunitySolutionRevision(ImmutableProofRecord):
    solution = models.ForeignKey(CommunitySolution, on_delete=models.CASCADE, related_name="revisions")
    source_attempt = models.ForeignKey(
        CommunityAttempt, null=True, blank=True, on_delete=models.SET_NULL, related_name="published_revisions",
    )
    statement_revision = models.ForeignKey(
        CommunityProblemRevision, on_delete=models.PROTECT, related_name="solution_revisions",
    )
    number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    title = models.CharField(max_length=160)
    summary = models.CharField(max_length=500, blank=True)
    body_source = models.TextField()
    public_credit = models.CharField(max_length=128)
    consented_at = models.DateTimeField()
    content_digest = models.CharField(max_length=64)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["solution", "number"], name="pages_csr_solution_number_unique"),
            models.CheckConstraint(condition=models.Q(number__gte=1), name="pages_csr_number_positive"),
        ]

    def __str__(self):
        return f"Solution {self.solution_id}, revision {self.number}"

    def clean(self):
        super().clean()
        if self.statement_revision_id and self.solution_id:
            if self.statement_revision.problem_id != self.solution.problem_id:
                message = "The proof statement revision must belong to this solution's problem."
                raise ValidationError({"statement_revision": message})
        if self.source_attempt_id and self.solution_id:
            attempt = self.source_attempt
            if (
                attempt.problem_id != self.solution.problem_id
                or attempt.owner_id != self.solution.author_id
                or attempt.statement_revision_id != self.statement_revision_id
            ):
                message = "The source attempt must belong to this author, problem, and statement revision."
                raise ValidationError({"source_attempt": message})


class CommunityPrivateAsset(ImmutableProofRecord):
    attempt = models.ForeignKey(CommunityAttempt, on_delete=models.CASCADE, related_name="assets")
    name = models.CharField(max_length=200, unique=True)
    content_type = models.CharField(max_length=64)
    data = models.BinaryField()
    sha256 = models.CharField(max_length=64)

    def __str__(self):
        return f"Private asset {self.pk}"


class CommunitySolutionAsset(ImmutableProofRecord):
    revision = models.ForeignKey(CommunitySolutionRevision, on_delete=models.CASCADE, related_name="assets")
    name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=64)
    data = models.BinaryField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["revision", "name"], name="pages_csa_revision_name_unique"),
        ]

    def __str__(self):
        return f"Published asset {self.pk}"


class ModerationEvent(ImmutableProofRecord):
    problem = models.ForeignKey("CommunityProblem", on_delete=models.PROTECT, related_name="moderation_events")
    solution = models.ForeignKey(
        CommunitySolution, null=True, blank=True, on_delete=models.PROTECT, related_name="moderation_events",
    )
    statement_revision = models.ForeignKey(
        CommunityProblemRevision, null=True, blank=True, on_delete=models.PROTECT, related_name="moderation_events",
    )
    solution_revision = models.ForeignKey(
        CommunitySolutionRevision, null=True, blank=True, on_delete=models.PROTECT, related_name="moderation_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="community_moderation_events",
    )
    action = models.CharField(max_length=40)
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.action}: {self.problem_id}"

    def clean(self):
        super().clean()
        errors = {}
        if self.solution_id and self.solution.problem_id != self.problem_id:
            errors["solution"] = "The moderated solution must belong to this problem."
        if self.statement_revision_id and self.statement_revision.problem_id != self.problem_id:
            errors["statement_revision"] = "The moderated statement revision must belong to this problem."
        if self.solution_revision_id:
            revision = self.solution_revision
            if revision.solution.problem_id != self.problem_id or (
                self.solution_id and revision.solution_id != self.solution_id
            ):
                errors["solution_revision"] = "The moderated proof revision must belong to this problem and solution."
        if errors:
            raise ValidationError(errors)


class CommunityContentReport(models.Model):
    class Reason(models.TextChoices):
        GAP = "gap", "Possible proof gap"
        COPIED = "copied", "Copied content"
        ABUSE = "abuse", "Abusive content"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    problem = models.ForeignKey("CommunityProblem", on_delete=models.PROTECT, related_name="content_reports")
    solution = models.ForeignKey(
        CommunitySolution, null=True, blank=True, on_delete=models.PROTECT, related_name="content_reports",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="community_content_reports",
    )
    reason = models.CharField(max_length=16, choices=Reason.choices)
    details = models.TextField(max_length=2000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="reviewed_community_content_reports",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]

    def __str__(self):
        return f"Content report {self.pk}"

    def clean(self):
        super().clean()
        if self.solution_id and self.solution.problem_id != self.problem_id:
            message = "The reported solution must belong to this problem."
            raise ValidationError({"solution": message})
