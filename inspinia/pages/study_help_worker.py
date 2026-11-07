"""Bounded claims, settlement, and recovery for the database worker."""

# ruff: noqa: EM101, PLR2004, TRY301

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from inspinia.pages.study_help import StudyHelpError
from inspinia.pages.study_help import _prior
from inspinia.pages.study_help import budget_available
from inspinia.pages.study_help import check_read
from inspinia.pages.study_help import event_for
from inspinia.pages.study_help import generation_ready
from inspinia.pages.study_help import locked_account
from inspinia.pages.study_help_access import can_use_study_help
from inspinia.pages.study_help_access import lock_study_help
from inspinia.pages.study_help_access import source_problem
from inspinia.pages.study_help_access import statement_revision
from inspinia.pages.study_help_models import StudyHelpAdminEvent
from inspinia.pages.study_help_models import StudyHelpEvent
from inspinia.pages.study_help_models import StudyHelpPolicy
from inspinia.pages.study_help_models import StudyHelpQualification
from inspinia.pages.study_help_models import StudyHelpRequest
from inspinia.pages.study_help_models import StudyHelpSpend
from inspinia.pages.study_help_provider import TIMEOUT_SECONDS
from inspinia.pages.study_help_provider import ProviderResult
from inspinia.pages.study_help_provider import call_provider
from inspinia.pages.study_help_provider import cost_micros
from inspinia.pages.study_help_provider import input_messages
from inspinia.pages.study_help_provider import profile_digest
from inspinia.pages.study_help_provider import validate_result

QUEUE_TTL = timedelta(minutes=15)
LEASE_TTL = timedelta(seconds=TIMEOUT_SECONDS + 60)


@dataclass(frozen=True)
class Claim:
    spend_id: UUID
    model: str
    action: str
    messages: list


def _policy():
    return StudyHelpPolicy.objects.select_related("active_prompt").filter(pk=1).first()


def _job(spend):
    return StudyHelpRequest.objects.select_for_update().filter(spend=spend).first()


def _context(job, policy):
    from inspinia.pages.models import ContestProblemStatement

    user = locked_account(job.owner_id)
    if user is None or not can_use_study_help(user, policy):
        raise StudyHelpError("unavailable")
    statement = ContestProblemStatement.objects.select_for_update().filter(statement_uuid=job.statement_uuid).first()
    if statement is None:
        raise StudyHelpError("inactive_statement")
    check_read(user, statement, job.problem_uuid)
    if (
        source_problem(statement)
        or statement_revision(statement) != job.revision
        or statement.problem_uuid != job.problem_uuid
        or statement.statement_latex != job.statement_text
    ):
        raise StudyHelpError("stale_action")
    if (
        not generation_ready(policy)
        or job.model != policy.model
        or job.profile_digest != profile_digest(job.prompt, job.model)
        or not StudyHelpQualification.objects.filter(prompt=job.prompt, profile_digest=job.profile_digest).exists()
    ):
        raise StudyHelpError("generation_paused")
    return _prior(user, statement, job.prior_id)


def _end_job(job, state, now, code="", body="", method=""):  # noqa: PLR0913
    if job is None:
        return
    job.state, job.finished_at, job.failure_code = state, now, code
    job.body, job.method, job.statement_text = body, method, ""
    job.save(update_fields=["state", "finished_at", "failure_code", "body", "method", "statement_text"])
    kind = StudyHelpEvent.Kind.COMPLETED if state == StudyHelpRequest.State.READY else StudyHelpEvent.Kind.FAILED
    event_for(job, kind)


def _settle(spend, amount, now):
    spend.actual_micros, spend.settled_at, spend.state = amount, now, StudyHelpSpend.State.SETTLED
    spend.save(update_fields=["state", "actual_micros", "settled_at"])


def _unknown(spend, job, now):
    spend.state = StudyHelpSpend.State.UNKNOWN
    spend.save(update_fields=["state"])
    _end_job(job, StudyHelpRequest.State.UNKNOWN, now, "reconciliation_pending")


def _reap(now):
    for spend in StudyHelpSpend.objects.filter(
        Q(state=StudyHelpSpend.State.RESERVED) & (Q(created_at__lte=now - QUEUE_TTL) | Q(generation__isnull=True))
        | Q(state=StudyHelpSpend.State.DISPATCHED, dispatched_at__lte=now - LEASE_TTL),
    ).order_by("created_at")[:50]:
        job = _job(spend)
        if spend.state == StudyHelpSpend.State.RESERVED:
            _settle(spend, 0, now)
            _end_job(job, StudyHelpRequest.State.FAILED, now, "expired")
        else:
            _unknown(spend, job, now)


