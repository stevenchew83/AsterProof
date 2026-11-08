"""Archive Study Help acceptance, including PostgreSQL concurrency."""

# ruff: noqa: FBT003, PLR2004
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from io import StringIO
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.db import close_old_connections
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.study_help import ProblemUsage
from inspinia.pages.study_help import RequestSpec
from inspinia.pages.study_help import StudyHelpError
from inspinia.pages.study_help import enqueue
from inspinia.pages.study_help import status
from inspinia.pages.study_help_access import statement_revision
from inspinia.pages.study_help_models import StudyHelpAction
from inspinia.pages.study_help_models import StudyHelpEnrollment
from inspinia.pages.study_help_models import StudyHelpEvent
from inspinia.pages.study_help_models import StudyHelpPolicy
from inspinia.pages.study_help_models import StudyHelpPrompt
from inspinia.pages.study_help_models import StudyHelpQualification
from inspinia.pages.study_help_models import StudyHelpRequest
from inspinia.pages.study_help_models import StudyHelpSpend
from inspinia.pages.study_help_provider import ProviderResult
from inspinia.pages.study_help_provider import profile_digest
from inspinia.pages.study_help_worker import claim_next
from inspinia.pages.study_help_worker import finish
from inspinia.pages.study_help_worker import process_next
from inspinia.pages.study_help_worker import reconcile
from inspinia.solutions.admin_review_models import SelfSolutionReviewUsage
from inspinia.solutions.admin_reviews import self_review_allowance
from inspinia.solutions.evaluation_models import AssistancePolicy
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def learner():
    return UserFactory(is_approved=True)


@pytest.fixture
def policy(settings):
    settings.STUDY_HELP_ENABLED = True
    settings.STUDY_HELP_OPENAI_API_KEY = "fixture-key-never-sent"
    prompt = StudyHelpPrompt.objects.create(hint="Suggest an idea.", solution="Write a proof.")
    model = "fixture-model"
    StudyHelpQualification.objects.create(prompt=prompt, profile_digest=profile_digest(prompt, model), evidence={})
    return StudyHelpPolicy.objects.create(
        audience=StudyHelpPolicy.Audience.ALL,
        generation_enabled=True,
        active_prompt=prompt,
        model=model,
        input_price=10_000,
        output_price=30_000,
        pricing_verified_at=timezone.now(),
        worker_checked_at=timezone.now(),
        request_cap=2_000,
        day_cap=10_000_000,
        month_cap=50_000_000,
    )


@pytest.fixture
def archive():
    return archive_statement(1)


def archive_statement(number, text=r"Prove that \(1+3+\cdots+(2n-1)=n^2\) for all positive integers \(n\)."):
    return ContestProblemStatement.objects.create(
        contest_name="Study Help Test",
        contest_year=2025,
        problem_number=number,
        problem_code=f"P{number}",
        statement_latex=text,
    )


def spec(statement, action="solution", slot=1, prior_id=None):
    return RequestSpec(uuid4(), uuid4(), StudyHelpAction(action), statement_revision(statement), slot, prior_id, True)


def post(client, statement, route, value):
    return client.post(
        reverse(f"pages:study_help_{route}", args=[statement.statement_uuid]),
        value,
        format="json",
        content_type="application/json",
    )


def submit(client, statement, request, *, confirmed=True):
    return post(
        client,
        statement,
        "request",
        {
            "request_key": str(request.request_key),
            "interaction_key": str(request.interaction_key),
            "action": request.action,
            "revision": request.revision,
            "slot": request.slot,
            "prior_id": str(request.prior_id) if request.prior_id else None,
            "confirmed": confirmed,
        },
    )


def saved(client, statement, job, key=None):
    return post(client, statement, "reveal", {"response_id": str(job.pk), "interaction_key": str(key or uuid4())})


def result(body, method="", *, tokens=100):
    return ProviderResult(
        payload={"outcome": "ready", "body": body, "method": method},
        input_tokens=tokens,
        output_tokens=tokens,
        response_id="fixture-response",
    )


