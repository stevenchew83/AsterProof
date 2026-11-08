"""Archive Study Help acceptance, including PostgreSQL concurrency."""

# ruff: noqa: FBT003, PLR2004
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from hashlib import sha256
from io import StringIO
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from inspinia.pages import study_help
from inspinia.pages import study_help_access
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.study_help import ProblemUsage
from inspinia.pages.study_help import RequestSpec
from inspinia.pages.study_help import StudyHelpError
from inspinia.pages.study_help import enqueue
from inspinia.pages.study_help import status
from inspinia.pages.study_help_access import statement_revision
from inspinia.pages.study_help_models import StudyHelpAction
from inspinia.pages.study_help_models import StudyHelpAdminEvent
from inspinia.pages.study_help_models import StudyHelpEnrollment
from inspinia.pages.study_help_models import StudyHelpEvent
from inspinia.pages.study_help_models import StudyHelpPolicy
from inspinia.pages.study_help_models import StudyHelpPrompt
from inspinia.pages.study_help_models import StudyHelpQualification
from inspinia.pages.study_help_models import StudyHelpRequest
from inspinia.pages.study_help_models import StudyHelpSpend
from inspinia.pages.study_help_pilot import LEARNER_ARM
from inspinia.pages.study_help_pilot import LEARNER_FUNDING
from inspinia.pages.study_help_pilot import PILOT_ARM
from inspinia.pages.study_help_pilot import PILOT_MODEL
from inspinia.pages.study_help_pilot import PILOT_PROMPT
from inspinia.pages.study_help_pilot import PILOT_STATEMENT
from inspinia.pages.study_help_pilot import pilot_review_key
from inspinia.pages.study_help_provider import ProviderResult
from inspinia.pages.study_help_provider import profile_digest
from inspinia.pages.study_help_worker import claim_next
from inspinia.pages.study_help_worker import finish
from inspinia.pages.study_help_worker import process_next
from inspinia.pages.study_help_worker import reconcile
from inspinia.solutions.admin_review_models import AdminSolutionReviewSettings
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


@pytest.fixture
def draft_pilot(settings, monkeypatch, policy, archive):
    settings.STUDY_HELP_ENABLED = False
    settings.STUDY_HELP_DRAFT_HINT_PILOT_ENABLED = True
    admin = UserFactory(is_approved=True, role=User.Role.ADMIN)
    problem = ProblemSolveRecord.objects.create(contest="BMO", year=2023, problem="P1")
    archive.statement_uuid = PILOT_STATEMENT
    archive.linked_problem = problem
    archive.save()
    monkeypatch.setattr(study_help_access, "PILOT_REVISION", statement_revision(archive))
    reviewed_hint = "One Level 1 hint.\n\nLeave the choice of inputs to the student."
    prompt = StudyHelpPrompt.objects.create(
        pk=PILOT_PROMPT,
        hint=reviewed_hint.replace("\n", "\r\n"),
        solution="Proof.",
    )
    reviewed = SimpleNamespace(hint=reviewed_hint, solution=prompt.solution)
    monkeypatch.setattr(study_help, "PILOT_DIGEST", profile_digest(reviewed, PILOT_MODEL))
    encryption_key = Fernet.generate_key()
    settings.ADMIN_SOLUTION_REVIEW_ENCRYPTION_KEY = encryption_key.decode()
    AdminSolutionReviewSettings.objects.create(
        models_enabled=[PILOT_MODEL],
        encrypted_key=Fernet(encryption_key).encrypt(b"review-key-fixture"),
    )
    policy.generation_enabled = False
    policy.save(update_fields=["generation_enabled"])
    call_command("study_help_control", PILOT_ARM, operator_id=admin.pk, approval_ref="fixture", stdout=StringIO())
    policy.refresh_from_db()
    assert claim_next() is None
    policy.refresh_from_db()
    return admin, prompt, reverse("solutions:problem_solution_edit", args=[problem.problem_uuid])


