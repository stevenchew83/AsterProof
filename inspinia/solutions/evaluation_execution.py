"""Shared offline execution, deletion-safe accounting and assistance policy."""

# ruff: noqa: EM101, EM102, TRY003, PLR0913, PLR2004
import hashlib
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from inspinia.pages.study_help_access import assistance_restricted
from inspinia.pages.study_help_access import bind_statement_restrictions
from inspinia.pages.study_help_access import lock_study_help

from .evaluation import EvaluationError
from .evaluation import audit
from .evaluation import create_bundle
from .evaluation import digest
from .evaluation import verify_bundle
from .evaluation_models import AssistancePolicy
from .evaluation_models import EvaluationLifecycle
from .evaluation_models import HintRevealEvent
from .evaluation_models import ReviewerProfile
from .evaluation_models import ReviewExecutionAttempt
from .evaluation_models import ReviewSpendEvent
from .review_models import SolutionReviewPolicy


def software_digest():
    package = Path(__file__).resolve().parent
    names = ("evaluation.py", "evaluation_execution.py", "evaluation_scoring.py", "review_provider.py", "reviews.py")
    return digest({name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in names})


def require_offline_provider():
    """No real-provider authority is issued by the offline architecture release."""
    raise EvaluationError(
        "Provider execution is disabled in the offline workspace.",
        code="offline_execution",
        status=503,
    )


def assert_assistance(user, problem_uuid, *, delivery=False, review=None):
    if assistance_restricted(user, (problem_uuid,)):
        raise EvaluationError(
            "AI assistance is restricted for this problem.",
            code="assistance_restricted",
            status=403,
        )
    if review is not None and EvaluationLifecycle.objects.filter(target_id=review.pk, eligible=False).exists():
        raise EvaluationError("This feedback is withheld.", code="feedback_withheld", status=403)
    if not delivery and not getattr(settings, "SOLUTION_AI_REVIEW_ENABLED", False):
        raise EvaluationError("AI review is disabled.", code="review_disabled", status=503)


@transaction.atomic
def set_assistance_policy(actor, problem_uuid, mode, starts_at, ends_at, reason, *, user=None):
    from inspinia.pages.models import ContestProblemStatement

    from .evaluation import WORKSPACE
    from .evaluation import require

    lock_study_help()
    require(actor, "activation", WORKSPACE)
    if mode not in {"independent_practice", "guided_training", "restricted_assessment", "quarantine", "withdrawal"}:
        raise EvaluationError("Unknown assistance mode.", status=422)
    if timezone.is_naive(starts_at) or timezone.is_naive(ends_at) or ends_at <= starts_at or not reason.strip():
        raise EvaluationError("Provide a bounded aware policy window and reason.", status=422)
    # Serialize policy changes with enqueue/dispatch decisions.
    SolutionReviewPolicy.objects.select_for_update().filter(singleton_key=1).first()
    item = AssistancePolicy.objects.create(
        problem_uuid=problem_uuid,
        actor_id_scope=getattr(user, "pk", None),
        mode=mode,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=reason[:200],
        appointed_by=actor,
    )
    if problem_uuid is not None:
        statement_uuid = (
            ContestProblemStatement.objects.filter(problem_uuid=problem_uuid).values_list("statement_uuid", flat=True)
            .first()
        )
        if statement_uuid is not None:
            bind_statement_restrictions(statement_uuid, (problem_uuid,))
    audit(actor, item, "assistance_policy_set", {"mode": mode})
    return item


@transaction.atomic
def bind_review(review):
    from .review_provider import FEEDBACK_SCHEMA
    from .review_provider import SYSTEM_PROMPT
    from .reviews import SolutionBodyImage
    from .reviews import _read_image

    snapshot = review.input_snapshot
    assets = []
    for manifest in snapshot["images"]:
        image = SolutionBodyImage.objects.get(solution_id=review.revision.solution_id, file=manifest["path"])
        raw, current = _read_image(image)
        if current != manifest:
            raise EvaluationError("Managed image changed before freezing.", status=409)
        assets.append({"data": raw, "role": "supporting_image"})
    missing = snapshot.get("diagram_source_only") or "\\includegraphics" in snapshot["statement"]
    bundle = create_bundle(
        review.author,
        {
            "statement": snapshot["statement"],
            "source": snapshot["body_source"],
            "language": "unspecified",
            "problem_uuid": str(review.revision.solution.problem.problem_uuid),
            "revision_id": str(review.revision_id),
            "statement_version": snapshot["statement_id"],
            "completeness": "missing_essential_context" if missing else "present",
            "problem_integrity": "unresolved",
            "limitations": ["Official diagram completeness has not been coach confirmed."],
        },
        assets,
    )
    payload = {
        "model": review.model,
        "prompt": SYSTEM_PROMPT,
        "rubric": review.rubric_version,
        "output_schema": FEEDBACK_SCHEMA,
        "preprocessing": "rgb-png-2048-v1",
        "reasoning": {"effort": "medium"},
        "output_limit": 16000,
        "timeout": 300,
        "retry_policy": "none",
        "pricing": review.pricing_snapshot,
    }
    profile, _ = ReviewerProfile.objects.get_or_create(digest=digest(payload), defaults={"payload": payload})
    attempt = ReviewExecutionAttempt.objects.create(
        review=review,
        bundle=bundle,
        profile=profile,
        subject_id=review.revision_id,
        origin="deterministic_fixture",
    )
    spend(attempt, "reservation", review.reserved_micros, "reserve", {"budget_subject": review.author_id})
    audit(
        review.author,
        attempt,
        "execution_queued",
        {"bundle_digest": bundle.digest, "profile_digest": profile.digest},
    )
    return attempt