def provider_for(body, method=""):
    return lambda *_args: result(body, method)


def scoped_rule(statement, learner=None, *, begins=None):
    now = timezone.now()
    return AssistancePolicy.objects.create(
        problem_uuid=statement.problem_uuid,
        actor_id_scope=learner.pk if learner else None,
        mode="restricted_assessment",
        starts_at=begins or now - timedelta(minutes=1),
        ends_at=now + timedelta(days=1),
        reason="Fixture restriction",
    )


def test_progressive_hints_are_private_and_follow_an_explicit_reveal(client, learner, policy, archive):
    client.force_login(learner)
    request = spec(archive, "hint")
    response = submit(client, archive, request)
    assert response.status_code == 202
    job = StudyHelpRequest.objects.get(pk=response.json()["id"])
    assert process_next(provider_for(r"Try comparing \((n+1)^2\) and \(n^2\).")) == "ready"
    page = client.get(reverse("pages:problem_statement_detail", args=[archive.statement_uuid]))
    read = client.get(reverse("pages:study_help_status", args=[archive.statement_uuid]))
    assert b"Try comparing" not in page.content + read.content
    assert "no-store" in read["Cache-Control"]
    assert read.json()["account_remaining"] == 49
    assert "stronger_hint" not in read.json()["actions"]
    client.force_login(UserFactory(is_approved=True))
    assert saved(client, archive, job).status_code == 404
    client.force_login(learner)
    same_click = uuid4()
    assert saved(client, archive, job, same_click).json()["response"]["body"].startswith("Try comparing")
    assert saved(client, archive, job, same_click).status_code == 200
    assert StudyHelpEvent.objects.filter(kind="first_reveal").count() == 1
    assert StudyHelpEvent.objects.filter(kind="view_click").count() == 1
    assert submit(client, archive, spec(archive, "stronger_hint", 2, job.pk)).status_code == 202
    claim = claim_next()
    assert "substantively different" in claim.messages[0]["content"]
    assert json.loads(claim.messages[1]["content"])["prior_body"] == r"Try comparing \((n+1)^2\) and \(n^2\)."
    assert finish(claim.spend_id, result(r"TRY comparing \((n+1)^2\) and \(n^2\)!")) == "failed"
    assert status(learner, archive.statement_uuid)["account_remaining"] == 49

    archive.statement_latex += " Use any valid argument."
    archive.save()
    assert submit(client, archive, spec(archive, "stronger_hint", 2, job.pk)).status_code == 202
    assert process_next(provider_for("Use the difference of two consecutive squares as an induction step.")) == "ready"
    final = status(learner, archive.statement_uuid)
    assert final["account_remaining"] == 48
    assert final["statement_hints_used"] == 2
    assert not (set(final["actions"]) & {"hint", "stronger_hint"})
    assert submit(client, archive, spec(archive, "hint")).json()["code"] == "hint_statement_limit"


def test_draft_study_help_shares_archive_identity_and_access(client, settings, learner, policy, archive):
    problem = ProblemSolveRecord.objects.create(contest=archive.contest_name, year=archive.contest_year, problem="P1")
    archive.linked_problem = problem
    archive.save()
    client.force_login(learner)
    draft_url = reverse("solutions:problem_solution_edit", args=[problem.problem_uuid])
    status_url = reverse("pages:study_help_status", args=[archive.statement_uuid])
    archive_url = reverse("pages:problem_statement_detail", args=[archive.statement_uuid])
    draft = client.get(draft_url).content.decode()
    archive_page = client.get(archive_url).content.decode()

    for page in (draft, archive_page):
        status_attribute = f'data-status-url="{status_url}"'
        assert page.count(status_attribute) == 1
        panel = page.split(status_attribute, 1)[1].split("</section>", 1)[0]
        assert 'name="csrfmiddlewaretoken"' in panel
    assert "data-study-help-draft" in draft
    assert "data-study-help-draft" not in archive_page
    assert draft.index("study-help.js") < draft.index("tex-mml-chtml.js")

    policy.audience = StudyHelpPolicy.Audience.COHORT
    policy.save(update_fields=["audience"])
    assert client.get(status_url).status_code == 404
    StudyHelpEnrollment.objects.create(user=learner)
    assert "hint" in client.get(status_url).json()["actions"]

    settings.STUDY_HELP_ENABLED = False
    assert b"study-help.js" not in client.get(draft_url).content
    settings.STUDY_HELP_ENABLED = True
    archive.is_active = False
    archive.save(update_fields=["is_active"])
    assert b"study-help.js" not in client.get(draft_url).content


