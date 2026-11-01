"""Private append-only synthetic reports and attributed progressive hint reveals."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from inspinia.solutions.assessment_contracts import MODES
from inspinia.solutions.evaluation_contracts import EvaluationDataError
from inspinia.solutions.problem_evaluation_models import AppendOnlyRecord


class SyntheticReview(AppendOnlyRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="synthetic_reviews",
    )
    idempotency_key = models.UUIDField()
    case_id = models.CharField(max_length=120)
    mode = models.CharField(max_length=16, choices=list(MODES.items()))
    packet = models.JSONField()
    assessment = models.JSONField()
    mode_feedback = models.JSONField()
    report = models.JSONField()
    private_hints = models.JSONField(default=dict, blank=True)
    prompt_manifest = models.JSONField()
    content_digest = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(AppendOnlyRecord.Meta):
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["requested_by", "idempotency_key"], name="synthetic_review_idempotency"),
            models.CheckConstraint(condition=models.Q(mode__in=list(MODES)), name="synthetic_review_valid_mode"),
        ]

    def clean(self):
        from inspinia.solutions.synthetic_reviews import require_prototype
        from inspinia.solutions.synthetic_reviews import stored_review_digest
        from inspinia.solutions.synthetic_reviews import synthetic_bundle

        super().clean()
        require_prototype(self.requested_by, "add_syntheticreview")
        require_prototype(self.requested_by)
        try:
            expected = synthetic_bundle(self.case_id, self.mode)
        except EvaluationDataError as error:
            raise ValidationError(str(error)) from error
        if any(getattr(self, key) != value for key, value in expected.items()):
            message = "This prototype stores only validated bundled synthetic assessments."
            raise ValidationError(message)
        self.content_digest = stored_review_digest(self)

    def check_integrity(self):
        from inspinia.solutions.synthetic_reviews import stored_review_digest

        if self.content_digest != stored_review_digest(self):
            message = "The private report no longer matches its frozen digest."
            raise ValidationError(message)

    def __str__(self):
        return f"Synthetic {self.mode} report: {self.case_id}"


class SyntheticHintReveal(AppendOnlyRecord):
    review = models.ForeignKey(SyntheticReview, on_delete=models.PROTECT, related_name="hint_reveals")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="synthetic_hint_reveals",
    )
    finding_id = models.CharField(max_length=120)
    level = models.PositiveSmallIntegerField(choices=[(1, "First hint"), (2, "Second hint")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(AppendOnlyRecord.Meta):
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["review", "reviewer", "finding_id", "level"],
                name="synthetic_hint_reveal_once",
            ),
            models.CheckConstraint(condition=models.Q(level__in=[1, 2]), name="synthetic_hint_valid_level"),
        ]

    def clean(self):
        from inspinia.solutions.synthetic_reviews import require_prototype

        super().clean()
        require_prototype(self.reviewer)
        require_prototype(self.reviewer, "add_synthetichintreveal")
        if not self.review_id:
            return
        review = SyntheticReview.objects.get(pk=self.review_id)
        review.check_integrity()
        hints = review.private_hints.get(self.finding_id, [])
        if type(self.level) is not int or not 1 <= self.level <= len(hints):
            message = "Choose an available hint for this report."
            raise ValidationError(message)
        if (
            self.level > 1
            and not SyntheticHintReveal.objects.filter(
                review=review,
                reviewer=self.reviewer,
                finding_id=self.finding_id,
                level=self.level - 1,
            ).exists()
        ):
            message = "Reveal hints in order."
            raise ValidationError(message)
