# ruff: noqa: PLR2004 - HTTP status codes and explicit event counts are regression assertions.
"""Synthetic admin workflow must not touch paid review or student publication paths."""

import socket
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.db import connection
from django.http import Http404
from django.test import Client
from django.urls import reverse

from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionReview
from inspinia.solutions.prototype_models import SyntheticHintReveal
from inspinia.solutions.prototype_models import SyntheticReview
from inspinia.solutions.synthetic_reviews import create_synthetic_review
from inspinia.solutions.synthetic_reviews import private_report_payload
from inspinia.solutions.synthetic_reviews import reveal_hint
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
CASE = "synthetic-nt-held_out-invalid"


@pytest.fixture
def admin_user():
    return UserFactory(role="admin", is_staff=True, is_superuser=True)


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def create(user, mode="coach", **overrides):
    return create_synthetic_review(
        user,
        **{
            "case_id": CASE,
            "mode": mode,
            "idempotency_key": uuid.uuid4(),
            **overrides,
        },
    )[0]


def detail_url(review):
    return reverse("solutions:synthetic_review_detail", args=[review.pk])


def test_anonymous_and_non_admin_users_cannot_access_reports(admin_user, client):
    review = create(admin_user, "examiner")
    assert client.get(detail_url(review)).status_code == 302
    user = UserFactory(role="trainer", is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="solutions"))
    client.force_login(user)
    assert client.get(detail_url(review)).status_code == 403
    assert client.get(reverse("solutions:synthetic_review_workspace")).status_code == 403
    with pytest.raises(PermissionDenied):
        create(user)


def test_explicit_permissions_and_current_role_are_required():
    user = UserFactory(role="admin")
    with pytest.raises(PermissionDenied):
        create(user)
    user.user_permissions.add(*Permission.objects.filter(codename__in=["view_syntheticreview", "add_syntheticreview"]))
    review = create(user)
    type(user).objects.filter(pk=user.pk).update(role="trainer")
    with pytest.raises(PermissionDenied):
        private_report_payload(review, user)


def test_feature_is_disabled_outside_local_settings(admin_user, admin_client, settings):
    settings.SYNTHETIC_REVIEW_PROTOTYPE_ENABLED = False
    assert admin_client.get(reverse("solutions:synthetic_review_workspace")).status_code == 404
    with pytest.raises(Http404):
        create(admin_user)
    assert not SyntheticReview.objects.exists()