def test_draft_pilot_limits_access_and_keeps_proofs_off(client, settings, policy, archive, draft_pilot):
    admin, prompt, draft_url = draft_pilot
    status_url = reverse("pages:study_help_status", args=[archive.statement_uuid])
    client.force_login(admin)
    assert b"data-study-help-draft" in client.get(draft_url).content
    assert set(client.get(status_url).json()["actions"]) == {"hint"}

    # A stale global flag must not expose the archive panel or widen the pilot.
    settings.STUDY_HELP_ENABLED = True
    archive_url = reverse("pages:problem_statement_detail", args=[archive.statement_uuid])
    assert b"data-study-help" not in client.get(archive_url).content
    assert client.get(status_url).status_code == 404
    settings.STUDY_HELP_ENABLED = False
    assert submit(client, archive_statement(2), spec(archive, "hint")).status_code == 404
    assert submit(client, archive, spec(archive, "solution")).status_code == 404
    assert submit(client, archive, spec(archive, "alternative", 2)).status_code == 404
    assert not StudyHelpSpend.objects.exists()
    assert not StudyHelpEvent.objects.exists()

    learner = UserFactory(is_approved=True)
    StudyHelpEnrollment.objects.create(user=learner)
    for user in (learner, UserFactory(is_approved=True, role=User.Role.ADMIN)):
        client.force_login(user)
        assert b"data-study-help-draft" not in client.get(draft_url).content
        assert client.get(status_url).status_code == 404
        assert submit(client, archive, spec(archive, "hint")).status_code == 404

    client.force_login(admin)
    policy.audience = StudyHelpPolicy.Audience.ALL
    policy.save(update_fields=["audience"])
    assert client.get(status_url).status_code == 404
    policy.active_prompt = prompt
    settings.STUDY_HELP_DRAFT_HINT_PILOT_ENABLED = False
    settings.STUDY_HELP_ENABLED = True
    assert not study_help.generation_ready(policy)
    settings.STUDY_HELP_ENABLED = False
    assert b"data-study-help-draft" not in client.get(draft_url).content


def test_draft_pilot_uses_saved_prompt_and_shared_credits(client, archive, draft_pilot):
    admin, prompt, _ = draft_pilot
    client.force_login(admin)
    SelfSolutionReviewUsage.objects.create(
        user=admin, problem_uuid=archive.problem_uuid, batch_id=uuid4(), succeeded=True,
    )
    status_url = reverse("pages:study_help_status", args=[archive.statement_uuid])
    first = "Hint (Level 1): Look for a pattern in the first few partial sums."
    second = "Hint (Level 1): What can you tell from the change between successive sums?"

    assert client.get(status_url).json()["account_remaining"] == 49
    request = spec(archive, "hint")
    assert submit(client, archive, request).status_code == 202
    job = StudyHelpRequest.objects.get(request_key=request.request_key)
    assert job.prompt == prompt
    assert job.profile_digest == study_help.PILOT_DIGEST

    def first_provider(model, action, messages):
        assert model == PILOT_MODEL
        assert action == StudyHelpAction.HINT
        assert "One Level 1 hint.\n\nLeave the choice of inputs to the student." in messages[0]["content"]
        assert "\r" not in messages[0]["content"]
        return result(first)

    assert process_next(first_provider) == "ready"
    assert self_review_allowance(admin, archive.problem_uuid)["account_remaining"] == 48
    assert not client.get(status_url).json()["actions"]
    assert saved(client, archive, job).json()["response"]["body"] == first
    assert saved(client, archive, job).json()["status"]["account_remaining"] == 48
    assert set(client.get(status_url).json()["actions"]) == {"stronger_hint"}

    def second_provider(model, action, messages):
        assert model == PILOT_MODEL
        assert action == StudyHelpAction.STRONGER_HINT
        assert "substantively different" in messages[0]["content"]
        assert "\r" not in messages[0]["content"]
        assert json.loads(messages[1]["content"])["prior_body"] == first
        return result(second)

    assert submit(client, archive, spec(archive, "stronger_hint", 2, job.pk)).status_code == 202
    assert process_next(second_provider) == "ready"
    latest = StudyHelpRequest.objects.get(action=StudyHelpAction.STRONGER_HINT)
    assert saved(client, archive, latest).json()["response"]["body"] == second
    assert self_review_allowance(admin, archive.problem_uuid)["account_remaining"] == 47
    assert client.get(status_url).json()["actions"] == {}
    assert submit(client, archive, spec(archive, "hint")).json()["code"] == "hint_statement_limit"
    assert StudyHelpSpend.objects.count() == 2
    prompt.refresh_from_db()
    assert "\r\n" in prompt.hint


