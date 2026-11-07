"""Admission, entitlements, private delivery, and analytics for Study Help."""

# ruff: noqa: EM101, PLR2004, TRY003, TRY301

import re
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.study_help_access import assistance_restricted
from inspinia.pages.study_help_access import can_use_study_help
from inspinia.pages.study_help_access import lock_study_help
from inspinia.pages.study_help_access import source_problem
from inspinia.pages.study_help_access import statement_revision
from inspinia.pages.study_help_models import HINT_ACTIONS
from inspinia.pages.study_help_models import SOLUTION_ACTIONS
from inspinia.pages.study_help_models import StudyHelpAction
from inspinia.pages.study_help_models import StudyHelpEvent
from inspinia.pages.study_help_models import StudyHelpPolicy
from inspinia.pages.study_help_models import StudyHelpQualification
from inspinia.pages.study_help_models import StudyHelpRequest
from inspinia.pages.study_help_models import StudyHelpSpend
from inspinia.pages.study_help_provider import cost_micros
from inspinia.pages.study_help_provider import input_messages
from inspinia.pages.study_help_provider import maximum_tokens
from inspinia.pages.study_help_provider import profile_digest

ACTIVE = (StudyHelpRequest.State.QUEUED, StudyHelpRequest.State.RUNNING)
CHARGED_OR_HELD = (*ACTIVE, StudyHelpRequest.State.READY)
KUALA_LUMPUR = ZoneInfo("Asia/Kuala_Lumpur")
PRICING_MAX_AGE = timedelta(days=30)
REVISION_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Allowance:
    hints_daily: int = 5
    solutions_total: int = 50
    solutions_per_statement: int = 2


def entitlement_for(_user):
    return Allowance()


ERRORS = {
    "unavailable": (404, "AI study help is unavailable."),
    "assistance_restricted": (403, "AI study help is unavailable during this assessment or restriction."),
    "inactive_statement": (403, "AI study help is unavailable for this archived statement."),
    "diagram_required": (422, "AI study help is currently available for text-only problems."),
    "unsupported_statement": (422, "This statement is incomplete or too large for AI study help."),
    "generation_paused": (503, "New AI responses are paused. You can still open saved responses."),
    "budget_limit": (503, "AI study help has reached its current capacity. Try again later."),
    "hints_exhausted": (429, "You've used today's hints. Your allowance resets at midnight in Kuala Lumpur."),
    "solutions_exhausted": (429, "You've used all your free solution credits."),
    "statement_limit": (429, "You've used both solution slots for this problem."),
    "generation_pending": (409, "You already have a response in progress."),
    "reconciliation_pending": (409, "The previous request could not be verified. No credit was used."),
    "stale_action": (409, "The available help has changed. Check the current options and try again."),
    "request_conflict": (409, "This request was already used for a different action."),
    "interaction_limit": (429, "Too many Study Help actions. Please wait a moment."),
    "invalid_request": (422, "Submit a valid Study Help request."),
    "confirmation_required": (422, "Confirm before generating a full solution."),
    "missing_response": (404, "That saved response was not found."),
}
FAILURE_MESSAGES = {
    "abstained": "AI couldn't give useful help for this problem. No credit was used.",
    "no_alternative": "AI couldn't find a different approach. No credit was used.",
    "expired": "The request expired. No credit was used.",
    "stale_action": "The statement changed while the response was being generated. No credit was used.",
    "assistance_restricted": "The response is unavailable during this restriction. No credit was used.",
    "reconciliation_pending": ERRORS["reconciliation_pending"][1],
}


class StudyHelpError(ValueError):
    def __init__(self, code):
        self.code = code
        self.status, message = ERRORS[code]
        super().__init__(message)


@dataclass(frozen=True)
class RequestSpec:
    request_key: UUID
    interaction_key: UUID
    action: StudyHelpAction
    revision: str
    slot: int
    prior_id: UUID | None
    confirmed: bool

    @classmethod
    def parse(cls, data):
        try:
            revision = data["revision"]
            slot = data["slot"]
            if not REVISION_PATTERN.fullmatch(revision) or type(slot) is not int or slot not in (1, 2):
                raise ValueError
            spec = cls(
                UUID(data["request_key"]),
                UUID(data["interaction_key"]),
                StudyHelpAction(data["action"]),
                revision,
                slot,
                UUID(data["prior_id"]) if data.get("prior_id") else None,
                data.get("confirmed") is True,
            )
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise StudyHelpError("invalid_request") from error
        if spec.action in SOLUTION_ACTIONS and not spec.confirmed:
            raise StudyHelpError("confirmation_required")
        return spec