def test_proof_confirmations_clicks_and_stale_actions(client, learner, policy, archive):
    client.force_login(learner)
    request = spec(archive)
    click_data = {"interaction_key": str(request.interaction_key), "action": "solution"}
    assert post(client, archive, "click", click_data).status_code == 200
    assert post(client, archive, "click", click_data).status_code == 200
    assert submit(client, archive, request, confirmed=False).status_code == 422
    first = submit(client, archive, request)
    assert first.status_code == 202
    assert submit(client, archive, request).status_code == 200
    assert process_next(provider_for("Induct on the number of terms.", "Induction")) == "ready"
    assert submit(client, archive, spec(archive)).json()["code"] == "stale_action"
    alternate = spec(archive, "alternative", 2, StudyHelpRequest.objects.get(pk=first.json()["id"]).pk)
    assert submit(client, archive, alternate).status_code == 202
    assert process_next(provider_for("Repeat the induction.", "Induction")) == "failed"
    usage = status(learner, archive.statement_uuid)
    assert usage["solutions_left"] == 49
    assert usage["statement_solutions_used"] == 1
    assert "different approach" in usage["failure"]
    assert set(
        StudyHelpEvent.objects.filter(interaction_key=request.interaction_key).values_list("kind", flat=True),
    ) == {
        "click",
        "confirmed",
        "accepted",
        "completed",
    }
    assert StudyHelpEvent.objects.filter(interaction_key=request.interaction_key, generation__isnull=True).count() == 0


def test_proof_slots_survive_source_changes_and_pause(client, learner, policy, archive):
    client.force_login(learner)
    first, _ = enqueue(learner, archive.statement_uuid, spec(archive))
    assert process_next(provider_for("First proof.", "Induction")) == "ready"
    archive.statement_latex += r" Assume \(n\geq 1\)."
    archive.problem_uuid = uuid4()
    archive.save()
    details = status(learner, archive.statement_uuid)
    assert details["saved"][0]["current"] is False
    assert details["actions"]["solution"]["slot"] == 2
    second, _ = enqueue(learner, archive.statement_uuid, spec(archive, slot=2))
    assert process_next(provider_for("Second proof.", "Telescoping")) == "ready"
    policy.generation_enabled = False
    policy.save(update_fields=["generation_enabled"])
    details = status(learner, archive.statement_uuid)
    assert details["statement_solutions_used"] == 2
    assert details["solutions_left"] == 48
    assert "paused" in details["message"]
    assert saved(client, archive, first).json()["response"]["current"] is False
    assert saved(client, archive, second).json()["response"]["current"] is True


def test_restrictions_apply_on_relink_dispatch_and_reveal(client, learner, policy, archive):
    client.force_login(learner)
    job, _ = enqueue(learner, archive.statement_uuid, spec(archive))
    assert process_next(provider_for("Proof.", "Induction")) == "ready"
    scoped_rule(archive, learner)
    archive.problem_uuid = uuid4()
    archive.save()
    assert saved(client, archive, job).status_code == 403
    assert submit(client, archive, spec(archive)).status_code == 403

    next_statement = archive_statement(2)
    queued, _ = enqueue(learner, next_statement.statement_uuid, spec(next_statement))
    scoped_rule(next_statement, learner)
    assert claim_next() is None
    queued.refresh_from_db()
    assert queued.failure_code == "assistance_restricted"
    assert queued.spend.actual_micros == 0

    third = archive_statement(3)
    running, _ = enqueue(learner, third.statement_uuid, spec(third))
    assert claim_next()
    scoped_rule(third, learner)
    assert finish(running.spend_id, result("Withheld proof", "Parity")) == "failed"
    running.refresh_from_db()
    assert running.body == ""
    assert running.spend.actual_micros > 0


