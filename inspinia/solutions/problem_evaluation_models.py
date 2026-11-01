"""Append-only reference packages and separately attributed human decisions."""

import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import models

from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.evaluation_contracts import EvaluationDataError
from inspinia.solutions.evaluation_contracts import package_digest
from inspinia.solutions.evaluation_contracts import text
from inspinia.users.roles import user_has_admin_role


def require_curator(user_id, permission):
    # Reload authority rather than trusting caller-supplied role flags or cached permissions.
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if not user_has_admin_role(user) or not user.has_perm(f"solutions.{permission}"):
        raise PermissionDenied


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        message = "Evaluation history is append-only. Create a new version or decision."
        raise ValidationError(message)

    def delete(self):
        message = "Evaluation history cannot be deleted through the application."
        raise ValidationError(message)

    def bulk_update(self, objs, fields, batch_size=None):
        return self.update()

    def bulk_create(self, objs, **kwargs):
        message = "Create evaluation records individually so validation and attribution cannot be skipped."
        raise ValidationError(message)


class AppendOnlyRecord(models.Model):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True
        base_manager_name = "objects"

    def save(self, *args, **kwargs):
        if not self._state.adding or kwargs.get("force_update"):
            message = "Evaluation history is append-only. Create a new version or decision."
            raise ValidationError(message)
        # Derive internal digest fields before Django validates required fields.
        self.clean()
        self.full_clean()
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return self.__class__.objects.none().delete()


class ProblemEvaluationPackage(AppendOnlyRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    problem = models.ForeignKey(
        "pages.ProblemSolveRecord",
        on_delete=models.PROTECT,
        related_name="evaluation_packages",
    )
    version = models.PositiveIntegerField()
    content = models.JSONField(help_text="Frozen statement, references, image hashes, and optional marking rubric.")
    content_digest = models.CharField(max_length=64, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="evaluation_packages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(AppendOnlyRecord.Meta):
        ordering = ["problem_id", "version"]
        constraints = [
            models.UniqueConstraint(fields=["problem", "version"], name="evaluation_package_problem_version"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="evaluation_package_positive_version"),
        ]

    def clean(self):
        super().clean()
        require_curator(self.created_by_id, "add_problemevaluationpackage")
        if self.problem_id:
            try:
                self.content_digest = self.expected_digest()
            except EvaluationDataError as error:
                raise ValidationError({"content": str(error)}) from error

    def expected_digest(self):
        # Do not bind history to an unsaved change on a caller's related object.
        try:
            problem_uuid = ProblemSolveRecord.objects.values_list("problem_uuid", flat=True).get(pk=self.problem_id)
        except ProblemSolveRecord.DoesNotExist as error:
            message = "Choose an existing problem for the evaluation package."
            raise ValidationError({"problem": message}) from error
        return package_digest(str(problem_uuid), self.version, self.content)

    def check_integrity(self):
        expected = self.expected_digest()
        if self.content_digest != expected:
            message = "The stored evaluation package no longer matches its frozen digest."
            raise ValidationError(message)

    @property
    def approval_status(self):
        if self._state.adding:
            return "pending"
        self.check_integrity()
        decision = self.approvals.order_by("-pk").first()
        if decision is None:
            return "pending"
        if decision.package_digest != self.content_digest:
            message = "The human decision does not match this package."
            raise ValidationError(message)
        return decision.decision

    def __str__(self):
        return f"Problem {self.problem_id}, evaluation package v{self.version}"


class EvaluationPackageApproval(AppendOnlyRecord):
    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        REVOKED = "revoked", "Revoked"

    package = models.ForeignKey(ProblemEvaluationPackage, on_delete=models.PROTECT, related_name="approvals")
    package_digest = models.CharField(max_length=64, editable=False)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="package_approvals")
    decision = models.CharField(max_length=16, choices=Decision.choices)
    notes = models.TextField(help_text="Human mathematical review and reasons for this decision.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(AppendOnlyRecord.Meta):
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(decision__in=["approved", "rejected", "revoked"]),
                name="evaluation_package_valid_decision",
            ),
        ]

    def clean(self):
        super().clean()
        require_curator(self.reviewer_id, "add_evaluationpackageapproval")
        if not text(self.notes):
            message = "Record the human review and reasons for the decision."
            raise ValidationError({"notes": message})
        if self.package_id:
            # Fetch persisted content, not a potentially modified related object.
            try:
                package = ProblemEvaluationPackage.objects.get(pk=self.package_id)
            except ProblemEvaluationPackage.DoesNotExist as error:
                message = "Choose an existing evaluation package."
                raise ValidationError({"package": message}) from error
            package.check_integrity()
            if self.decision == self.Decision.APPROVED and not package.content["references"]:
                message = "Approval requires at least one reviewed reference solution."
                raise ValidationError({"package": message})
            self.package_digest = package.content_digest

    def __str__(self):
        return f"Package {self.package_id}: {self.decision}"