def _statement(statement_uuid, *, lock=False):
    queryset = ContestProblemStatement.objects.select_for_update() if lock else ContestProblemStatement.objects
    statement = queryset.filter(statement_uuid=statement_uuid).first()
    if statement is None:
        raise StudyHelpError("unavailable")
    return statement


def policy_for(user):
    policy = StudyHelpPolicy.objects.select_related("active_prompt").filter(pk=1).first()
    if not can_use_study_help(user, policy):
        raise StudyHelpError("unavailable")
    return policy


def locked_account(user_id):
    return get_user_model().objects.select_for_update().filter(pk=user_id).first()


def _restricted(user, statement, prior_uuid=None):
    return assistance_restricted(
        user,
        (statement.problem_uuid, prior_uuid),
        statement_uuid=statement.statement_uuid,
    )


def check_read(user, statement, prior_uuid=None):
    if not statement.is_active:
        raise StudyHelpError("inactive_statement")
    if _restricted(user, statement, prior_uuid):
        raise StudyHelpError("assistance_restricted")


def pricing_ready(policy):
    now = timezone.now()
    return bool(
        policy
        and policy.model.strip()
        and policy.pricing_verified_at
        and now - PRICING_MAX_AGE <= policy.pricing_verified_at <= now
        and 0 < policy.request_cap <= policy.day_cap <= policy.month_cap
        and min(policy.input_price, policy.output_price) > 0,
    )


def generation_ready(policy):
    return bool(
        settings.STUDY_HELP_ENABLED
        and settings.STUDY_HELP_OPENAI_API_KEY
        and pricing_ready(policy)
        and policy.generation_enabled
        and policy.worker_checked_at
        and policy.worker_checked_at >= timezone.now() - timedelta(minutes=5)
        and policy.active_prompt
        and StudyHelpQualification.objects.filter(
            prompt=policy.active_prompt,
            profile_digest=profile_digest(policy.active_prompt, policy.model),
        ).exists(),
    )


def budget_available(policy, additional=0):
    now = timezone.now().astimezone(ZoneInfo("UTC"))
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    spend = StudyHelpSpend.objects.all()
    holds = spend.filter(actual_micros__isnull=True).aggregate(total=Sum("reserved_micros"))["total"] or 0
    settled = spend.filter(state=StudyHelpSpend.State.SETTLED)
    return all(
        holds
        + additional
        + (settled.filter(dispatched_at__gte=start).aggregate(total=Sum("actual_micros"))["total"] or 0)
        <= limit
        for start, limit in ((day, policy.day_cap), (month, policy.month_cap))
    )


def telemetry_available(user):
    since = timezone.now() - timedelta(minutes=1)
    return StudyHelpEvent.objects.filter(owner=user, created_at__gte=since).count() < 60


def record_event(user, statement_uuid, interaction, action, kind, generation=None):  # noqa: PLR0913
    event, created = StudyHelpEvent.objects.get_or_create(
        owner=user,
        statement_uuid=statement_uuid,
        interaction_key=interaction,
        action=action,
        kind=kind,
        defaults={"generation": generation},
    )
    if not created and generation and event.generation_id is None:
        StudyHelpEvent.objects.filter(pk=event.pk, generation__isnull=True).update(generation=generation)


def event_for(job, kind):
    record_event(job.owner, job.statement_uuid, job.interaction_key, job.action, kind, job)


