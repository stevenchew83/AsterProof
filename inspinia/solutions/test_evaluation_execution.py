"""Execution-contract regression tests use only synthetic proofs and injected providers."""
# ruff: noqa: PLR2004

from __future__ import annotations

import builtins
import json
from copy import deepcopy
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from inspinia.solutions import evaluation_execution as execution
from inspinia.solutions.evaluation import EvaluationError
from inspinia.solutions.evaluation_models import AssistancePolicy
from inspinia.solutions.evaluation_models import HintRevealEvent
from inspinia.solutions.evaluation_models import ReviewExecutionAttempt
from inspinia.solutions.evaluation_models import ReviewInputBundle
from inspinia.solutions.evaluation_models import ReviewSpendEvent
from inspinia.solutions.review_models import SolutionReview
from inspinia.solutions.review_provider import ProviderError
from inspinia.solutions.review_provider import ProviderResult
from inspinia.solutions.review_provider import generate_review
from inspinia.solutions.reviews import process_next_review
from inspinia.solutions.reviews import review_payload
from inspinia.solutions.test_reviews import coach as coach_fixture
from inspinia.solutions.test_reviews import provider
from inspinia.solutions.test_reviews import report
from inspinia.solutions.test_reviews import request as request_review
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def coach(settings):
    return coach_fixture.__wrapped__(settings)


def restrict(coach, *, mode="restricted_assessment", problem_scope=True, actor_scope=True):
    return AssistancePolicy.objects.create(
        problem_uuid=coach.problem.problem_uuid if problem_scope else None,
        actor_id_scope=coach.user.pk if actor_scope else None,
        mode=mode,
        starts_at=timezone.now() - timedelta(minutes=1),
        ends_at=timezone.now() + timedelta(minutes=10),
        reason="Synthetic restriction test",
    )


def completed_review(coach, review_provider=provider):
    review, _ = request_review(coach)
    assert process_next_review(review_provider)["state"] == "completed"
    review.refresh_from_db()
    return review


def status_url(coach, review):
    return reverse("solutions:solution_review_status", args=[coach.problem.problem_uuid, review.pk])


def test_real_provider_is_rejected_before_sdk_import_or_credentials(monkeypatch, settings):
    imports = []
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "openai":
            imports.append(name)
            message = "The provider SDK must not be imported."
            raise AssertionError(message)
        return original_import(name, *args, **kwargs)

    class CredentialsMustNotBeRead:
        @property
        def OPENAI_API_KEY(self):  # noqa: N802 - mirrors a Django setting name
            message = "Credentials must not be read before the offline guard."
            raise AssertionError(message)

    from inspinia.solutions import review_provider

    settings.SOLUTION_AI_EXECUTION_MODE = "provider"
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(review_provider, "settings", CredentialsMustNotBeRead())
    with pytest.raises(EvaluationError) as caught:
        generate_review(None, [])
    assert caught.value.code == "offline_execution"
    assert imports == []


def test_spend_events_are_idempotent_immutable_and_conflicts_fail(coach):
    review, _ = request_review(coach)
    attempt = review.execution
    first = execution.spend(attempt, "adjustment", 17, "synthetic-adjustment")
    assert execution.spend(attempt, "adjustment", 17, "synthetic-adjustment").pk == first.pk
    assert ReviewSpendEvent.objects.filter(attempt=attempt, idempotency_key="synthetic-adjustment").count() == 1
    with pytest.raises(EvaluationError, match="idempotency conflict"):
        execution.spend(attempt, "adjustment", 18, "synthetic-adjustment")
    with pytest.raises(ValidationError):
        ReviewSpendEvent.objects.filter(pk=first.pk).update(amount_micros=0)