def test_expired_draft_pilot_only_allows_the_enrolled_admin_to_reopen_saved_hints(client, archive, draft_pilot):
    admin, _, draft_url = draft_pilot
    client.force_login(admin)
    status_url = reverse("pages:study_help_status", args=[archive.statement_uuid])
    first = "Hint (Level 1): Look for a pattern in the first few partial sums."
    second = "Hint (Level 1): What can you tell from the change between successive sums?"

    job, _ = enqueue(admin, archive.statement_uuid, spec(archive, "hint"))
    assert process_next(provider_for(first)) == "ready"
    assert saved(client, archive, job).status_code == 200
    latest, _ = enqueue(admin, archive.statement_uuid, spec(archive, "stronger_hint", 2, job.pk))
    assert process_next(provider_for(second)) == "ready"
    assert saved(client, archive, latest).status_code == 200
    balance = client.get(status_url).json()["account_remaining"]
    assert balance == 48

    StudyHelpAdminEvent.objects.filter(action=PILOT_ARM).update(created_at=timezone.now() - timedelta(minutes=31))
    assert not pilot_review_key()
    assert b"data-study-help-draft" in client.get(draft_url).content
    expired = client.get(status_url).json()
    assert expired["actions"] == {}
    assert expired["message"] == study_help.ERRORS["generation_paused"][1]
    assert {entry["id"] for entry in expired["saved"]} == {str(job.pk), str(latest.pk)}
    for response, body in ((job, first), (latest, second)):
        reopened = saved(client, archive, response).json()
        assert reopened["response"]["body"] == body
        assert reopened["status"]["account_remaining"] == expired["account_remaining"] == balance
    assert submit(client, archive, spec(archive, "hint")).status_code == 404
    assert submit(client, archive, spec(archive, "solution")).status_code == 404
    assert StudyHelpSpend.objects.count() == 2

    other_admin = UserFactory(is_approved=True, role=User.Role.ADMIN)
    StudyHelpEnrollment.objects.create(user=other_admin)
    client.force_login(other_admin)
    assert b"data-study-help-draft" not in client.get(draft_url).content
    assert client.get(status_url).status_code == 404
    assert saved(client, archive, job).status_code == 404

    client.force_login(admin)
    StudyHelpEnrollment.objects.filter(user=admin).delete()
    assert b"data-study-help-draft" not in client.get(draft_url).content
    assert client.get(status_url).status_code == 404
    assert saved(client, archive, job).status_code == 404


@pytest.fixture
def finished_bmo_pilot(client, archive, draft_pilot):
    admin, _, draft_url = draft_pilot
    client.force_login(admin)
    first, _ = enqueue(admin, archive.statement_uuid, spec(archive, "hint"))
    assert process_next(provider_for("Hint (Level 1): Look for a pattern in the partial sums.")) == "ready"
    assert saved(client, archive, first).status_code == 200
    second, _ = enqueue(admin, archive.statement_uuid, spec(archive, "stronger_hint", 2, first.pk))
    assert process_next(provider_for("Hint (Level 1): Compare two successive sums.")) == "ready"
    assert saved(client, archive, second).status_code == 200
    call_command("study_help_control", "pause", operator_id=admin.pk, approval_ref="fixture", stdout=StringIO())
    StudyHelpAdminEvent.objects.filter(action=PILOT_ARM).update(created_at=timezone.now() - timedelta(minutes=31))
    assert claim_next() is None
    return admin, draft_url


def authorize_bmo_learners(admin, budget=1_000_000):
    call_command(
        "study_help_control", LEARNER_ARM, operator_id=admin.pk, approval_ref="learner fixture",
        budget_micros=budget, stdout=StringIO(),
    )