@pytest.mark.parametrize(
    "source",
    [
        "[asy]draw((0,0)--(1,0));[/asy]",
        r"See \includegraphics{source}.",
        "Use the attached file.",
        "The diagram below shows the arrangement.",
        "![diagram](https://example.com/image.png)",
    ],
)
def test_diagram_sources_cannot_enter_queue(client, learner, policy, source):
    client.force_login(learner)
    statement = archive_statement(2, source)
    response = submit(client, statement, spec(statement))
    assert response.status_code == 422
    assert response.json()["code"] == "diagram_required"
    assert not StudyHelpSpend.objects.exists()


def test_hints_share_the_last_review_credit_and_do_not_reset_daily(monkeypatch, learner, policy, archive):
    from inspinia.pages import study_help

    now = datetime(2026, 11, 7, 15, 59, tzinfo=UTC)
    monkeypatch.setattr(study_help.timezone, "now", lambda: now)
    policy.worker_checked_at = policy.pricing_verified_at = now
    policy.save(update_fields=["worker_checked_at", "pricing_verified_at"])
    SelfSolutionReviewUsage.objects.bulk_create([
        SelfSolutionReviewUsage(user=learner, problem_uuid=uuid4(), batch_id=uuid4(), succeeded=True)
        for _ in range(49)
    ])
    assert status(learner, archive.statement_uuid)["account_remaining"] == 1
    enqueue(learner, archive.statement_uuid, spec(archive, "hint"))
    assert self_review_allowance(learner, archive.problem_uuid) == {
        "active": True, "account_remaining": 1, "problem_remaining": 2,
    }
    assert claim_next()
    now += timedelta(minutes=1)
    running = StudyHelpRequest.objects.get(state="running")
    assert finish(running.spend_id, result("Try an identity.")) == "ready"
    assert running.hint_day.isoformat() == "2026-11-07"
    assert status(learner, archive.statement_uuid)["account_remaining"] == 0
    assert self_review_allowance(learner, archive.problem_uuid) == {
        "active": False, "account_remaining": 0, "problem_remaining": 2,
    }
    with pytest.raises(StudyHelpError, match="used all your AI credits"):
        enqueue(learner, archive.statement_uuid, spec(archive, "hint"))


def test_uncertain_dispatch_expiry_and_manual_reconciliation(learner, policy, archive):
    job, _ = enqueue(learner, archive.statement_uuid, spec(archive))
    assert claim_next()
    StudyHelpSpend.objects.filter(pk=job.spend_id).update(dispatched_at=timezone.now() - timedelta(minutes=5))
    assert claim_next() is None
    job.refresh_from_db()
    assert job.state == "unknown"
    assert job.spend.actual_micros is None
    assert finish(job.spend_id, result("Late proof", "Induction")) == "fenced"
    with pytest.raises(StudyHelpError, match="No credit was used"):
        enqueue(learner, archive.statement_uuid, spec(archive))
    reconcile(job.spend_id, 12, "invoice-evidence", learner)
    assert status(learner, archive.statement_uuid)["solutions_left"] == 50
    assert enqueue(learner, archive.statement_uuid, spec(archive))[1]


def test_account_erasure_during_dispatch_preserves_only_spend(learner, policy, archive):
    job, _ = enqueue(learner, archive.statement_uuid, spec(archive))
    assert claim_next()
    learner.delete()
    assert finish(job.spend_id, result("Never publish", "Induction")) == "owner_deleted"
    assert not StudyHelpRequest.objects.exists()
    assert not StudyHelpEvent.objects.exists()
    spend = StudyHelpSpend.objects.get(pk=job.spend_id)
    assert spend.state == "settled"
    assert spend.actual_micros > 0


