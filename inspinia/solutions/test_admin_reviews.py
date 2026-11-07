"""Admin review drafts are version-bound, private and safe to publish once."""

import json
import uuid
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from django.core import mail
from django.db import IntegrityError
from django.db import transaction
from django.test import Client
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions import admin_review_worker as worker
from inspinia.solutions import forum
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_review_models import AdminSolutionReviewSettings
from inspinia.solutions.admin_reviews import read_credential
from inspinia.solutions.models import ProblemSolution
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
KEY = "sk-test-synthetic-no-api-access"
FEEDBACK = "Check the equality case. <script>never_execute()</script>"
PROMPT = "Focus on the equality cases."
MODELS = ["gpt-6.1-sol", "gpt-6-astra"]
SETTINGS_URL = "solutions:admin_ai_review_settings"


@pytest.fixture
def proof(settings):
    settings.ADMIN_SOLUTION_REVIEW_ENABLED = True
    settings.ADMIN_SOLUTION_REVIEW_ENCRYPTION_KEY = Fernet.generate_key().decode("ascii")
    author = UserFactory()
    problem = ProblemSolveRecord.objects.create(
        contest="REVIEW", year=2026, problem="P3", topic="ALG", contest_year_problem="REVIEW 2026 P3",
    )
    statement = ContestProblemStatement.objects.create(
        linked_problem=problem, contest_name="REVIEW", contest_year=2026, problem_code="P3",
        problem_number=3, statement_latex="Prove the inequality, including the equality case.",
    )
    solution = ProblemSolution.objects.create(
        problem=problem, author=author, status=ProblemSolution.Status.PUBLISHED, title="A submitted proof",
    )
    block = solution.blocks.create(position=1, body_source="By completing the square, the expression is nonnegative.")
    return SimpleNamespace(
        author=author, admin=UserFactory(role="admin"), trainer=UserFactory(role="trainer"),
        member=UserFactory(), solution=solution, problem=problem, statement=statement, block=block,
        url=reverse("solutions:solution_detail", args=[solution.pk]),
        queue_url=reverse("solutions:admin_ai_review_generate", args=[solution.pk]),
    )


def settings_post(client, **values):
    return client.post(reverse(SETTINGS_URL), {
        "models_enabled": MODELS, "effort": "high", "output_limit": 8000, "daily_limit": 8,
        "prompt": PROMPT, "api_key": KEY, **values,
    })


@pytest.fixture
def config(client, proof):
    client.force_login(proof.admin)
    assert settings_post(client).status_code == HTTPStatus.FOUND
    return AdminSolutionReviewSettings.objects.get()


def queue(client, proof, config, **values):
    return client.post(proof.queue_url, {
        "target_key": forum.current_target_data(proof.solution)["key"], "problem_label": "REVIEW 2026 P3",
        "settings_version": str(config.version), "models": MODELS, "batch_id": str(uuid.uuid4()), **values,
    })


def publisher(proof, review):
    return reverse("solutions:admin_ai_review_publish", args=[proof.solution.pk, review.pk])


def response(score=6, feedback=FEEDBACK):
    return SimpleNamespace(status="completed", id="resp_fixture", output_text=json.dumps({
        "score": score, "feedback": feedback,
    }))


def test_admin_key_is_write_only_and_rotation_invalidates_queued_work(client, proof, config, monkeypatch):
    assert KEY.encode() not in bytes(config.encrypted_key)
    assert read_credential(config) == KEY
    page = client.get(reverse(SETTINGS_URL))
    assert page.status_code == HTTPStatus.OK
    assert "no-store" in page["Cache-Control"]
    assert b"Key saved" in page.content
    assert KEY.encode() not in page.content
    assert queue(client, proof, config).status_code == HTTPStatus.FOUND
    invalid = settings_post(client, version=config.version, clear_key="on")
    assert invalid.status_code == HTTPStatus.BAD_REQUEST
    assert KEY.encode() not in invalid.content

    assert settings_post(client, version=config.version, api_key="sk-fake-replacement").status_code == HTTPStatus.FOUND
    provider = Mock()
    monkeypatch.setattr(worker, "request_review", provider)
    assert worker.process_next()["status"] == AdminSolutionReview.Status.FAILED
    provider.assert_not_called()
    config.refresh_from_db()
    assert settings_post(client, version=config.version, api_key="", clear_key="on").status_code == HTTPStatus.FOUND
    config.refresh_from_db()
    assert not config.encrypted_key