def test_bmo_learner_hints_use_shared_credits_and_stay_on_the_pinned_draft(
    client, archive, learner, finished_bmo_pilot,
):
    admin, draft_url = finished_bmo_pilot
    status_url = reverse("pages:study_help_status", args=[archive.statement_uuid])
    client.force_login(learner)
    assert client.get(status_url).status_code == 404
    assert b"data-study-help-draft" not in client.get(draft_url).content
    authorize_bmo_learners(admin)
    assert pilot_review_key() == "review-key-fixture"
    assert b"data-study-help-draft" in client.get(draft_url).content
    assert submit(client, archive_statement(2), spec(archive, "hint")).status_code == 404
    assert submit(client, archive, spec(archive, "solution")).status_code == 404
    assert submit(client, archive, spec(archive, "alternative", 2)).status_code == 404
    SelfSolutionReviewUsage.objects.create(
        user=learner, problem_uuid=archive.problem_uuid, batch_id=uuid4(), succeeded=True,
    )
    assert client.get(status_url).json()["account_remaining"] == 49

    first_body = "Hint (Level 1): What pattern do the partial sums suggest?"
    first_request = submit(client, archive, spec(archive, "hint"))
    assert first_request.status_code == 202
    first = StudyHelpRequest.objects.get(pk=first_request.json()["id"])
    assert first.funding_source == LEARNER_FUNDING
    assert process_next(provider_for(first_body)) == "ready"
    assert saved(client, archive, first).json()["status"]["account_remaining"] == 48

    def second_provider(model, action, messages):
        assert model == PILOT_MODEL
        assert action == StudyHelpAction.STRONGER_HINT
        assert "substantively different" in messages[0]["content"]
        assert json.loads(messages[1]["content"])["prior_body"] == first_body
        return result("Hint (Level 1): Compare successive sums.")

    second_request = submit(client, archive, spec(archive, "stronger_hint", 2, first.pk))
    assert second_request.status_code == 202
    assert process_next(second_provider) == "ready"
    assert self_review_allowance(learner, archive.problem_uuid)["account_remaining"] == 47
    second = StudyHelpRequest.objects.get(pk=second_request.json()["id"])
    assert saved(client, archive, second).json()["response"]["body"] == "Hint (Level 1): Compare successive sums."
    assert submit(client, archive, spec(archive, "hint")).json()["code"] == "hint_statement_limit"
    assert client.get(status_url).json()["actions"] == {}

    call_command("study_help_control", "pause", operator_id=admin.pk, approval_ref="fixture", stdout=StringIO())
    assert not pilot_review_key()
    assert saved(client, archive, first).json()["status"]["account_remaining"] == 47
    assert submit(client, archive, spec(archive, "hint")).json()["code"] == "generation_paused"
    client.force_login(UserFactory(is_approved=False))
    assert b"data-study-help-draft" not in client.get(draft_url).content
    denied = client.get(status_url)
    assert denied.status_code == 302
    assert denied.url == reverse("users:approval_pending")


def test_bmo_learner_cap_counts_receipts_from_earlier_days_without_an_account(
    client, archive, learner, finished_bmo_pilot,
):
    admin, _ = finished_bmo_pilot
    with pytest.raises(CommandError, match="approved total budget"):
        authorize_bmo_learners(admin, 100)
    StudyHelpPolicy.objects.update(worker_checked_at=None)
    with pytest.raises(CommandError, match="recent Study Help worker heartbeat"):
        authorize_bmo_learners(admin)
    assert not StudyHelpAdminEvent.objects.filter(action=LEARNER_ARM).exists()
    assert not StudyHelpPolicy.objects.get().generation_enabled
    assert claim_next() is None
    authorize_bmo_learners(admin)
    now = timezone.now()
    StudyHelpAdminEvent.objects.filter(action=LEARNER_ARM).update(created_at=now - timedelta(days=3))
    receipt = StudyHelpSpend.objects.create(
        reserved_micros=999_999,
        actual_micros=999_999,
        state=StudyHelpSpend.State.SETTLED,
        input_price=1,
        output_price=1,
        dispatched_at=now - timedelta(days=2),
    )
    StudyHelpSpend.objects.filter(pk=receipt.pk).update(created_at=now - timedelta(days=2))
    client.force_login(learner)
    response = submit(client, archive, spec(archive, "hint"))
    assert response.status_code == 503
    assert response.json()["code"] == "budget_limit"
    assert not StudyHelpRequest.objects.filter(owner=learner).exists()