def test_edits_and_invalid_payloads_release_user_credit(learner, policy, archive):
    job, _ = enqueue(learner, archive.statement_uuid, spec(archive))
    assert claim_next()
    archive.statement_latex = "Prove that a square is nonnegative."
    archive.save()
    assert finish(job.spend_id, result("Old proof", "Induction")) == "failed"
    enqueue(learner, archive.statement_uuid, spec(archive))
    assert process_next(provider_for(r"Try \require{html}\href{https://example.com}{a link}.", "Unsafe")) == "failed"
    assert status(learner, archive.statement_uuid)["solutions_left"] == 50
    assert not StudyHelpRequest.objects.exclude(body="").exists()


def test_provider_overrun_pauses_new_generation(learner, policy, archive):
    enqueue(learner, archive.statement_uuid, spec(archive))
    assert process_next(lambda *_: result("Overrun", "Induction", tokens=1_000_000)) == "failed"
    policy.refresh_from_db()
    assert policy.generation_enabled is False
    assert status(learner, archive.statement_uuid)["solutions_left"] == 50


def test_launch_flag_roles_csrf_and_admin_drafts(client, settings, learner, policy, archive):
    client.force_login(learner)
    settings.STUDY_HELP_ENABLED = False
    route = reverse("pages:problem_statement_detail", args=[archive.statement_uuid])
    disabled_page = client.get(route).content
    assert b'id="study-help-title"' not in disabled_page
    assert b"study-help.js" not in disabled_page
    assert submit(client, archive, spec(archive)).status_code == 404
    assert client.get(reverse("pages:study_help_admin")).status_code == 403

    settings.STUDY_HELP_ENABLED = True
    policy.audience = StudyHelpPolicy.Audience.COHORT
    policy.save(update_fields=["audience"])
    assert submit(client, archive, spec(archive)).status_code == 404
    StudyHelpEnrollment.objects.create(user=learner)
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(learner)
    assert submit(csrf_client, archive, spec(archive)).status_code == 403

    admin = UserFactory(role=User.Role.ADMIN, is_approved=True)
    client.force_login(admin)
    admin_url = reverse("pages:study_help_admin")
    draft = client.post(admin_url, {"operation": "draft", "hint": "New hint.", "solution": "New proof."})
    assert draft.status_code == 302
    new = StudyHelpPrompt.objects.get(hint="New hint.")
    assert b"Fixture preview" in client.get(draft["Location"]).content
    client.post(admin_url, {"operation": "publish", "prompt": str(new.pk)})
    policy.refresh_from_db()
    assert policy.active_prompt != new
    StudyHelpQualification.objects.create(prompt=new, profile_digest=profile_digest(new, policy.model), evidence={})
    client.post(admin_url, {"operation": "publish", "prompt": str(new.pk)})
    policy.refresh_from_db()
    assert policy.active_prompt == new
    report = StringIO()
    call_command("study_help_control", "readiness", stdout=report)
    assert json.loads(report.getvalue())["generation_ready"] is True


def test_ai_settings_saves_hint_draft_without_publishing(client, learner, policy):
    settings_url = reverse("solutions:admin_ai_review_settings")
    original = policy.active_prompt
    data = {"operation": "hint_draft", "hint": "Give a small starting example.", "prompt": str(original.pk)}
    client.force_login(learner)
    assert client.post(settings_url, data).status_code == 403
    client.force_login(UserFactory(role=User.Role.ADMIN))
    page = client.post(settings_url, data, follow=True)
    assert page.status_code == 200
    assert b"Give a small starting example." in page.content
    draft = StudyHelpPrompt.objects.get(hint=data["hint"])
    assert draft.solution == original.solution
    client.post(settings_url, {"operation": "publish", "prompt": str(draft.pk)})
    policy.refresh_from_db()
    assert policy.active_prompt == original


