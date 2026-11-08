"""Admin review drafts are version-bound, private and safe to publish once."""

import base64
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from http import HTTPStatus
from io import BytesIO
from queue import Queue
from threading import Barrier
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from django.core import mail
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.db import close_old_connections
from django.db import connection
from django.db import connections
from django.db import transaction
from django.http import QueryDict
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.study_help_access import statement_revision
from inspinia.pages.study_help_models import StudyHelpPrompt
from inspinia.pages.study_help_models import StudyHelpRequest
from inspinia.pages.study_help_models import StudyHelpSpend
from inspinia.solutions import admin_review_worker as worker
from inspinia.solutions import admin_reviews
from inspinia.solutions import forum
from inspinia.solutions.admin_review_models import AdminSolutionReview
from inspinia.solutions.admin_review_models import AdminSolutionReviewSettings
from inspinia.solutions.admin_review_models import SelfSolutionReviewUsage
from inspinia.solutions.admin_reviews import read_credential
from inspinia.solutions.document_source import source_digest
from inspinia.solutions.evaluation_models import AssistancePolicy
from inspinia.solutions.management.commands import process_admin_solution_reviews as review_command
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionBodyImage
from inspinia.solutions.models import SolutionRevision
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
KEY = "sk-test-synthetic-no-api-access"
FEEDBACK = "Check the equality case. <script>never_execute()</script>"
PROMPT = "Focus on the equality cases."
MODELS = ["gpt-6.1-sol", "gpt-6-astra"]
SETTINGS_URL = "solutions:admin_ai_review_settings"
QUEUE_URL = "solutions:admin_ai_review_queue"


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


@pytest.fixture
def second_solution(proof):
    problem = ProblemSolveRecord.objects.create(
        contest="REVIEW", year=2026, problem="P4", topic="ALG", contest_year_problem="REVIEW 2026 P4",
    )
    ContestProblemStatement.objects.create(
        linked_problem=problem, contest_name="REVIEW", contest_year=2026, problem_code="P4",
        problem_number=4, statement_latex="Prove the second inequality.",
    )
    solution = ProblemSolution.objects.create(
        problem=problem, author=proof.author, status=ProblemSolution.Status.SUBMITTED,
    )
    solution.blocks.create(position=1, body_source="The difference is a square.")
    return solution


def settings_post(client, **values):
    return client.post(reverse(SETTINGS_URL), {
        "models_enabled": MODELS, "effort": "high", "output_limit": 8000,
        "prompt": PROMPT, "api_key": KEY, **values,
    })


@pytest.fixture
def config(client, proof):
    client.force_login(proof.admin)
    assert settings_post(client).status_code == HTTPStatus.FOUND
    return AdminSolutionReviewSettings.objects.get()


@pytest.fixture
def review_backlog(client, proof, config):
    queue(client, proof, config, models=MODELS[:1])
    first = AdminSolutionReview.objects.get()
    AdminSolutionReview.objects.bulk_create([
        AdminSolutionReview(
            target=first.target, solver=proof.author, requested_by=proof.admin, batch_id=uuid.uuid4(),
            key_version=config.key_version, problem_label=first.problem_label, model=first.model,
            effort=first.effort, output_limit=first.output_limit, instructions=first.instructions,
        )
        for _ in range(6)
    ])
    return list(AdminSolutionReview.objects.order_by("created_at", "pk"))


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


def assert_review_notice(notice, proof, review, other_score):
    assert notice.to == [proof.author.email]
    assert f"{proof.url}?ai_review={review.pk}#ai-review-{review.pk}" in notice.body
    html = notice.alternatives[0][0]
    for body in (notice.body, html):
        assert f"Your score: {review.score}/7" in body
        assert f"{other_score}/7" not in body
        assert "Check the equality case." not in body
        assert proof.block.body_source not in body
    assert "Read your review" in html
    assert notice.attachments[0]["Content-ID"] == "<asterproof-logo>"


def test_admin_key_is_write_only_and_rotation_invalidates_queued_work(client, proof, config, monkeypatch):
    assert KEY.encode() not in bytes(config.encrypted_key)
    assert read_credential(config) == KEY
    page = client.get(reverse(SETTINGS_URL))
    assert page.status_code == HTTPStatus.OK
    assert "no-store" in page["Cache-Control"]
    assert b"Key saved" in page.content
    assert b'name="daily_limit"' not in page.content
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


