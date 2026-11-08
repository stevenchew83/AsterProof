"""Private coaching dispatch, cost controls, and immutable source attribution."""
# ruff: noqa: PLR2004

import hashlib
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from threading import Event
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.db import close_old_connections
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionBodyImage
from inspinia.solutions.models import SolutionRevision
from inspinia.solutions.review_models import SolutionReview
from inspinia.solutions.review_models import SolutionReviewPolicy
from inspinia.solutions.review_provider import ProviderError
from inspinia.solutions.review_provider import ProviderResult
from inspinia.solutions.reviews import ReviewError
from inspinia.solutions.reviews import _token_cost
from inspinia.solutions.reviews import enqueue_review
from inspinia.solutions.reviews import process_next_review
from inspinia.solutions.reviews import review_available
from inspinia.solutions.reviews import review_payload
from inspinia.solutions.reviews import validate_feedback
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def coach(settings):
    settings.SOLUTION_AI_REVIEW_ENABLED = True
    settings.SOLUTION_AI_EXECUTION_MODE = "fixture"
    user = UserFactory()
    user.groups.add(Group.objects.create(name="solution-ai-pilot"))
    problem = ProblemSolveRecord.objects.create(contest="COACH", year=2026, problem="A1", topic="ALG")
    statement = ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_name="COACH",
        contest_year=2026,
        problem_code="A1",
        problem_number=1,
        statement_latex="Prove that every positive square is nonnegative.",
    )
    solution = ProblemSolution.objects.create(problem=problem, author=user)
    source = "Let $x>0$.\nThen $x^2>0$."
    revision = SolutionRevision.objects.create(
        solution=solution,
        sequence=1,
        body_source=source,
        source_digest=hashlib.sha256(source.encode()).hexdigest(),
    )
    solution.current_revision = revision
    solution.edit_version = 1
    solution.save()
    policy = SolutionReviewPolicy.objects.create(
        enabled=True,
        daily_budget_micros=100_000_000,
        monthly_budget_micros=1_000_000_000,
        request_budget_micros=100_000_000,
        pricing_verified_at=timezone.now(),
        worker_seen_at=timezone.now(),
    )
    return SimpleNamespace(
        user=user,
        problem=problem,
        statement=statement,
        solution=solution,
        revision=revision,
        policy=policy,
    )


def request(coach, **kwargs):
    return enqueue_review(
        coach.user,
        coach.problem.problem_uuid,
        coach.revision.pk,
        kwargs.pop("idempotency_key", uuid.uuid4()),
        acknowledged=kwargs.pop("acknowledged", True),
        **kwargs,
    )


def report():
    return {
        "assessment": "gap_found",
        "summary": "Explain the asserted step.",
        "strengths": [],
        "findings": [
            {
                "category": "logical_gap",
                "severity": "major",
                "quote": "Then $x^2>0$.",
                "context_before": "",
                "context_after": "",
                "explanation": "The step needs a justification.",
                "hints": ["Use the sign of a product.", "Both factors are positive."],
            },
        ],
        "next_step": "Justify the product's sign.",
        "limitations": [],
    }


def provider(_review, _images):
    return ProviderResult(
        feedback=report(),
        response_id="resp_test",
        request_id="req_test",
        usage={"input_tokens": 100, "output_tokens": 50},
    )


def test_review_requires_both_gates_invitation_pricing_and_budget(coach, settings):
    assert review_available(coach.user)
    settings.SOLUTION_AI_REVIEW_ENABLED = False
    assert not review_available(coach.user)
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.status == 503
    settings.SOLUTION_AI_REVIEW_ENABLED = True
    coach.policy.pricing_verified_at = None
    coach.policy.save()
    assert not review_available(coach.user)
    coach.policy.pricing_verified_at = timezone.now()
    coach.policy.monthly_budget_micros = 0
    coach.policy.save()
    assert not review_available(coach.user)
    coach.policy.monthly_budget_micros = 1_000_000_000
    coach.policy.save()
    coach.user.groups.clear()
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.status == 403
    assert not SolutionReview.objects.exists()


@pytest.mark.parametrize(("model", "price"), [("unreviewed-model", 10_000_000), ("gpt-6-astra", 1)])
def test_unpriced_or_underpriced_models_are_denied(coach, model, price):
    coach.policy.model = model
    coach.policy.input_price_micros_per_million = price
    coach.policy.save()
    assert not review_available(coach.user)
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.code == "review_disabled"