def _ready_proof(owner, statement, policy):
    return StudyHelpRequest.objects.create(
        owner=owner,
        request_key=uuid4(),
        interaction_key=uuid4(),
        statement_uuid=statement.statement_uuid,
        problem_uuid=statement.problem_uuid,
        revision=statement_revision(statement),
        action="solution",
        slot=1,
        state="ready",
        prompt=policy.active_prompt,
        model=policy.model,
        profile_digest=profile_digest(policy.active_prompt, policy.model),
        body="Synthetic proof.",
        finished_at=timezone.now(),
        spend=StudyHelpSpend.objects.create(
            state="settled",
            actual_micros=1,
            reserved_micros=1,
            input_price=1,
            output_price=1,
        ),
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("different_statements", [True, False])
def test_postgres_enforces_the_last_credit_and_no_competing_first_proofs(learner, policy, different_statements):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL transaction locks.")
    if different_statements:
        for number in range(1, 50):
            _ready_proof(learner, archive_statement(number), policy)
    first = archive_statement(51)
    second = archive_statement(52) if different_statements else first
    barrier = Barrier(2)

    def submit_concurrently(statement):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            enqueue(learner, statement.statement_uuid, spec(statement))
        except StudyHelpError as error:
            return error.code
        else:
            return "queued"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit_concurrently, [first, second])) == ["generation_pending", "queued"]
    assert process_next(provider_for("A final proof.", "Induction")) == "ready"
    other = (
        first
        if not different_statements
        else (second if StudyHelpRequest.objects.filter(statement_uuid=first.statement_uuid).exists() else first)
    )
    expected = "solutions_exhausted" if different_statements else "stale_action"
    with pytest.raises(StudyHelpError) as error:
        enqueue(learner, other.statement_uuid, spec(other))
    assert error.value.code == expected
    assert ProblemUsage(learner, other).solutions_left == (0 if different_statements else 49)


def test_abandoned_queued_request_releases_capacity(learner, policy, archive):
    job, _ = enqueue(learner, archive.statement_uuid, spec(archive))
    StudyHelpSpend.objects.filter(pk=job.spend_id).update(created_at=timezone.now() - timedelta(minutes=20))
    assert claim_next() is None
    job.refresh_from_db()
    assert job.failure_code == "expired"
    assert job.spend.actual_micros == 0
    assert status(learner, archive.statement_uuid)["solutions_left"] == 50


def test_an_unreconciled_receipt_reserves_capacity_across_utc_windows(learner, policy, archive):
    policy.day_cap = 2_000
    policy.save(update_fields=["day_cap"])
    StudyHelpSpend.objects.create(
        reserved_micros=1_990, state=StudyHelpSpend.State.UNKNOWN, dispatched_at=timezone.now() - timedelta(days=40),
        input_price=1, output_price=1,
    )
    with pytest.raises(StudyHelpError) as error:
        enqueue(learner, archive.statement_uuid, spec(archive))
    assert error.value.code == "budget_limit"


def test_provider_transport_disables_tools_storage_and_retries(settings, monkeypatch):
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from inspinia.pages.study_help_provider import call_provider

    sdk = MagicMock()
    response = SimpleNamespace(
        status="completed", id="receipt",
        usage=SimpleNamespace(input_tokens=40, output_tokens=20),
        output=[SimpleNamespace(type="message", content=[SimpleNamespace(
            type="output_text", text='{"outcome":"ready","body":"Try parity.","method":""}',
        )])],
    )
    factory = sdk.OpenAI
    transport = factory.return_value.__enter__.return_value.responses.create
    transport.return_value = response
    monkeypatch.setitem(sys.modules, "openai", sdk)
    settings.STUDY_HELP_ENABLED = False
    settings.STUDY_HELP_OPENAI_API_KEY = "fixture"
    assert call_provider("fixture", "hint", []).error == "provider_disabled"
    factory.assert_not_called()
    settings.STUDY_HELP_ENABLED = True
    result = call_provider("fixture", "hint", [])
    assert result.payload["body"] == "Try parity."
    assert result.output_tokens == 20
    assert factory.call_args.kwargs["max_retries"] == 0
    assert transport.call_args.kwargs["store"] is False
    assert transport.call_args.kwargs["max_output_tokens"] == 2_000
    assert "tools" not in transport.call_args.kwargs