class ProblemUsage:
    def __init__(self, user, statement):
        self.statement = statement
        self.revision = statement_revision(statement)
        self.day = timezone.now().astimezone(KUALA_LUMPUR).date()
        self.allowance = entitlement_for(user)
        owned = StudyHelpRequest.objects.filter(owner=user)
        self.saved = list(
            owned.filter(statement_uuid=statement.statement_uuid, state=StudyHelpRequest.State.READY)
            .defer("body", "statement_text", "method")
            .order_by("-finished_at", "-id"),
        )
        self.pending = owned.filter(state__in=ACTIVE).only("id", "statement_uuid", "action", "state").first()
        self.latest_failed = (
            owned.filter(statement_uuid=statement.statement_uuid, revision=self.revision)
            .only("id", "state", "failure_code")
            .order_by("-created_at")
            .first()
        )
        self.unreconciled = owned.filter(
            statement_uuid=statement.statement_uuid,
            spend__state=StudyHelpSpend.State.UNKNOWN,
        ).exists()
        held = owned.filter(state__in=CHARGED_OR_HELD)
        self.hints_left = max(0, self.allowance.hints_daily - held.filter(hint_day=self.day).count())
        self.solutions_left = max(
            0,
            self.allowance.solutions_total - held.filter(action__in=SOLUTION_ACTIONS).count(),
        )
        self.used_slots = {item.slot for item in self.saved if item.action in SOLUTION_ACTIONS}
        self.solution_slot = next(
            (slot for slot in range(1, self.allowance.solutions_per_statement + 1) if slot not in self.used_slots),
            None,
        )
        current = [item for item in self.saved if item.revision == self.revision]
        self.hint = next((item for item in current if item.action == StudyHelpAction.HINT), None)
        self.stronger = next((item for item in current if item.action == StudyHelpAction.STRONGER_HINT), None)
        self.proof = next((item for item in current if item.action in SOLUTION_ACTIONS), None)

    def actions(self):
        options = {}
        if self.hints_left:
            if not self.hint:
                options[StudyHelpAction.HINT] = {"slot": 1, "prior_id": None}
            elif self.hint.revealed_at and not self.stronger:
                options[StudyHelpAction.STRONGER_HINT] = {"slot": 2, "prior_id": str(self.hint.pk)}
        if self.solutions_left and self.solution_slot:
            action = StudyHelpAction.ALTERNATIVE if self.proof else StudyHelpAction.SOLUTION
            options[action] = {"slot": self.solution_slot, "prior_id": str(self.proof.pk) if self.proof else None}
        return options

    def availability(self, policy):
        return (
            source_problem(self.statement)
            or ("reconciliation_pending" if self.unreconciled else "")
            or ("generation_pending" if self.pending else "")
            or ("generation_paused" if not generation_ready(policy) else "")
        )

    def payload(self, policy, user):
        unavailable = self.availability(policy)
        # Current scope was already checked by the status caller. Only historical canonical IDs need a recheck.
        withheld = {
            problem_uuid
            for problem_uuid in {item.problem_uuid for item in self.saved} - {self.statement.problem_uuid}
            if _restricted(user, self.statement, problem_uuid)
        }
        saved = [
            {
                "id": str(item.pk),
                "action": item.action,
                "current": item.revision == self.revision,
                "created_at": item.finished_at,
                "revealed": bool(item.revealed_at),
            }
            for item in self.saved
            if item.problem_uuid not in withheld
        ]
        pending_here = self.pending and self.pending.statement_uuid == self.statement.statement_uuid
        failure = self.latest_failed
        return {
            "revision": self.revision,
            "hints_left": self.hints_left,
            "solutions_left": self.solutions_left,
            "statement_solutions_used": len(self.used_slots),
            "statement_solution_limit": self.allowance.solutions_per_statement,
            "actions": {} if unavailable else self.actions(),
            "message": ERRORS[unavailable][1] if unavailable else "",
            "failure": (
                FAILURE_MESSAGES.get(failure.failure_code, "AI couldn't finish this request. No credit was used.")
                if failure and failure.state in (StudyHelpRequest.State.FAILED, StudyHelpRequest.State.UNKNOWN)
                else ""
            ),
            "pending": bool(self.pending),
            "pending_here": str(self.pending.pk) if pending_here else None,
            "saved": saved,
        }


@transaction.atomic
def status(user, statement_uuid):
    lock_study_help()
    policy = policy_for(user)
    statement = _statement(statement_uuid)
    check_read(user, statement)
    return ProblemUsage(user, statement).payload(policy, user)


def _check_replay(job, statement_uuid, spec):
    if (
        job.statement_uuid != statement_uuid
        or job.action != spec.action
        or job.revision != spec.revision
        or job.slot != spec.slot
        or job.prior_id != spec.prior_id
        or job.interaction_key != spec.interaction_key
    ):
        raise StudyHelpError("request_conflict")
    return job, False


