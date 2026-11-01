"""Reuse consent is explicit, owner-only and independent of disabled AI review."""

import json
import uuid
from datetime import timedelta
from hashlib import sha256
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from inspinia.solutions.evaluation_assistance import REUSE_POLICY_VERSION
from inspinia.solutions.evaluation_assistance import record_reuse_consent
from inspinia.solutions.evaluation_models import EvaluationAuditEvent
from inspinia.solutions.evaluation_models import EvaluationCase
from inspinia.solutions.evaluation_models import EvaluationLifecycle
from inspinia.solutions.evaluation_models import ReviewConsent
from inspinia.solutions.models import SolutionRevision
from inspinia.solutions.review_models import SolutionReview
from inspinia.solutions.test_reviews import coach as coach_fixture
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def coach(settings):
    result = coach_fixture.__wrapped__(settings)
    settings.SOLUTION_AI_REVIEW_ENABLED = False
    result.policy.enabled = False
    result.policy.save()
    return result


def create_url(coach):
    return reverse("solutions:solution_reuse_consent_create", args=[coach.problem.problem_uuid])


def withdraw_url(consent):
    return reverse("solutions:solution_reuse_consent_withdraw", args=[consent.pk])


def consent_data(coach, **changes):
    return {
        "revision_id": str(coach.revision.pk),
        "expires_at": (timezone.now() + timedelta(days=10)).isoformat(),
        "policy_version": REUSE_POLICY_VERSION,
        **changes,
    }


def test_explicit_consent_does_not_copy_work_or_enable_ai(coach, client, settings):
    client.force_login(coach.user)
    revisions_before = SolutionRevision.objects.count()
    response = client.post(create_url(coach), json.dumps(consent_data(coach)), content_type="application/json")
    assert response.status_code == HTTPStatus.CREATED
    data = response.json()
    consent = ReviewConsent.objects.get(pk=data["id"])
    assert consent.actor_id == coach.user.pk
    assert data["revision_id"] == str(coach.revision.pk)
    assert data["source_digest"] == coach.revision.source_digest
    assert data["eligibility"] == "pending_independent_approval"
    assert not data["copied_to_benchmark"]
    assert EvaluationAuditEvent.objects.filter(target_id=consent.pk, kind="reuse_consent_recorded").exists()
    assert SolutionRevision.objects.count() == revisions_before
    assert not EvaluationCase.objects.exists()
    assert not SolutionReview.objects.exists()
    assert not settings.SOLUTION_AI_REVIEW_ENABLED
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]


def test_anonymous_requests_cannot_record_or_withdraw_consent(coach, client):
    consent = record_reuse_consent(
        coach.user,
        coach.revision,
        timezone.now() + timedelta(days=10),
        REUSE_POLICY_VERSION,
    )
    response = client.post(create_url(coach), json.dumps(consent_data(coach)), content_type="application/json")
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert client.post(withdraw_url(consent)).status_code == HTTPStatus.UNAUTHORIZED
    assert not EvaluationAuditEvent.objects.filter(target_id=consent.pk, kind="reuse_consent_withdrawn").exists()


def test_other_user_cannot_access_revision_or_consent_by_identifier(coach, client):
    consent = record_reuse_consent(
        coach.user,
        coach.revision,
        timezone.now() + timedelta(days=10),
        REUSE_POLICY_VERSION,
    )
    client.force_login(UserFactory(is_approved=True))
    response = client.post(create_url(coach), json.dumps(consent_data(coach)), content_type="application/json")
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert client.post(withdraw_url(consent)).status_code == HTTPStatus.NOT_FOUND
    assert not EvaluationAuditEvent.objects.filter(target_id=consent.pk, kind="reuse_consent_withdrawn").exists()


def test_wrong_problem_cannot_authorize_an_owned_revision(coach, client):
    client.force_login(coach.user)
    url = reverse("solutions:solution_reuse_consent_create", args=[uuid.uuid4()])
    response = client.post(url, json.dumps(consent_data(coach)), content_type="application/json")
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert not ReviewConsent.objects.exists()