@pytest.mark.parametrize("scores", [(0, 6), (6, 0)])
def test_admin_can_compare_drafts_then_publish_once_to_solver(client, proof, config, monkeypatch, scores):
    client.force_login(proof.admin)
    assert b"Generate AI review" in client.get(proof.url).content
    batch = str(uuid.uuid4())
    assert queue(client, proof, config, batch_id=batch).status_code == HTTPStatus.FOUND
    assert queue(client, proof, config, batch_id=batch).status_code == HTTPStatus.FOUND
    assert AdminSolutionReview.objects.count() == len(MODELS)

    published_score, other_score = scores
    provider = Mock(side_effect=[response(published_score), response(other_score, "Unpublished feedback.")])
    monkeypatch.setattr(worker, "request_review", provider)
    assert worker.process_next()["status"] == "completed"
    assert worker.process_next()["status"] == "completed"
    review = AdminSolutionReview.objects.get(score=published_score)
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
    other_review = AdminSolutionReview.objects.get(score=other_score)
    assert client.post(publisher(proof, other_review)).status_code == HTTPStatus.FOUND
    assert AdminSolutionReview.objects.filter(published_at__isnull=False).count() == 1
    review.refresh_from_db()
    assert review.notification == AdminSolutionReview.Notification.PENDING
    assert worker.process_next()["notification"] == AdminSolutionReview.Notification.SENT
    assert worker.process_next()["status"] == "idle"
    notice, = mail.outbox
    assert_review_notice(notice, proof, review, other_score)

    client.force_login(proof.author)
    author_page = client.get(proof.url)
    assert f"{published_score} / 7".encode() in author_page.content
    assert b"&lt;script&gt;" in author_page.content
    assert b"Unpublished feedback." not in author_page.content
    assert b"Publish and notify solver" not in author_page.content
    for user in (proof.trainer, proof.member):
        client.force_login(user)
        assert b"Check the equality case." not in client.get(proof.url, {"ai_review": review.pk}).content
        assert client.get(reverse(SETTINGS_URL)).status_code == HTTPStatus.FORBIDDEN
        assert queue(client, proof, config).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures("self_review_enabled")
def test_admin_queue_lists_active_model_requests_and_refreshes_privately(client, proof, config, second_solution):
    queue(client, proof, config)
    waiting = list(AdminSolutionReview.objects.order_by("created_at", "pk"))
    client.force_login(proof.author)
    client.post(reverse("solutions:admin_ai_review_generate", args=[second_solution.pk]), {
        "target_key": forum.current_target_data(second_solution)["key"],
        "problem_label": admin_reviews.problem_label(second_solution),
        "settings_version": config.version, "models": MODELS[:1], "batch_id": uuid.uuid4(),
    })
    url = reverse(QUEUE_URL)
    assert client.get(url).status_code == HTTPStatus.FORBIDDEN
    assert client.get(url, {"fragment": "1"}).status_code == HTTPStatus.FORBIDDEN
    running = SelfSolutionReviewUsage.objects.get().review
    AdminSolutionReview.objects.filter(pk=running.pk).update(status="running", feedback=FEEDBACK)

    client.force_login(proof.admin)
    page = client.get(url)
    assert page.status_code == HTTPStatus.OK
    assert list(page.context["queue_page"]) == [running, *waiting]
    assert b"2 waiting" in page.content
    assert b"1 reviewing" in page.content
    assert b">Solver</td>" in page.content
    assert b">Admin</td>" in page.content
    assert f'{reverse("solutions:solution_detail", args=[second_solution.pk])}#ai-review'.encode() in page.content
    assert b"Check the equality case." not in page.content

    AdminSolutionReview.objects.filter(pk=running.pk).update(status="failed")
    fragment = client.get(url, {"fragment": "1"})
    assert "no-store" in fragment["Cache-Control"]
    assert list(fragment.context["queue_page"]) == waiting
    assert b"0 reviewing" in fragment.content


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