def test_inflight_deletion_settles_once_without_private_content_archive(coach):
    review, _ = request_review(coach)
    attempt_id = review.execution.pk
    source = coach.revision.body_source

    def deleting_provider(active_review, images):
        SolutionReview.objects.filter(pk=active_review.pk).delete()
        return provider(active_review, images)

    assert process_next_review(deleting_provider)["state"] == "discarded"
    attempt = ReviewExecutionAttempt.objects.get(pk=attempt_id)
    assert attempt.review_id is None
    assert attempt.receipt["status"] == "completed"
    assert attempt.receipt["origin"] == "deterministic_fixture"
    assert ReviewSpendEvent.objects.filter(attempt=attempt, kind="settlement").count() == 1
    before = list(attempt.spend_events.values_list("pk", flat=True))
    assert execution.ledger_totals(timezone.now() - timedelta(days=1)) > 0
    assert not SolutionReview.objects.filter(pk=review.pk).exists()
    remaining_content = list(ReviewInputBundle.objects.filter(pk=attempt.bundle_id).values_list("payload", flat=True))
    assert source not in json.dumps([attempt.receipt, remaining_content])
    review._execution_id = attempt_id  # noqa: SLF001 - retain the same in-flight identity for reconciliation
    execution.finish_attempt(review)
    assert list(attempt.spend_events.values_list("pk", flat=True)) == before


def test_unknown_inflight_deletion_keeps_reservation_and_does_not_retry(coach):
    review, _ = request_review(coach)
    attempt_id = review.execution.pk
    calls = []

    def uncertain_provider(active_review, _images):
        calls.append(active_review.pk)
        SolutionReview.objects.filter(pk=active_review.pk).delete()
        code = "synthetic_uncertain"
        raise ProviderError(code)

    assert process_next_review(uncertain_provider)["state"] == "discarded"
    attempt = ReviewExecutionAttempt.objects.get(pk=attempt_id)
    assert attempt.status == "outcome_unknown"
    assert execution.ledger_totals(timezone.now() - timedelta(days=1)) == review.reserved_micros
    assert process_next_review(uncertain_provider)["state"] == "idle"
    assert calls == [review.pk]


@pytest.mark.parametrize("mode", ["restricted_assessment", "quarantine", "withdrawal"])
def test_restrictions_deny_enqueue_on_server(coach, mode):
    restrict(coach, mode=mode)
    with pytest.raises(EvaluationError) as caught:
        request_review(coach)
    assert caught.value.code == "assistance_restricted"
    assert not SolutionReview.objects.exists()
    assert not ReviewSpendEvent.objects.exists()


def test_new_restriction_blocks_already_queued_dispatch_without_provider_call(coach):
    review, _ = request_review(coach)
    restrict(coach)
    calls = []

    def never_called(*args):
        calls.append(args)
        return provider(*args)

    result = process_next_review(never_called)
    assert result["state"] == "failed"
    assert result["error_code"] == "assistance_restricted"
    assert calls == []
    review.refresh_from_db()
    assert review.status == "failed"
    assert execution.ledger_totals(timezone.now() - timedelta(days=1)) == 0


def test_never_dispatched_queue_expiry_releases_durable_reservation(coach):
    review, _ = request_review(coach)
    SolutionReview.objects.filter(pk=review.pk).update(created_at=timezone.now() - timedelta(minutes=20))
    calls = []

    def never_called(*args):
        calls.append(args)
        return provider(*args)

    assert process_next_review(never_called)["state"] == "idle"
    review.refresh_from_db()
    assert review.status == "expired"
    assert calls == []
    assert execution.ledger_totals(timezone.now() - timedelta(days=1)) == 0
    assert ReviewSpendEvent.objects.filter(attempt=review.execution, kind="release").count() == 1


def test_invitation_revocation_releases_never_dispatched_reservation(coach):
    review, _ = request_review(coach)
    coach.user.groups.clear()
    calls = []

    def never_called(*args):
        calls.append(args)
        return provider(*args)

    assert process_next_review(never_called)["state"] == "expired"
    assert calls == []
    assert execution.ledger_totals(timezone.now() - timedelta(days=1)) == 0
    assert ReviewSpendEvent.objects.filter(attempt=review.execution, kind="release").count() == 1