@transaction.atomic
def claim_next():
    lock_study_help()
    now = timezone.now()
    _reap(now)
    policy = _policy()
    if policy:
        policy.worker_checked_at = now
        policy.save(update_fields=["worker_checked_at"])
    if StudyHelpSpend.objects.filter(state=StudyHelpSpend.State.DISPATCHED).exists():
        return None
    spend = (
        StudyHelpSpend.objects.filter(state=StudyHelpSpend.State.RESERVED, generation__isnull=False)
        .order_by("created_at", "pk")
        .first()
    )
    if spend is None:
        return None
    job = _job(spend)
    try:
        if job is None:
            raise StudyHelpError("unavailable")
        prior = _context(job, policy)
        if (
            _frozen_pricing(spend) != {"input_price": policy.input_price, "output_price": policy.output_price}
            or spend.reserved_micros > policy.request_cap
            or not budget_available(policy)
        ):
            raise StudyHelpError("budget_limit")
    except StudyHelpError as error:
        _settle(spend, 0, now)
        _end_job(job, StudyHelpRequest.State.FAILED, now, error.code)
        return None

    job.state = StudyHelpRequest.State.RUNNING
    job.save(update_fields=["state"])
    spend.state = StudyHelpSpend.State.DISPATCHED
    spend.dispatched_at = now
    spend.save(update_fields=["state", "dispatched_at"])
    return Claim(spend.pk, job.model, job.action, input_messages(job.action, job.statement_text, job.prompt, prior))


@transaction.atomic
def finish(spend_id, result):
    lock_study_help()
    now = timezone.now()
    spend = StudyHelpSpend.objects.get(pk=spend_id)
    if spend.state != StudyHelpSpend.State.DISPATCHED:
        return "fenced"
    job = _job(spend)
    policy = _policy()
    spend.provider_request_id = result.request_id[:160]
    spend.provider_response_id = result.response_id[:160]
    token_counts = (result.input_tokens, result.output_tokens)
    known_usage = all(type(count) is int and 0 <= count <= 2_147_483_647 for count in token_counts)
    if known_usage:
        spend.input_tokens, spend.output_tokens = token_counts
    spend.save(update_fields=["provider_request_id", "provider_response_id", "input_tokens", "output_tokens"])

    if result.definitive_rejection and not known_usage:
        _settle(spend, 0, now)
    elif known_usage:
        amount = cost_micros(*token_counts, _frozen_pricing(spend))
        _settle(spend, amount, now)
        if amount > spend.reserved_micros and policy:
            policy.generation_enabled = False
            policy.save(update_fields=["generation_enabled"])
            StudyHelpAdminEvent.objects.create(action="overrun_pause", reference=str(spend.pk))
    else:
        _unknown(spend, job, now)
        return StudyHelpRequest.State.UNKNOWN

    if job is None:
        return "evaluation" if spend.evaluation_key else "owner_deleted"
    if now >= spend.dispatched_at + LEASE_TTL:
        _end_job(job, StudyHelpRequest.State.FAILED, now, "expired")
        return StudyHelpRequest.State.FAILED
    try:
        prior = _context(job, policy)
    except StudyHelpError as error:
        _end_job(job, StudyHelpRequest.State.FAILED, now, error.code)
        return StudyHelpRequest.State.FAILED

    body, method, code = validate_result(job.action, result, prior)
    state = StudyHelpRequest.State.FAILED if code else StudyHelpRequest.State.READY
    _end_job(job, state, now, code, body, method)
    return state


def _frozen_pricing(spend):
    return {"input_price": spend.input_price, "output_price": spend.output_price}


def process_next(provider=call_provider):
    claim = claim_next()
    if claim is None:
        return "idle"
    try:
        result = provider(claim.model, claim.action, claim.messages)
    except Exception:  # noqa: BLE001 - do not retry or log potentially sensitive provider exceptions.
        result = ProviderResult(error="provider_uncertain")
    return finish(claim.spend_id, result)


@transaction.atomic
def reconcile(spend_id, amount, evidence_ref, actor):
    lock_study_help()
    spend = StudyHelpSpend.objects.get(pk=spend_id, state=StudyHelpSpend.State.UNKNOWN)
    now = timezone.now()
    spend.reconciliation_ref = evidence_ref
    spend.save(update_fields=["reconciliation_ref"])
    _settle(spend, amount, now)
    policy = _policy()
    if policy and amount > spend.reserved_micros:
        policy.generation_enabled = False
        policy.save(update_fields=["generation_enabled"])
    StudyHelpAdminEvent.objects.create(actor=actor, action="reconcile", reference=str(spend.pk))