@pytest.mark.usefixtures("self_review_enabled")
def test_solver_sees_streamed_feedback_and_receives_completed_review_automatically(client, proof, config, monkeypatch):
    client.force_login(proof.author)
    page = client.get(proof.url)
    assert b"Generate AI review" in page.content
    assert b"50</span> AI credits left" in page.content
    assert queue(client, proof, config).status_code == HTTPStatus.FOUND
    assert not AdminSolutionReview.objects.exists()  # One model per author request.

    batch = uuid.uuid4()
    assert queue(client, proof, config, batch_id=batch, models=MODELS[:1]).status_code == HTTPStatus.FOUND
    assert queue(client, proof, config, batch_id=batch, models=MODELS[:1]).status_code == HTTPStatus.FOUND
    review = AdminSolutionReview.objects.get()
    progress_url = reverse("solutions:admin_ai_review_progress", args=[proof.solution.pk, batch])
    queued_page = client.get(proof.url)
    assert b"Waiting in queue" in queued_page.content
    assert client.get(progress_url).json()["reviews"][0]["status"] == "Queued"

    client.force_login(proof.member)
    assert b"Generate AI review" not in client.get(proof.url).content
    assert client.get(progress_url).status_code == HTTPStatus.FORBIDDEN
    assert queue(client, proof, config, models=MODELS[:1]).status_code == HTTPStatus.NOT_FOUND
    client.force_login(proof.author)
    assert client.post(publisher(proof, review)).status_code == HTTPStatus.FORBIDDEN

    def provider(review, key, *, on_preview):
        on_preview(FEEDBACK)
        progress = client.get(progress_url)
        assert progress.json()["reviews"] == [{
            "id": str(review.pk), "status": "Reviewing", "active": True, "feedback": FEEDBACK,
        }]
        assert "no-store" in progress["Cache-Control"]
        live_page = client.get(proof.url).content
        assert b"data-ai-review-live" in live_page
        assert b"Check the equality case. &lt;script&gt;" in live_page
        assert b"6 / 7" not in live_page
        client.force_login(proof.member)
        assert client.get(progress_url).status_code == HTTPStatus.FORBIDDEN
        assert b"Check the equality case." not in client.get(proof.url).content
        client.force_login(proof.author)
        return response()

    monkeypatch.setattr(worker, "request_review", provider)
    assert worker.process_next()["status"] == "completed"
    assert SelfSolutionReviewUsage.objects.get().succeeded
    review.refresh_from_db()
    assert review.published_at is not None
    assert review.published_by is None
    assert review.notification == AdminSolutionReview.Notification.PENDING
    assert not client.get(progress_url).json()["reviews"][0]["active"]
    page = client.get(proof.url)
    assert b"49</span> AI credits left" in page.content
    assert b"6 / 7" in page.content
    assert b"Check the equality case." in page.content
    assert not getattr(mail, "outbox", [])

    assert worker.process_next()["notification"] == "sent"
    assert worker.process_next()["status"] == "idle"
    assert [notice.to for notice in mail.outbox] == [[proof.author.email]]


@pytest.mark.usefixtures("self_review_enabled")
def test_autoshare_does_not_replace_an_admin_review_published_during_generation(client, proof, config, monkeypatch):
    queue(client, proof, config, models=MODELS[:1])
    monkeypatch.setattr(worker, "request_review", Mock(return_value=response(7, "Admin selected feedback.")))
    assert worker.process_next()["status"] == "completed"
    admin_review = AdminSolutionReview.objects.get()

    client.force_login(proof.author)
    queue(client, proof, config, models=MODELS[:1])

    def provider(*args, **kwargs):
        assert admin_reviews.publish(proof.admin, proof.solution.pk, admin_review.pk)
        return response()

    monkeypatch.setattr(worker, "request_review", provider)
    assert worker.process_next()["status"] == "completed"
    page = client.get(proof.url).content
    assert b"Admin selected feedback." in page
    assert b"Check the equality case." not in page
    assert worker.process_next()["notification"] == "sent"
    assert worker.process_next()["status"] == "idle"
    assert len(mail.outbox) == 1