def test_restriction_is_checked_for_feedback_and_hint_delivery(coach, client):
    review = completed_review(coach)
    payload = review_payload(review)
    reveal_url = payload["feedback"]["findings"][0]["reveal_url"]
    restrict(coach)
    client.force_login(coach.user)
    assert client.get(status_url(coach, review)).status_code == 403
    assert client.post(reveal_url, {"level": 1}).status_code == 403
    assert not HintRevealEvent.objects.exists()


def test_disabling_new_requests_preserves_permitted_existing_feedback(coach, client, settings):
    review = completed_review(coach)
    settings.SOLUTION_AI_REVIEW_ENABLED = False
    client.force_login(coach.user)
    assert client.get(status_url(coach, review)).status_code == 200


def test_hint_query_cannot_bypass_recorded_post_release(coach, client):
    review = completed_review(coach)
    client.force_login(coach.user)
    response = client.get(status_url(coach, review) + "?hint_level=2")
    finding = response.json()["feedback"]["findings"][0]
    assert "hints" not in finding
    assert finding["released_level"] == 0
    assert not HintRevealEvent.objects.exists()
    assert client.get(finding["reveal_url"]).status_code == 405
    assert client.post(finding["reveal_url"], {"level": 2}).status_code == 409
    assert not HintRevealEvent.objects.exists()
    first = client.post(finding["reveal_url"], {"level": 1})
    assert first.status_code == 200
    assert len(first.json()["feedback"]["findings"][0]["hints"]) == 1
    assert HintRevealEvent.objects.count() == 1
    assert client.post(finding["reveal_url"], {"level": 1}).status_code == 200
    assert HintRevealEvent.objects.count() == 1
    assert client.post(finding["reveal_url"], {"level": 2}).status_code == 200
    assert HintRevealEvent.objects.count() == 2


def test_reveal_is_per_finding_and_bound_to_content_version(coach, client):
    feedback = report()
    second = deepcopy(feedback["findings"][0])
    second["explanation"] = "A separately identified concern in this synthetic report."
    second["hints"] = ["A separate first hint.", "A separate second hint."]
    feedback["findings"].append(second)

    def two_findings(_review, _images):
        return ProviderResult(feedback=feedback, usage={"input_tokens": 10, "output_tokens": 10})

    review = completed_review(coach, two_findings)
    client.force_login(coach.user)
    findings = review_payload(review)["feedback"]["findings"]
    assert client.post(findings[0]["reveal_url"], {"level": 1}).status_code == 200
    updated = client.get(status_url(coach, review)).json()["feedback"]["findings"]
    assert "hints" in updated[0]
    assert "hints" not in updated[1]
    review.feedback["findings"][0]["hints"][0] = "Changed content must require a fresh disclosure."
    review.save(update_fields=["feedback"])
    changed = client.get(status_url(coach, review)).json()["feedback"]["findings"][0]
    assert "hints" not in changed
    assert changed["id"] != findings[0]["id"]
    assert client.post(findings[0]["reveal_url"], {"level": 1}).status_code == 403
    assert HintRevealEvent.objects.count() == 1


def test_other_learner_cannot_read_or_release_hints(coach, client):
    review = completed_review(coach)
    finding = review_payload(review)["feedback"]["findings"][0]
    client.force_login(UserFactory())
    assert client.get(status_url(coach, review)).status_code == 404
    assert client.post(finding["reveal_url"], {"level": 1}).status_code == 404
    assert not HintRevealEvent.objects.exists()


def test_hint_release_requires_csrf_for_authenticated_session(coach):
    from django.test import Client

    review = completed_review(coach)
    finding = review_payload(review)["feedback"]["findings"][0]
    client = Client(enforce_csrf_checks=True)
    client.force_login(coach.user)
    assert client.post(finding["reveal_url"], {"level": 1}).status_code == 403
    assert not HintRevealEvent.objects.exists()