def test_coach_evidence_import_rejects_a_spoiler_and_checks_exact_profile(policy, tmp_path):
    from django.core.management.base import CommandError

    from inspinia.pages.study_help_qualification import DOMAINS

    operator, reviewer = UserFactory.create_batch(2, role=User.Role.ADMIN, is_approved=True)
    candidate = StudyHelpPrompt.objects.create(hint="New candidate hint.", solution="New candidate proof.")
    fixtures, ratings = [], {}
    for number in range(24):
        statement = archive_statement(number + 1)
        key = str(statement.statement_uuid)
        fixtures.append({
            "statement_uuid": key, "revision": statement_revision(statement),
            "domain": DOMAINS[number // 6], "alternative": number < 8,
        })
        ratings[key] = dict.fromkeys(("hint", "stronger_hint", "solution"), "usable")
        if number < 8:
            ratings[key]["alternative"] = "usable"
    evidence = {
        "profile_digest": profile_digest(candidate, policy.model), "fixtures": fixtures,
        "reviews": [
            {"reviewer_id": actor.pk, "ratings": {key: dict(value) for key, value in ratings.items()}}
            for actor in (operator, reviewer)
        ],
    }
    path = tmp_path / "reviews.json"

    def qualify():
        path.write_text(json.dumps(evidence))
        call_command(
            "study_help_control", "qualify", "--operator-id", str(operator.pk),
            "--approval-ref", "fixture-review-packet", "--prompt", str(candidate.pk), "--evidence", str(path),
            stdout=StringIO(),
        )

    key = fixtures[0]["statement_uuid"]
    evidence["reviews"][0]["ratings"][key]["hint"] = "spoiler"
    with pytest.raises(CommandError, match="spoiler"):
        qualify()
    assert not StudyHelpQualification.objects.filter(prompt=candidate).exists()
    evidence["reviews"][0]["ratings"][key]["hint"] = "usable"
    qualify()
    record = StudyHelpQualification.objects.get(prompt=candidate)
    assert record.profile_digest == profile_digest(candidate, policy.model)
    assert record.evidence["usable"]["alternative"] == 8


def test_paid_sample_claim_is_separate_funded_and_never_replayed(settings, policy, archive):
    from django.core.management.base import CommandError

    from inspinia.pages.management.commands.evaluate_study_help import _claim

    actor = UserFactory(role=User.Role.ADMIN, is_approved=True)
    manifest = {
        "actor": actor, "profile_digest": profile_digest(policy.active_prompt, policy.model),
        "pricing": {"input_price": policy.input_price, "output_price": policy.output_price},
        "expires": timezone.now() + timedelta(minutes=2), "budget_micros": policy.request_cap,
        "batch": "f" * 64, "digest": "e" * 64,
    }
    policy.generation_enabled = False
    policy.save(update_fields=["generation_enabled"])
    settings.STUDY_HELP_EVALUATION_ENABLED = False
    with pytest.raises(CommandError, match="configuration"):
        _claim(policy.active_prompt, archive, StudyHelpAction.HINT, None, manifest)
    assert not StudyHelpSpend.objects.exists()
    settings.STUDY_HELP_EVALUATION_ENABLED = True
    spend, model, messages = _claim(policy.active_prompt, archive, StudyHelpAction.HINT, None, manifest)
    assert model == policy.model
    assert set(json.loads(messages[1]["content"])) == {"action", "problem_statement"}
    assert not StudyHelpRequest.objects.exists()
    assert finish(spend.pk, result("Try induction.")) == "evaluation"
    with pytest.raises(CommandError, match="already exists"):
        _claim(policy.active_prompt, archive, StudyHelpAction.HINT, None, manifest)
    assert StudyHelpSpend.objects.count() == 1