@pytest.mark.usefixtures("self_review_enabled")
def test_ai_history_and_account_usage_are_admin_only(client, proof, config, monkeypatch):
    monkeypatch.setattr(worker, "request_review", Mock(return_value=response()))
    queue(client, proof, config, models=MODELS[:1])
    assert worker.process_next()["status"] == "completed"
    client.force_login(proof.author)
    queue(client, proof, config, models=MODELS[:1])
    assert worker.process_next()["status"] == "completed"
    StudyHelpRequest.objects.create(
        owner=proof.author, request_key=uuid.uuid4(), interaction_key=uuid.uuid4(),
        statement_uuid=proof.statement.statement_uuid, problem_uuid=proof.problem.problem_uuid,
        revision=statement_revision(proof.statement), action="hint", slot=1, state="ready",
        prompt=StudyHelpPrompt.objects.create(hint="Offer a direction.", solution="Write a proof."),
        body="Try a square. <script>never_execute()</script>", finished_at=timezone.now(),
        spend=StudyHelpSpend.objects.create(reserved_micros=0, input_price=0, output_price=0),
    )
    routes = [reverse(f"pages:{name}") for name in ("ai_hint_history", "ai_review_history", "ai_user_usage")]
    for url in routes:
        assert client.get(url).status_code == HTTPStatus.FORBIDDEN
    client.force_login(proof.trainer)
    for url in routes:
        assert client.get(url).status_code == HTTPStatus.FORBIDDEN
    client.force_login(proof.admin)
    hints, reviews, usage = [client.get(url, {"user": proof.author.pk}) for url in routes]
    for page in (hints, reviews, usage):
        assert page.status_code == HTTPStatus.OK
        assert "no-store" in page.headers["Cache-Control"]
        assert proof.author.email.encode() in page.content
    assert b"REVIEW 2026 P3" in hints.content
    assert b"REVIEW 2026 P3" in reviews.content
    assert b"&lt;script&gt;never_execute()" in hints.content
    assert b"Check the equality case." in reviews.content
    assert {bool(getattr(review, "self_request", None)) for review in reviews.context["page_obj"]} == {False, True}
    row = usage.context["rows"][0]
    assert (row["hint_count"], row["review_count"], row["admin_review_count"], row["remaining"]) == (1, 1, 1, 48)
    assert client.get(routes[0], {"q": "unknown problem"}).context["page_obj"].paginator.count == 0


@pytest.fixture
def self_review_enabled(settings):
    settings.SELF_SOLUTION_REVIEW_ENABLED = True


@pytest.mark.usefixtures("self_review_enabled")
@pytest.mark.parametrize(("requester", "models"), [("author", MODELS[:1]), ("admin", MODELS)])
def test_review_requests_ignore_the_legacy_site_cap(client, proof, config, requester, models):
    config.daily_limit = 1
    config.save(update_fields=["daily_limit"])
    SelfSolutionReviewUsage.objects.create(
        user=proof.member, problem_uuid=proof.problem.problem_uuid, batch_id=uuid.uuid4(),
    )

    client.force_login(getattr(proof, requester))
    assert queue(client, proof, config, models=models).status_code == HTTPStatus.FOUND
    assert set(AdminSolutionReview.objects.values_list("model", flat=True)) == set(models)


@pytest.mark.usefixtures("self_review_enabled")
def test_self_review_limits_count_successes_and_survive_proof_deletion(
    client, proof, config, second_solution, monkeypatch,
):
    client.force_login(proof.author)
    monkeypatch.setattr(worker, "request_review", Mock(side_effect=[response(8), response(), response()]))
    assert queue(client, proof, config, models=MODELS[:1]).status_code == HTTPStatus.FOUND
    assert worker.process_next()["status"] == "failed"
    assert not SelfSolutionReviewUsage.objects.get().succeeded
    assert queue(client, proof, config, models=MODELS[:1]).status_code == HTTPStatus.FOUND
    assert worker.process_next()["status"] == "completed"
    assert worker.process_next()["notification"] == "sent"
    proof.block.body_source += " The equality case follows directly."
    proof.block.save()
    assert queue(client, proof, config, models=MODELS[:1]).status_code == HTTPStatus.FOUND
    assert worker.process_next()["status"] == "completed"
    proof.block.body_source += " Equality forces the variables to coincide."
    proof.block.save()
    rejection = queue(client, proof, config, models=MODELS[:1])
    assert rejection.status_code == HTTPStatus.FOUND
    assert b"used both AI reviews for this problem" in client.get(rejection.url).content
    proof.solution.delete()
    assert admin_reviews.self_review_allowance(proof.author, proof.problem.problem_uuid) == {
        "active": False, "account_remaining": 48, "problem_remaining": 0,
    }

    assert not AdminSolutionReview.objects.exists()
    SelfSolutionReviewUsage.objects.bulk_create([
        SelfSolutionReviewUsage(user=proof.author, problem_uuid=uuid.uuid4(), batch_id=uuid.uuid4(), succeeded=True)
        for _ in range(48)
    ])
    data = {
        "settings_version": config.version, "target_key": forum.current_target_data(second_solution)["key"],
        "problem_label": admin_reviews.problem_label(second_solution), "batch_id": uuid.uuid4(), "models": MODELS[:1],
    }
    second_url = reverse("solutions:admin_ai_review_generate", args=[second_solution.pk])
    page = client.post(second_url, data, follow=True)
    assert b"used all 50 AI credits" in page.content
    assert not AdminSolutionReview.objects.exists()