def test_missing_official_diagram_blocks_positive_feedback(coach):
    coach.statement.statement_latex += r"\includegraphics{missing-official-diagram.png}"
    coach.statement.save()

    def incorrectly_positive(_review, _images):
        positive = report()
        positive.update(assessment="no_issues_found", findings=[])
        return ProviderResult(feedback=positive, usage={"input_tokens": 10, "output_tokens": 10})

    review = completed_review(coach, incorrectly_positive)
    assert review.execution.bundle.payload["completeness"] == "missing_essential_context"
    assert review.feedback["assessment"] == "unable_to_assess"
    assert review.feedback["limitations"]


def test_disabled_execution_mode_overrides_funded_student_flags(coach, settings):
    from inspinia.solutions.reviews import ReviewError
    from inspinia.solutions.reviews import review_available

    settings.SOLUTION_AI_EXECUTION_MODE = "offline"
    assert not review_available(coach.user)
    with pytest.raises(ReviewError, match="not available"):
        request_review(coach)


def test_queued_review_settles_with_frozen_long_context_pricing(coach, monkeypatch):
    from inspinia.solutions import reviews

    review, _ = request_review(coach)
    monkeypatch.setattr(reviews, "LONG_CONTEXT_THRESHOLD", 1)
    assert process_next_review(provider)["state"] == "completed"
    review.refresh_from_db()
    assert review.accounted_micros == 3500


def test_unknown_cached_pricing_preserves_usage_and_reservation(coach):
    def cached_provider(review, images):
        result = provider(review, images)
        result.usage["input_tokens_details"] = {"cached_tokens": 40}
        return result

    review, _ = request_review(coach)
    assert process_next_review(cached_provider)["state"] == "completed"
    review.refresh_from_db()
    assert review.usage["input_tokens_details"]["cached_tokens"] == 40
    assert review.usage["cost_unreconciled"]
    assert review.accounted_micros == review.reserved_micros
    assert not review.execution.spend_events.filter(kind="settlement").exists()


def test_deleting_legacy_review_preserves_recorded_financial_exposure(coach):
    from uuid import uuid4

    legacy = SolutionReview.objects.create(
        author=coach.user,
        revision=coach.revision,
        idempotency_key=uuid4(),
        status="completed",
        input_snapshot={"body_source": "private legacy proof"},
        input_digest="a" * 64,
        model="legacy-unverified",
        reserved_micros=500,
        accounted_micros=500,
        pricing_snapshot={},
        acknowledged_at=timezone.now(),
    )
    legacy.delete()
    attempt = ReviewExecutionAttempt.objects.get(status="legacy_unreconciled")
    attempt._meta.get_field("status").run_validators(attempt.status)  # noqa: SLF001 - validate PostgreSQL's field bound
    assert attempt.bundle_id is None
    assert attempt.profile.payload["legacy_incomplete"]
    assert attempt.spend_events.get().amount_micros == 500
    assert "private legacy proof" not in json.dumps(attempt.receipt)


def test_hint_release_accepts_csrf_checked_multipart_form(coach):
    from django.test import Client

    review = completed_review(coach)
    finding = review_payload(review)["feedback"]["findings"][0]
    client = Client(enforce_csrf_checks=True)
    client.force_login(coach.user)
    csrf = "a" * 32
    client.cookies["csrftoken"] = csrf
    response = client.post(finding["reveal_url"], {"level": 1, "csrfmiddlewaretoken": csrf})
    assert response.status_code == 200
    assert response.json()["feedback"]["findings"][0]["released_level"] == 1


@pytest.mark.parametrize("limit_field", ["user_daily_limit", "global_daily_limit"])
def test_deleting_review_does_not_restore_daily_request_allowance(coach, limit_field):
    from inspinia.solutions.reviews import ReviewError

    setattr(coach.policy, limit_field, 1)
    coach.policy.save()
    review = completed_review(coach)
    review.delete()
    with pytest.raises(ReviewError, match="allowance"):
        request_review(coach)
