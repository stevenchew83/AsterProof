"""Erase private execution copies when their learner-facing review is deleted."""

from django.db import transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .evaluation import audit
from .evaluation import decision_lock
from .evaluation import digest
from .evaluation_execution import spend
from .evaluation_models import EvaluationAuditEvent
from .evaluation_models import EvaluationCase
from .evaluation_models import ReviewBundleAsset
from .evaluation_models import ReviewConsent
from .evaluation_models import ReviewerProfile
from .evaluation_models import ReviewExecutionAttempt
from .evaluation_models import ReviewInputBundle
from .review_models import SolutionReview
from .review_models import SolutionReviewPolicy


@receiver(pre_delete, sender=SolutionReview)
def purge_review_copy(sender, instance, **kwargs):
    with transaction.atomic():
        decision_lock()
        SolutionReviewPolicy.objects.select_for_update().filter(singleton_key=1).first()
        attempt = ReviewExecutionAttempt.objects.select_for_update().filter(review=instance).first()
        for event in EvaluationAuditEvent.objects.filter(target_id=instance.pk, kind="repair_assessed"):
            minimal = {key: event.metadata.get(key) for key in ("finding_id", "revision_id", "state")}
            minimal["content_deleted"] = True
            EvaluationAuditEvent._base_manager.filter(pk=event.pk).update(metadata=minimal)  # noqa: SLF001
        if attempt is None:
            if instance.accounted_micros and instance.status not in {"queued", "expired"}:
                # Preserve old recorded exposure without inventing a complete profile or verified charge.
                payload = {
                    "legacy_incomplete": True,
                    "model": instance.model,
                    "pricing_digest": digest(instance.pricing_snapshot),
                }
                profile, _ = ReviewerProfile.objects.get_or_create(
                    digest=digest(payload),
                    defaults={"payload": payload},
                )
                attempt = ReviewExecutionAttempt.objects.create(
                    profile=profile,
                    subject_id=instance.revision_id,
                    origin="unverified_external",
                    status="legacy_unreconciled",
                    receipt={
                        "legacy_incomplete": True,
                        "provider_execution_verified": False,
                        "request_id": instance.provider_request_id,
                        "response_id": instance.provider_response_id,
                    },
                )
                spend(
                    attempt,
                    "reservation",
                    instance.accounted_micros,
                    "legacy_recorded_exposure",
                    {"classification": "unverified_legacy_accounting_requires_reconciliation"},
                )
                audit(None, attempt, "legacy_accounting_preserved")
            return
        if attempt.status == "queued":
            reservation = attempt.spend_events.filter(kind="reservation").first()
            if reservation:
                spend(attempt, "release", reservation.amount_micros, "cancel_undispatched")
            attempt.status = "cancelled"
        if attempt.bundle_id:
            key = attempt.bundle_id
            ReviewBundleAsset._base_manager.filter(bundle_id=key).delete()  # noqa: SLF001
            ReviewInputBundle._base_manager.filter(pk=key).update(payload={}, owner=None)  # noqa: SLF001
            attempt.bundle = None
        attempt.save(update_fields=["bundle", "status"])
        audit(None, attempt, "review_content_deleted", {"review_digest": digest(str(instance.pk))})


@receiver(pre_delete, sender=ReviewConsent)
def purge_reuse_copy(sender, instance, **kwargs):
    if instance.purpose != "benchmark_reuse":
        return
    from .evaluation import _invalidate
    from .evaluation import decision_lock

    with transaction.atomic():
        decision_lock()
        for case in EvaluationCase.objects.filter(provenance__consent_reference=str(instance.pk)):
            _invalidate(None, case, "withdrawal", purge=True)