@pytest.mark.parametrize("mode", ["coach", "provisional", "examiner"])
def test_mode_reports_are_private_revision_bound_and_leave_live_records_untouched(admin_user, admin_client, mode):
    learner = UserFactory()
    problem = ProblemSolveRecord.objects.create(contest="SYNTHETIC-PROTOTYPE", year=2026, problem="P1", topic="NT")
    solution = ProblemSolution.objects.create(problem=problem, author=learner, title="Existing synthetic work")
    completion = UserProblemCompletion.objects.create(
        user=learner,
        problem=problem,
        status="attempted",
        proof_completed=False,
    )
    solution_before = ProblemSolution.objects.values().get(pk=solution.pk)
    completion_before = UserProblemCompletion.objects.values().get(pk=completion.pk)
    live_before = (ProblemSolution.objects.count(), SolutionReview.objects.count())
    review = create(admin_user, mode)
    review.refresh_from_db()
    review.check_integrity()
    response = admin_client.get(detail_url(review))
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert response["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert response.context["report"]["mode"] == mode
    assert review.packet["input_digest"]
    assert "candidate_labels" not in review.packet
    assert review.prompt_manifest["stages"]["assessment"]["instructions_digest"]
    assert (ProblemSolution.objects.count(), SolutionReview.objects.count()) == live_before
    assert ProblemSolution.objects.values().get(pk=solution.pk) == solution_before
    assert UserProblemCompletion.objects.values().get(pk=completion.pk) == completion_before
    reference = review.packet["package"]["content"]["references"][0]["proof"]
    body = response.content.decode()
    if mode == "examiner":
        assert reference in body
        assert "Not human-approved" in body
        assert "Provisional rubric score" not in body
    else:
        assert reference not in body
        assert review.private_hints["finding-1"][0] not in body
        assert "Complete synthetic reference solution" not in body
    if mode == "provisional":
        assert response.context["report"]["score"]["total"] == 3
    if mode == "coach":
        assert "score" not in response.context["report"]


def test_hints_require_post_progress_in_order_and_are_attributed_idempotently(admin_user, admin_client):
    review = create(admin_user)
    url = reverse("solutions:synthetic_review_hint", args=[review.pk])
    assert admin_client.get(url).status_code == 405
    assert admin_client.post(url, {"finding_id": "finding-1", "level": 2}).status_code == 400
    for _repeat in range(2):
        assert admin_client.post(url, {"finding_id": "finding-1", "level": 1}).status_code == 302
    assert SyntheticHintReveal.objects.count() == 1
    event = SyntheticHintReveal.objects.get()
    assert event.reviewer_id == admin_user.pk
    assert event.created_at is not None
    report = admin_client.get(detail_url(review)).context["report"]
    assert report["findings"][0]["hints"] == review.private_hints["finding-1"][:1]
    assert admin_client.post(url, {"finding_id": "finding-1", "level": 2}).status_code == 302
    assert SyntheticHintReveal.objects.count() == 2
    other_admin = UserFactory(role="admin", is_superuser=True)
    assert private_report_payload(review, other_admin)["findings"][0]["hints"] == []


def test_examiner_and_unknown_findings_cannot_reveal_hints(admin_user):
    review = create(admin_user, "examiner")
    with pytest.raises(ValidationError, match="available hint"):
        reveal_hint(admin_user, review, "finding-1", 1)
    coach = create(admin_user)
    with pytest.raises(ValidationError, match="available hint"):
        reveal_hint(admin_user, coach, "invented", 1)


def test_unreadable_submission_withholds_score_in_the_rendered_report(admin_user, admin_client):
    review = create(admin_user, "provisional", case_id="synthetic-geo-held_out-partial")
    response = admin_client.get(detail_url(review))
    assert response.status_code == 200
    assert response.context["report"]["score"]["total"] is None
    assert "Score withheld: human review required." in response.content.decode()


def test_read_permission_does_not_grant_hint_reveal(admin_user, client):
    review = create(admin_user)
    viewer = UserFactory(role="admin")
    viewer.user_permissions.add(Permission.objects.get(codename="view_syntheticreview"))
    client.force_login(viewer)
    response = client.get(detail_url(review))
    assert response.status_code == 200
    assert "Reveal hint 1" not in response.content.decode()
    url = reverse("solutions:synthetic_review_hint", args=[review.pk])
    assert client.post(url, {"finding_id": "finding-1", "level": 1}).status_code == 403
    assert not SyntheticHintReveal.objects.exists()


def test_requests_and_report_history_are_append_only_and_idempotent(admin_user):
    key = uuid.uuid4()
    first = create(admin_user, idempotency_key=key)
    second = create(admin_user, idempotency_key=key)
    assert first.pk == second.pk
    assert SyntheticReview.objects.count() == 1
    with pytest.raises(ValidationError, match="different case"):
        create(admin_user, "examiner", idempotency_key=key)
    with pytest.raises(ValidationError, match="append-only"):
        first.save()
    with pytest.raises(ValidationError, match="append-only"):
        SyntheticReview.objects.filter(pk=first.pk).update(mode="examiner")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        first.delete()
    first.report["summary"] = "Changed report."
    with pytest.raises(ValidationError, match="frozen digest"):
        first.check_integrity()


def test_workspace_post_rejects_real_input_and_obeys_csrf(admin_client):
    url = reverse("solutions:synthetic_review_workspace")
    data = {"case_id": CASE, "mode": "coach", "idempotency_key": str(uuid.uuid4())}
    assert admin_client.post(url, {**data, "submission": "Real student text"}).status_code == 400
    assert admin_client.post(url, {**data, "case_id": "real-student-revision"}).status_code == 422
    assert not SyntheticReview.objects.exists()
    response = admin_client.post(url, data)
    assert response.status_code == 302
    assert SyntheticReview.objects.count() == 1
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(response.wsgi_request.user)
    assert csrf_client.post(url, data).status_code == 403


def test_all_modes_execute_without_provider_or_network(admin_user, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("The synthetic prototype must not contact a provider.")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.setattr("inspinia.solutions.review_provider.generate_review", forbidden)
    for mode in ("coach", "provisional", "examiner"):
        create(admin_user, mode)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", ["report", "hint"])
def test_postgres_duplicate_requests_are_idempotent_during_model_validation(admin_user, monkeypatch, operation):
    if connection.vendor != "postgresql":
        pytest.skip("Concurrent application validation requires PostgreSQL")
    key = uuid.uuid4()
    review = create(admin_user) if operation == "hint" else None
    model = SyntheticHintReveal if review else SyntheticReview
    original_save = model.save
    entered, release, second_finished = Event(), Event(), Event()

    def delayed_save(instance, *args, **kwargs):
        # Pause the first insertion before full_clean checks uniqueness. A second
        # request must wait for the service lock rather than race that validation.
        if not entered.is_set():
            entered.set()
            assert release.wait(timeout=5)
        return original_save(instance, *args, **kwargs)

    monkeypatch.setattr(model, "save", delayed_save)

    def run(*, second=False):
        close_old_connections()
        try:
            if review:
                return reveal_hint(admin_user, review, "finding-1", 1).pk
            return create(admin_user, idempotency_key=key).pk
        finally:
            close_old_connections()
            if second:
                second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run)
        assert entered.wait(timeout=5)
        second = executor.submit(run, second=True)
        try:
            second_finished.wait(timeout=1)
        finally:
            release.set()
        assert first.result(timeout=5) == second.result(timeout=5)
    assert model.objects.count() == 1