def test_worker_rechecks_restrictions_before_sending_owner_proof(client, proof, config, settings, monkeypatch):
    settings.SELF_SOLUTION_REVIEW_ENABLED = True
    client.force_login(proof.author)
    queue(client, proof, config, models=MODELS[:1])
    now = timezone.now()
    AssistancePolicy.objects.create(
        actor_id_scope=proof.author.pk, problem_uuid=proof.problem.problem_uuid, mode="restricted_assessment",
        starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(minutes=10), appointed_by=proof.admin,
    )
    provider = Mock()
    monkeypatch.setattr(worker, "request_review", provider)
    assert worker.process_next()["status"] == "failed"
    provider.assert_not_called()
    assert b"AI review is restricted for this problem." in client.get(proof.url).content
    queue(client, proof, config, models=MODELS[:1])
    assert AdminSolutionReview.objects.count() == 1


@pytest.mark.usefixtures("self_review_enabled")
def test_changed_proof_during_generation_does_not_use_the_owners_allowance(client, proof, config, monkeypatch):
    client.force_login(proof.author)
    queue(client, proof, config, models=MODELS[:1])
    review = AdminSolutionReview.objects.get()
    progress_url = reverse("solutions:admin_ai_review_progress", args=[proof.solution.pk, review.batch_id])

    def provider(_review, _key, *, on_preview):
        on_preview(FEEDBACK)
        proof.block.body_source += " A revised step."
        proof.block.save()
        assert client.get(progress_url).status_code == HTTPStatus.FORBIDDEN
        assert b"Check the equality case." not in client.get(proof.url).content
        return response()

    monkeypatch.setattr(worker, "request_review", provider)
    assert worker.process_next()["status"] == "failed"
    review.refresh_from_db()
    assert review.score is None
    assert not review.feedback
    assert review.published_at is None
    assert not SelfSolutionReviewUsage.objects.get().succeeded


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_self_requests_reserve_only_one_account_slot(proof, config, second_solution, settings):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks.")
    settings.SELF_SOLUTION_REVIEW_ENABLED = True
    ready = Barrier(2, timeout=10)

    def request_review(solution):
        close_old_connections()
        try:
            data = QueryDict(mutable=True)
            data.update({
                "settings_version": str(config.version), "target_key": forum.current_target_data(solution)["key"],
                "problem_label": admin_reviews.problem_label(solution), "batch_id": str(uuid.uuid4()),
            })
            data.setlist("models", MODELS[:1])
            ready.wait()
            return admin_reviews.enqueue(proof.author, solution.pk, data)
        except forum.ForumError as error:
            return str(error)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(request_review, (proof.solution, second_solution)))
    assert results.count(True) == 1
    assert "You already have an AI request in progress." in results
    assert SelfSolutionReviewUsage.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_worker_refills_a_review_slot_while_other_reviews_and_email_are_running(review_backlog, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL worker connections.")

    first = review_backlog[0]
    notice = AdminSolutionReview.objects.create(
        target_id=first.target_id, solver_id=first.solver_id, requested_by_id=first.requested_by_id,
        batch_id=uuid.uuid4(), key_version=first.key_version, model=first.model, output_limit=first.output_limit,
        problem_label=first.problem_label, status=worker.Status.COMPLETED, score=6, published_at=timezone.now(),
        notification=worker.Notice.PENDING,
    )
    review_ids = [row.pk for row in review_backlog]
    slots = 5
    gates = {job_id: Event() for job_id in [*review_ids, notice.pk]}
    started = Queue()
    results = []
    provider = Mock(return_value=response())
    monkeypatch.setattr(worker, "request_review", provider)

    def execute(job_id, *, notification=False):
        try:
            started.put(job_id)
            assert gates[job_id].wait(10), "Test did not release the worker"
            return worker.process_claim(job_id, notification=notification)
        finally:
            connections.close_all()

    def drain(executor):
        try:
            worker.drain_queue(executor, execute, results.append)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=slots + 1) as jobs, ThreadPoolExecutor(max_workers=1) as supervisor:
        run = supervisor.submit(drain, jobs)
        try:
            assert {started.get(timeout=10) for _ in range(slots + 1)} == {*review_ids[:slots], notice.pk}
            assert worker.claim_review() is None  # A second worker also sees the cap.
            gates[review_ids[0]].set()
            assert started.get(timeout=10) == review_ids[slots]
            assert AdminSolutionReview.objects.filter(status=worker.Status.RUNNING).count() == slots
        finally:
            for gate in gates.values():
                gate.set()
        run.result(timeout=10)

    assert provider.call_count == len(review_ids)
    assert {result["review"] for result in results if result.get("status") == "completed"} == set(map(str, review_ids))
    assert {result["review"] for result in results if result.get("notification") == "sent"} == {str(notice.pk)}