@transaction.atomic
def spend(attempt, kind, amount, key, metadata=None):
    SolutionReviewPolicy.objects.select_for_update().filter(singleton_key=1).first()
    ReviewExecutionAttempt.objects.select_for_update().get(pk=attempt.pk)
    if (
        kind not in {"reservation", "settlement", "release", "adjustment", "credit"}
        or type(amount) is not int
        or amount < 0
    ):
        raise EvaluationError("Invalid financial event.", status=422)
    existing = ReviewSpendEvent.objects.filter(attempt=attempt, idempotency_key=key).first()
    if existing:
        if existing.kind != kind or existing.amount_micros != amount:
            raise EvaluationError("Financial idempotency conflict.", status=409)
        return existing
    event = ReviewSpendEvent.objects.create(
        attempt=attempt,
        kind=kind,
        amount_micros=amount,
        idempotency_key=key,
        metadata=metadata or {},
    )
    audit(None, attempt, "spend_recorded", {"event_id": str(event.pk), "kind": kind, "amount_micros": amount})
    return event


def ledger_totals(since):
    """All outstanding holds plus settled expenditure in the requested UTC period."""
    totals = {}
    for event in ReviewSpendEvent.objects.order_by("created_at", "id"):
        row = totals.setdefault(event.attempt_id, {"hold": 0, "settled": 0})
        if event.kind == "reservation":
            row["hold"] += event.amount_micros
        elif event.kind == "release":
            row["hold"] = max(0, row["hold"] - event.amount_micros)
        elif event.kind == "settlement":
            row["hold"] = 0
            if event.created_at >= since:
                row["settled"] += event.amount_micros
        elif event.kind == "adjustment" and event.created_at >= since:
            row["settled"] += event.amount_micros
        elif event.kind == "credit" and event.created_at >= since:
            row["settled"] -= event.amount_micros
    return sum(r["hold"] + max(0, r["settled"]) for r in totals.values())


def accepted_request_counts(user, since):
    events = ReviewSpendEvent.objects.filter(
        kind="reservation", attempt__run__isnull=True, attempt__created_at__gte=since,
    )
    seen, owned = set(), set()
    for event in events:
        seen.add(event.attempt_id)
        if event.metadata.get("budget_subject") == user.pk:
            owned.add(event.attempt_id)
    return len(owned), len(seen)


@transaction.atomic
def cancel_undispatched(review, reason):
    SolutionReviewPolicy.objects.select_for_update().filter(singleton_key=1).first()
    attempt = ReviewExecutionAttempt.objects.select_for_update().filter(review=review).first()
    if attempt is None or attempt.status != "queued":
        return
    reservation = attempt.spend_events.filter(kind="reservation").first()
    if reservation:
        spend(attempt, "release", reservation.amount_micros, "cancel_undispatched")
    attempt.status = "expired"
    attempt.save(update_fields=["status"])
    audit(None, attempt, "execution_cancelled", {"reason": reason})


@transaction.atomic
def start_attempt(review):
    from .reviews import _configured

    policy = SolutionReviewPolicy.objects.select_for_update().get(singleton_key=1)
    if not _configured(policy):
        raise EvaluationError("AI review is disabled.", code="review_disabled", status=503)
    assert_assistance(review.author, review.revision.solution.problem.problem_uuid, review=review)
    attempt = ReviewExecutionAttempt.objects.select_for_update().get(review=review)
    if attempt.status != "queued":
        raise EvaluationError("This execution attempt cannot be dispatched again.", status=409)
    verify_bundle(attempt.bundle)
    from .evaluation import lifecycle

    lifecycle(attempt.profile)
    if digest(attempt.profile.payload) != attempt.profile.digest:
        raise EvaluationError("Reviewer profile changed.", status=409)
    attempt.status = "running"
    attempt.save(update_fields=["status"])
    audit(review.author, attempt, "dispatch_started", {"origin": "deterministic_fixture"})
    return attempt