@pytest.mark.parametrize("offset", [timedelta(days=-31), timedelta(minutes=1)])
def test_expired_or_future_price_verification_disables_dispatch(coach, offset):
    coach.policy.pricing_verified_at = timezone.now() + offset
    coach.policy.save()
    assert not review_available(coach.user)
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.code == "review_disabled"


@pytest.mark.parametrize(("field", "value"), [("user_daily_limit", 4), ("global_daily_limit", 21)])
def test_orm_policy_edits_cannot_expand_hard_pilot_limits(coach, field, value):
    SolutionReviewPolicy.objects.filter(pk=coach.policy.pk).update(**{field: value})
    assert not review_available(coach.user)
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.code == "review_disabled"


def test_long_context_pricing_tier_is_included():
    pricing = {"input": 10_000_000, "output": 50_000_000}
    assert _token_cost(100, 50, pricing) == 3500
    assert _token_cost(300_000, 16_000, pricing) == 7_200_000


def test_acknowledgement_snapshot_and_idempotency(coach):
    with pytest.raises(ReviewError, match="Acknowledge"):
        request(coach, acknowledged=False)
    key = uuid.uuid4()
    review, created = request(coach, idempotency_key=key)
    duplicate, again = request(coach, idempotency_key=key, acknowledged=False)
    assert created
    assert not again
    assert duplicate.pk == review.pk
    assert review.input_snapshot["statement"] == coach.statement.statement_latex
    assert review.reserved_micros > 0
    assert review.reserved_micros == review.accounted_micros
    assert SolutionReview.objects.count() == 1
    assert coach.solution.status == ProblemSolution.Status.DRAFT
    coach.policy.enabled = False
    coach.policy.save()
    reconciled, created = request(coach, idempotency_key=key)
    assert reconciled.pk == review.pk
    assert not created


def test_worker_readiness_and_per_request_reservation(coach):
    coach.policy.worker_seen_at = timezone.now() - timedelta(minutes=3)
    coach.policy.save()
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.code == "worker_unavailable"
    coach.policy.worker_seen_at = timezone.now()
    coach.policy.request_budget_micros = 1
    coach.policy.save()
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.code == "request_budget"


def test_current_revision_and_owner_required(coach):
    other = UserFactory()
    other.groups.add(Group.objects.get(name="solution-ai-pilot"))
    with pytest.raises(ReviewError) as caught:
        enqueue_review(other, coach.problem.problem_uuid, coach.revision.pk, uuid.uuid4(), acknowledged=True)
    assert caught.value.status == 404
    second = SolutionRevision.objects.create(
        solution=coach.solution,
        sequence=2,
        body_source="New proof",
        source_digest="a" * 64,
    )
    coach.solution.current_revision = second
    coach.solution.save()
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.status == 409


def test_budget_limits_and_one_active_review(coach):
    review, _ = request(coach)
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.code == "review_in_progress"
    review.status = SolutionReview.Status.COMPLETED
    review.save()
    coach.policy.daily_budget_micros = review.accounted_micros
    coach.policy.save()
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.code == "review_budget"
    coach.policy.daily_budget_micros = 100_000_000
    coach.policy.user_daily_limit = 1
    coach.policy.save()
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.code == "user_daily_limit"
    coach.policy.user_daily_limit = 3
    coach.policy.global_daily_limit = 1
    coach.policy.save()
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.code == "global_daily_limit"


def test_success_reconciles_usage_and_hides_hints(coach):
    review, _ = request(coach)
    result = process_next_review(provider)
    review.refresh_from_db()
    assert result["state"] == "completed"
    assert review.accounted_micros == 3500
    assert review.provider_request_id == "req_test"
    hidden = review_payload(review)
    assert "hints" not in hidden["feedback"]["findings"][0]
    assert hidden["feedback"]["findings"][0]["anchor"] == {"line": 2, "end_line": 2}
    from .evaluation_execution import reveal_hint

    finding = hidden["feedback"]["findings"][0]
    assert "hints" not in review_payload(review, 2)["feedback"]["findings"][0]
    reveal_hint(coach.user, review, finding["id"], 1)
    assert review_payload(review)["feedback"]["findings"][0]["hints"] == ["Use the sign of a product."]
    reveal_hint(coach.user, review, finding["id"], 2)
    assert len(review_payload(review)["feedback"]["findings"][0]["hints"]) == 2
    assert process_next_review(provider)["state"] == "idle"
    coach.solution.refresh_from_db()
    assert coach.solution.status == ProblemSolution.Status.DRAFT