@pytest.mark.django_db(transaction=True)
def test_concurrent_claims_cannot_exceed_five_or_pick_the_same_review(review_backlog):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL advisory locks.")
    slots = 5
    ready = Barrier(len(review_backlog), timeout=10)

    def claim():
        try:
            ready.wait()
            return worker.claim_review()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(review_backlog)) as workers:
        claims = [workers.submit(claim) for _ in review_backlog]
        results = [task.result(timeout=10) for task in claims]

    assert results.count(None) == len(review_backlog) - slots
    assert set(results) - {None} == {row.pk for row in review_backlog[:slots]}


@pytest.mark.django_db(transaction=True)
def test_job_deadline_marks_only_the_timed_out_review_unknown(review_backlog, monkeypatch):
    timed_out, next_review, *_ = review_backlog
    assert worker.claim_review() == timed_out.pk
    assert worker.claim_review() == next_review.pk
    monkeypatch.setattr(worker, "process_claim", Mock(side_effect=review_command.WorkerDeadline))

    assert review_command._process_claim(timed_out.pk)["status"] == worker.Status.UNKNOWN  # noqa: SLF001
    timed_out.refresh_from_db()
    next_review.refresh_from_db()
    assert timed_out.status == worker.Status.UNKNOWN
    assert next_review.status == worker.Status.RUNNING
    worker.expire_claims()
    assert worker.claim_review() == review_backlog[2].pk


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