def test_stale_saved_revision_requires_fresh_consent_action(coach, client):
    source = "A revised independently written proof."
    newer = SolutionRevision.objects.create(
        solution=coach.solution,
        sequence=2,
        body_source=source,
        source_digest=sha256(source.encode()).hexdigest(),
    )
    coach.solution.current_revision = newer
    coach.solution.save()
    client.force_login(coach.user)
    response = client.post(create_url(coach), json.dumps(consent_data(coach)), content_type="application/json")
    assert response.status_code == HTTPStatus.CONFLICT
    assert not ReviewConsent.objects.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"revision_id": "invalid"},
        {"expires_at": None},
        {"expires_at": "not-a-date"},
        {"expires_at": "2026-11-02T10:00:00"},
        {"expires_at": "2020-01-01T00:00:00+00:00"},
        {"policy_version": "unknown-policy"},
        {"policy_version": None},
    ],
)
def test_invalid_expiry_or_policy_cannot_create_a_consent(coach, client, changes):
    client.force_login(coach.user)
    response = client.post(
        create_url(coach),
        json.dumps(consent_data(coach, **changes)),
        content_type="application/json",
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not ReviewConsent.objects.exists()


@pytest.mark.parametrize("body", ["[]", "{broken", "x" * 16_001], ids=["array", "malformed-json", "oversized"])
def test_malformed_or_oversized_request_is_rejected(coach, client, body):
    client.force_login(coach.user)
    response = client.post(create_url(coach), body, content_type="application/json")
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not ReviewConsent.objects.exists()


def test_owner_withdrawal_is_idempotent_and_preserves_authored_revision(coach, client):
    source = coach.revision.body_source
    consent = record_reuse_consent(
        coach.user,
        coach.revision,
        timezone.now() + timedelta(days=10),
        REUSE_POLICY_VERSION,
    )
    client.force_login(coach.user)
    for _ in range(2):
        response = client.post(withdraw_url(consent))
        assert response.status_code == HTTPStatus.OK
        assert response.json()["status"] == "withdrawn"
    assert not EvaluationLifecycle.objects.get(target_id=consent.pk).eligible
    assert EvaluationAuditEvent.objects.filter(target_id=consent.pk, kind="reuse_consent_withdrawn").count() == 1
    coach.revision.refresh_from_db()
    assert coach.revision.body_source == source


def test_feedback_permission_cannot_be_revoked_through_benchmark_endpoint(coach, client):
    consent = ReviewConsent.objects.create(
        actor=coach.user,
        purpose="feedback",
        payload={},
        expires_at=timezone.now() + timedelta(days=10),
    )
    client.force_login(coach.user)
    assert client.post(withdraw_url(consent)).status_code == HTTPStatus.NOT_FOUND
    assert not EvaluationLifecycle.objects.filter(target_id=consent.pk, eligible=False).exists()


def test_get_cannot_record_or_withdraw_consent(coach, client):
    consent = record_reuse_consent(
        coach.user,
        coach.revision,
        timezone.now() + timedelta(days=10),
        REUSE_POLICY_VERSION,
    )
    client.force_login(coach.user)
    assert client.get(create_url(coach)).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert client.get(withdraw_url(consent)).status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_consent_routes_enforce_csrf(coach):
    client = Client(enforce_csrf_checks=True)
    client.force_login(coach.user)
    data = json.dumps(consent_data(coach))
    assert client.post(create_url(coach), data, content_type="application/json").status_code == HTTPStatus.FORBIDDEN
    token = "a" * 32
    client.cookies["csrftoken"] = token
    response = client.post(create_url(coach), data, content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert response.status_code == HTTPStatus.CREATED
    form_response = client.post(create_url(coach), consent_data(coach), HTTP_X_CSRFTOKEN=token)
    assert form_response.status_code == HTTPStatus.CREATED
    consent = ReviewConsent.objects.get(pk=response.json()["id"])
    assert client.post(withdraw_url(consent)).status_code == HTTPStatus.FORBIDDEN
    assert client.post(withdraw_url(consent), HTTP_X_CSRFTOKEN=token).status_code == HTTPStatus.OK