@pytest.mark.parametrize(("definitive", "expected"), [(True, "failed"), (False, "outcome_unknown")])
def test_provider_failure_never_redispatches(coach, definitive, expected):
    review, _ = request(coach)
    calls = []

    def fails(_review, _images):
        calls.append(True)
        msg = "test_failure"
        raise ProviderError(msg, definitive=definitive)

    assert process_next_review(fails)["state"] == expected
    assert process_next_review(fails)["state"] == "idle"
    review.refresh_from_db()
    assert review.accounted_micros == review.reserved_micros
    assert len(calls) == 1


def test_invalid_output_fails_without_rendering_and_contradictory_reports_rejected(coach):
    request(coach)
    assert (
        process_next_review(lambda _review, _images: ProviderResult(feedback={"summary": "bad"}))["state"] == "failed"
    )
    bad = report()
    bad["assessment"] = "no_issues_found"
    with pytest.raises(ReviewError):
        validate_feedback(bad, coach.revision.body_source)
    bad["assessment"] = "gap_found"
    bad["findings"][0]["quote"] = "Invented quotation"
    assert validate_feedback(bad, coach.revision.body_source)["findings"][0]["anchor"] is None


@pytest.mark.parametrize("value", [None, [], "text", {"assessment": []}])
def test_any_malformed_json_report_is_a_validation_failure(value):
    with pytest.raises(ReviewError):
        validate_feedback(value, "source")


def test_known_usage_and_provider_ids_survive_invalid_feedback(coach):
    review, _ = request(coach)
    process_next_review(
        lambda _review, _images: ProviderResult(
            feedback={},
            response_id="resp_bad",
            usage={"input_tokens": 100, "output_tokens": 50},
        ),
    )
    review.refresh_from_db()
    assert review.status == "failed"
    assert review.provider_response_id == "resp_bad"
    assert review.accounted_micros == 3500


def test_underestimated_reservation_disables_next_dispatch(coach):
    request(coach)
    process_next_review(
        lambda _review, _images: ProviderResult(
            feedback=report(),
            usage={"input_tokens": 100_000_000, "output_tokens": 50},
        ),
    )
    coach.policy.refresh_from_db()
    assert not coach.policy.enabled


def test_deleted_review_is_not_recreated_after_provider_returns(coach):
    review, _ = request(coach)

    def delete_then_return(_review, images):
        SolutionReview.objects.filter(pk=review.pk).delete()
        return provider(_review, images)

    assert process_next_review(delete_then_return)["state"] == "discarded"
    assert not SolutionReview.objects.exists()


def test_ambiguous_quotes_do_not_jump_to_wrong_passage():
    value = report()
    value["findings"][0]["quote"] = "same"
    assert validate_feedback(value, "same\nsame")["findings"][0]["anchor"] is None
    value["findings"][0]["context_before"] = "\n"
    assert validate_feedback(value, "same\nsame")["findings"][0]["anchor"]["line"] == 2


def test_expired_queued_and_interrupted_running_jobs_are_not_dispatched(coach):
    review, _ = request(coach)
    SolutionReview.objects.filter(pk=review.pk).update(created_at=timezone.now() - timedelta(minutes=16))
    assert process_next_review(provider)["state"] == "idle"
    review.refresh_from_db()
    assert review.status == "expired"
    assert review.accounted_micros == 0
    next_review, _ = request(coach)
    SolutionReview.objects.filter(pk=next_review.pk).update(
        status="running",
        dispatched_at=timezone.now() - timedelta(seconds=361),
    )
    assert process_next_review(provider)["state"] == "idle"
    next_review.refresh_from_db()
    assert next_review.status == "outcome_unknown"
    assert next_review.accounted_micros == next_review.reserved_micros


def test_active_worker_lease_prevents_dispatch(coach):
    request(coach)
    coach.policy.lease_token = uuid.uuid4()
    coach.policy.lease_until = timezone.now() + timedelta(seconds=60)
    coach.policy.save()
    assert process_next_review(provider)["state"] == "idle"
    assert SolutionReview.objects.get().status == "queued"