@pytest.mark.parametrize("change", ["statement", "prompt", "proof", "expiry"])
def test_draft_pilot_fences_ineligible_jobs_before_dispatch(client, archive, draft_pilot, change):
    admin, prompt, draft_url = draft_pilot
    client.force_login(admin)
    assert submit(client, archive, spec(archive, "hint")).status_code == 202
    if change == "statement":
        archive.statement_latex += " Additional condition."
        archive.save(update_fields=["statement_latex"])
        assert b"data-study-help-draft" not in client.get(draft_url).content
    elif change == "prompt":
        StudyHelpPrompt.objects.filter(pk=prompt.pk).update(hint="An unreviewed prompt.")
    elif change == "proof":
        StudyHelpRequest.objects.update(action=StudyHelpAction.SOLUTION)
    else:
        StudyHelpAdminEvent.objects.filter(action=PILOT_ARM).update(created_at=timezone.now() - timedelta(minutes=31))
    assert claim_next() is None
    job = StudyHelpRequest.objects.get()
    assert job.state == StudyHelpRequest.State.FAILED
    assert job.spend.actual_micros == 0
    assert self_review_allowance(admin, archive.problem_uuid)["account_remaining"] == 50


def test_draft_pilot_one_shot_access_and_key_version(client, archive, draft_pilot):
    admin, _, _ = draft_pilot
    assert pilot_review_key() == "review-key-fixture"
    AdminSolutionReviewSettings.objects.update(key_version=uuid4())
    assert not pilot_review_key()
    client.force_login(admin)
    assert submit(client, archive, spec(archive, "hint")).status_code == 202
    assert process_next(provider_for("An unusable hint.")) == "failed"
    assert submit(client, archive, spec(archive, "hint")).json()["code"] == "stale_action"
    assert StudyHelpSpend.objects.count() == 1
    call_command("study_help_control", "pause", operator_id=admin.pk, approval_ref="fixture", stdout=StringIO())
    with pytest.raises(CommandError, match="only be authorized once"):
        call_command("study_help_control", PILOT_ARM, operator_id=admin.pk, approval_ref="fixture", stdout=StringIO())


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


def test_single_hint_pair_passes_the_first_hint_and_keeps_learner_generation_off(
    settings, policy, archive, tmp_path, monkeypatch,
):
    from django.core.management.base import CommandError

    from inspinia.pages.management.commands import evaluate_study_help

    settings.STUDY_HELP_EVALUATION_ENABLED = True
    policy.generation_enabled = False
    policy.save(update_fields=["generation_enabled"])
    actor = UserFactory(role=User.Role.ADMIN, is_approved=True)
    first_hint = "Compare the sum for n with the sum for n minus one."
    second_hint = "Try arranging successive odd numbers as borders of square arrays."
    answers = {StudyHelpAction.HINT: first_hint, StudyHelpAction.STRONGER_HINT: second_hint}
    calls = []

    def provider(_model, action, messages, *, evaluation):
        assert evaluation
        calls.append((action, messages))
        return result(answers[action])

    monkeypatch.setattr(evaluate_study_help, "call_provider", provider)
    manifest = {
        "mode": "hint_pair",
        "prompt": str(policy.active_prompt_id),
        "profile_digest": profile_digest(policy.active_prompt, policy.model),
        "expires": (timezone.now() + timedelta(minutes=2)).isoformat(),
        "budget_micros": 2 * policy.request_cap,
        "pricing": {"input_price": policy.input_price, "output_price": policy.output_price},
        "fixtures": [{
            "statement_uuid": str(archive.statement_uuid), "revision": statement_revision(archive),
            "domain": "algebra", "alternative": False,
        }],
    }
    path = tmp_path / "hint-pair.json"
    raw = json.dumps(manifest).encode()
    path.write_bytes(raw)
    stdout = StringIO()
    arguments = (
        "--manifest", str(path), "--manifest-sha256", sha256(raw).hexdigest(),
        "--approval-ref", "synthetic-hint-pair", "--operator-id", str(actor.pk),
    )

    with pytest.raises(CommandError, match="configuration"):
        call_command("evaluate_study_help", *arguments, stdout=stdout)
    assert not calls
    settings.STUDY_HELP_ENABLED = False
    call_command("evaluate_study_help", *arguments, stdout=stdout)
    assert [action for action, _ in calls] == [StudyHelpAction.HINT, StudyHelpAction.STRONGER_HINT]
    assert json.loads(calls[1][1][1]["content"])["prior_body"] == first_hint
    assert [json.loads(line)["body"] for line in stdout.getvalue().splitlines()] == [first_hint, second_hint]
    assert StudyHelpSpend.objects.filter(state=StudyHelpSpend.State.SETTLED).count() == 2
    assert not StudyHelpRequest.objects.exists()
    with pytest.raises(CommandError, match="already exists"):
        call_command("evaluate_study_help", *arguments, stdout=stdout)
    assert len(calls) == 2