@pytest.fixture
def image_storage(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture(params=["text", "admin-image", "author-image", "legacy"])
def provider_job(request, client, proof, config, image_storage):
    request_kind = request.param
    author_request = request_kind == "author-image"
    source = proof.block.body_source
    image_path = None
    if request_kind != "text":
        drawing = Image.new("RGBA", (20, 10))
        drawing.putpixel((3, 4), (255, 0, 0, 255))
        png = BytesIO()
        drawing.save(png, "PNG")
        image = SolutionBodyImage(solution=proof.solution, uploaded_by=proof.author)
        image.file.save("diagram.png", ContentFile(png.getvalue()), save=True)
        image_path = image.file.name
        commented = "solution_body_images/" + "f" * 32 + ".png"
        source = "\n".join((
            source,
            rf"\includegraphics[width=0.5\textwidth]{{{image_path}}} \includegraphics{{{image_path}}}",
            rf"% \includegraphics{{{commented}}}",
            r"\includegraphics{https://example.invalid/remote.png}",
        ))
        proof.block.body_source = source
        proof.block.save(update_fields=["body_source"])
    if author_request:
        request.getfixturevalue("self_review_enabled")
        proof.solution.current_revision = SolutionRevision.objects.create(
            solution=proof.solution, sequence=1, body_source=source, source_digest=source_digest(source),
        )
        proof.solution.save(update_fields=["current_revision"])
        client.force_login(proof.author)
    if request_kind != "text":
        page = client.get(proof.url)
        assert b"embedded proof images to OpenAI" in page.content
        assert b'name="include_solution_images" value="1"' in page.content
        stale_form = queue(client, proof, config, models=MODELS[:1])
        assert b"Reload the page to review what will be sent" in client.get(stale_form.url).content
        assert not AdminSolutionReview.objects.exists()
    queue(client, proof, config, models=MODELS[:1], include_solution_images="1")
    review = AdminSolutionReview.objects.get()
    if request_kind == "legacy":
        # Simulate a request queued when the review form disclosed text only.
        AdminSolutionReview.objects.filter(pk=review.pk).update(instructions=f"{admin_reviews.REVIEW_RULES}\n\n{PROMPT}")
        image_path = None
    return SimpleNamespace(review=review, source=source, image_path=image_path, author_request=author_request)


def test_provider_uses_actual_sdk_with_a_mock_transport(client, proof, config, monkeypatch, provider_job):
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx2")
    seen = []
    sdk = openai.OpenAI
    review = provider_job.review
    progress = reverse("solutions:admin_ai_review_progress", args=[proof.solution.pk, review.batch_id])

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            delta = {"type": "response.output_text.delta", "delta": '{"score":6,"feedback":"First draft',
                     "item_id": "msg_fixture", "output_index": 0, "content_index": 0, "sequence_number": 1}
            yield f"data: {json.dumps(delta)}\n\n".encode()
            client.force_login(proof.admin)
            live = client.get(progress)
            assert live.json()["reviews"] == [{
                "id": str(review.pk), "active": True, "status": "Reviewing", "feedback": "First draft",
            }]
            assert "no-store" in live["Cache-Control"]
            client.force_login(proof.author)
            owner_progress = client.get(progress)
            if provider_job.author_request:
                assert owner_progress.status_code == HTTPStatus.OK
                assert owner_progress.json()["reviews"][0]["feedback"] == "First draft"
                assert b"First draft" in client.get(proof.url).content
            else:
                assert owner_progress.status_code == HTTPStatus.FORBIDDEN
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
    review.refresh_from_db()
    assert bool(review.published_at) == provider_job.author_request
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
    expected_text = {
        "problem_label": proof.problem.contest_year_problem,
        "problem_statement": proof.statement.statement_latex,
        "problem_solution": provider_job.source,
    }
    content = payload["input"][1]["content"]
    if provider_job.image_path:
        text_part, image_part = content
        assert text_part["type"] == "input_text"
        assert json.loads(text_part["text"]) == {**expected_text, "solution_image_paths": [provider_job.image_path]}
        assert image_part["type"] == "input_image"
        mime, encoded = image_part["image_url"].split(",", 1)
        assert mime == "data:image/png;base64"
        with Image.open(BytesIO(base64.b64decode(encoded, validate=True))) as sent:
            assert sent.size == (20, 10)
            assert sent.getpixel((3, 4)) == (255, 0, 0)
            assert sent.getpixel((0, 0)) == (255, 255, 255)
    else:
        assert json.loads(content) == expected_text
    assert payload["text"]["format"]["schema"]["properties"]["score"]["enum"] == list(range(8))


@pytest.fixture(params=["missing", "cross-solution"])
def unavailable_image(request, proof, second_solution, image_storage):
    path = "solution_body_images/" + "a" * 32 + ".png"
    cross_solution = request.param == "cross-solution"
    image = SolutionBodyImage.objects.create(solution=second_solution if cross_solution else proof.solution, file=path)
    if cross_solution:
        stored = image_storage / path
        stored.parent.mkdir()
        Image.new("RGB", (10, 10), "red").save(stored, "PNG")
    proof.block.body_source += rf" \includegraphics{{{image.file.name}}}"
    proof.block.save(update_fields=["body_source"])


@pytest.mark.usefixtures("self_review_enabled", "unavailable_image")
def test_unavailable_image_fails_before_openai(client, proof, config, monkeypatch):
    openai = pytest.importorskip("openai")
    client.force_login(proof.author)
    queue(client, proof, config, models=MODELS[:1], include_solution_images="1")
    api = Mock()
    monkeypatch.setattr(openai, "OpenAI", api)
    assert worker.process_next()["status"] == "failed"
    api.assert_not_called()
    assert not SelfSolutionReviewUsage.objects.get().succeeded
    assert admin_reviews.IMAGE_INPUT_ERROR.encode() in client.get(proof.url).content


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