def test_feedback_style_round_trips_and_is_snapshotted_for_new_reviews(client, proof, config):
    url = reverse(SETTINGS_URL)
    page = client.get(url)
    assert page.context["form"]["feedback_style"].value() == ""
    assert page.context["form"]["prompt"].value() == PROMPT
    assert b"Step-by-step proof audit" in page.content

    assert settings_post(
        client, version=config.version, api_key="", feedback_style="proof-audit",
    ).status_code == HTTPStatus.FOUND
    config.refresh_from_db()
    page = client.get(url)
    assert page.context["form"]["feedback_style"].value() == "proof-audit"
    assert page.context["form"]["prompt"].value() == PROMPT

    assert queue(client, proof, config, models=[MODELS[0]]).status_code == HTTPStatus.FOUND
    assert settings_post(
        client, version=config.version, api_key="", feedback_style="socratic-hints",
    ).status_code == HTTPStatus.FOUND
    config.refresh_from_db()
    assert "ask targeted questions" in config.prompt
    assert "Walk through the key steps" not in config.prompt
    assert config.prompt.endswith(PROMPT)

    review = AdminSolutionReview.objects.get()
    assert "out of a total of 7" in review.instructions
    assert "Walk through the key steps" in review.instructions
    assert "ask targeted questions" not in review.instructions
    assert PROMPT in review.instructions

    assert settings_post(
        client, version=config.version, api_key="", feedback_style="",
    ).status_code == HTTPStatus.FOUND
    config.refresh_from_db()
    assert config.prompt == PROMPT


def test_admin_can_compare_drafts_then_publish_once_to_solver(client, proof, config, monkeypatch):
    client.force_login(proof.admin)
    assert b"Generate AI review" in client.get(proof.url).content
    batch = str(uuid.uuid4())
    assert queue(client, proof, config, batch_id=batch).status_code == HTTPStatus.FOUND
    assert queue(client, proof, config, batch_id=batch).status_code == HTTPStatus.FOUND
    assert AdminSolutionReview.objects.count() == len(MODELS)

    provider = Mock(side_effect=[response(), response(0, "No justified progress.")])
    monkeypatch.setattr(worker, "request_review", provider)
    assert worker.process_next()["status"] == "completed"
    assert worker.process_next()["status"] == "completed"
    review = AdminSolutionReview.objects.get(score=6)
    assert review.response_text
    assert review.provider_response_id == "resp_fixture"
    assert review.effort == "high"
    assert review.output_limit == config.output_limit
    assert "out of a total of 7" in review.instructions
    assert PROMPT in review.instructions
    assert b"6 / 7" in client.get(proof.url).content
    assert b"0 / 7" in client.get(proof.url).content
    assert not getattr(mail, "outbox", [])

    client.force_login(proof.author)
    assert b"Check the equality case." not in client.get(proof.url).content
    assert client.post(publisher(proof, review)).status_code == HTTPStatus.FORBIDDEN

    client.force_login(proof.admin)
    assert client.post(publisher(proof, review)).status_code == HTTPStatus.FOUND
    assert client.post(publisher(proof, review)).status_code == HTTPStatus.FOUND
    assert client.post(publisher(proof, AdminSolutionReview.objects.get(score=0))).status_code == HTTPStatus.FOUND
    assert AdminSolutionReview.objects.filter(published_at__isnull=False).count() == 1
    review.refresh_from_db()
    assert review.notification == AdminSolutionReview.Notification.PENDING
    assert worker.process_next()["notification"] == AdminSolutionReview.Notification.SENT
    assert worker.process_next()["status"] == "idle"
    notice, = mail.outbox
    assert notice.to == [proof.author.email]
    assert f"{proof.url}?ai_review={review.pk}#ai-review-{review.pk}" in notice.body
    assert FEEDBACK not in notice.body
    assert "Read your review" in notice.alternatives[0][0]
    assert notice.attachments[0]["Content-ID"] == "<asterproof-logo>"

    client.force_login(proof.author)
    author_page = client.get(proof.url)
    assert b"6 / 7" in author_page.content
    assert b"&lt;script&gt;" in author_page.content
    assert b"No justified progress." not in author_page.content
    assert b"Publish and notify solver" not in author_page.content
    for user in (proof.trainer, proof.member):
        client.force_login(user)
        assert b"Check the equality case." not in client.get(proof.url, {"ai_review": review.pk}).content
        assert client.get(reverse(SETTINGS_URL)).status_code == HTTPStatus.FORBIDDEN
        assert queue(client, proof, config).status_code == HTTPStatus.FORBIDDEN


def test_missing_solution_and_statement_block_generation(client, proof, config):
    body = proof.block.body_source
    proof.block.body_source = "  % only a comment"
    proof.block.save()
    page = client.get(proof.url)
    assert b"Save a solution with proof content" in page.content
    assert b"Generate AI review" not in page.content
    assert queue(client, proof, config).status_code == HTTPStatus.FOUND
    assert not AdminSolutionReview.objects.exists()

    proof.block.body_source = body
    proof.block.save()
    proof.statement.is_active = False
    proof.statement.save()
    page = client.get(proof.url)
    assert b"Link an active problem statement" in page.content
    assert queue(client, proof, config).status_code == HTTPStatus.FOUND
    assert not AdminSolutionReview.objects.exists()


def test_changed_statement_cancels_queued_work_and_prevents_publication(client, proof, config, monkeypatch):
    queue(client, proof, config)
    provider = Mock(return_value=response())
    monkeypatch.setattr(worker, "request_review", provider)
    worker.process_next()
    draft = AdminSolutionReview.objects.get(status="completed")
    proof.statement.statement_latex = "Updated statement."
    proof.statement.save()
    assert worker.process_next()["status"] == "failed"
    assert provider.call_count == 1
    assert client.post(publisher(proof, draft)).status_code == HTTPStatus.FOUND
    draft.refresh_from_db()
    assert draft.published_at is None