def _check_action(usage, spec):
    if spec.action in HINT_ACTIONS and not usage.hints_left:
        raise StudyHelpError("hints_exhausted")
    if spec.action in SOLUTION_ACTIONS:
        if not usage.solutions_left:
            raise StudyHelpError("solutions_exhausted")
        if not usage.solution_slot:
            raise StudyHelpError("statement_limit")
    expected = {"slot": spec.slot, "prior_id": str(spec.prior_id) if spec.prior_id else None}
    if spec.revision != usage.revision or usage.actions().get(spec.action) != expected:
        raise StudyHelpError("stale_action")


@transaction.atomic
def enqueue(user, statement_uuid, spec):
    if spec.action in SOLUTION_ACTIONS and not spec.confirmed:
        raise StudyHelpError("confirmation_required")
    lock_study_help()
    user = locked_account(user.pk)
    if user is None:
        raise StudyHelpError("unavailable")
    policy = policy_for(user)
    statement = _statement(statement_uuid, lock=True)
    check_read(user, statement)
    existing = StudyHelpRequest.objects.filter(owner=user, request_key=spec.request_key).first()
    if existing:
        return _check_replay(existing, statement_uuid, spec)
    if StudyHelpRequest.objects.filter(owner=user, interaction_key=spec.interaction_key).exists():
        raise StudyHelpError("request_conflict")
    usage = ProblemUsage(user, statement)
    unavailable = usage.availability(policy)
    if unavailable:
        raise StudyHelpError(unavailable)
    _check_action(usage, spec)
    prior = _prior(user, statement, spec.prior_id)
    messages = input_messages(spec.action, statement.statement_latex, policy.active_prompt, prior)
    pricing = {"input_price": policy.input_price, "output_price": policy.output_price}
    input_limit, output_limit = maximum_tokens(spec.action, messages)
    reserve = cost_micros(input_limit, output_limit, pricing)
    if reserve > policy.request_cap or not budget_available(policy, reserve):
        raise StudyHelpError("budget_limit")
    job = StudyHelpRequest.objects.create(
        owner=user,
        request_key=spec.request_key,
        interaction_key=spec.interaction_key,
        statement_uuid=statement_uuid,
        problem_uuid=statement.problem_uuid,
        revision=usage.revision,
        action=spec.action,
        slot=spec.slot,
        prior_id=spec.prior_id,
        hint_day=usage.day if spec.action in HINT_ACTIONS else None,
        prompt=policy.active_prompt,
        model=policy.model,
        profile_digest=profile_digest(policy.active_prompt, policy.model),
        statement_text=statement.statement_latex,
        spend=StudyHelpSpend.objects.create(reserved_micros=reserve, **pricing),
    )
    StudyHelpEvent.objects.filter(
        owner=user,
        statement_uuid=statement_uuid,
        interaction_key=spec.interaction_key,
        action=spec.action,
        generation__isnull=True,
    ).update(generation=job)
    event_for(job, StudyHelpEvent.Kind.ACCEPTED)
    return job, True


def _prior(user, statement, response_id):
    if response_id is None:
        return None
    prior = StudyHelpRequest.objects.filter(
        owner=user,
        statement_uuid=statement.statement_uuid,
        revision=statement_revision(statement),
        pk=response_id,
        state=StudyHelpRequest.State.READY,
    ).first()
    if prior is None or _restricted(user, statement, prior.problem_uuid):
        raise StudyHelpError("stale_action")
    return prior


@transaction.atomic
def reveal(user, statement_uuid, response_id, interaction, *, automatic=False):
    lock_study_help()
    statement = _statement(statement_uuid, lock=True)
    item = (
        StudyHelpRequest.objects.select_for_update()
        .filter(
            owner=user,
            statement_uuid=statement_uuid,
            pk=response_id,
            state=StudyHelpRequest.State.READY,
        )
        .first()
    )
    if item is None:
        raise StudyHelpError("missing_response")
    user = locked_account(user.pk)
    if user is None:
        raise StudyHelpError("unavailable")
    policy_for(user)
    check_read(user, statement, item.problem_uuid)
    if (not automatic or item.action in SOLUTION_ACTIONS) and telemetry_available(user):
        record_event(user, statement_uuid, interaction, item.action, StudyHelpEvent.Kind.VIEW_CLICK, item)
    if item.revealed_at is None:
        item.revealed_at = timezone.now()
        item.save(update_fields=["revealed_at"])
        event_for(item, StudyHelpEvent.Kind.FIRST_REVEAL)
    return {
        "id": str(item.pk),
        "body": item.body,
        "action": item.action,
        "current": item.revision == statement_revision(statement),
    }