@transaction.atomic
def finish_attempt(review):
    SolutionReviewPolicy.objects.select_for_update().filter(singleton_key=1).first()
    attempt = ReviewExecutionAttempt.objects.select_for_update().filter(review_id=review.pk).first()
    if attempt is None:
        # SET_NULL removes the review association, but the in-flight object retains its attempt id.
        key = getattr(review, "execution_attempt_id", None)
        attempt = ReviewExecutionAttempt.objects.select_for_update().filter(pk=key).first()
    if attempt is None or attempt.receipt:
        return
    if review.usage.get("input_tokens") is not None and not review.usage.get("cost_unreconciled"):
        spend(attempt, "settlement", review.accounted_micros, "settle", {"usage": review.usage})
    elif review.status == "failed":
        # A definitive pre-dispatch failure has no charge; provider ambiguity retains its hold.
        if attempt.status == "queued":
            spend(attempt, "release", review.reserved_micros, "release")
    attempt.status = review.status
    attempt.receipt = {
        "schema_version": 1,
        "environment": "offline",
        "origin": attempt.origin,
        "attempt_id": str(attempt.pk),
        "input_digest": review.input_digest,
        "bundle_digest": attempt.bundle.digest if attempt.bundle_id else None,
        "profile_digest": attempt.profile.digest,
        "request_id": review.provider_request_id,
        "response_id": review.provider_response_id,
        "status": review.status,
        "usage": review.usage,
        "output_digest": digest(review.feedback),
        "completed_at": review.completed_at.isoformat(),
        "software_digest": software_digest(),
    }
    attempt.save(update_fields=["status", "receipt"])
    audit(None, attempt, "execution_finished", {"status": review.status, "origin": attempt.origin})


def finding_identity(review, finding, index):
    return hashlib.sha256(f"{review.pk}:{index}:{digest(finding)}".encode()).hexdigest()


@transaction.atomic
def reveal_hint(user, review, finding_id, level):
    from .review_models import SolutionReview

    if review.author_id != user.pk:
        raise EvaluationError
    review = SolutionReview.objects.select_for_update().get(pk=review.pk)
    assert_assistance(user, review.revision.solution.problem.problem_uuid, delivery=True, review=review)
    if review.status != "completed" or type(level) is not int or level not in {1, 2}:
        raise EvaluationError("Choose an available hint level.", status=422)
    for index, finding in enumerate(review.feedback["findings"]):
        if finding_identity(review, finding, index) != finding_id:
            continue
        content_digest = digest(finding)
        if level > len(finding["hints"]):
            raise EvaluationError("This hint does not exist.", status=422)
        if (
            level == 2
            and not HintRevealEvent.objects.filter(
                review=review,
                finding_id=finding_id,
                content_digest=content_digest,
                level=1,
            ).exists()
        ):
            raise EvaluationError("Reveal the first hint before the second.", status=409)
        item, created = HintRevealEvent.objects.get_or_create(
            review=review,
            finding_id=finding_id,
            content_digest=content_digest,
            level=level,
            defaults={"actor": user},
        )
        if created:
            audit(
                user,
                review.pk,
                "hint_released",
                {
                    "event_id": str(item.pk),
                    "finding_id": finding_id,
                    "level": level,
                    "revision_id": str(review.revision_id),
                },
            )
        return item
    raise EvaluationError


@transaction.atomic
def import_attempts(run, cases):
    """Bind unverified imports to exact inputs without manufacturing provider receipts."""
    from .evaluation_models import EvaluationCase
    from .evaluation_scoring import _validate_report

    software = software_digest()
    for row in cases:
        report = run.reports[row["id"]]
        try:
            _validate_report(report)
        except ValueError as error:
            raise EvaluationError(str(error), status=422) from error
        case = EvaluationCase.objects.get(pk=row["id"])
        attempt = ReviewExecutionAttempt.objects.create(
            run=run,
            bundle=case.bundle,
            profile=run.profile,
            subject_id=case.pk,
            origin=run.origin,
            status=report["status"],
        )
        attempt.receipt = {
            "schema_version": 1,
            "run_id": str(run.pk),
            "attempt_id": str(attempt.pk),
            "dataset_digest": run.snapshot.digest,
            "case_digest": row["input_digest"],
            "profile_digest": run.profile.digest,
            "software_digest": software,
            "environment": "offline_import",
            "origin": run.origin,
            "status": report["status"],
            "output_digest": digest(report),
            "imported_at": timezone.now().isoformat(),
            "provider_execution_verified": False,
        }
        attempt.save(update_fields=["receipt"])
        audit(run.actor, attempt, "import_receipt_recorded", {"origin": run.origin})