def test_provider_uses_actual_sdk_with_a_mock_transport(client, proof, config, monkeypatch):
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx2")
    queue(client, proof, config, models=MODELS[:1])
    seen = []
    sdk = openai.OpenAI

    review = AdminSolutionReview.objects.get()
    progress = reverse("solutions:admin_ai_review_progress", args=[proof.solution.pk, review.batch_id])

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            delta = {"type": "response.output_text.delta", "delta": '{"score":6,"feedback":"First draft',
                     "item_id": "msg_fixture", "output_index": 0, "content_index": 0, "sequence_number": 1}
            yield f"data: {json.dumps(delta)}\n\n".encode()
            live = client.get(progress)
            assert live.json()["reviews"] == [{
                "id": str(review.pk), "active": True, "status": "Reviewing", "feedback": "First draft",
            }]
            assert "no-store" in live["Cache-Control"]
            client.force_login(proof.author)
            assert client.get(progress).status_code == HTTPStatus.FORBIDDEN
            assert b"First draft" not in client.get(proof.url).content
            client.force_login(proof.admin)
            complete = {
                "type": "response.completed", "sequence_number": 2,
                "response": {
                    "id": "resp_fixture", "object": "response", "created_at": 1,
                    "status": "completed", "model": MODELS[0],
                    "output": [{"id": "msg_fixture", "type": "message", "role": "assistant", "status": "completed",
                                "content": [{
                                    "type": "output_text", "text": response().output_text, "annotations": [],
                                }]}],
                },
            }
            yield f"data: {json.dumps(complete)}\n\n".encode()

    def fake_api(request):
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())

    def mock_client(**options):
        return sdk(http_client=httpx.Client(transport=httpx.MockTransport(fake_api)), **options)

    monkeypatch.setenv("OPENAI_BASE_URL", "https://ignore-me.example/v1")
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "Authorization: Bearer ignore-me")
    monkeypatch.setattr(openai, "OpenAI", mock_client)
    assert worker.process_next()["status"] == "completed"
    request, = seen
    assert str(request.url) == "https://api.openai.com/v1/responses"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    payload = json.loads(request.content)
    assert payload["store"] is False
    assert payload["stream"] is True
    assert payload["reasoning"] == {"effort": "high"}
    assert payload["max_output_tokens"] == config.output_limit
    assert "out of a total of 7" in payload["input"][0]["content"]
    assert PROMPT in payload["input"][0]["content"]
    assert json.loads(payload["input"][1]["content"]) == {
        "problem_label": proof.problem.contest_year_problem,
        "problem_statement": proof.statement.statement_latex,
        "problem_solution": proof.block.body_source,
    }
    assert payload["text"]["format"]["schema"]["properties"]["score"]["enum"] == list(range(8))


def test_invalid_score_is_not_publishable_and_database_enforces_range(client, proof, config, monkeypatch):
    queue(client, proof, config, models=MODELS[:1])
    monkeypatch.setattr(worker, "request_review", Mock(return_value=response(8)))
    assert worker.process_next()["status"] == "failed"
    review = AdminSolutionReview.objects.get()
    assert review.score is None
    assert review.response_text
    assert client.post(publisher(proof, review)).status_code == HTTPStatus.FOUND
    assert not AdminSolutionReview.objects.filter(published_at__isnull=False).exists()
    with pytest.raises(IntegrityError), transaction.atomic():
        AdminSolutionReview.objects.filter(pk=review.pk).update(score=8, status="completed")


def test_admin_posts_require_csrf_and_debug_does_not_grant_access(client, proof, config, settings):
    client = Client(enforce_csrf_checks=True)
    client.force_login(proof.admin)
    assert queue(client, proof, config).status_code == HTTPStatus.FORBIDDEN
    assert settings_post(client).status_code == HTTPStatus.FORBIDDEN
    settings.DEBUG = True
    client.force_login(proof.member)
    assert client.get(reverse(SETTINGS_URL)).status_code == HTTPStatus.FORBIDDEN


def test_interrupted_stream_clears_preview_and_is_never_retried(client, proof, config, monkeypatch):
    queue(client, proof, config, models=MODELS[:1])

    def interrupted(_review, _key, *, on_preview):
        on_preview("Unfinished feedback")
        message = "The connection closed before the final response."
        raise worker.ReviewProviderError(message, uncertain=True)

    provider = Mock(side_effect=interrupted)
    monkeypatch.setattr(worker, "request_review", provider)
    assert worker.process_next()["status"] == "unknown"
    assert worker.process_next()["status"] == "idle"
    provider.assert_called_once()
    review = AdminSolutionReview.objects.get()
    assert review.feedback == ""
    assert review.score is None
    client.post(publisher(proof, review))
    review.refresh_from_db()
    assert review.published_at is None