def test_statement_and_proof_changes_mark_report_stale(coach):
    review, _ = request(coach)
    assert not review_payload(review)["stale"]
    coach.statement.statement_latex = "A changed problem."
    coach.statement.save()
    assert review_payload(review)["stale"]
    assert review_payload(review)["reviewed_source"] == coach.revision.body_source
    coach.statement.delete()
    assert review_payload(review)["stale"]


def test_missing_statement_requires_confirmed_input(coach):
    coach.statement.delete()
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.code == "statement_required"
    review, _ = request(coach, statement_text="Prove $x^2>0$ when $x>0$.", statement_confirmed=True)
    assert review.input_snapshot["statement_id"] is None


def test_blank_canonical_statement_accepts_confirmed_manual_context(coach):
    coach.statement.statement_latex = "   "
    coach.statement.save()
    review, _ = request(coach, statement_text="Prove $x^2>0$ when $x>0$.", statement_confirmed=True)
    assert review.input_snapshot["statement_id"] is None
    assert not review_payload(review)["stale"]


def test_diagram_source_limitation_prevents_false_clearance(coach):
    coach.statement.statement_latex += r"\begin{asy}draw((0,0)--(1,1));\end{asy}"
    coach.statement.save()
    request(coach)
    value = report()
    value["assessment"] = "no_issues_found"
    value["findings"] = []
    process_next_review(lambda _review, _images: ProviderResult(feedback=value))
    review = SolutionReview.objects.get()
    assert review.feedback["assessment"] == "unable_to_assess"
    assert "source text" in review.feedback["limitations"][-1]


def _image(coach):
    data = BytesIO()
    Image.new("RGB", (10, 10), "white").save(data, format="PNG")
    image = SolutionBodyImage(solution=coach.solution, uploaded_by=coach.user)
    image.file.save("test.png", ContentFile(data.getvalue()), save=True)
    return image


def _revision_with_image(coach, path):
    source = rf"Proof. \includegraphics{{{path}}}"
    revision = SolutionRevision.objects.create(
        solution=coach.solution,
        sequence=2,
        body_source=source,
        source_digest=hashlib.sha256(source.encode()).hexdigest(),
    )
    coach.solution.current_revision = revision
    coach.solution.save()
    coach.revision = revision


def test_images_are_owned_frozen_and_normalized(coach, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    image = _image(coach)
    _revision_with_image(coach, image.file.name)
    review, _ = request(coach)
    assert len(review.input_snapshot["images"]) == 1
    assert review.reserved_micros == 22_200_000
    inputs = []

    def with_image(_review, images):
        inputs.extend(images)
        return provider(_review, images)

    assert process_next_review(with_image)["state"] == "completed"
    assert Image.open(BytesIO(inputs[0])).format == "PNG"


def test_unowned_external_and_changed_images_never_reach_provider(coach, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    image = _image(coach)
    _revision_with_image(coach, image.file.name)
    request(coach)
    image.file.delete(save=False)
    called = []
    assert process_next_review(lambda *_args: called.append(True))["state"] == "failed"
    assert not called
    with pytest.raises(ReviewError):
        request(coach)


@pytest.mark.parametrize("path", ["https://example.invalid/image.png", "solution_body_images/" + "a" * 32 + ".png"])
def test_unowned_image_paths_are_rejected_without_fetching(coach, path):
    _revision_with_image(coach, path)
    with pytest.raises(ReviewError) as caught:
        request(coach)
    assert caught.value.code == "unowned_image"


def test_create_status_endpoints_are_owner_only_and_filter_hints(coach, client):
    create = reverse("solutions:solution_review_create", args=[coach.problem.problem_uuid])
    assert client.post(create, {}, content_type="application/json").status_code == 401
    client.force_login(coach.user)
    response = client.post(
        create,
        json.dumps(
            {
                "revision_id": str(coach.revision.pk),
                "idempotency_key": str(uuid.uuid4()),
                "acknowledged": True,
            },
        ),
        content_type="application/json",
    )
    assert response.status_code == 202
    process_next_review(provider)
    status_url = response.json()["status_url"]
    payload = client.get(status_url).json()
    assert "hints" not in payload["feedback"]["findings"][0]
    assert "hints" not in client.get(status_url + "?hint_level=2").json()["feedback"]["findings"][0]
    reveal_url = payload["feedback"]["findings"][0]["reveal_url"]
    assert client.post(reveal_url, {"level": 1}, content_type="application/json").status_code == 200
    assert client.get(status_url).json()["feedback"]["findings"][0]["hints"]
    client.force_login(UserFactory())
    assert client.get(status_url).status_code == 404
    assert client.get(status_url)["Cache-Control"].find("no-store") >= 0


def test_provider_boundary_has_no_tools_storage_or_retries(coach, monkeypatch, settings):
    from inspinia.solutions.review_provider import generate_review

    settings.OPENAI_API_KEY = "local-fake-key"
    review, _ = request(coach)
    captured = {}
    response = SimpleNamespace(
        status="completed",
        id="resp",
        _request_id="req",
        model="gpt-6-astra",
        output=[],
        output_text=json.dumps(report()),
        usage=None,
    )

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.responses = self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def create(self, **kwargs):
            captured["request"] = kwargs
            return response

    class FakeAPIError(Exception):
        pass

    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(
            OpenAI=Client,
            APITimeoutError=FakeAPIError,
            APIConnectionError=FakeAPIError,
            APIStatusError=FakeAPIError,
        ),
    )
    result = generate_review(review, [], fake_client_factory=Client)
    assert result.response_id == "resp"
    assert result.usage["model"] == "gpt-6-astra"
    assert captured["client"]["max_retries"] == 0
    assert captured["client"]["timeout"] == 300
    assert captured["request"]["store"] is False
    assert captured["request"]["max_output_tokens"] == 16_000
    assert "tools" not in captured["request"]


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_requests_reserve_once(coach):
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock behavior requires PostgreSQL")
    barrier = Barrier(2)

    def run():
        close_old_connections()
        barrier.wait(timeout=5)
        try:
            return request(coach)[1]
        except ReviewError as error:
            return error.code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: run(), range(2)))
    assert results.count(True) == 1
    assert results.count("review_in_progress") == 1
    assert SolutionReview.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_postgres_competing_workers_dispatch_once(coach):
    if connection.vendor != "postgresql":
        pytest.skip("Worker claim locks require PostgreSQL")
    request(coach)
    entered, release = Event(), Event()
    calls = []

    def blocked_provider(review, images):
        calls.append(review.pk)
        entered.set()
        assert release.wait(timeout=5)
        return provider(review, images)

    def work():
        close_old_connections()
        try:
            return process_next_review(blocked_provider)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(work)
        assert entered.wait(timeout=5)
        try:
            second = executor.submit(work).result(timeout=5)
        finally:
            release.set()
        assert first.result(timeout=5)["state"] == "completed"
    assert second["state"] == "idle"
    assert len(calls) == 1


def test_review_route_and_editor_history_are_scoped_to_each_solution(client, coach):
    alternate = ProblemSolution.objects.create(
        problem=coach.problem, author=coach.user, additional_draft_key=uuid.uuid4(), title="Coordinate proof",
    )
    revision = SolutionRevision.objects.create(
        solution=alternate, sequence=1, body_source=coach.revision.body_source,
        source_digest=coach.revision.source_digest,
    )
    alternate.current_revision = revision
    alternate.save(update_fields=["current_revision"])
    client.force_login(coach.user)
    problem_uuid = coach.problem.problem_uuid
    args = [problem_uuid, alternate.pk]
    create = reverse("solutions:solution_review_create", args=args)
    data = {"revision_id": str(coach.revision.pk), "idempotency_key": str(uuid.uuid4()), "acknowledged": True}
    assert client.post(create, data, content_type="application/json").status_code == 404
    response = client.post(create, {**data, "revision_id": str(revision.pk)}, content_type="application/json")
    assert response.status_code == 202, response.json()
    review = SolutionReview.objects.get()
    assert review.revision.solution_id == alternate.pk
    assert client.get(response.json()["status_url"]).status_code == 200
    assert client.get(reverse(
        "solutions:solution_review_status", args=[problem_uuid, coach.solution.pk, review.pk],
    )).status_code == 404
    original_editor = client.get(reverse("solutions:problem_solution_edit", args=[problem_uuid]))
    alternate_editor = client.get(reverse("solutions:problem_solution_edit", args=args))
    assert original_editor.context["solution_review_config"]["latestStatusUrl"] == ""
    assert alternate_editor.context["solution_review_config"]["latestStatusUrl"] == response.json()["status_url"]
